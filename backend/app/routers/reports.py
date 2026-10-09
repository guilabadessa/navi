from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Client, Report, ReportRun
from ..schemas import GenerateIn, ReportIn, SendIn
from ..security import require
from ..services import delivery_service, kpi_service, report_service
from ..services import destinations as dest_svc
from ..util import to_dict

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("")
def list_reports(db: Session = Depends(get_db), _=Depends(require("reports.view"))):
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    last = {r: (g, st) for r, g, st in db.execute(select(ReportRun.report_id, func.max(ReportRun.generated_at), func.count())
                                                 .group_by(ReportRun.report_id)).all()}
    cl = {c.id: c for c in db.scalars(select(Client))}
    return [{**to_dict(r), "destinations": dest_svc.describe(cl.get(r.client_id)), "client_name": names.get(r.client_id), "last_run": (last.get(r.id) or (None, 0))[0] and last[r.id][0].isoformat(),
             "runs": (last.get(r.id) or (None, 0))[1]} for r in db.scalars(select(Report).order_by(Report.created_at.desc()))]


@router.post("")
def create_report(body: ReportIn, request: Request, db: Session = Depends(get_db), me=Depends(require("reports.edit"))):
    r = Report(**body.model_dump(), created_by=me.email)
    db.add(r)
    db.flush()
    audit.log(db, request, "report_create", "report", r.id, detail={"name": r.name})
    db.commit()
    return to_dict(r)


@router.get("/runs")
def runs(client_id: int | None = None, page: int = 1, size: int = 50, db: Session = Depends(get_db), _=Depends(require("reports.view"))):
    stmt = select(ReportRun)
    if client_id:
        stmt = stmt.where(ReportRun.client_id == client_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    rows = db.scalars(stmt.order_by(ReportRun.generated_at.desc()).offset((page - 1) * size).limit(min(size, 200)))
    return {"total": total, "items": [{**to_dict(r), "client_name": names.get(r.client_id)} for r in rows]}


@router.get("/runs/{rid}/download")
def download(rid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("reports.view"))):
    run = db.get(ReportRun, rid)
    if not run or not run.file_path or not Path(run.file_path).exists():
        raise HTTPException(404, "Arquivo não encontrado")
    audit.log(db, request, "report_download", "report_run", rid)
    db.commit()
    return FileResponse(run.file_path, media_type="application/pdf", filename=Path(run.file_path).name)


@router.get("/runs/{rid}/destinations")
def destinations(rid: int, db: Session = Depends(get_db), _=Depends(require("reports.send"))):
    """Destinos padrao sugeridos para a etapa de confirmacao de envio."""
    run = db.get(ReportRun, rid)
    rep = db.get(Report, run.report_id) if run and run.report_id else None
    if not run:
        raise HTTPException(404)
    c = db.get(Client, run.client_id) if run.client_id else None
    wa = rep.wa_dest if rep and rep.wa_dest and rep.wa_dest != "client" else ((c.whatsapp_group_jid or c.whatsapp) if c else None)
    wa_kind = "grupo" if (c and c.whatsapp_group_jid and wa == c.whatsapp_group_jid) else ("celular" if wa else None)
    mail = rep.email_dest if rep and rep.email_dest and rep.email_dest != "client" else dest_svc.report_emails(c)
    return {"wa": wa or "", "wa_kind": wa_kind, "email": mail or "", "client": c.trade_name if c else None,
            "wa_missing": not wa, "email_missing": not mail}


@router.post("/runs/{rid}/send")
def resend(rid: int, body: SendIn, request: Request, db: Session = Depends(get_db), _=Depends(require("reports.send"))):
    run = db.get(ReportRun, rid)
    rep = db.get(Report, run.report_id) if run and run.report_id else None
    if not run or not rep:
        raise HTTPException(404)
    delivery_service.deliver(db, run, rep, body.wa_dest, body.email_to, body.email_cc, body.email_bcc, body.subject)
    audit.log(db, request, "report_send", "report_run", rid, detail={"wa": run.wa_status, "email": run.email_status})
    db.commit()
    return to_dict(run, {"kpis"})


@router.get("/{rid}")
def get_report(rid: int, db: Session = Depends(get_db), _=Depends(require("reports.view"))):
    r = db.get(Report, rid)
    if not r:
        raise HTTPException(404)
    return to_dict(r)


@router.put("/{rid}")
def update_report(rid: int, body: ReportIn, request: Request, db: Session = Depends(get_db), _=Depends(require("reports.edit"))):
    r = db.get(Report, rid)
    if not r:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit.log(db, request, "report_update", "report", rid)
    db.commit()
    return to_dict(r)


@router.delete("/runs/{rid}")
def delete_run(rid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("reports.edit"))):
    run = db.get(ReportRun, rid)
    if not run:
        raise HTTPException(404)
    if run.file_path:
        Path(run.file_path).unlink(missing_ok=True)
    db.delete(run)
    audit.log(db, request, "report_run_delete", "report_run", rid)
    db.commit()
    return {"ok": True}


@router.delete("/{rid}")
def delete_report(rid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("reports.edit"))):
    """Exclui a definicao, as rotinas ligadas a ela e os PDFs ja gerados."""
    r = db.get(Report, rid)
    if not r:
        raise HTTPException(404)
    for run in db.scalars(select(ReportRun).where(ReportRun.report_id == rid)):
        if run.file_path:
            Path(run.file_path).unlink(missing_ok=True)
        db.delete(run)
    db.delete(r)
    audit.log(db, request, "report_delete", "report", rid)
    db.commit()
    return {"ok": True}


def _period(r: Report, b: GenerateIn):
    if b.period_mode:
        return report_service.resolve_period(b.period_mode, b.period_days)
    a, e = b.period_start or r.period_start, b.period_end or r.period_end
    if not (a and e):
        raise HTTPException(422, "Informe o período")
    return a, e


@router.post("/{rid}/preview")
def preview(rid: int, body: GenerateIn, db: Session = Depends(get_db), _=Depends(require("reports.view"))):
    r = db.get(Report, rid)
    if not r:
        raise HTTPException(404)
    a, e = _period(r, body)
    client = db.get(Client, r.client_id) if r.client_id else None
    mods = report_service.resolve_modules(db, r, client)
    if "infra" not in mods:
        return {"kpis": None, "events": 0, "hosts": 0, "modules": mods}
    k, events, hosts, client = report_service.build(db, r, a, e)
    return {"kpis": k, "events": len(events), "hosts": len(hosts), "modules": mods}


@router.post("/{rid}/generate")
def generate(rid: int, body: GenerateIn, request: Request, db: Session = Depends(get_db), me=Depends(require("reports.edit"))):
    r = db.get(Report, rid)
    if not r:
        raise HTTPException(404)
    a, e = _period(r, body)
    try:
        run = report_service.generate(db, r, me.email, a, e)
    except Exception as ex:  # noqa: BLE001
        audit.log(db, request, "report_generate", "report", rid, result="falha", detail={"error": str(ex)[:300]})
        db.commit()
        raise HTTPException(422 if isinstance(ex, ValueError) else 500, f"Falha ao gerar relatório: {ex}")
    audit.log(db, request, "report_generate", "report", rid, detail={"run": run.id})
    db.commit()
    return to_dict(run, {"kpis"})
