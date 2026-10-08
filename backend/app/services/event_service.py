"""Camada propria de eventos/incidentes: ingestao por API (polling) e webhook (tempo real)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Client, ClientHost, ClientHostGroup, Event, ZbxHost, ZbxHostGroup
from . import notification_service as N
from .zabbix_service import ZabbixService

BACKFILL_DAYS = 90
ALERT_WINDOW = timedelta(minutes=20)  # so alerta eventos "recentes" (evita enxurrada no backfill)


def _dt(v) -> datetime | None:
    try:
        v = int(v)
        return datetime.fromtimestamp(v, tz=timezone.utc) if v > 0 else None
    except (TypeError, ValueError):
        return None


def client_map(db: Session):
    """(groupid -> client_id, hostid -> client_id)"""
    g = {r.zbx_groupid: r.client_id for r in db.scalars(select(ClientHostGroup))}
    h = {r.zbx_hostid: r.client_id for r in db.scalars(select(ClientHost))}
    return g, h


def resolve_client(hostid, group_ids, gmap, hmap) -> int | None:
    if hostid in hmap:
        return hmap[hostid]
    for gid in group_ids or []:
        if gid in gmap:
            return gmap[gid]
    return None


def _host_info(db: Session, hostid: str | None):
    h = db.get(ZbxHost, hostid) if hostid else None
    gnames = []
    if h and h.group_ids:
        gnames = [g.name for g in db.scalars(select(ZbxHostGroup).where(ZbxHostGroup.groupid.in_(h.group_ids)))]
    return h, gnames


def upsert_problem(db: Session, d: dict, alert: bool = True) -> tuple[Event, bool]:
    """d: eventid, hostid, host, ip, triggerid, trigger_name, itemid, item_name, severity, started_at(dt), tags, opdata, source"""
    ev = db.scalar(select(Event).where(Event.zbx_eventid == str(d["eventid"])))
    created = ev is None
    h, gnames = _host_info(db, d.get("hostid"))
    gmap, hmap = client_map(db)
    gids = (h.group_ids if h else None) or []
    if ev is None:
        ev = Event(zbx_eventid=str(d["eventid"]), status="PROBLEM", started_at=d["started_at"])
        try:
            with db.begin_nested():  # savepoint: tolera corrida entre worker e sync manual
                db.add(ev)
                db.flush()
        except IntegrityError:
            ev = db.scalar(select(Event).where(Event.zbx_eventid == str(d["eventid"])))
            created = False
    ev.hostid = d.get("hostid") or ev.hostid
    ev.host = (h.name if h else None) or d.get("host") or ev.host
    ev.ip = d.get("ip") or (h.ip if h else None) or ev.ip
    ev.triggerid = d.get("triggerid") or ev.triggerid
    ev.trigger_name = d.get("trigger_name") or ev.trigger_name
    ev.itemid = d.get("itemid") or ev.itemid
    ev.item_name = d.get("item_name") or ev.item_name
    ev.severity = int(d.get("severity") if d.get("severity") is not None else ev.severity or 0)
    ev.tags = d.get("tags") or ev.tags
    ev.opdata = d.get("opdata") or ev.opdata
    ev.group_ids, ev.group_names = gids, gnames
    ev.client_id = resolve_client(d.get("hostid"), gids, gmap, hmap)
    ev.source = d.get("source", ev.source or "api")
    if d.get("acknowledged") is not None:
        ev.acknowledged = bool(int(d["acknowledged"]))
    db.flush()
    if created and alert and (datetime.now(timezone.utc) - ev.started_at) <= ALERT_WINDOW:
        N.plan_problem(db, ev)
    return ev, created


def mark_resolved(db: Session, ev: Event, recovered_at: datetime, r_eventid: str | None = None, alert: bool = True):
    if ev.status == "RESOLVED":
        return False
    ev.status, ev.recovered_at = "RESOLVED", recovered_at
    ev.r_eventid = r_eventid or ev.r_eventid
    ev.duration_s = max(0, int((recovered_at - ev.started_at).total_seconds()))
    db.flush()
    if alert and (datetime.now(timezone.utc) - recovered_at) <= ALERT_WINDOW:
        N.plan_recovery(db, ev)
    return True


# ---------------- Webhook (tempo real) ----------------
def from_webhook(db: Session, p: dict) -> dict:
    """Payload esperado (Media Type webhook do Zabbix):
    {eventid, status: PROBLEM|RESOLVED, hostid, host, ip, triggerid, trigger, itemid, item, severity(0-5|nome),
     opdata, clock(epoch), recovery_clock, r_eventid, tags:[{tag,value}]}"""
    status = str(p.get("status", "PROBLEM")).upper()
    sev = p.get("severity", 0)
    if isinstance(sev, str) and not sev.isdigit():
        sev = {"NOT CLASSIFIED": 0, "INFORMATION": 1, "WARNING": 2, "AVERAGE": 3, "HIGH": 4, "DISASTER": 5}.get(sev.upper(), 0)
    started = _dt(p.get("clock")) or datetime.now(timezone.utc)
    ev, created = upsert_problem(db, {
        "eventid": p["eventid"], "hostid": p.get("hostid"), "host": p.get("host"), "ip": p.get("ip"),
        "triggerid": p.get("triggerid"), "trigger_name": p.get("trigger"), "itemid": p.get("itemid"),
        "item_name": p.get("item"), "severity": int(sev), "started_at": started, "tags": p.get("tags"),
        "opdata": p.get("opdata"), "source": "webhook"})
    resolved = False
    if status in ("RESOLVED", "OK"):
        resolved = mark_resolved(db, ev, _dt(p.get("recovery_clock")) or datetime.now(timezone.utc), p.get("r_eventid"))
    db.commit()
    return {"id": ev.id, "created": created, "resolved": resolved}


# ---------------- Polling pela API ----------------
def poll(db: Session, z: ZabbixService, backfill: bool = False) -> dict:
    last = db.scalar(select(func.max(Event.started_at)))
    if last is None or backfill:
        since = int((datetime.now(timezone.utc) - timedelta(days=BACKFILL_DAYS)).timestamp())
        first = True
    else:
        since, first = int((last - timedelta(minutes=30)).timestamp()), False
    new = upd = 0
    t_from = since
    while True:
        batch = z.problem_events(t_from, limit=2000)
        if not batch:
            break
        tids = list({b["objectid"] for b in batch})
        titems = z.trigger_items(tids) if len(tids) < 2000 else {}
        for b in batch:
            host = (b.get("hosts") or [{}])[0]
            trig = b.get("relatedObject") or {}
            its = titems.get(b["objectid"]) or []
            ev, created = upsert_problem(db, {
                "eventid": b["eventid"], "hostid": host.get("hostid"), "host": host.get("name") or host.get("host"),
                "triggerid": b["objectid"], "trigger_name": b.get("name") or trig.get("description"),
                "itemid": its[0]["itemid"] if its else None, "item_name": its[0]["name"] if its else None,
                "severity": b.get("severity"), "started_at": _dt(b["clock"]), "tags": b.get("tags"),
                "acknowledged": b.get("acknowledged"), "source": "api"}, alert=not first)
            if created:
                new += 1
            elif _dt(b["clock"]) and ev.source == "webhook":
                ev.started_at = _dt(b["clock"])  # horario oficial do Zabbix substitui o horario de recebimento
            if b.get("r_eventid") not in (None, "0", 0):
                ev.r_eventid = b["r_eventid"]
        db.commit()
        if len(batch) < 2000:
            break
        t_from = int(batch[-1]["clock"])
    resolved = refresh_open(db, z, alert=not first)
    return {"new": new, "resolved": resolved, "first_run": first}


def refresh_open(db: Session, z: ZabbixService, alert: bool = True) -> int:
    """Confere no Zabbix os eventos ainda abertos e fecha os que ja foram recuperados."""
    open_evs = db.scalars(select(Event).where(Event.status == "PROBLEM")).all()
    if not open_evs:
        return 0
    n = 0
    byid = {e.zbx_eventid: e for e in open_evs}
    ids = list(byid)
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        res = z.call("event.get", {"eventids": part, "output": ["eventid", "r_eventid", "acknowledged"], "source": 0, "object": 0})
        rmap = {r["eventid"]: r["r_eventid"] for r in res if r.get("r_eventid") not in (None, "0", 0)}
        for r in res:
            byid[r["eventid"]].acknowledged = bool(int(r.get("acknowledged") or 0))
        if rmap:
            recs = {e["eventid"]: _dt(e["clock"]) for e in z.events_by_ids(list(rmap.values()))}
            for eid, rid in rmap.items():
                if recs.get(rid):
                    n += mark_resolved(db, byid[eid], recs[rid], rid, alert=alert)
        db.commit()
    return n
