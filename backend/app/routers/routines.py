from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, scheduling
from ..db import get_db
from ..jobs import JOBS
from ..models import JobStatus, Report, Schedule
from ..schemas import ScheduleIn
from ..security import require
from ..services import delivery_service, report_service
from ..util import to_dict

router = APIRouter(prefix="/routines", tags=["routines"])


@router.get("/schedules")
def schedules(db: Session = Depends(get_db), _=Depends(require("routines.view"))):
    names = dict(db.execute(select(Report.id, Report.name)).all())
    return [{**to_dict(s), "report_name": names.get(s.report_id)} for s in db.scalars(select(Schedule).order_by(Schedule.name))]


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
    run = report_service.generate(db, rep, me.email, a, b, name_suffix="_manual")
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
