"""Inscricao em notificacoes push do app (por usuario/aparelho)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import PushSub, User
from ..security import current_user
from ..services import push_service

router = APIRouter(prefix="/push", tags=["push"])


class SubIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1024)
    p256dh: str = Field(min_length=10, max_length=255)
    auth: str = Field(min_length=4, max_length=64)


class EndpointIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1024)


@router.get("/key")
def key(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"key": push_service.vapid_keys(db)[1], "devices": db.query(PushSub).filter(PushSub.user_id == user.id).count()}


@router.post("/subscribe")
def subscribe(body: SubIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not body.endpoint.startswith("https://"):
        raise HTTPException(400, "Endpoint inválido")
    s = db.scalar(select(PushSub).where(PushSub.endpoint == body.endpoint))
    if s is None:
        s = PushSub(endpoint=body.endpoint)
        db.add(s)
    s.user_id, s.p256dh, s.auth, s.ua = user.id, body.p256dh, body.auth, (request.headers.get("user-agent") or "")[:255]
    db.commit()
    return {"ok": True}


@router.post("/unsubscribe")
def unsubscribe(body: EndpointIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.execute(delete(PushSub).where(PushSub.endpoint == body.endpoint, PushSub.user_id == user.id))
    db.commit()
    return {"ok": True}


@router.post("/test")
def test(db: Session = Depends(get_db), user: User = Depends(current_user)):
    subs = list(db.scalars(select(PushSub).where(PushSub.user_id == user.id)))
    if not subs:
        raise HTTPException(400, "Nenhum aparelho inscrito")
    n = sum(push_service.send(db, s, {"title": "NAVI", "body": "Notificações ativadas neste aparelho.", "url": "/cliente/", "tag": "test"}) for s in subs)
    db.commit()
    if not n:
        raise HTTPException(502, "O serviço de push não aceitou o envio")
    return {"sent": n}
