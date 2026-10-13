"""Chamados (helpdesk): numeracao, destinatarios (fila + observadores) e aviso por e-mail/WhatsApp.
Reusa os mesmos canais dos alertas (mailer/evolution); nao atrapalha o motor de alertas (tabelas separadas)."""
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Client, Ticket, TicketMessage, TicketQueue, TicketWatcher
from . import factory, mailer

log = logging.getLogger("navi.tickets")

STATUS_LABEL = {"aberto": "Aberto", "andamento": "Em andamento", "aguardando_cliente": "Aguardando cliente",
                "resolvido": "Resolvido", "fechado": "Fechado"}
PRIORITY_LABEL = {"baixa": "Baixa", "media": "Média", "alta": "Alta", "critica": "Crítica"}


def next_number(db: Session) -> int:
    n = db.scalar(select(func.max(Ticket.number)))
    return (n or 1000) + 1


def _wa_send(db: Session, jid: str, text: str, ticket: Ticket):
    try:
        factory.evolution(db).send_text(jid, text)
    except Exception as e:  # noqa: BLE001
        log.warning("falha ao avisar WhatsApp do chamado #%s (%s): %s", ticket.number, jid, e)


def _mail_send(db: Session, to: list[str], subject: str, body_lines: list[str], ticket: Ticket):
    if not to:
        return
    try:
        mailer.send(db, "notice", to, subject, mailer.notice_ctx(subject, body_lines, greeting="Olá!"),
                   log="Chamado", client_id=ticket.client_id)
    except Exception as e:  # noqa: BLE001
        log.warning("falha ao avisar e-mail do chamado #%s (%s): %s", ticket.number, to, e)


def notify(db: Session, ticket: Ticket, kind: str, message: TicketMessage | None = None, extra_text: str | None = None):
    """Avisa a fila (se configurada) e os observadores (CC) do chamado. kind: 'aberto' | 'atualizado' | 'encerrado'."""
    client = db.get(Client, ticket.client_id)
    queue = db.get(TicketQueue, ticket.queue_id) if ticket.queue_id else None
    cliente = client.trade_name if client else "—"
    header = {"aberto": f"Novo chamado #{ticket.number} · {cliente}", "atualizado": f"Atualização no chamado #{ticket.number} · {cliente}",
             "encerrado": f"Chamado #{ticket.number} encerrado · {cliente}"}[kind]
    lines = [f"Cliente: {cliente}", f"Assunto: {ticket.subject}", f"Fila: {queue.name if queue else 'Sem fila'}",
             f"Prioridade: {PRIORITY_LABEL.get(ticket.priority, ticket.priority)}", f"Situação: {STATUS_LABEL.get(ticket.status, ticket.status)}"]
    if message and message.body:
        lines.append(f"{'Nota interna' if message.internal else 'Mensagem'} de {message.author_name or 'NAVI'}: {message.body}")
    if extra_text:
        lines.append(extra_text)
    wa_text = header + "\n\n" + "\n".join(lines)
    emails: set[str] = set()
    wa_jids: set[str] = set()
    if queue and queue.active:
        emails |= {e.strip() for e in (queue.notify_emails or "").split(",") if e.strip()}
        if queue.notify_wa_jid:
            wa_jids.add(queue.notify_wa_jid)
    for w in ticket.watchers:
        if w.kind == "email":
            emails.add(w.target.strip())
        elif w.kind == "whatsapp":
            wa_jids.add(w.target.strip())
    for jid in wa_jids:
        _wa_send(db, jid, wa_text, ticket)
    if emails:
        _mail_send(db, sorted(emails), header, lines, ticket)
