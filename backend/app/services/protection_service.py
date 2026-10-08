"""Backup (Acronis) e endpoints (EMS): sincroniza tenants/maquinas e transforma problemas em eventos NAVI (kind=backup),
que passam pelo mesmo motor de alertas do Zabbix (regras, agrupamento, escalonamento, manutencao, modo sombra)."""
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..models import Client, Event, ExtAsset, ExtTenant
from . import event_service
from . import notification_service as N

log = logging.getLogger("navi.protection")
SRC = "acronis"
SEV = {"critical": 5, "error": 4, "warning": 2, "information": 1}
TEXT = {
    "BackupFailed": "Falha no backup",
    "BackupFinishedWithWarnings": "Backup concluído com avisos",
    "BackupCancelled": "Backup cancelado",
    "BackupMissed": "Backup não executado no horário",
    "BackupDidNotStart": "Backup não iniciou",
    "ActiveProtectionServiceNotRunning": "Serviço de proteção ativa parado",
    "MalwareDetected": "Malware detectado",
    "AgentOffline": "Agente offline",
    "LicenseExpired": "Licença expirada",
    "QuotaExceeded": "Cota de armazenamento excedida",
}


def human_type(t: str | None) -> str:
    if not t:
        return "Alerta do Acronis"
    if t in TEXT:
        return TEXT[t]
    return re.sub(r"(?<!^)(?=[A-Z])", " ", t).strip()  # camelCase -> palavras


def cfg(db: Session) -> dict:
    return {"stale_h": int(S.get(db, "protection.stale_h") or 72), "offline_min": int(S.get(db, "protection.offline_min") or 240),
            "acronis_enabled": (S.get(db, "protection.acronis_enabled") or "1") == "1"}


def _dt(v) -> datetime | None:
    if not v:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    t = re.sub(r"(\.\d{6})\d+", r"\1", str(v).replace("Z", "+00:00"))
    d = datetime.fromisoformat(t)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ---------------- tenants ----------------
def sync_tenants(db: Session, svc) -> tuple[dict, dict]:
    tree = svc.tenant_tree()
    by_id = {t["id"]: t for t in tree}

    def customer(t):
        seen = 0
        while t and t.get("kind") != "customer" and seen < 12:
            t, seen = by_id.get(t.get("parent_id")), seen + 1
        return t if t and t.get("kind") == "customer" else None

    existing = {x.ext_id: x for x in db.scalars(select(ExtTenant).where(ExtTenant.source == SRC))}
    now = datetime.now(timezone.utc)
    seen_ids = set()
    for t in tree:
        if t.get("kind") != "customer":
            continue
        x = existing.get(t["id"]) or ExtTenant(source=SRC, ext_id=t["id"], name=t["name"])
        x.name, x.kind, x.enabled, x.active, x.synced_at = t["name"], "customer", bool(t.get("enabled", True)), True, now
        if x.id is None:
            db.add(x)
            existing[t["id"]] = x
        seen_ids.add(t["id"])
    for k, x in existing.items():
        if k not in seen_ids:
            x.active = False
    db.flush()
    by_uuid, by_name = {}, {}
    for t in tree:
        c = customer(t)
        if c and c["id"] in existing:
            by_uuid[t["id"]] = existing[c["id"]]
            by_name[(t.get("name") or "").strip().lower()] = existing[c["id"]]
    return by_uuid, by_name


# ---------------- ativos e atividades ----------------
def _asset(db: Session, cache: dict, ext_id: str, name: str, typ: str, tenant: ExtTenant | None) -> ExtAsset:
    ext_id = ext_id.lower()
    a = cache.get(ext_id)
    if a is None:
        a = ExtAsset(source=SRC, ext_id=ext_id, name=name, type=typ)
        db.add(a)
        cache[ext_id] = a
    a.name, a.type, a.active = name or a.name, typ or a.type, True
    if tenant is not None:
        a.ext_tenant_id = tenant.id
    a.last_seen_at = datetime.now(timezone.utc)
    return a


def sync_assets(db: Session, svc, by_uuid: dict, by_name: dict):
    cache = {a.ext_id: a for a in db.scalars(select(ExtAsset).where(ExtAsset.source == SRC))}
    agents = {a["id"]: a for a in svc.agents()}
    now = datetime.now(timezone.utc)
    cfg_ = cfg(db)
    for r in svc.resources("resource.machine"):
        tn = by_name.get((r.get("tenant_name") or "").strip().lower())
        a = _asset(db, cache, r["id"], r.get("user_defined_name") or r.get("name") or r["id"], "machine", tn)
        ag = agents.get(r.get("agent_id"))
        if ag is not None:
            if a.ext_tenant_id is None:
                t2 = by_name.get(((ag.get("tenant") or {}).get("name") or "").strip().lower())
                a.ext_tenant_id = t2.id if t2 else None
            online = bool(ag.get("online")) if ag.get("enabled", True) else None
            if online is False and a.online is not False:
                a.offline_since = now
            if online is not False:
                a.offline_since = None
            a.online = online
    # atividades de backup: ultimo sucesso/falha por recurso
    cur = S.get(db, "acronis.activity_cursor")
    since = (_dt(cur) - timedelta(minutes=30)) if cur else now - timedelta(days=8)
    started = now
    by_name_asset = {}
    for x in cache.values():
        if x.type == "machine":
            by_name_asset.setdefault((x.name or "").strip().lower(), x)
    for act in svc.backup_activities(since):
        res = act["resource"]
        t = by_uuid.get(((act.get("tenant") or {}).get("uuid")) or "")
        rtype = (res.get("type") or "resource").lower()
        a = by_name_asset.get((res.get("name") or "").strip().lower()) if rtype == "instance" else None  # "instance" = a propria maquina
        if a is None:
            nm = res.get("name") or res["id"]
            mach = (act.get("context") or {}).get("MachineName")
            if rtype == "instance":  # instancia que nao e uma maquina registrada = banco de dados (SQL etc.)
                rtype = "database"
                if mach and mach.lower() not in nm.lower():
                    nm = f"{nm} ({mach})"
            a = _asset(db, cache, res["id"], nm, rtype, t)
        a.policy_name = (act.get("policy") or {}).get("name") or a.policy_name
        if act.get("state") != "completed":
            continue
        done = _dt(act.get("completedAt")) or _dt(act.get("startedAt"))
        code = ((act.get("result") or {}).get("code") or "").lower()
        a.last_result = code
        if code in ("ok", "warning", "warnings"):
            if not a.last_success_at or done > a.last_success_at:
                a.last_success_at = done
        elif not a.last_failure_at or done > a.last_failure_at:
            a.last_failure_at = done
    S.put(db, "acronis.activity_cursor", started.isoformat())
    db.flush()
    return cache


# ---------------- eventos ----------------
def _desired(db: Session, svc, cache: dict, by_uuid: dict, by_name: dict) -> dict[str, dict]:
    now = datetime.now(timezone.utc)
    c = cfg(db)
    tenants = {t.id: t for t in db.scalars(select(ExtTenant).where(ExtTenant.source == SRC))}
    out: dict[str, dict] = {}
    for al in svc.alerts():
        det = al.get("details") or {}
        rid = (det.get("resourceId") or "").lower()
        a = cache.get(rid)
        ten = tenants.get(a.ext_tenant_id) if a else None
        out[f"alert:{al['id']}"] = {
            "host": det.get("resourceName") or (a.name if a else "—"), "hostid": rid or None, "tenant": ten,
            "triggerid": al.get("type"), "trigger_name": human_type(al.get("type")), "item_name": det.get("planName"),
            "severity": SEV.get((al.get("severity") or "").lower(), 3), "started_at": _dt(al.get("createdAt")) or now,
            "opdata": ("Plano: " + det["planName"]) if det.get("planName") else None, "type": al.get("type")}
    for a in cache.values():
        if not a.active or a.ignored:
            continue
        ten = tenants.get(a.ext_tenant_id)
        last_ok = a.last_success_at
        if last_ok and (now - last_ok) > timedelta(hours=c["stale_h"]):
            h = int((now - last_ok).total_seconds() // 3600)
            out[f"stale:{a.ext_id}"] = {"host": a.name, "hostid": a.ext_id, "tenant": ten, "triggerid": "NoRecentBackup",
                                        "trigger_name": f"Sem backup bem-sucedido há {h // 24}d {h % 24}h" if h >= 48 else f"Sem backup bem-sucedido há {h}h",
                                        "item_name": a.policy_name, "severity": 4, "started_at": now, "type": "NoRecentBackup",
                                        "opdata": f"Último sucesso: {last_ok.astimezone().strftime('%d/%m/%Y %H:%M')}"}
        if a.online is False and a.offline_since and (now - a.offline_since) > timedelta(minutes=c["offline_min"]):
            out[f"offline:{a.ext_id}"] = {"host": a.name, "hostid": a.ext_id, "tenant": ten, "triggerid": "AgentOffline",
                                          "trigger_name": "Agente de backup offline", "item_name": a.policy_name, "severity": 3,
                                          "started_at": a.offline_since, "type": "AgentOffline",
                                          "opdata": f"Offline desde {a.offline_since.astimezone().strftime('%d/%m/%Y %H:%M')}"}
    return out


def reconcile(db: Session, desired: dict[str, dict]) -> dict:
    now = datetime.now(timezone.utc)
    stats = {"new": 0, "resolved": 0, "open": 0}
    open_evs = {e.zbx_eventid: e for e in db.scalars(select(Event).where(Event.kind == "backup", Event.source == SRC, Event.status == "PROBLEM"))}
    for key, d in desired.items():
        eid = f"{SRC}:{key}"
        ten: ExtTenant | None = d["tenant"]
        ev = open_evs.get(eid) or db.scalar(select(Event).where(Event.zbx_eventid == eid))
        if ev is None:
            ev = Event(zbx_eventid=eid, status="PROBLEM", started_at=d["started_at"], kind="backup", source=SRC)
            db.add(ev)
            created = True
        else:
            created = False
            if ev.status == "RESOLVED":  # voltou a ocorrer: reabre como novo ciclo
                ev.status, ev.recovered_at, ev.duration_s, ev.started_at, created = "PROBLEM", None, None, d["started_at"], True
        ev.hostid, ev.host, ev.triggerid, ev.trigger_name = d["hostid"], d["host"], d["triggerid"], d["trigger_name"]
        ev.item_name, ev.opdata, ev.severity = d.get("item_name"), d.get("opdata"), d["severity"]
        ev.group_ids, ev.group_names = ([ten.ext_id] if ten else []), ([ten.name] if ten else [])
        ev.client_id = ten.client_id if ten else None
        ev.tags = [{"tag": "origem", "value": "Acronis"}, {"tag": "tipo", "value": d.get("type") or ""}]
        db.flush()
        stats["open"] += 1
        if created:
            stats["new"] += 1
            from ..models import SEVERITIES  # noqa: F401
            if (now - ev.started_at) <= event_service.ALERT_WINDOW:
                N.plan_problem(db, ev)
    for eid, ev in open_evs.items():
        if eid.split(":", 1)[1] not in desired:
            if event_service.mark_resolved(db, ev, now):
                stats["resolved"] += 1
    db.commit()
    return stats


def relink(db: Session) -> int:
    """Reaplica a associacao tenant -> cliente aos eventos de backup (apos mapear um tenant)."""
    tmap = {t.ext_id: t.client_id for t in db.scalars(select(ExtTenant).where(ExtTenant.source == SRC))}
    n = 0
    for ev in db.scalars(select(Event).where(Event.kind == "backup")):
        cid = tmap.get((ev.group_ids or [None])[0])
        if cid != ev.client_id:
            ev.client_id, n = cid, n + 1
    db.commit()
    return n


def sync_acronis(db: Session, svc) -> dict:
    if not svc.configured or not cfg(db)["acronis_enabled"]:
        return {"skipped": True}
    by_uuid, by_name = sync_tenants(db, svc)
    cache = sync_assets(db, svc, by_uuid, by_name)
    db.commit()
    desired = _desired(db, svc, cache, by_uuid, by_name)
    stats = reconcile(db, desired)
    relink(db)
    return {**stats, "assets": len(cache), "tenants": len(by_uuid)}
