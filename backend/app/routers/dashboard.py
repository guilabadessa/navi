import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from .. import audit, settings_store
from ..models import INCIDENT_MIN_SEV, Client, ClientHost, ClientHostGroup, Dispatch, Event, ExtAsset, ExtTenant, HealthCheck, JobStatus, ZbxHost
from ..security import current_user, require
from ..services import kpi_service, maintenance_service, services_service
from ..util import NO_CLIENT, by_client, to_dict
from .clients import client_hosts

router = APIRouter(tags=["dashboard"])
_cache: dict[str, tuple[float, dict]] = {}
LINK_WORDS = ("link", "wan", "vpn", "interface", "ifoper", "ping", "icmp", "unavailable", "down")


def _cached(key: str, ttl: int, fn):
    t = time.time()
    if key in _cache and t - _cache[key][0] < ttl:
        return _cache[key][1]
    v = fn()
    _cache[key] = (t, v)
    return v


def cloud_stats(db: Session, client_id: int | None) -> dict | None:
    from ..models import CloudVm
    q = select(CloudVm).where(CloudVm.active.is_(True))
    if client_id:
        q = q.where(CloudVm.client_id == client_id)
    vms = list(db.scalars(q))
    if not vms:
        return None
    return {"total": len(vms), "running": sum(1 for v in vms if v.state == "RUNNING"), "clients": len({v.client_id for v in vms}),
            "off": sum(1 for v in vms if v.state != "RUNNING" and not (v.expected_off or v.ignored))}


def _sig(j: JobStatus, kind: str) -> str:
    return f"erro:{(j.error or '')[:200]}" if kind == "erro" else f"atraso:{j.last_run.isoformat() if j.last_run else ''}"


def job_alerts(db: Session) -> list[dict]:
    """Rotinas com erro ou atrasadas que ainda nao receberam aceite. Falha nova (outro erro / novo atraso) volta a aparecer."""
    now = datetime.now(timezone.utc)
    out = []
    for j in db.scalars(select(JobStatus)):
        if not j.enabled:
            continue
        kind = None
        if j.status == "error":
            kind = "erro"
        elif j.last_run and j.interval_s and (now - j.last_run).total_seconds() > max(j.interval_s * 4, 180):
            kind = "atraso"
        if not kind or j.ack_sig == _sig(j, kind):
            continue
        out.append({"name": j.name, "label": j.label or j.name, "kind": kind, "error": j.error if kind == "erro" else None,
                    "last_run": j.last_run.isoformat() if j.last_run else None, "interval_s": j.interval_s})
    return out


def failed_dispatches(db: Session) -> list[dict]:
    """Envios de alerta que falharam nas ultimas 24h e ainda sem ciencia (ciencia = maior id reconhecido)."""
    ack = int(settings_store.get(db, "alerts.failed_ack_id", "0") or 0)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = db.execute(select(Dispatch, Event.host, Event.trigger_name, Event.client_id)
                      .join(Event, Event.id == Dispatch.event_id, isouter=True)
                      .where(Dispatch.status == "failed", Dispatch.created_at >= since, Dispatch.id > ack)
                      .order_by(Dispatch.id.desc()).limit(50)).all()
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    return [{"id": d.id, "channel": d.channel, "dest": (d.dest_jid or "")[:120], "kind": d.kind, "error": d.error, "attempts": d.attempts,
             "at": d.created_at.isoformat() if d.created_at else None, "host": h, "trigger": t, "client": names.get(c)} for d, h, t, c in rows]


@router.post("/dashboard/dispatches/ack")
def ack_dispatches(request: Request, user=Depends(current_user), db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    top = db.scalar(select(func.max(Dispatch.id)).where(Dispatch.status == "failed")) or 0
    settings_store.put(db, "alerts.failed_ack_id", str(top), user.name)
    audit.log(db, request, "dispatch_ack", "dispatch", top)
    db.commit()
    return {"ok": True}


@router.post("/dashboard/jobs/{name}/ack")
def ack_job(name: str, request: Request, user=Depends(current_user), db: Session = Depends(get_db), _=Depends(require("routines.edit"))):
    j = db.get(JobStatus, name)
    if not j:
        raise HTTPException(404, "Rotina não encontrada")
    kind = "erro" if j.status == "error" else "atraso"
    j.ack_sig, j.ack_by, j.ack_at = _sig(j, kind), user.name, datetime.now(timezone.utc)
    audit.log(db, request, "job_ack", "job", name, detail={"job": name, "tipo": kind})
    db.commit()
    return {"ok": True}


@router.get("/dashboard")
def dashboard(client_id: int | None = None, days: float = 30, db: Session = Depends(get_db), _=Depends(require("dashboard.view"))):
    days = round(max(1 / 24, min(days, 90)), 4)  # de 1 hora a 90 dias

    def build():
        now = datetime.now(timezone.utc)
        dN, d7 = now - timedelta(days=days), now - timedelta(days=7)
        d24 = now - timedelta(hours=24)
        today = datetime.now(timezone.utc).astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        hosts = list(db.scalars(select(ZbxHost).where(ZbxHost.active.is_(True), ZbxHost.status == 0)))
        nocl = client_id == NO_CLIENT  # filtro "Sem cliente associado"
        evf = [Event.kind == "infra", Event.severity >= INCIDENT_MIN_SEV] + ([by_client(Event.client_id, client_id)] if client_id else [])
        if nocl:
            assigned = set(db.scalars(select(ClientHostGroup.zbx_groupid)))
            hids = set(db.scalars(select(ClientHost.zbx_hostid)))
            hosts = [h for h in hosts if not (set(h.group_ids or []) & assigned) and h.hostid not in hids]
        elif client_id:
            c = db.get(Client, client_id)
            hosts = client_hosts(db, c) if c else []
        open_ev = list(db.scalars(select(Event).where(Event.status == "PROBLEM", *evf).order_by(Event.severity.desc(), Event.started_at)))
        cnt = lambda since: db.scalar(select(func.count()).select_from(Event).where(Event.started_at >= since, *evf))  # noqa: E731
        evN = list(db.scalars(select(Event).where(Event.started_at < now, (Event.recovered_at.is_(None)) | (Event.recovered_at > dN), *evf)))
        k = kpi_service.compute(evN, [{"hostid": h.hostid, "name": h.name, "ip": h.ip} for h in hosts], dN, now,
                                exclude=maintenance_service.exclusions(db, client_id, dN, now) if client_id and not nocl else None)
        names = dict(db.execute(select(Client.id, Client.trade_name)).all())
        top_clients = {}
        for e in evN:
            if e.client_id:
                c = top_clients.setdefault(e.client_id, {"client_id": e.client_id, "client": names.get(e.client_id), "incidents": 0, "downtime_s": 0})
                c["incidents"] += 1
                c["downtime_s"] += e.duration_s or int((now - e.started_at).total_seconds())
        links_down = [e for e in open_ev if any(w in (e.trigger_name or "").lower() or w in (e.item_name or "").lower() for w in LINK_WORDS)]
        health = {h.name: {"ok": h.ok, "detail": h.detail, "checked_at": h.checked_at.isoformat()} for h in db.scalars(select(HealthCheck))}
        by_hour = {}
        for e in db.scalars(select(Event).where(Event.started_at >= d24, *evf)):
            hk = e.started_at.astimezone().strftime("%H")
            by_hour[hk] = by_hour.get(hk, 0) + 1
        hours = [(now - timedelta(hours=i)).astimezone().strftime("%H") for i in range(23, -1, -1)]
        bk = [Event.kind == "backup", Event.status == "PROBLEM", Event.severity >= INCIDENT_MIN_SEV] + ([by_client(Event.client_id, client_id)] if client_id else [])
        backup_active = db.scalar(select(func.count()).select_from(Event).where(*bk)) or 0
        ep = [Event.kind == "endpoint", Event.status == "PROBLEM", Event.severity >= INCIDENT_MIN_SEV] + ([by_client(Event.client_id, client_id)] if client_id else [])
        endpoint_active = db.scalar(select(func.count()).select_from(Event).where(*ep)) or 0
        sent = dict(db.execute(select(Dispatch.status, func.count()).where(Dispatch.created_at >= d24).group_by(Dispatch.status)).all())
        shadow = settings_store.get(db, "alerts.shadow") == "1"
        cov = {}
        if not client_id:
            assigned = set(db.scalars(select(ClientHostGroup.zbx_groupid))) | set()
            hids = set(db.scalars(select(ClientHost.zbx_hostid)))
            unc = [h for h in hosts if not (set(h.group_ids or []) & assigned) and h.hostid not in hids]
            pend = [t for t in db.scalars(select(ExtTenant).where(ExtTenant.client_id.is_(None), ExtTenant.active.is_(True), ExtTenant.source.in_(("acronis", "ems")))) if not (t.info or {}).get("ignored")]
            from ..models import CloudAccount
            cov = {"hosts_uncovered": len(unc), "hosts_total": len(hosts), "tenants_pending": [{"name": t.name, "source": t.source} for t in pend],
                   "cloud_errors": [{"client": names.get(a.client_id), "error": (a.last_error or "")[:120]} for a in db.scalars(select(CloudAccount).where(CloudAccount.enabled.is_(True), CloudAccount.last_error.is_not(None)))]}
        return {
            "filter": {"client_id": client_id, "days": days},
            "hosts_total": len(hosts), "hosts_down": sum(1 for h in hosts if h.available == 2),
            "problems_active": len(open_ev), "problems_today": cnt(today), "problems_7d": cnt(d7), "problems_30d": cnt(dN),
            "availability_30d": k["summary"]["availability"], "mttr_s": k["summary"]["mttr_s"],
            "clients_affected": len({e.client_id for e in open_ev if e.client_id}),
            "links_down": len(links_down), "sla_30d": k["summary"]["availability"],
            "top_hosts": [{"hostid": h.get("hostid"), "host": h["host"], "incidents": h["incidents"], "downtime_s": h["downtime_s"]} for h in k["by_host"][:10] if h["incidents"]],
            "top_clients": sorted(top_clients.values(), key=lambda x: -x["downtime_s"])[:10],
            "by_severity": k["by_severity"], "by_day": k["by_day"],
            "by_hour": [{"h": h + "h", "v": by_hour.get(h, 0)} for h in hours],
            "live": [to_dict(e) | {"client_name": names.get(e.client_id)} for e in open_ev[:30]], "health": health,
            "backup_active": backup_active, "endpoint_active": endpoint_active, "coverage": cov, "cloud": cloud_stats(db, client_id), "services": services_service.of_client(db, db.get(Client, client_id)) if client_id and not nocl and db.get(Client, client_id) else None, "alerts_24h": sent, "shadow": shadow, "generated_at": now.isoformat()}
    return {**_cached(f"dash{client_id}-{days}", 20, build), "stale_jobs": job_alerts(db), "failed_dispatches": failed_dispatches(db)}


@router.get("/dashboard/clients-health")
def clients_health(db: Session = Depends(get_db), _=Depends(require("dashboard.view"))):
    """Uma linha por cliente: infraestrutura, backup e endpoints lado a lado (visao unica do NOC)."""
    def build():
        from ..models import CloudVm
        from ..services import protection_service as P
        from .protection import asset_status
        now = datetime.now(timezone.utc)
        pc = P.cfg(db)
        clients = list(db.scalars(select(Client).where(Client.status == "ativo").order_by(Client.trade_name)))
        svc = services_service.of_clients(db, clients)
        rows = {}
        for c in clients:
            rows[c.id] = {"client_id": c.id, "client": c.trade_name, "hosts": 0, "hosts_down": 0, "infra": 0, "infra_worst": -1, "backup": 0, "backup_worst": -1, "backup_items": 0, "backup_bad": 0,
                          "endpoint": 0, "endpoint_worst": -1, "endpoint_items": 0, "endpoint_bad": 0, "cloud": 0, "cloud_worst": -1, "cloud_items": 0, "cloud_off": 0,
                          "has_backup": svc[c.id]["backup"], "has_ems": svc[c.id]["endpoint"], "has_cloud": svc[c.id]["cloud"], "has_infra": svc[c.id]["infra"]}
            hs = client_hosts(db, c)
            rows[c.id]["hosts"], rows[c.id]["hosts_down"] = len(hs), sum(1 for h in hs if h.available == 2)
            if svc[c.id]["endpoint"]:
                eps = P.endpoint_rows(db, c.id)
                rows[c.id]["endpoint_items"], rows[c.id]["endpoint_bad"] = len(eps), sum(1 for e in eps if not e["ok"])
        for e in db.scalars(select(Event).where(Event.status == "PROBLEM", Event.severity >= INCIDENT_MIN_SEV, Event.client_id.in_(list(rows) or [0]))):
            r = rows[e.client_id]
            key = e.kind if e.kind in ("infra", "backup", "endpoint", "cloud") else "infra"
            r[key] += 1
            r[key + "_worst"] = max(r[key + "_worst"], e.severity or 0)
        tens = {t.id: t for t in db.scalars(select(ExtTenant).where(ExtTenant.client_id.is_not(None), ExtTenant.source == "acronis"))}
        for a in db.scalars(select(ExtAsset).where(ExtAsset.active.is_(True), ExtAsset.ignored.is_(False), ExtAsset.source == "acronis", ExtAsset.ext_tenant_id.in_(list(tens) or [0]))):
            r = rows.get(tens[a.ext_tenant_id].client_id)
            if r:
                r["backup_items"] += 1
                r["backup_bad"] += asset_status(a, pc, now) in ("falha", "sem backup", "offline")
        for v in db.scalars(select(CloudVm).where(CloudVm.active.is_(True))):
            r = rows.get(v.client_id)
            if r:
                r["cloud_items"] += 1
                r["cloud_off"] += v.state != "RUNNING" and not (v.expected_off or v.ignored)
        worst = lambda r: max(r["infra_worst"], r["backup_worst"], r["endpoint_worst"], r["cloud_worst"])  # noqa: E731
        return {"items": sorted(rows.values(), key=lambda r: -(worst(r) * 100 + r["infra"] + r["backup"] + r["endpoint"] + r["cloud"]))}
    return _cached("clients-health", 30, build)
