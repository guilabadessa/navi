"""Portal do cliente: acesso somente leitura aos dados do PROPRIO cliente do usuario (perfil CLIENTE)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Client, Event, ExtAsset, ExtTenant, MaintenanceWindow, ReportRun, User
from ..security import require
from ..services import kpi_service, maintenance_service
from .clients import client_hosts

router = APIRouter(prefix="/portal", tags=["portal"])


def _client(db: Session, user: User) -> Client:
    c = db.get(Client, user.client_id) if user.client_id else None
    if not c or c.status != "ativo":
        raise HTTPException(403, "Seu acesso não está associado a um cliente ativo. Fale com a Orca TI.")
    return c


def _ev(e: Event) -> dict:
    # somente o necessario para o cliente (sem destinos, mensagens, notas internas, grupos do Zabbix)
    return {"id": e.id, "host": e.host, "ip": e.ip, "trigger_name": e.trigger_name, "severity": e.severity, "status": e.status,
            "started_at": e.started_at.isoformat(), "recovered_at": e.recovered_at.isoformat() if e.recovered_at else None,
            "duration_s": e.duration_s}


@router.get("/overview")
def overview(days: int = 30, db: Session = Depends(get_db), user: User = Depends(require("portal.view"))):
    c = _client(db, user)
    days = max(1, min(days, 90))
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    hosts = client_hosts(db, c)
    evs = list(db.scalars(select(Event).where(Event.kind == "infra", Event.client_id == c.id, Event.started_at < end,
                                              (Event.recovered_at.is_(None)) | (Event.recovered_at > start)).order_by(Event.started_at.desc())))
    k = kpi_service.compute(evs, [{"hostid": h.hostid, "name": h.name, "ip": h.ip} for h in hosts], start, end, c.sla_target,
                            exclude=maintenance_service.exclusions(db, c.id, start, end))
    now = datetime.now(timezone.utc)
    upcoming = []
    for w in db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.enabled.is_(True), MaintenanceWindow.name != "Manutenção rápida",
                                                        MaintenanceWindow.client_id.is_(None) | (MaintenanceWindow.client_id == c.id))):
        for a, b in maintenance_service.expand(w, now, now + timedelta(days=30)):
            if b > now:
                upcoming.append({"name": w.name, "start": a.isoformat(), "end": b.isoformat()})
    tids = list(db.scalars(select(ExtTenant.id).where(ExtTenant.client_id == c.id, ExtTenant.source == "acronis")))
    from .protection import asset_status
    from ..services import protection_service as P
    pc = P.cfg(db)
    bk_assets = [] if not tids else [{"name": a.name, "type": a.type, "last_success_at": a.last_success_at.isoformat() if a.last_success_at else None,
                                      "status": asset_status(a, pc, now)}
                                     for a in db.scalars(select(ExtAsset).where(ExtAsset.ext_tenant_id.in_(tids), ExtAsset.active.is_(True), ExtAsset.ignored.is_(False)).order_by(ExtAsset.name))]
    bk_alerts = [{"host": e.host, "trigger_name": e.trigger_name, "severity": e.severity, "started_at": e.started_at.isoformat()}
                 for e in db.scalars(select(Event).where(Event.kind == "backup", Event.status == "PROBLEM", Event.client_id == c.id))]
    etids = list(db.scalars(select(ExtTenant.id).where(ExtTenant.client_id == c.id, ExtTenant.source == "ems")))
    ems_days = pc["ems_offline_days"]
    from ..models import ExtAsset as _A
    ep_assets = [] if not etids else [{"name": a.name, "user": (a.meta or {}).get("user"), "os": (a.meta or {}).get("os"), "status": P.ems_status(a, ems_days, now),
                                       "last_contact": a.last_success_at.isoformat() if a.last_success_at else None}
                                      for a in db.scalars(select(_A).where(_A.ext_tenant_id.in_(etids), _A.active.is_(True), _A.ignored.is_(False)).order_by(_A.name))]
    runs = db.scalars(select(ReportRun).where(ReportRun.client_id == c.id, ReportRun.file_path.is_not(None)).order_by(ReportRun.generated_at.desc()).limit(2))
    return {
        "client": {"name": c.trade_name, "sla_target": c.sla_target},
        "summary": k["summary"], "by_day": k["by_day"], "by_severity": k["by_severity"],
        "by_host": [{"host": h["host"], "incidents": h["incidents"], "downtime_s": h["downtime_s"], "availability": h["availability"]} for h in k["by_host"][:15]],
        "hosts": [{"name": h.name, "ip": h.ip, "available": h.available} for h in hosts],
        "active": [_ev(e) for e in evs if e.status == "PROBLEM"],
        "history": [_ev(e) for e in evs[:80]],
        "backup": {"enabled": bool(tids), "assets": bk_assets, "alerts": bk_alerts},
        "endpoints": {"enabled": bool(etids), "assets": ep_assets},
        "maintenance": sorted(upcoming, key=lambda x: x["start"])[:5],
        "reports": [{"id": r.id, "name": r.name, "period_start": r.period_start.isoformat() if r.period_start else None,
                     "period_end": r.period_end.isoformat() if r.period_end else None, "generated_at": r.generated_at.isoformat()} for r in runs]}


@router.get("/reports/{rid}/download")
def download(rid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("portal.view"))):
    c = _client(db, user)
    run = db.get(ReportRun, rid)
    if not run or run.client_id != c.id or not run.file_path or not Path(run.file_path).exists():
        raise HTTPException(404, "Arquivo não encontrado")
    audit.log(db, request, "portal_report_download", "report_run", rid)
    db.commit()
    return FileResponse(run.file_path, media_type="application/pdf", filename=Path(run.file_path).name)
