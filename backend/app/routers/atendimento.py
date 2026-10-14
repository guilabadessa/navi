"""Atendimento por WhatsApp: monitor das filas e chat do analista. Todos os analistas veem e tratam todas as filas."""
import json
import re
import unicodedata
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, settings_store as S
from ..db import get_db
from ..models import TICKET_OPEN_STATUSES, Client, Ticket, User, WaConversation, WaMessage, WaQueue, WaTag
from ..security import require
from ..services import atendimento_service as A, factory, flow_service as FS
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
    open_t: dict[int, list] = {}
    for t in db.scalars(select(Ticket).where(Ticket.client_id.in_(list(clients) or [0]), Ticket.status.in_(TICKET_OPEN_STATUSES), Ticket.internal.is_(False))
                        .order_by(Ticket.id.desc()).limit(200)).all():
        if len(open_t.setdefault(t.client_id, [])) < 3:
            open_t[t.client_id].append({"id": t.id, "number": t.number, "subject": t.subject, "status": t.status})
    last = {}
    if ids:
        mx = db.execute(select(func.max(WaMessage.id)).where(WaMessage.conversation_id.in_(ids)).group_by(WaMessage.conversation_id)).scalars().all()
        for m in db.execute(select(WaMessage.conversation_id, WaMessage.text, WaMessage.type).where(WaMessage.id.in_(mx or [0]))).all():
            last[m[0]] = m[1] or f"[{(m[2] or '').lower()}]"
    qm = A.queue_map(db)
    return [{"id": c.id, "jid": c.jid, "number": c.jid.split("@")[0], "name": c.contact_name or c.push_name, "queue": c.queue,
             "queue_name": qm[c.queue].name if c.queue in qm else c.queue, "queue_color": qm[c.queue].color if c.queue in qm else "#6b7a99",
             "tags": c.tags or [], "state": c.state,
             "assigned_to": c.assigned_to, "assigned_name": users.get(c.assigned_to), "unread": c.unread or 0,
             "client": ({"id": clients[c.client_id].id, "name": clients[c.client_id].trade_name, "cnpj": clients[c.client_id].cnpj, "tickets": open_t.get(c.client_id, [])}
                        if c.client_id in clients else None),
             "queued_at": c.queued_at, "wait_seconds": _wait(c), "last_message_at": c.last_message_at, "last_text": last.get(c.id, "")} for c in rows]


def _conv(db: Session, conv_id: int) -> WaConversation:
    c = db.get(WaConversation, conv_id)
    if not c:
        raise HTTPException(404, "Conversa não encontrada")
    return c


@router.get("/queues")
def queues(db: Session = Depends(get_db), _=Depends(require("atendimento.view"))):
    """Monitor: uma linha por fila ativa, na ordem configurada."""
    rows = db.execute(select(WaConversation.queue, WaConversation.state, func.count(), func.min(WaConversation.queued_at))
                      .where(WaConversation.state.in_(("aguardando", "atendendo"))).group_by(WaConversation.queue, WaConversation.state)).all()
    geral = A.cfg(db)["wait_alert_min"]
    out = {q.slug: {"queue": q.slug, "label": q.name, "color": q.color, "waiting": 0, "active": 0, "oldest_seconds": 0, "alert_min": q.wait_alert_min or geral}
           for q in A.queue_map(db).values() if q.active}
    now = datetime.now(timezone.utc)
    for q, st, n, oldest in rows:
        if q not in out:
            continue
        if st == "aguardando":
            out[q]["waiting"] = n
            out[q]["oldest_seconds"] = max(0, int((now - oldest).total_seconds())) if oldest else 0
        else:
            out[q]["active"] = n
    return {"queues": list(out.values()), "wait_alert_min": geral}


def _slugify(name: str) -> str:
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40] or "fila"


class QueueIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#1e73f8", pattern=r"^#[0-9a-fA-F]{6}$")
    active: bool = True
    alert_enabled: bool = False
    alert_to: list[str] = Field(default_factory=list, max_length=10)
    wait_alert_min: int | None = Field(default=None, ge=1, le=240)


def _queue_out(q: WaQueue, open_n: int = 0) -> dict:
    return {"id": q.id, "slug": q.slug, "name": q.name, "color": q.color, "sort": q.sort, "active": q.active, "system": q.system,
            "alert_enabled": q.alert_enabled, "alert_to": q.alert_to or [], "wait_alert_min": q.wait_alert_min, "open": open_n}


def _clean_dests(v: list[str]) -> list[str]:
    return [x.strip() for x in v if x and x.strip()]


@router.get("/queue-defs")
def queue_defs(db: Session = Depends(get_db), _=Depends(require("atendimento.view"))):
    counts = dict(db.execute(select(WaConversation.queue, func.count()).where(WaConversation.state != "encerrada").group_by(WaConversation.queue)).all())
    return [_queue_out(q, counts.get(q.slug, 0)) for q in db.scalars(select(WaQueue).order_by(WaQueue.sort, WaQueue.id)).all()]


@router.post("/queue-defs")
def queue_create(body: QueueIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("settings.edit"))):
    taken = set(db.scalars(select(WaQueue.slug)).all())
    base = slug = _slugify(body.name)
    n = 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    nxt = (db.scalar(select(func.max(WaQueue.sort))) or 0) + 1
    q = WaQueue(slug=slug, name=body.name.strip(), color=body.color, sort=nxt, active=body.active, alert_enabled=body.alert_enabled,
                alert_to=_clean_dests(body.alert_to), wait_alert_min=body.wait_alert_min)
    db.add(q)
    audit.log(db, request, "atendimento_fila_criar", "whatsapp", resource_id=slug)
    db.commit()
    return _queue_out(q)


class OrderIn(BaseModel):
    ids: list[int] = Field(max_length=100)


@router.put("/queue-defs/order")
def queue_order(body: OrderIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("settings.edit"))):
    by = {q.id: q for q in db.scalars(select(WaQueue)).all()}
    for i, qid in enumerate(body.ids):
        if qid in by:
            by[qid].sort = i
    audit.log(db, request, "atendimento_fila_ordem", "whatsapp")
    db.commit()
    return {"ok": True}


def _queue(db: Session, qid: int) -> WaQueue:
    q = db.get(WaQueue, qid)
    if not q:
        raise HTTPException(404, "Fila não encontrada")
    return q


@router.put("/queue-defs/{qid}")
def queue_update(qid: int, body: QueueIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("settings.edit"))):
    q = _queue(db, qid)
    if q.system and not body.active:
        raise HTTPException(409, "A fila Geral é do sistema e não pode ser desativada")
    q.name, q.color, q.active, q.alert_enabled = body.name.strip(), body.color, body.active, body.alert_enabled  # o slug nunca muda
    q.alert_to, q.wait_alert_min = _clean_dests(body.alert_to), body.wait_alert_min
    audit.log(db, request, "atendimento_fila_editar", "whatsapp", resource_id=q.slug)
    db.commit()
    return _queue_out(q)


@router.delete("/queue-defs/{qid}")
def queue_delete(qid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("settings.edit"))):
    q = _queue(db, qid)
    if q.system:
        raise HTTPException(409, "A fila Geral é do sistema e não pode ser excluída")
    n = db.scalar(select(func.count()).select_from(WaConversation).where(WaConversation.queue == q.slug, WaConversation.state != "encerrada")) or 0
    if n:
        raise HTTPException(409, f"Há {n} conversa(s) aberta(s) nesta fila. Transfira ou encerre antes de excluir.")
    definition, _is_default = FS.load_flow(db, A.cfg(db)["greeting"], int(A.cfg(db)["menu_timeout_min"]), list(A.queue_map(db)))
    uso = [x["id"] for x in definition.get("nodes", []) if x.get("type") == "enqueue" and (x.get("data") or {}).get("queue") == q.slug]
    if uso:
        raise HTTPException(409, "A fila é usada no fluxo de atendimento (passo: " + ", ".join(uso) + "). Troque a fila nesses passos antes de excluir.")
    audit.log(db, request, "atendimento_fila_excluir", "whatsapp", resource_id=q.slug)
    db.delete(q)
    db.commit()
    return {"ok": True}


@router.get("/agents")
def agents(db: Session = Depends(get_db), _=Depends(require("atendimento.view"))):
    """Analistas que podem receber uma transferencia."""
    rows = db.scalars(select(User).where(User.active.is_(True), User.role.in_(("ADMIN", "GESTOR", "ANALISTA_NOC"))).order_by(User.name)).all()
    return [{"id": u.id, "name": u.name} for u in rows]


@router.get("/conversations")
def conversations(queue: str = "", state: str = "", mine: bool = False, db: Session = Depends(get_db), user: User = Depends(require("atendimento.view"))):
    stmt = select(WaConversation)
    stmt = stmt.where(WaConversation.state == state) if state in ("menu", "aguardando", "atendendo", "encerrada") else stmt.where(WaConversation.state != "encerrada")
    if queue:
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
    queue: str | None = Field(default=None, max_length=40)


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
    if body.queue and (body.queue not in A.queue_map(db) or not A.queue_map(db)[body.queue].active):
        raise HTTPException(422, "Setor inválido")
    A.transfer(db, c, body.user_id, body.queue, factory.whatsapp(db))
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
    A.close(db, c, user.id, body.send_closing, factory.whatsapp(db))
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
        m = A.send(db, c, user.id, body.text.strip(), factory.whatsapp(db))
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
        m = A.send_media(db, c, user.id, data, file.filename or "arquivo", mime, caption, factory.whatsapp(db))
    except WaAkgError:
        db.commit()
        raise HTTPException(502, "Não foi possível enviar pelo WhatsApp.")
    db.commit()
    return {"id": m.id}


class QueueCfg(BaseModel):
    alert_enabled: bool = False
    alert_to: list[str] = Field(default_factory=list, max_length=10)


class QuickReply(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=1000)


class CfgIn(BaseModel):
    greeting: str = Field(min_length=1, max_length=1000)
    menu_timeout_min: int = Field(ge=1, le=60)
    wait_alert_min: int = Field(ge=1, le=240)
    closing_message: str = Field(max_length=500)
    inactivity_hours: int = Field(default=24, ge=0, le=720)
    inactivity_message: str = Field(default="", max_length=500)
    quick_replies: list[QuickReply] = Field(default_factory=list, max_length=50)


@router.get("/config")
def get_config(db: Session = Depends(get_db), _=Depends(require("atendimento.view"))):
    return A.cfg(db)


@router.put("/config")
def put_config(body: CfgIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("settings.edit"))):
    S.put(db, "atendimento.config", json.dumps(body.model_dump()), user=user.email)
    audit.log(db, request, "atendimento_config", "whatsapp")
    db.commit()
    return A.cfg(db)


# ---- Fluxo (diagrama BPMN editavel) ----
class FlowIn(BaseModel):
    definition: dict


class SimIn(BaseModel):
    definition: dict
    inputs: list[str] = Field(default_factory=list, max_length=30)


def _active_slugs(db: Session) -> list[str]:
    return [q.slug for q in A.queue_map(db).values() if q.active]


@router.get("/flow")
def get_flow(db: Session = Depends(get_db), _=Depends(require("atendimento.view"))):
    c = A.cfg(db)
    definition, is_default = FS.load_flow(db, c["greeting"], int(c["menu_timeout_min"]), list(A.queue_map(db)))
    return {"definition": definition, "is_default": is_default,
            "queues": [{"slug": q.slug, "name": q.name, "color": q.color} for q in A.queue_map(db).values() if q.active]}


@router.post("/flow/validate")
def validate_flow(body: FlowIn, db: Session = Depends(get_db), _=Depends(require("atendimento.view"))):
    return {"errors": FS.validate_flow(body.definition, _active_slugs(db))}


@router.put("/flow")
def put_flow(body: FlowIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("settings.edit"))):
    errs = FS.validate_flow(body.definition, _active_slugs(db))
    if errs:
        raise HTTPException(422, "Fluxo inválido: " + "; ".join(e["msg"] for e in errs[:5]))
    FS.save_flow(db, body.definition, user.email)
    audit.log(db, request, "atendimento_fluxo", "whatsapp", detail={"passos": len(body.definition.get("nodes", []))})
    db.commit()
    return {"ok": True}


@router.post("/flow/reset")
def reset_flow(request: Request, db: Session = Depends(get_db), user: User = Depends(require("settings.edit"))):
    FS.reset_flow(db)
    audit.log(db, request, "atendimento_fluxo_padrao", "whatsapp")
    db.commit()
    c = A.cfg(db)
    return {"definition": FS.default_flow(c["greeting"], int(c["menu_timeout_min"]))}


@router.post("/flow/simulate")
def simulate_flow(body: SimIn, db: Session = Depends(get_db), _=Depends(require("atendimento.view"))):
    """Roda o fluxo com respostas de teste. Consulta o cliente de verdade; nada e enviado e nenhum chamado e criado."""
    return FS.simulate(db, body.definition, [x[:500] for x in body.inputs], _active_slugs(db))
