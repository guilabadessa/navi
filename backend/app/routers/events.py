from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Dispatch, Event
from ..security import require
from ..util import parse_dt, to_dict

router = APIRouter(prefix="/events", tags=["events"])


class NoteIn(BaseModel):
    notes: str | None = None


@router.get("")
def list_events(status: str | None = None, client_id: int | None = None, hostid: str | None = None, q: str | None = None,
                min_severity: int | None = None, since: str | None = None, until: str | None = None, page: int = 1,
                size: int = 50, db: Session = Depends(get_db), _=Depends(require("events.view"))):
    stmt = select(Event)
    if status:
        stmt = stmt.where(Event.status == status.upper())
    if client_id:
        stmt = stmt.where(Event.client_id == client_id)
    if hostid:
        stmt = stmt.where(Event.hostid == hostid)
    if min_severity is not None:
        stmt = stmt.where(Event.severity >= min_severity)
    if since:
        stmt = stmt.where(Event.started_at >= parse_dt(since))
    if until:
        stmt = stmt.where(Event.started_at < parse_dt(until))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Event.host.ilike(like) | Event.trigger_name.ilike(like) | Event.ip.ilike(like) | Event.item_name.ilike(like))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Event.started_at.desc()).offset((page - 1) * size).limit(min(size, 200)))
    return {"total": total, "items": [to_dict(e) for e in rows]}


@router.get("/{eid}")
def get_event(eid: int, db: Session = Depends(get_db), _=Depends(require("events.view"))):
    e = db.get(Event, eid)
    if not e:
        raise HTTPException(404)
    d = to_dict(e)
    d["dispatches"] = [to_dict(x) for x in db.scalars(select(Dispatch).where(Dispatch.event_id == eid).order_by(Dispatch.id))]
    return d


@router.put("/{eid}/notes")
def notes(eid: int, body: NoteIn, request: Request, db: Session = Depends(get_db), _=Depends(require("events.edit"))):
    e = db.get(Event, eid)
    if not e:
        raise HTTPException(404)
    e.notes = body.notes
    audit.log(db, request, "event_note", "event", eid)
    db.commit()
    return {"ok": True}
