"""Chamados (helpdesk): fila por tecnologia (equipe define quem e avisado), equipe abre/atualiza para qualquer
cliente, cliente abre/acompanha os proprios pelo portal. Observadores (CC) recebem copia por e-mail ou WhatsApp."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Client, Ticket, TicketMessage, TicketQueue, TicketWatcher, TICKET_OPEN_STATUSES, TICKET_PRIORITIES, TICKET_STATUSES, User
from ..security import require
from ..services import ticket_service as TS
from .portal import _client_for

router = APIRouter(tags=["tickets"])


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
    return {"id": m.id, "author_name": m.author_name, "origin": m.origin, "internal": m.internal, "body": m.body, "created_at": m.created_at.isoformat()}


def _ticket_out(t: Ticket, portal: bool = False) -> dict:
    return {"id": t.id, "number": t.number, "client_id": t.client_id, "client": t.client.trade_name if t.client else None,
            "queue_id": t.queue_id, "queue": t.queue.name if t.queue else None, "subject": t.subject, "status": t.status,
            "status_label": TS.STATUS_LABEL.get(t.status, t.status), "priority": t.priority, "priority_label": TS.PRIORITY_LABEL.get(t.priority, t.priority),
            "origin": t.origin, "created_by_name": t.created_by_name, "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat(),
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
    watchers: list[WatcherIn] = Field(default_factory=list)


class TicketPortalIn(BaseModel):
    queue_id: int | None = None
    subject: str = Field(min_length=3, max_length=255)
    priority: str = Field(default="media")
    body: str = Field(min_length=1, max_length=8000)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    internal: bool = False
    notify: bool = True


class StatusIn(BaseModel):
    status: str
    queue_id: int | None = None
    priority: str | None = None
    assigned_to_id: int | None = None


def _create(db: Session, request: Request, client_id: int, queue_id: int | None, subject: str, priority: str, body: str,
           watchers: list[WatcherIn], user: User, origin: str) -> Ticket:
    if priority not in TICKET_PRIORITIES:
        raise HTTPException(422, "Prioridade inválida")
    if queue_id and not db.get(TicketQueue, queue_id):
        raise HTTPException(422, "Fila inválida")
    if not db.get(Client, client_id):
        raise HTTPException(404, "Cliente não encontrado")
    t = Ticket(number=TS.next_number(db), client_id=client_id, queue_id=queue_id, subject=subject.strip(), priority=priority,
              origin=origin, created_by_id=user.id, created_by_name=user.name)
    db.add(t)
    db.flush()
    for w in watchers:
        db.add(TicketWatcher(ticket_id=t.id, kind=w.kind, target=w.target.strip(), label=w.label))
    msg = TicketMessage(ticket_id=t.id, author_id=user.id, author_name=user.name, origin=origin, body=body.strip(), notified=True)
    db.add(msg)
    db.flush()
    db.refresh(t)
    audit.log(db, request, "ticket_create", "ticket", t.id, detail={"numero": t.number, "cliente_id": client_id, "origem": origin})
    db.commit()
    TS.notify(db, t, "aberto", msg)
    return t


@router.get("/tickets")
def list_tickets(client_id: int | None = None, queue_id: int | None = None, status: str | None = None, open_only: bool = False,
                 db: Session = Depends(get_db), _=Depends(require("tickets.view"))):
    q = select(Ticket)
    if client_id:
        q = q.where(Ticket.client_id == client_id)
    if queue_id:
        q = q.where(Ticket.queue_id == queue_id)
    if status:
        q = q.where(Ticket.status == status)
    if open_only:
        q = q.where(Ticket.status.in_(TICKET_OPEN_STATUSES))
    rows = list(db.scalars(q.order_by(Ticket.created_at.desc()).limit(300)))
    return [_ticket_out(t) for t in rows]


@router.post("/tickets")
def create_ticket(body: TicketIn, request: Request, db: Session = Depends(get_db), user=Depends(require("tickets.edit"))):
    t = _create(db, request, body.client_id, body.queue_id, body.subject, body.priority, body.body, body.watchers, user, "staff")
    return _ticket_out(t)


@router.get("/tickets/{tid}")
def get_ticket(tid: int, db: Session = Depends(get_db), _=Depends(require("tickets.view"))):
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404)
    out = _ticket_out(t)
    out["messages"] = [_msg_out(m) for m in _messages_q(db, tid, False)]
    return out


@router.post("/tickets/{tid}/messages")
def add_message(tid: int, body: MessageIn, request: Request, db: Session = Depends(get_db), user=Depends(require("tickets.edit"))):
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404)
    m = TicketMessage(ticket_id=tid, author_id=user.id, author_name=user.name, origin="staff", internal=body.internal,
                      body=body.body.strip(), notified=body.notify and not body.internal)
    db.add(m)
    t.updated_at = datetime.now(timezone.utc)
    audit.log(db, request, "ticket_message", "ticket", tid, detail={"numero": t.number, "interna": body.internal})
    db.commit()
    if body.notify and not body.internal:
        TS.notify(db, t, "atualizado", m)
    return _msg_out(m)


@router.put("/tickets/{tid}")
def update_ticket(tid: int, body: StatusIn, request: Request, db: Session = Depends(get_db), user=Depends(require("tickets.edit"))):
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404)
    if body.status not in TICKET_STATUSES:
        raise HTTPException(422, "Situação inválida")
    if body.priority and body.priority not in TICKET_PRIORITIES:
        raise HTTPException(422, "Prioridade inválida")
    was_open, closing = t.status not in ("resolvido", "fechado"), body.status in ("resolvido", "fechado")
    t.status = body.status
    if body.queue_id is not None:
        t.queue_id = body.queue_id or None
    if body.priority:
        t.priority = body.priority
    if body.assigned_to_id is not None:
        t.assigned_to_id = body.assigned_to_id or None
    t.updated_at = datetime.now(timezone.utc)
    if closing and not t.closed_at:
        t.closed_at = datetime.now(timezone.utc)
    elif not closing:
        t.closed_at = None
    audit.log(db, request, "ticket_update", "ticket", tid, detail={"numero": t.number, "situacao": body.status})
    db.commit()
    if was_open and closing:
        TS.notify(db, t, "encerrado", extra_text=f"Encerrado por {user.name}.")
    else:
        TS.notify(db, t, "atualizado", extra_text=f"Alterado por {user.name}.")
    return _ticket_out(t)


@router.post("/tickets/{tid}/watchers")
def add_watcher(tid: int, body: WatcherIn, request: Request, db: Session = Depends(get_db), _=Depends(require("tickets.edit"))):
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404)
    w = TicketWatcher(ticket_id=tid, kind=body.kind, target=body.target.strip(), label=body.label)
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
    rows = list(db.scalars(select(Ticket).where(Ticket.client_id == c.id).order_by(Ticket.created_at.desc()).limit(200)))
    return [_ticket_out(t, portal=True) for t in rows]


@router.post("/portal/tickets")
def portal_create(body: TicketPortalIn, request: Request, client_id: int | None = None, db: Session = Depends(get_db),
                  user: User = Depends(require("portal.tickets"))):
    c = _client_for(db, user, client_id)
    t = _create(db, request, c.id, body.queue_id, body.subject, body.priority, body.body, [], user, "portal")
    return _ticket_out(t, portal=True)


@router.get("/portal/tickets/{tid}")
def portal_get(tid: int, client_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(require("portal.tickets"))):
    c = _client_for(db, user, client_id)
    t = db.get(Ticket, tid)
    if not t or t.client_id != c.id:
        raise HTTPException(404)
    out = _ticket_out(t, portal=True)
    out["messages"] = [_msg_out(m) for m in _messages_q(db, tid, True)]
    return out


@router.post("/portal/tickets/{tid}/messages")
def portal_add_message(tid: int, body: MessageIn, request: Request, client_id: int | None = None, db: Session = Depends(get_db),
                       user: User = Depends(require("portal.tickets"))):
    c = _client_for(db, user, client_id)
    t = db.get(Ticket, tid)
    if not t or t.client_id != c.id:
        raise HTTPException(404)
    if t.status in ("resolvido", "fechado"):
        raise HTTPException(409, "Este chamado já foi encerrado. Abra um novo chamado se o problema persistir.")
    m = TicketMessage(ticket_id=tid, author_id=user.id, author_name=user.name, origin="portal", internal=False, body=body.body.strip(), notified=True)
    db.add(m)
    if t.status == "aguardando_cliente":
        t.status = "andamento"
    t.updated_at = datetime.now(timezone.utc)
    audit.log(db, request, "ticket_message", "ticket", tid, detail={"numero": t.number, "origem": "portal"})
    db.commit()
    TS.notify(db, t, "atualizado", m)
    return _msg_out(m)
