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


class PrefsIn(BaseModel):
    min_sev: int = Field(ge=3, le=5)
    quiet_start: int | None = Field(default=None, ge=0, le=23)
    quiet_end: int | None = Field(default=None, ge=0, le=23)
    recovery: bool = True


def _prefs(u: User) -> dict:
    return {"min_sev": u.push_min_sev or 3, "quiet_start": u.push_quiet_start, "quiet_end": u.push_quiet_end, "recovery": bool(u.push_recovery)}


@router.get("/prefs")
def get_prefs(user: User = Depends(current_user)):
    return _prefs(user)


@router.put("/prefs")
def put_prefs(body: PrefsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    quiet = body.quiet_start is not None and body.quiet_end is not None
    user.push_min_sev, user.push_recovery = body.min_sev, body.recovery
    user.push_quiet_start, user.push_quiet_end = (body.quiet_start, body.quiet_end) if quiet else (None, None)
    db.commit()
    return _prefs(user)


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


class FcmIn(BaseModel):
    token: str = Field(min_length=20, max_length=512)


@router.post("/fcm")
def subscribe_fcm(body: FcmIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Aparelho do app Android (FCM). Guardado como endpoint 'fcm:<token>' na mesma tabela das inscricoes web."""
    ep = "fcm:" + body.token
    s = db.scalar(select(PushSub).where(PushSub.endpoint == ep))
    if s is None:
        s = PushSub(endpoint=ep)
        db.add(s)
    s.user_id, s.p256dh, s.auth, s.ua = user.id, "", "", "app-android"
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
