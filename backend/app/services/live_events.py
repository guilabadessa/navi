"""Eventos de um periodo consultados AO VIVO na API do Zabbix (nao dependem da retencao local)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ZbxHost, ZbxHostGroup
from .zabbix_service import ZabbixService

LOOKBACK_DAYS = 30  # pega problemas iniciados antes do periodo que ainda o atravessam


def _dt(v):
    try:
        v = int(v)
        return datetime.fromtimestamp(v, tz=timezone.utc) if v > 0 else None
    except (TypeError, ValueError):
        return None


def fetch(db: Session, z: ZabbixService, hostids: list[str], start: datetime, end: datetime, client_id: int | None = None):
    if not hostids:
        return []
    hosts = {h.hostid: h for h in db.scalars(select(ZbxHost).where(ZbxHost.hostid.in_(hostids)))}
    t_from = int((start - timedelta(days=LOOKBACK_DAYS)).timestamp())
    t_till = int(end.timestamp())
    raw, last = [], None
    while True:
        params = {"output": ["eventid", "r_eventid", "clock", "name", "severity", "objectid", "acknowledged"], "source": 0,
                  "object": 0, "value": 1, "hostids": hostids, "time_from": t_from, "time_till": t_till,
                  "sortfield": ["eventid"], "sortorder": "ASC", "limit": 2000, "selectHosts": ["hostid", "name"],
                  "selectTags": "extend"}
        if last:
            params["eventid_from"] = str(int(last) + 1)
        batch = z.call("event.get", params)
        raw += batch
        if len(batch) < 2000:
            break
        last = batch[-1]["eventid"]
    # recuperacoes
    rids = [e["r_eventid"] for e in raw if e.get("r_eventid") not in (None, "0", 0)]
    rec = {}
    for i in range(0, len(rids), 500):
        for e in z.events_by_ids(rids[i:i + 500]):
            rec[e["eventid"]] = _dt(e["clock"])
    # itens por trigger
    tids = list({e["objectid"] for e in raw})
    items = {}
    for i in range(0, len(tids), 500):
        items.update(z.trigger_items(tids[i:i + 500]))
    gnames = {g.groupid: g.name for g in db.scalars(select(ZbxHostGroup))}
    out = []
    for e in raw:
        started = _dt(e["clock"])
        r = rec.get(e.get("r_eventid")) if e.get("r_eventid") not in (None, "0", 0) else None
        if started >= end or (r is not None and r <= start):
            continue
        hid = (e.get("hosts") or [{}])[0].get("hostid")
        h = hosts.get(hid)
        its = items.get(e["objectid"]) or []
        dur_end = r or min(datetime.now(timezone.utc), end)
        out.append(SimpleNamespace(
            zbx_eventid=e["eventid"], hostid=hid, host=(h.name if h else (e.get("hosts") or [{}])[0].get("name")),
            ip=h.ip if h else None, trigger_name=e["name"], item_name=its[0]["name"] if its else None,
            severity=int(e["severity"]), status="RESOLVED" if r else "PROBLEM", started_at=started, recovered_at=r,
            duration_s=int((dur_end - started).total_seconds()), client_id=client_id,
            group_names=[gnames.get(g, g) for g in (h.group_ids if h else [])]))
    return out
