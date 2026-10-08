import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Client, Event, HealthCheck, ZbxHost
from ..security import require
from ..services import kpi_service
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
def dashboard(db: Session = Depends(get_db), _=Depends(require("dashboard.view"))):
    def build():
        now = datetime.now(timezone.utc)
        d30, d7 = now - timedelta(days=30), now - timedelta(days=7)
        today = datetime.now(timezone.utc).astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        hosts = list(db.scalars(select(ZbxHost).where(ZbxHost.active.is_(True), ZbxHost.status == 0)))
        open_ev = list(db.scalars(select(Event).where(Event.status == "PROBLEM").order_by(Event.severity.desc(), Event.started_at)))
        cnt = lambda since: db.scalar(select(func.count()).select_from(Event).where(Event.started_at >= since))  # noqa: E731
        ev30 = list(db.scalars(select(Event).where(Event.started_at < now, (Event.recovered_at.is_(None)) | (Event.recovered_at > d30))))
        k = kpi_service.compute(ev30, [{"hostid": h.hostid, "name": h.name, "ip": h.ip} for h in hosts], d30, now)
        names = dict(db.execute(select(Client.id, Client.trade_name)).all())
        top_clients = {}
        for e in ev30:
            if e.client_id:
                c = top_clients.setdefault(e.client_id, {"client": names.get(e.client_id), "incidents": 0, "downtime_s": 0})
                c["incidents"] += 1
                c["downtime_s"] += e.duration_s or int((now - e.started_at).total_seconds())
        links_down = [e for e in open_ev if any(w in (e.trigger_name or "").lower() or w in (e.item_name or "").lower() for w in LINK_WORDS)]
        health = {h.name: {"ok": h.ok, "detail": h.detail, "checked_at": h.checked_at.isoformat()} for h in db.scalars(select(HealthCheck))}
        return {
            "hosts_total": len(hosts), "hosts_down": sum(1 for h in hosts if h.available == 2),
            "problems_active": len(open_ev), "problems_today": cnt(today), "problems_7d": cnt(d7), "problems_30d": cnt(d30),
            "availability_30d": k["summary"]["availability"], "mttr_s": k["summary"]["mttr_s"],
            "clients_affected": len({e.client_id for e in open_ev if e.client_id}),
            "links_down": len(links_down), "sla_30d": k["summary"]["availability"],
            "top_hosts": [{"host": h["host"], "incidents": h["incidents"], "downtime_s": h["downtime_s"]} for h in k["by_host"][:10] if h["incidents"]],
            "top_clients": sorted(top_clients.values(), key=lambda x: -x["downtime_s"])[:10],
            "by_severity": k["by_severity"], "by_day": k["by_day"],
            "live": [to_dict(e) for e in open_ev[:25]], "health": health, "generated_at": now.isoformat()}
    return _cached("dash", 20, build)


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
            k = kpi_service.compute(evs, [{"hostid": h.hostid, "name": h.name, "ip": h.ip} for h in hosts], start, now, c.sla_target)
            s = k["summary"]
            out.append({"client_id": c.id, "client": c.trade_name, "hosts": len(hosts), "sla_target": c.sla_target,
                        "availability": s["availability"], "incidents": s["incidents"], "downtime_s": s["downtime_s"],
                        "mttr_s": s["mttr_s"], "mtbf_s": s["mtbf_s"], "met": s["sla_met"]})
        return {"days": days, "items": sorted(out, key=lambda x: (x["met"] is not False, x["availability"]))}
    return _cached(f"sla{days}", 60, build)
