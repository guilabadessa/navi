"""Camada propria de eventos/incidentes: ingestao por API (polling) e webhook (tempo real)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Client, ClientHost, ClientHostGroup, Event, ZbxHost, ZbxHostGroup
from . import notification_service as N
from . import severity_service
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
    ev.severity = severity_service.effective(severity_service.rules(db), ev.host, ev.trigger_name, ev.severity)
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
        hmap = _hosts_by_trigger(z, [b["objectid"] for b in batch if not b.get("hosts")])
        for b in batch:
            host = (b.get("hosts") or [hmap.get(b["objectid"]) or {}])[0]
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
    new += ingest_active(db, z, alert=not first)
    resolved = refresh_open(db, z, alert=not first)
    return {"new": new, "resolved": resolved, "first_run": first}


def _hosts_by_trigger(z: ZabbixService, triggerids: list[str]) -> dict:
    out = {}
    for i in range(0, len(triggerids), 500):
        for t in z.call("trigger.get", {"triggerids": triggerids[i:i + 500], "output": ["triggerid"], "selectHosts": ["hostid", "name"]}):
            if t.get("hosts"):
                out[t["triggerid"]] = t["hosts"][0]
    return out


def ingest_active(db: Session, z: ZabbixService, alert: bool = True) -> int:
    """Garante que todo problema ATIVO no Zabbix exista na NAVI, mesmo que tenha iniciado antes da janela do backfill."""
    active = z.active_problems()
    have = {e for (e,) in db.execute(select(Event.zbx_eventid).where(Event.zbx_eventid.in_([a["eventid"] for a in active])))} if active else set()
    missing = [a["eventid"] for a in active if a["eventid"] not in have]
    n = 0
    for i in range(0, len(missing), 200):
        batch = z.call("event.get", {"eventids": missing[i:i + 200], "output": ["eventid", "r_eventid", "clock", "name", "severity", "objectid", "acknowledged"],
                                      "source": 0, "object": 0, "selectHosts": ["hostid", "host", "name"], "selectTags": "extend"})
        tids = list({b["objectid"] for b in batch})
        titems = z.trigger_items(tids) if tids else {}
        hmap = _hosts_by_trigger(z, [b["objectid"] for b in batch if not b.get("hosts")])
        for b in batch:
            host = (b.get("hosts") or [hmap.get(b["objectid"]) or {}])[0]
            its = titems.get(b["objectid"]) or []
            ev, created = upsert_problem(db, {
                "eventid": b["eventid"], "hostid": host.get("hostid"), "host": host.get("name") or host.get("host"),
                "triggerid": b["objectid"], "trigger_name": b.get("name"), "itemid": its[0]["itemid"] if its else None,
                "item_name": its[0]["name"] if its else None, "severity": b.get("severity"), "started_at": _dt(b["clock"]),
                "tags": b.get("tags"), "acknowledged": b.get("acknowledged"), "source": "api"}, alert=alert)
            n += int(created)
        db.commit()
    return n


def refresh_open(db: Session, z: ZabbixService, alert: bool = True) -> int:
    """Confere no Zabbix os eventos abertos na NAVI. Fecha os recuperados e os que o Zabbix nao considera mais ativos."""
    open_evs = db.scalars(select(Event).where(Event.status == "PROBLEM")).all()
    if not open_evs:
        return 0
    n = 0
    byid = {e.zbx_eventid: e for e in open_evs}
    active_ids = {a["eventid"] for a in z.active_problems()}
    ids = list(byid)
    now = datetime.now(timezone.utc)
    # completa host dos eventos abertos que ficaram sem host (via trigger)
    nohost = [e for e in open_evs if not e.hostid and e.triggerid]
    if nohost:
        hm = _hosts_by_trigger(z, list({e.triggerid for e in nohost}))
        for e in nohost:
            h = hm.get(e.triggerid)
            if h:
                e.hostid, e.host = h["hostid"], h.get("name")
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        res = z.call("event.get", {"eventids": part, "output": ["eventid", "r_eventid", "acknowledged"], "source": 0, "object": 0})
        seen = {r["eventid"]: r for r in res}
        rmap = {k: r["r_eventid"] for k, r in seen.items() if r.get("r_eventid") not in (None, "0", 0)}
        for k, r in seen.items():
            byid[k].acknowledged = bool(int(r.get("acknowledged") or 0))
        recs = {e["eventid"]: _dt(e["clock"]) for e in z.events_by_ids(list(rmap.values()))} if rmap else {}
        for eid in part:
            ev = byid[eid]
            rid = rmap.get(eid)
            if rid and recs.get(rid):
                n += mark_resolved(db, ev, recs[rid], rid, alert=alert)
            elif eid not in active_ids:
                # Zabbix nao lista mais como ativo e nao ha evento de recuperacao (trigger/host removido ou descoberta expirada):
                # encerra sem contar como indisponibilidade (duracao desconhecida).
                ev.notes = ((ev.notes + "\n") if ev.notes else "") + "Encerrado automaticamente: o Zabbix não considera mais o problema ativo (sem evento de recuperação)."
                n += mark_resolved(db, ev, ev.started_at, None, alert=False)
        db.commit()
    return n


def relink_events(db: Session) -> int:
    """Reassocia eventos aos clientes conforme os host groups/hosts atuais (a associacao pode ser feita depois do evento)."""
    gmap, hmap = client_map(db)
    hosts = {h.hostid: h for h in db.scalars(select(ZbxHost))}
    gnames = {g.groupid: g.name for g in db.scalars(select(ZbxHostGroup))}
    changed = 0
    for ev in db.scalars(select(Event)):
        h = hosts.get(ev.hostid) if ev.hostid else None
        gids = (h.group_ids if h else None) or ev.group_ids or []
        cid = resolve_client(ev.hostid, gids, gmap, hmap)
        if h:
            names = [gnames.get(g, g) for g in gids]
            if ev.group_ids != gids:
                ev.group_ids = gids
            if ev.group_names != names:
                ev.group_names = names
        if cid != ev.client_id:
            ev.client_id = cid
            changed += 1
    db.commit()
    return changed
