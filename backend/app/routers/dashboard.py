import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from .. import settings_store
from ..models import Client, ClientHost, ClientHostGroup, Dispatch, Event, HealthCheck, JobStatus, ZbxHost
from ..security import require
from ..services import kpi_service, maintenance_service
from ..util import to_dict
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


@router.get("/dashboard")
def dashboard(client_id: int | None = None, days: int = 30, db: Session = Depends(get_db), _=Depends(require("dashboard.view"))):
    days = max(1, min(days, 90))

    def build():
        now = datetime.now(timezone.utc)
        dN, d7 = now - timedelta(days=days), now - timedelta(days=7)
        d24 = now - timedelta(hours=24)
        today = datetime.now(timezone.utc).astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        hosts = list(db.scalars(select(ZbxHost).where(ZbxHost.active.is_(True), ZbxHost.status == 0)))
        evf = [Event.client_id == client_id] if client_id else []
        if client_id:
            c = db.get(Client, client_id)
            hosts = client_hosts(db, c) if c else []
        open_ev = list(db.scalars(select(Event).where(Event.status == "PROBLEM", *evf).order_by(Event.severity.desc(), Event.started_at)))
        cnt = lambda since: db.scalar(select(func.count()).select_from(Event).where(Event.started_at >= since, *evf))  # noqa: E731
        evN = list(db.scalars(select(Event).where(Event.started_at < now, (Event.recovered_at.is_(None)) | (Event.recovered_at > dN), *evf)))
        k = kpi_service.compute(evN, [{"hostid": h.hostid, "name": h.name, "ip": h.ip} for h in hosts], dN, now,
                                exclude=maintenance_service.exclusions(db, client_id, dN, now) if client_id else None)
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
        # saude do processamento (worker parado = nada alerta)
        stale = []
        for j in db.scalars(select(JobStatus)):
            if j.last_run and j.interval_s and (now - j.last_run).total_seconds() > max(j.interval_s * 4, 180):
                stale.append(j.label or j.name)
            elif j.status == "error":
                stale.append((j.label or j.name) + " (erro)")
        sent = dict(db.execute(select(Dispatch.status, func.count()).where(Dispatch.created_at >= d24).group_by(Dispatch.status)).all())
        shadow = settings_store.get(db, "alerts.shadow") == "1"
        cov = {}
        if not client_id:
            assigned = set(db.scalars(select(ClientHostGroup.zbx_groupid))) | set()
            hids = set(db.scalars(select(ClientHost.zbx_hostid)))
            unc = [h for h in hosts if not (set(h.group_ids or []) & assigned) and h.hostid not in hids]
            cov = {"hosts_uncovered": len(unc), "hosts_total": len(hosts)}
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
            "coverage": cov, "stale_jobs": stale, "alerts_24h": sent, "shadow": shadow, "generated_at": now.isoformat()}
    return _cached(f"dash{client_id}-{days}", 20, build)


@router.get("/sla")
def sla(days: int = 30, db: Session = Depends(get_db), _=Depends(require("sla.view"))):
    days = max(1, min(days, 90))  # limite = retencao local de eventos

    def build():
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        out = []
        for c in db.scalars(select(Client).where(Client.status == "ativo").order_by(Client.trade_name)):
            hosts = client_hosts(db, c)
            evs = list(db.scalars(select(Event).where(Event.client_id == c.id, Event.started_at < now,
                                                      (Event.recovered_at.is_(None)) | (Event.recovered_at > start))))
            k = kpi_service.compute(evs, [{"hostid": h.hostid, "name": h.name, "ip": h.ip} for h in hosts], start, now, c.sla_target,
                                    exclude=maintenance_service.exclusions(db, c.id, start, now))
            s = k["summary"]
            out.append({"client_id": c.id, "client": c.trade_name, "hosts": len(hosts), "sla_target": c.sla_target,
                        "availability": s["availability"], "incidents": s["incidents"], "downtime_s": s["downtime_s"],
                        "mttr_s": s["mttr_s"], "mtbf_s": s["mtbf_s"], "met": s["sla_met"]})
        return {"days": days, "items": sorted(out, key=lambda x: (x["met"] is not False, x["availability"]))}
    return _cached(f"sla{days}", 60, build)
