"""Silenciar alertas pela tela de Eventos (host e/ou problema, por tempo ou para sempre) e reativar depois."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Event, EventSilence
from ..security import require
from ..services import silence_service as SS

router = APIRouter(prefix="/event-silences", tags=["events"])
SCOPE_LABEL = {"host": "Todos os problemas do host", "problem_host": "Este problema neste host", "problem": "Este problema em todos os hosts"}


def out(db: Session, s: EventSilence) -> dict:
    n = db.scalar(select(func.count()).select_from(Event).where(Event.status == "PROBLEM", SS.clause([s]))) if SS.clause([s]) is not None else 0
    return {"id": s.id, "scope": s.scope, "scope_label": SCOPE_LABEL.get(s.scope, s.scope), "kind": s.kind, "host": s.host, "triggerid": s.triggerid,
            "trigger_name": s.trigger_name, "until": s.until, "reason": s.reason, "created_by": s.created_by, "created_at": s.created_at,
            "ignored_asset": bool(s.asset_id), "open_events": n or 0}


@router.get("")
def list_silences(include_expired: bool = False, db: Session = Depends(get_db), _=Depends(require("events.view"))):
    rows = db.scalars(select(EventSilence).order_by(EventSilence.id.desc()).limit(500)).all() if include_expired else SS.active(db)
    return [out(db, s) for s in rows]


class SilenceIn(BaseModel):
    event_ids: list[int] = Field(min_length=1, max_length=200)
    scope: str = Field(pattern="^(host|problem_host|problem)$")
    hours: int | None = Field(default=None, ge=1, le=8760)  # vazio = permanente
    reason: str | None = Field(default=None, max_length=255)


@router.post("")
def create_silence(body: SilenceIn, request: Request, db: Session = Depends(get_db), user=Depends(require("events.edit"))):
    evs = db.scalars(select(Event).where(Event.id.in_(body.event_ids))).all()
    if not evs:
        raise HTTPException(404, "Evento não encontrado")
    made: dict[int, EventSilence] = {}
    for ev in evs:
        try:
            s = SS.create(db, ev, body.scope, body.hours, body.reason, user.email)
        except ValueError as e:
            raise HTTPException(422, str(e))
        made[id(s)] = s
    audit.log(db, request, "event_silence", "event", detail={"eventos": len(evs), "escopo": body.scope, "horas": body.hours, "motivo": body.reason})
    db.commit()
    return [out(db, s) for s in made.values()]


@router.delete("/{sid}")
def remove_silence(sid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("events.edit"))):
    s = db.get(EventSilence, sid)
    if not s:
        raise HTTPException(404, "Silêncio não encontrado")
    audit.log(db, request, "event_silence_remove", "event", sid, detail={"host": s.host, "problema": s.trigger_name or s.triggerid})
    SS.remove(db, s)
    db.commit()
    return {"ok": True}
