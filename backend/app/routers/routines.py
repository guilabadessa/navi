from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, scheduling
from ..db import get_db
from ..jobs import JOBS
from ..models import Client, JobStatus, Report, Schedule
from ..schemas import ScheduleIn
from ..security import require
from ..services import commlog, delivery_service, destinations, report_service
from ..util import to_dict

router = APIRouter(prefix="/routines", tags=["routines"])


@router.get("/schedules")
def schedules(db: Session = Depends(get_db), _=Depends(require("routines.view"))):
    reps = {r.id: r for r in db.scalars(select(Report))}
    out = []
    for s in db.scalars(select(Schedule).order_by(Schedule.name)):
        rep = reps.get(s.report_id)
        client = db.get(Client, rep.client_id) if rep and rep.client_id else None
        out.append({**to_dict(s), "report_name": rep.name if rep else None, "resolved": _resolve(s, client)})
    return out


def _resolve(s: Schedule, client: Client | None) -> dict:
    """Destinos REAIS desta rotina (o que de fato recebe), com aviso quando algo esta faltando."""
    d = destinations.describe(client)
    wa = d["wa"] if s.wa_dest == "client" else (s.wa_dest or None)
    em = d["report_emails"] if s.email_to == "client" else (s.email_to or None)
    warn = []
    if s.wa_dest and not wa:
        warn.append("WhatsApp solicitado, mas o cliente não tem grupo nem celular cadastrado")
    if s.email_to and not em:
        warn.append("E-mail solicitado, mas o cliente não tem e-mail de relatório cadastrado")
    if not s.wa_dest and not s.email_to:
        warn.append("Nenhum destino configurado: o relatório será gerado e não enviado")
    return {"client": d["client"], "wa": wa, "wa_kind": d["wa_kind"] if s.wa_dest == "client" else ("informado na rotina" if wa else None), "email": em,
            "email_origin": "cadastro do cliente" if s.email_to == "client" else "informado na rotina", "warnings": warn}


def _fill(s: Schedule, b: ScheduleIn):
    for k, v in b.model_dump().items():
        setattr(s, k, v)
    s.next_run = scheduling.next_run(s) if s.enabled else None


@router.post("/schedules")
def create(body: ScheduleIn, request: Request, db: Session = Depends(get_db), _=Depends(require("routines.edit"))):
    if not db.get(Report, body.report_id):
        raise HTTPException(422, "Relatório inexistente")
    s = Schedule()
    _fill(s, body)
    db.add(s)
    db.flush()
    audit.log(db, request, "schedule_create", "schedule", s.id, detail={"name": s.name})
    db.commit()
    return to_dict(s)


@router.put("/schedules/{sid}")
def update(sid: int, body: ScheduleIn, request: Request, db: Session = Depends(get_db), _=Depends(require("routines.edit"))):
    s = db.get(Schedule, sid)
    if not s:
        raise HTTPException(404)
    _fill(s, body)
    audit.log(db, request, "schedule_update", "schedule", sid)
    db.commit()
    return to_dict(s)


@router.delete("/schedules/{sid}")
def delete(sid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("routines.edit"))):
    s = db.get(Schedule, sid)
    if not s:
        raise HTTPException(404)
    db.delete(s)
    audit.log(db, request, "schedule_delete", "schedule", sid)
    db.commit()
    return {"ok": True}


@router.post("/schedules/{sid}/run")
def run_now(sid: int, request: Request, db: Session = Depends(get_db), me=Depends(require("reports.send"))):
    s = db.get(Schedule, sid)
    rep = db.get(Report, s.report_id) if s else None
    if not s or not rep:
        raise HTTPException(404)
    a, b = report_service.resolve_period(s.period_mode, s.period_days)
    try:
        run = report_service.generate(db, rep, me.email, a, b, name_suffix="_manual")
    except Exception as e:
        for ch, want in (("whatsapp", s.wa_dest), ("email", s.email_to)):
            if want:
                commlog.record(ch, "Relatório agendado", None, "failed", f"Execução manual de '{s.name}' falhou antes do envio: {e}", rep.name, rep.client_id)
        if isinstance(e, ValueError):
            raise HTTPException(422, str(e))
        raise
    delivery_service.deliver(db, run, rep, s.wa_dest, s.email_to, s.email_cc, s.email_bcc, s.subject)
    s.last_run, s.last_status = datetime.now(timezone.utc), f"manual · WA: {run.wa_status or '-'} · E-mail: {run.email_status or '-'}"[:250]
    audit.log(db, request, "schedule_run", "schedule", sid, detail={"run": run.id})
    db.commit()
    return to_dict(run, {"kpis"})


@router.get("/jobs")
def jobs(db: Session = Depends(get_db), _=Depends(require("routines.view"))):
    have = {j.name: j for j in db.scalars(select(JobStatus))}
    out = []
    for name, (label, itv) in JOBS.items():
        j = have.get(name)
        out.append(to_dict(j) if j else {"name": name, "label": label, "interval_s": itv, "enabled": True, "last_run": None,
                                         "next_run": None, "status": None, "error": None, "last_duration_ms": None})
    return out


@router.put("/jobs/{name}")
def toggle_job(name: str, enabled: bool, request: Request, db: Session = Depends(get_db), _=Depends(require("routines.edit"))):
    if name not in JOBS:
        raise HTTPException(404)
    j = db.get(JobStatus, name) or JobStatus(name=name, label=JOBS[name][0], interval_s=JOBS[name][1])
    j.enabled = enabled
    db.merge(j)
    audit.log(db, request, "job_toggle", "job", name, detail={"enabled": enabled})
    db.commit()
    return {"ok": True}
