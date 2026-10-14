"""Atendimento por WhatsApp: monitor das filas e chat do analista. Todos os analistas veem e tratam todas as filas."""
import json
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, settings_store as S
from ..db import get_db
from ..models import Client, User, WaConversation, WaMessage
from ..security import require
from ..services import atendimento_service as A, factory
from ..services.wa_akg_service import WaAkgError

router = APIRouter(prefix="/atendimento", tags=["atendimento"])
MEDIA_MAX = 15 * 1024 * 1024
MEDIA_OK = ("image/", "application/pdf", "application/vnd.", "application/msword", "text/plain")


def _wait(c: WaConversation) -> int:
    ref = c.queued_at if c.state == "aguardando" else c.menu_sent_at if c.state == "menu" else None
    return max(0, int((datetime.now(timezone.utc) - ref).total_seconds())) if ref else 0


def _out(db: Session, rows: list[WaConversation]) -> list[dict]:
    ids = [c.id for c in rows]
    users = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_([c.assigned_to for c in rows if c.assigned_to] or [0]))).all()}
    clients = {c.id: c for c in db.scalars(select(Client).where(Client.id.in_([c.client_id for c in rows if c.client_id] or [0]))).all()}
    last = {}
    if ids:
        mx = db.execute(select(func.max(WaMessage.id)).where(WaMessage.conversation_id.in_(ids)).group_by(WaMessage.conversation_id)).scalars().all()
        for m in db.execute(select(WaMessage.conversation_id, WaMessage.text, WaMessage.type).where(WaMessage.id.in_(mx or [0]))).all():
            last[m[0]] = m[1] or f"[{(m[2] or '').lower()}]"
    return [{"id": c.id, "jid": c.jid, "number": c.jid.split("@")[0], "name": c.push_name, "queue": c.queue, "state": c.state,
             "assigned_to": c.assigned_to, "assigned_name": users.get(c.assigned_to), "unread": c.unread or 0,
             "client": ({"id": clients[c.client_id].id, "name": clients[c.client_id].trade_name, "cnpj": clients[c.client_id].cnpj}
                        if c.client_id in clients else None),
             "queued_at": c.queued_at, "wait_seconds": _wait(c), "last_message_at": c.last_message_at, "last_text": last.get(c.id, "")} for c in rows]


def _conv(db: Session, conv_id: int) -> WaConversation:
    c = db.get(WaConversation, conv_id)
    if not c:
        raise HTTPException(404, "Conversa não encontrada")
    return c


@router.get("/queues")
def queues(db: Session = Depends(get_db), _=Depends(require("atendimento.view"))):
    rows = db.execute(select(WaConversation.queue, WaConversation.state, func.count(), func.min(WaConversation.queued_at))
                      .where(WaConversation.state.in_(("aguardando", "atendendo"))).group_by(WaConversation.queue, WaConversation.state)).all()
    out = {q: {"queue": q, "label": A.LABEL[q], "waiting": 0, "active": 0, "oldest_seconds": 0} for q in A.QUEUES}
    now = datetime.now(timezone.utc)
    for q, st, n, oldest in rows:
        if q not in out:
            continue
        if st == "aguardando":
            out[q]["waiting"] = n
            out[q]["oldest_seconds"] = max(0, int((now - oldest).total_seconds())) if oldest else 0
        else:
            out[q]["active"] = n
    return {"queues": list(out.values()), "wait_alert_min": A.cfg(db)["wait_alert_min"]}


@router.get("/conversations")
def conversations(queue: str = "", state: str = "", mine: bool = False, db: Session = Depends(get_db), user: User = Depends(require("atendimento.view"))):
    stmt = select(WaConversation)
    stmt = stmt.where(WaConversation.state == state) if state in ("menu", "aguardando", "atendendo", "encerrada") else stmt.where(WaConversation.state != "encerrada")
    if queue in A.QUEUES:
        stmt = stmt.where(WaConversation.queue == queue)
    if mine:
        stmt = stmt.where(WaConversation.assigned_to == user.id)
    rows = db.scalars(stmt.order_by(WaConversation.queued_at.asc().nulls_last(), WaConversation.id.desc()).limit(200)).all()
    return _out(db, list(rows))


@router.get("/conversations/{conv_id}/messages")
def messages(conv_id: int, since: int = 0, db: Session = Depends(get_db), _=Depends(require("atendimento.view"))):
    c = _conv(db, conv_id)
    rows = db.scalars(select(WaMessage).where(WaMessage.conversation_id == conv_id, WaMessage.id > since).order_by(WaMessage.id).limit(500)).all()
    if c.unread:
        c.unread = 0
        db.commit()
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_([m.sent_by for m in rows if m.sent_by] or [0]))).all()}
    return {"conversation": _out(db, [c])[0],
            "messages": [{"id": m.id, "direction": m.direction, "type": m.type, "text": m.text, "has_media": bool(m.media_ref),
                          "failed": m.failed, "sent_by": names.get(m.sent_by), "created_at": m.created_at} for m in rows]}


@router.get("/messages/{msg_id}/media")
def media(msg_id: int, db: Session = Depends(get_db), _=Depends(require("atendimento.view"))):
    m = db.get(WaMessage, msg_id)
    if not m or not m.media_ref:
        raise HTTPException(404, "Mídia não encontrada")
    base = S.get(db, "wa_akg.url").rstrip("/")
    url = m.media_ref if m.media_ref.startswith("http") else base + "/" + m.media_ref.lstrip("/")
    if not url.startswith(base):
        raise HTTPException(404, "Mídia não encontrada")  # nunca busca em host externo (SSRF)
    try:
        r = httpx.get(url, headers={"X-API-Key": S.get(db, "wa_akg.api_key")}, timeout=30)
    except httpx.HTTPError:
        raise HTTPException(502, "Gateway indisponível")
    if r.status_code != 200:
        raise HTTPException(404, "Mídia indisponível")
    return Response(r.content, media_type=r.headers.get("content-type", "application/octet-stream"), headers={"X-Content-Type-Options": "nosniff"})


@router.post("/conversations/{conv_id}/assume")
def assume(conv_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("atendimento.act"))):
    c = _conv(db, conv_id)
    if not A.assume(db, conv_id, user.id):
        raise HTTPException(409, "Esta conversa já foi assumida ou encerrada")
    audit.log(db, request, "atendimento_assumir", "whatsapp", resource_id=c.jid)
    db.commit()
    db.refresh(c)
    return _out(db, [c])[0]


class TransferIn(BaseModel):
    user_id: int | None = None
    queue: str | None = Field(default=None, pattern="^(comercial|financeiro|suporte|geral)$")


@router.post("/conversations/{conv_id}/transfer")
def transfer(conv_id: int, body: TransferIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("atendimento.act"))):
    c = _conv(db, conv_id)
    if c.state == "encerrada":
        raise HTTPException(409, "Conversa encerrada")
    if body.user_id:
        dest = db.get(User, body.user_id)
        if not dest or not dest.active or dest.role == "CLIENTE":
            raise HTTPException(422, "Analista inválido")
    if not body.user_id and not body.queue:
        raise HTTPException(422, "Informe o analista ou o setor")
    A.transfer(db, c, body.user_id, body.queue, factory.wa_akg(db))
    audit.log(db, request, "atendimento_transferir", "whatsapp", resource_id=c.jid, detail={"user_id": body.user_id, "queue": body.queue})
    db.commit()
    return _out(db, [c])[0]


class CloseIn(BaseModel):
    send_closing: bool = True


@router.post("/conversations/{conv_id}/close")
def close(conv_id: int, body: CloseIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("atendimento.act"))):
    c = _conv(db, conv_id)
    if c.state == "encerrada":
        raise HTTPException(409, "Conversa já encerrada")
    A.close(db, c, user.id, body.send_closing, factory.wa_akg(db))
    audit.log(db, request, "atendimento_encerrar", "whatsapp", resource_id=c.jid)
    db.commit()
    return _out(db, [c])[0]


class LinkIn(BaseModel):
    client_id: int | None = None


@router.post("/conversations/{conv_id}/link-client")
def link_client(conv_id: int, body: LinkIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("atendimento.act"))):
    c = _conv(db, conv_id)
    if body.client_id and not db.get(Client, body.client_id):
        raise HTTPException(422, "Cliente inválido")
    c.client_id = body.client_id
    audit.log(db, request, "atendimento_vincular", "whatsapp", resource_id=c.jid, detail={"client_id": body.client_id})
    db.commit()
    return _out(db, [c])[0]


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _open_conv(db: Session, conv_id: int) -> WaConversation:
    c = _conv(db, conv_id)
    if c.state == "encerrada":
        raise HTTPException(409, "Conversa encerrada")
    return c


@router.post("/conversations/{conv_id}/send")
def send(conv_id: int, body: SendIn, db: Session = Depends(get_db), user: User = Depends(require("atendimento.act"))):
    c = _open_conv(db, conv_id)
    try:
        m = A.send(db, c, user.id, body.text.strip(), factory.wa_akg(db))
    except WaAkgError:
        db.commit()  # guarda a mensagem como "nao enviada" para o analista reenviar
        raise HTTPException(502, "Não foi possível enviar pelo WhatsApp. A mensagem ficou marcada como não enviada.")
    db.commit()
    return {"id": m.id}


@router.post("/conversations/{conv_id}/send-media")
async def send_media(conv_id: int, caption: str = Form(default="", max_length=1000), file: UploadFile = File(...),
                     db: Session = Depends(get_db), user: User = Depends(require("atendimento.act"))):
    c = _open_conv(db, conv_id)
    mime = (file.content_type or "application/octet-stream").lower()
    if not mime.startswith(MEDIA_OK):
        raise HTTPException(422, "Tipo de arquivo não permitido")
    data = await file.read(MEDIA_MAX + 1)
    if len(data) > MEDIA_MAX:
        raise HTTPException(413, "Arquivo maior que 15 MB")
    try:
        m = A.send_media(db, c, user.id, data, file.filename or "arquivo", mime, caption, factory.wa_akg(db))
    except WaAkgError:
        db.commit()
        raise HTTPException(502, "Não foi possível enviar pelo WhatsApp.")
    db.commit()
    return {"id": m.id}


class QueueCfg(BaseModel):
    alert_enabled: bool = False
    alert_to: list[str] = Field(default_factory=list, max_length=10)


class CfgIn(BaseModel):
    greeting: str = Field(min_length=1, max_length=1000)
    menu_timeout_min: int = Field(ge=1, le=60)
    wait_alert_min: int = Field(ge=1, le=240)
    closing_message: str = Field(max_length=500)
    queues: dict[str, QueueCfg]


@router.get("/config")
def get_config(db: Session = Depends(get_db), _=Depends(require("atendimento.view"))):
    return A.cfg(db)


@router.put("/config")
def put_config(body: CfgIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("settings.edit"))):
    data = body.model_dump()
    data["queues"] = {q: {"alert_enabled": bool(v["alert_enabled"]), "alert_to": [x.strip() for x in v["alert_to"] if x.strip()]}
                      for q, v in data["queues"].items() if q in A.QUEUES}
    S.put(db, "atendimento.config", json.dumps(data), user=user.email)
    audit.log(db, request, "atendimento_config", "whatsapp")
    db.commit()
    return A.cfg(db)
