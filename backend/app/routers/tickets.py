"""Chamados (helpdesk): fila por tecnologia (equipe define quem e avisado), equipe abre/atualiza para qualquer
cliente, cliente abre/acompanha os proprios pelo portal. Observadores (CC) recebem copia por e-mail ou WhatsApp."""
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..models import (Client, Ticket, TicketAttachment, TicketMessage, TicketQueue, TicketWatcher, TICKET_ATTACHMENT_EXTS, TICKET_ATTACHMENT_MAX_BYTES,
                      TICKET_OPEN_STATUSES, TICKET_PRIORITIES, TICKET_STATUSES, User)
from ..security import require
from ..services import ticket_service as TS
from ..util import titlecase
from .portal import _client_for

router = APIRouter(tags=["tickets"])
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _attach_dir(tid: int) -> Path:
    d = Path(get_settings().NAVI_STORAGE) / "tickets" / str(tid)
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _save_attachment(db: Session, t: Ticket, file: UploadFile, author_id: int | None, author_name: str | None, origin: str) -> TicketMessage:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in TICKET_ATTACHMENT_EXTS:
        raise HTTPException(422, f"Tipo de arquivo não permitido. Use: {', '.join(TICKET_ATTACHMENT_EXTS)}")
    data = await file.read(TICKET_ATTACHMENT_MAX_BYTES + 1)
    if len(data) > TICKET_ATTACHMENT_MAX_BYTES:
        raise HTTPException(413, f"Arquivo maior que {TICKET_ATTACHMENT_MAX_BYTES // (1024 * 1024)} MB.")
    safe = _SAFE_NAME.sub("_", Path(file.filename or "arquivo").name)[:150]
    stored = _attach_dir(t.id) / f"{uuid.uuid4().hex}_{safe}"
    stored.write_bytes(data)
    m = TicketMessage(ticket_id=t.id, author_id=author_id, author_name=author_name, origin=origin, body=f"📎 Anexo: {safe}", notified=True)
    db.add(m)
    db.flush()
    db.add(TicketAttachment(ticket_id=t.id, message_id=m.id, filename=safe, stored_path=str(stored), content_type=file.content_type, size_bytes=len(data)))
    return m


# ---------------- filas (somente ADMIN: define quem e avisado por tecnologia) ----------------
class QueueIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    notify_emails: str | None = Field(default=None, max_length=2000)
    notify_wa_jid: str | None = Field(default=None, max_length=128)
    active: bool = True
    sort: int = 0


def _queue_out(q: TicketQueue) -> dict:
    return {"id": q.id, "name": q.name, "notify_emails": q.notify_emails, "notify_wa_jid": q.notify_wa_jid, "active": q.active, "sort": q.sort}


@router.get("/tickets/queues")
def list_queues(db: Session = Depends(get_db), _=Depends(require("tickets.view"))):
    return [_queue_out(q) for q in db.scalars(select(TicketQueue).order_by(TicketQueue.sort, TicketQueue.name))]


@router.post("/tickets/queues")
def create_queue(body: QueueIn, request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    if db.scalar(select(TicketQueue.id).where(TicketQueue.name == body.name.strip())):
        raise HTTPException(422, "Já existe uma fila com esse nome.")
    q = TicketQueue(name=body.name.strip(), notify_emails=body.notify_emails, notify_wa_jid=body.notify_wa_jid, active=body.active, sort=body.sort)
    db.add(q)
    db.flush()
    audit.log(db, request, "ticket_queue_create", "ticket_queue", q.id, detail={"nome": q.name})
    db.commit()
    return _queue_out(q)


@router.put("/tickets/queues/{qid}")
def update_queue(qid: int, body: QueueIn, request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    q = db.get(TicketQueue, qid)
    if not q:
        raise HTTPException(404)
    q.name, q.notify_emails, q.notify_wa_jid, q.active, q.sort = body.name.strip(), body.notify_emails, body.notify_wa_jid, body.active, body.sort
    audit.log(db, request, "ticket_queue_update", "ticket_queue", qid, detail={"nome": q.name})
    db.commit()
    return _queue_out(q)


@router.delete("/tickets/queues/{qid}")
def delete_queue(qid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    q = db.get(TicketQueue, qid)
    if q:
        db.delete(q)
        audit.log(db, request, "ticket_queue_delete", "ticket_queue", qid)
        db.commit()
    return {"ok": True}


# ---------------- chamados ----------------
def _msg_out(m: TicketMessage) -> dict:
    a = m.attachment
    return {"id": m.id, "author_name": m.author_name, "origin": m.origin, "internal": m.internal, "body": m.body, "created_at": m.created_at.isoformat(),
            "status_change": m.status_change, "status_change_label": TS.STATUS_LABEL.get(m.status_change) if m.status_change else None,
            "attachment": {"id": a.id, "filename": a.filename, "size_bytes": a.size_bytes} if a else None}


def _ticket_out(t: Ticket, portal: bool = False, names: dict | None = None) -> dict:
    return {"id": t.id, "number": t.number, "client_id": t.client_id, "client": t.client.trade_name if t.client else None,
            "queue_id": t.queue_id, "queue": t.queue.name if t.queue else None, "subject": t.subject, "status": t.status,
            "status_label": TS.STATUS_LABEL.get(t.status, t.status), "priority": t.priority, "priority_label": TS.PRIORITY_LABEL.get(t.priority, t.priority),
            "origin": t.origin, "created_by_name": t.created_by_name, "contact_phone": t.contact_phone, "unit": t.unit, "internal": t.internal,
            "assigned_to_id": t.assigned_to_id, "assigned_to_name": (names or {}).get(t.assigned_to_id),
            "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat(),
            "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            "watchers": [] if portal else [{"id": w.id, "kind": w.kind, "target": w.target, "label": w.label} for w in t.watchers]}


def _messages_q(db: Session, ticket_id: int, portal: bool):
    q = select(TicketMessage).where(TicketMessage.ticket_id == ticket_id)
    if portal:
        q = q.where(TicketMessage.internal.is_(False))
    return list(db.scalars(q.order_by(TicketMessage.id)))


class WatcherIn(BaseModel):
    kind: str = Field(pattern="^(email|whatsapp)$")
    target: str = Field(min_length=3, max_length=255)
    label: str | None = Field(default=None, max_length=120)


class TicketIn(BaseModel):
    client_id: int
    queue_id: int | None = None
    subject: str = Field(min_length=3, max_length=255)
    priority: str = Field(default="media")
    body: str = Field(min_length=1, max_length=8000)
    contact_phone: str | None = Field(default=None, max_length=32)
    unit: str | None = Field(default=None, max_length=120)
    internal: bool = False  # chamado interno: registro so da equipe (nao aparece no portal, nao avisa cliente/fila/CC)
    watchers: list[WatcherIn] = Field(default_factory=list)


class TicketPortalIn(BaseModel):
    queue_id: int | None = None
    subject: str = Field(min_length=3, max_length=255)
    priority: str = Field(default="media")
    body: str = Field(min_length=1, max_length=8000)
    contact_phone: str | None = Field(default=None, max_length=32)
    unit: str | None = Field(default=None, max_length=120)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    internal: bool = False
    notify: bool = True
    status: str | None = None  # mudanca de situacao junto com o comentario (equipe: qualquer situacao; portal: so "resolvido")


class TicketFieldsIn(BaseModel):
    """Fila/prioridade/responsavel: ajustes administrativos que nao mudam a situacao do chamado.
    A situacao so muda junto de um comentario, em POST /tickets/{id}/messages (nunca sem explicacao)."""
    queue_id: int | None = None
    priority: str | None = None
    assigned_to_id: int | None = None
    unit: str | None = Field(default=None, max_length=120)


def _create(db: Session, request: Request, client_id: int, queue_id: int | None, subject: str, priority: str, body: str,
           watchers: list[WatcherIn], user: User, origin: str, contact_phone: str | None = None,
           unit: str | None = None, internal: bool = False) -> Ticket:
    if priority not in TICKET_PRIORITIES:
        raise HTTPException(422, "Prioridade inválida")
    if queue_id and not db.get(TicketQueue, queue_id):
        raise HTTPException(422, "Fila inválida")
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Cliente não encontrado")
    t = Ticket(client_id=client_id, queue_id=queue_id, subject=subject.strip(), priority=priority,  # numero: o banco atribui (sequencia), evita corrida
              origin=origin, created_by_id=user.id, created_by_name=user.name, contact_phone=(contact_phone or None),
              unit=(unit or "").strip() or None, internal=internal,
              status="aberto" if internal else "aguardando_cliente" if origin == "staff" else "aguardando_orca")
    db.add(t)
    db.flush()
    for w in ([] if internal else watchers):  # chamado interno nunca tem observadores (CC)
        db.add(TicketWatcher(ticket_id=t.id, kind=w.kind, target=w.target.strip(), label=titlecase(w.label)))
    has_email_watcher = any(w.kind == "email" for w in watchers)
    if internal:
        pass
    elif origin == "portal" and user.email and not any(w.kind == "email" and w.target.strip().lower() == user.email.lower() for w in watchers):
        db.add(TicketWatcher(ticket_id=t.id, kind="email", target=user.email, label=user.name))  # quem abriu pelo portal recebe copia por padrao
    elif origin == "staff" and client.email and not has_email_watcher:
        db.add(TicketWatcher(ticket_id=t.id, kind="email", target=client.email, label=client.trade_name))  # chamado aberto pela equipe: cliente tambem recebe copia por padrao
    msg = TicketMessage(ticket_id=t.id, author_id=user.id, author_name=user.name, origin=origin, body=body.strip(), notified=True)
    db.add(msg)
    db.flush()
    db.refresh(t)
    audit.log(db, request, "ticket_create", "ticket", t.id, detail={"numero": t.number, "cliente_id": client_id, "origem": origin, "interno": internal})
    db.commit()
    if not internal:
        TS.notify(db, t, "aberto", msg)
    return t


@router.get("/tickets")
def list_tickets(client_id: int | None = None, queue_id: int | None = None, status: str | None = None, assigned_to_id: int | None = None,
                 open_only: bool = False, internal: bool | None = None, db: Session = Depends(get_db), _=Depends(require("tickets.view"))):
    q = select(Ticket)
    if internal is not None:
        q = q.where(Ticket.internal.is_(internal))
    if client_id:
        q = q.where(Ticket.client_id == client_id)
    if queue_id:
        q = q.where(Ticket.queue_id == queue_id)
    if status:
        q = q.where(Ticket.status == status)
    if assigned_to_id:
        q = q.where(Ticket.assigned_to_id == assigned_to_id)
    if open_only:
        q = q.where(Ticket.status.in_(TICKET_OPEN_STATUSES))
    rows = list(db.scalars(q.order_by(Ticket.created_at.desc()).limit(300)))
    names = {u.id: u.name for u in db.scalars(select(User).where(User.role != "CLIENTE"))}
    return [_ticket_out(t, names=names) for t in rows]


@router.get("/tickets/staff")
def list_staff(db: Session = Depends(get_db), _=Depends(require("tickets.view"))):
    """Equipe que pode ser responsavel por um chamado (para o filtro e o campo Responsavel)."""
    rows = db.scalars(select(User).where(User.role != "CLIENTE", User.active.is_(True)).order_by(User.name))
    return [{"id": u.id, "name": u.name} for u in rows]


@router.post("/tickets")
def create_ticket(body: TicketIn, request: Request, db: Session = Depends(get_db), user=Depends(require("tickets.edit"))):
    t = _create(db, request, body.client_id, body.queue_id, body.subject, body.priority, body.body, body.watchers, user, "staff", body.contact_phone, body.unit, body.internal)
    return _ticket_out(t)


@router.get("/tickets/{tid}")
def get_ticket(tid: int, db: Session = Depends(get_db), _=Depends(require("tickets.view"))):
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404)
    names = {t.assigned_to_id: u.name for u in [db.get(User, t.assigned_to_id)] if u} if t.assigned_to_id else {}
    out = _ticket_out(t, names=names)
    out["messages"] = [_msg_out(m) for m in _messages_q(db, tid, False)]
    return out


@router.post("/tickets/{tid}/messages")
def add_message(tid: int, body: MessageIn, request: Request, db: Session = Depends(get_db), user=Depends(require("tickets.edit"))):
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404)
    status_change = None
    if body.status:
        if body.status not in TICKET_STATUSES:
            raise HTTPException(422, "Situação inválida")
        status_change = body.status
    internal = body.internal and not status_change  # mudanca de situacao e sempre visivel ao cliente, nunca so nota interna
    if t.internal:
        internal = True  # chamado interno: tudo e restrito a equipe
    m = TicketMessage(ticket_id=tid, author_id=user.id, author_name=user.name, origin="staff", internal=internal,
                      body=body.body.strip(), notified=(body.notify or bool(status_change)) and not internal, status_change=status_change)
    db.add(m)
    if status_change:
        t.status, t.escalated_at = status_change, None  # mudanca manual explicita, acompanhada do comentario (nunca sem explicacao)
        t.closed_at = datetime.now(timezone.utc) if status_change in ("resolvido", "fechado") else None
    elif not internal and not t.internal and t.status not in ("resolvido", "fechado"):
        t.status, t.escalated_at = "aguardando_cliente", None  # gatilho automatico: equipe respondeu, agora e a vez do cliente (pode ser alterado manualmente)
    t.updated_at = datetime.now(timezone.utc)
    audit.log(db, request, "ticket_message", "ticket", tid, detail={"numero": t.number, "interna": internal, "situacao": status_change})
    db.commit()
    if (body.notify or status_change) and not internal and not t.internal:
        TS.notify(db, t, "encerrado" if status_change in ("resolvido", "fechado") else "atualizado", m)
    return _msg_out(m)


@router.post("/tickets/{tid}/attachments")
async def add_attachment(tid: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(require("tickets.edit"))):
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404)
    m = await _save_attachment(db, t, file, user.id, user.name, "staff")
    if t.internal:
        m.internal = True
    elif t.status not in ("resolvido", "fechado"):
        t.status, t.escalated_at = "aguardando_cliente", None
    t.updated_at = datetime.now(timezone.utc)
    audit.log(db, request, "ticket_attachment", "ticket", tid, detail={"numero": t.number, "arquivo": m.attachment.filename})
    db.commit()
    if not t.internal:
        TS.notify(db, t, "atualizado", m)
    return _msg_out(m)


@router.get("/tickets/{tid}/attachments/{aid}")
def get_attachment(tid: int, aid: int, db: Session = Depends(get_db), _=Depends(require("tickets.view"))):
    a = db.get(TicketAttachment, aid)
    if not a or a.ticket_id != tid:
        raise HTTPException(404)
    return FileResponse(a.stored_path, filename=a.filename, media_type=a.content_type or "application/octet-stream")


@router.put("/tickets/{tid}")
def update_ticket(tid: int, body: TicketFieldsIn, request: Request, db: Session = Depends(get_db), user=Depends(require("tickets.edit"))):
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404)
    if body.priority and body.priority not in TICKET_PRIORITIES:
        raise HTTPException(422, "Prioridade inválida")
    if body.queue_id is not None:
        t.queue_id = body.queue_id or None
    if body.priority:
        t.priority = body.priority
    if body.unit is not None:
        t.unit = body.unit.strip() or None
    if body.assigned_to_id is not None:
        if body.assigned_to_id and not db.get(User, body.assigned_to_id):
            raise HTTPException(422, "Responsável inválido")
        t.assigned_to_id = body.assigned_to_id or None
    t.updated_at = datetime.now(timezone.utc)
    audit.log(db, request, "ticket_update", "ticket", tid, detail={"numero": t.number, "fila_id": body.queue_id, "prioridade": body.priority})
    db.commit()
    names = {t.assigned_to_id: u.name for u in [db.get(User, t.assigned_to_id)] if u} if t.assigned_to_id else {}
    return _ticket_out(t, names=names)


@router.post("/tickets/{tid}/watchers")
def add_watcher(tid: int, body: WatcherIn, request: Request, db: Session = Depends(get_db), _=Depends(require("tickets.edit"))):
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404)
    if t.internal:
        raise HTTPException(422, "Chamado interno não tem observadores (CC): ele não avisa ninguém.")
    w = TicketWatcher(ticket_id=tid, kind=body.kind, target=body.target.strip(), label=titlecase(body.label))
    db.add(w)
    audit.log(db, request, "ticket_watcher_add", "ticket", tid, detail={"tipo": body.kind, "destino": body.target})
    db.commit()
    return {"id": w.id, "kind": w.kind, "target": w.target, "label": w.label}


@router.delete("/tickets/{tid}/watchers/{wid}")
def del_watcher(tid: int, wid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("tickets.edit"))):
    w = db.get(TicketWatcher, wid)
    if w and w.ticket_id == tid:
        db.delete(w)
        audit.log(db, request, "ticket_watcher_del", "ticket", tid, detail={"id": wid})
        db.commit()
    return {"ok": True}


# ---------------- portal do cliente ----------------
@router.get("/portal/tickets/queues")
def portal_queues(db: Session = Depends(get_db), _=Depends(require("portal.tickets"))):
    return [{"id": q.id, "name": q.name} for q in db.scalars(select(TicketQueue).where(TicketQueue.active.is_(True)).order_by(TicketQueue.sort, TicketQueue.name))]


@router.get("/portal/tickets")
def portal_list(client_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(require("portal.tickets"))):
    c = _client_for(db, user, client_id)
    rows = list(db.scalars(select(Ticket).where(Ticket.client_id == c.id, Ticket.internal.is_(False)).order_by(Ticket.created_at.desc()).limit(200)))
    return [_ticket_out(t, portal=True) for t in rows]


@router.post("/portal/tickets")
def portal_create(body: TicketPortalIn, request: Request, client_id: int | None = None, db: Session = Depends(get_db),
                  user: User = Depends(require("portal.tickets"))):
    c = _client_for(db, user, client_id)
    t = _create(db, request, c.id, body.queue_id, body.subject, body.priority, body.body, [], user, "portal", body.contact_phone, body.unit)
    return _ticket_out(t, portal=True)


@router.get("/portal/tickets/{tid}")
def portal_get(tid: int, client_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(require("portal.tickets"))):
    c = _client_for(db, user, client_id)
    t = db.get(Ticket, tid)
    if not t or t.client_id != c.id or t.internal:
        raise HTTPException(404)
    out = _ticket_out(t, portal=True)
    out["messages"] = [_msg_out(m) for m in _messages_q(db, tid, True)]
    return out


@router.post("/portal/tickets/{tid}/messages")
def portal_add_message(tid: int, body: MessageIn, request: Request, client_id: int | None = None, db: Session = Depends(get_db),
                       user: User = Depends(require("portal.tickets"))):
    c = _client_for(db, user, client_id)
    t = db.get(Ticket, tid)
    if not t or t.client_id != c.id or t.internal:
        raise HTTPException(404)
    if t.status in ("resolvido", "fechado"):
        raise HTTPException(409, "Este chamado já foi encerrado. Abra um novo chamado se o problema persistir.")
    if body.status and body.status != "resolvido":
        raise HTTPException(422, "Pelo portal você só pode marcar o chamado como resolvido.")
    status_change = "resolvido" if body.status else None
    m = TicketMessage(ticket_id=tid, author_id=user.id, author_name=user.name, origin="portal", internal=False,
                      body=body.body.strip(), notified=True, status_change=status_change)
    db.add(m)
    if status_change:
        t.status, t.escalated_at, t.closed_at = "resolvido", None, datetime.now(timezone.utc)  # cliente encerrou o proprio chamado, acompanhado do comentario
    else:
        t.status, t.escalated_at = "aguardando_orca", None  # gatilho automatico: cliente respondeu, agora e a vez da equipe (pode ser alterado manualmente)
    t.updated_at = datetime.now(timezone.utc)
    audit.log(db, request, "ticket_message", "ticket", tid, detail={"numero": t.number, "origem": "portal", "situacao": status_change})
    db.commit()
    TS.notify(db, t, "encerrado" if status_change else "atualizado", m)
    return _msg_out(m)


@router.post("/portal/tickets/{tid}/attachments")
async def portal_add_attachment(tid: int, request: Request, file: UploadFile = File(...), client_id: int | None = None, db: Session = Depends(get_db),
                                user: User = Depends(require("portal.tickets"))):
    c = _client_for(db, user, client_id)
    t = db.get(Ticket, tid)
    if not t or t.client_id != c.id or t.internal:
        raise HTTPException(404)
    if t.status in ("resolvido", "fechado"):
        raise HTTPException(409, "Este chamado já foi encerrado. Abra um novo chamado se o problema persistir.")
    m = await _save_attachment(db, t, file, user.id, user.name, "portal")
    t.status, t.escalated_at = "aguardando_orca", None
    t.updated_at = datetime.now(timezone.utc)
    audit.log(db, request, "ticket_attachment", "ticket", tid, detail={"numero": t.number, "arquivo": m.attachment.filename, "origem": "portal"})
    db.commit()
    TS.notify(db, t, "atualizado", m)
    return _msg_out(m)


@router.get("/portal/tickets/{tid}/attachments/{aid}")
def portal_get_attachment(tid: int, aid: int, client_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(require("portal.tickets"))):
    c = _client_for(db, user, client_id)
    t = db.get(Ticket, tid)
    if not t or t.client_id != c.id or t.internal:
        raise HTTPException(404)
    a = db.get(TicketAttachment, aid)
    if not a or a.ticket_id != tid:
        raise HTTPException(404)
    m = db.get(TicketMessage, a.message_id)
    if m and m.internal:
        raise HTTPException(404)
    return FileResponse(a.stored_path, filename=a.filename, media_type=a.content_type or "application/octet-stream")
