from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Client, Dispatch, Event
from ..security import require
from ..services import silence_service as SS
from ..util import by_client, parse_dt, to_dict

router = APIRouter(prefix="/events", tags=["events"])


class NoteIn(BaseModel):
    notes: str | None = None


@router.get("")
def list_events(kind: str | None = None, status: str | None = None, client_id: int | None = None, hostid: str | None = None, q: str | None = None,
                min_severity: int | None = None, since: str | None = None, until: str | None = None, silenced: str | None = None, page: int = 1,
                size: int = 50, db: Session = Depends(get_db), _=Depends(require("events.view"))):
    stmt = select(Event)
    if kind:
        stmt = stmt.where(Event.kind == kind)
    if status:
        stmt = stmt.where(Event.status == status.upper())
    if client_id:
        stmt = stmt.where(by_client(Event.client_id, client_id))
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
        stmt = stmt.where(Event.host.ilike(like) | Event.trigger_name.ilike(like) | Event.ip.ilike(like) | Event.item_name.ilike(like)
                          | Event.client_id.in_(select(Client.id).where(Client.trade_name.ilike(like))))
    sils = SS.active(db)
    cl = SS.clause(sils)
    if silenced in ("hide", "only") and cl is not None:
        stmt = stmt.where(~cl if silenced == "hide" else cl)
    elif silenced == "only":
        stmt = stmt.where(Event.id < 0)  # nao ha silencios: nada a mostrar
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Event.started_at.desc()).offset((page - 1) * size).limit(min(size, 200)))
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    return {"total": total, "items": [to_dict(e) | {"client_name": names.get(e.client_id), "silenced": _sil(SS.match(db, e, sils))} for e in rows]}


def _sil(s):
    return {"id": s.id, "until": s.until, "reason": s.reason, "scope": s.scope} if s else None


@router.get("/summary")
def summary(kind: str | None = None, client_id: int | None = None, db: Session = Depends(get_db), _=Depends(require("events.view"))):
    """Problemas em aberto por severidade (os silenciados contados a parte)."""
    base = select(Event.severity, func.count()).where(Event.status == "PROBLEM")
    if kind:
        base = base.where(Event.kind == kind)
    if client_id:
        base = base.where(by_client(Event.client_id, client_id))
    cl = SS.clause(SS.active(db))
    live = dict(db.execute((base.where(~cl) if cl is not None else base).group_by(Event.severity)).all())
    muted = sum(dict(db.execute(base.where(cl).group_by(Event.severity)).all()).values()) if cl is not None else 0
    return {"by_severity": {str(k): v for k, v in live.items()}, "open": sum(live.values()), "silenced": muted}


@router.get("/{eid}")
def get_event(eid: int, db: Session = Depends(get_db), _=Depends(require("events.view"))):
    e = db.get(Event, eid)
    if not e:
        raise HTTPException(404)
    d = to_dict(e)
    c = db.get(Client, e.client_id) if e.client_id else None
    d["client_name"] = c.trade_name if c else None
    d["dispatches"] = [to_dict(x) for x in db.scalars(select(Dispatch).where(Dispatch.event_id == eid).order_by(Dispatch.id))]
    d["silenced"] = _sil(SS.match(db, e))
    d["recurrence"] = _recurrence(db, e)
    return d


def _recurrence(db: Session, e: Event) -> dict:
    """Quantas vezes o mesmo problema ocorreu neste host (ajuda a ver oscilacao e reincidencia)."""
    if not e.host or not (e.triggerid or e.trigger_name):
        return {"last_7d": 0, "last_30d": 0}
    same = [Event.host == e.host, (Event.triggerid == e.triggerid) if e.triggerid else (Event.trigger_name == e.trigger_name)]
    now = datetime.now(timezone.utc)
    n = lambda days: db.scalar(select(func.count()).select_from(Event).where(*same, Event.started_at >= now - timedelta(days=days))) or 0  # noqa: E731
    return {"last_7d": n(7), "last_30d": n(30)}


@router.put("/{eid}/notes")
def notes(eid: int, body: NoteIn, request: Request, db: Session = Depends(get_db), _=Depends(require("events.edit"))):
    e = db.get(Event, eid)
    if not e:
        raise HTTPException(404)
    e.notes = body.notes
    audit.log(db, request, "event_note", "event", eid)
    db.commit()
    return {"ok": True}
