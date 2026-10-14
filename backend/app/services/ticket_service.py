"""Chamados (helpdesk): destinatarios (fila + observadores) e aviso por e-mail/WhatsApp.
Reusa os mesmos canais dos alertas (mailer/evolution); nao atrapalha o motor de alertas (tabelas separadas).
Numeracao do chamado: atribuida pelo banco (sequencia `ticket_number_seq`), nunca calculada aqui -
evita a corrida de dois chamados simultaneos ganharem o mesmo numero (SELECT MAX+1 nao e seguro sob concorrencia)."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Client, Ticket, TicketMessage, TicketQueue, TicketWatcher
from . import factory, mailer

log = logging.getLogger("navi.tickets")
ESCALATION_HOURS = 24  # chamado aguardando a Orca TI sem resposta por mais tempo que isso: reenvia lembrete

STATUS_LABEL = {"aberto": "Aberto", "andamento": "Em andamento", "aguardando_cliente": "Aguardando cliente",
                "aguardando_orca": "Aguardando Orca TI", "resolvido": "Resolvido", "fechado": "Fechado"}
PRIORITY_LABEL = {"baixa": "Baixa", "media": "Média", "alta": "Alta", "critica": "Crítica"}


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
    if ticket.internal:
        return  # chamado interno e so registro da equipe: nunca avisa fila, observadores nem cliente
    client = db.get(Client, ticket.client_id)
    queue = db.get(TicketQueue, ticket.queue_id) if ticket.queue_id else None
    cliente = client.trade_name if client else "—"
    header = {"aberto": f"Novo chamado #{ticket.number} · {cliente}", "atualizado": f"Atualização no chamado #{ticket.number} · {cliente}",
             "encerrado": f"Chamado #{ticket.number} encerrado · {cliente}",
             "lembrete": f"⏰ Chamado #{ticket.number} sem resposta há mais de {ESCALATION_HOURS}h · {cliente}"}[kind]
    lines = [f"Cliente: {cliente}"] + ([f"Unidade: {ticket.unit}"] if ticket.unit else []) + [f"Assunto: {ticket.subject}", f"Fila: {queue.name if queue else 'Sem fila'}",
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


def check_escalations(db: Session, limit: int = 50) -> int:
    """Chamado aguardando a Orca TI ha mais de ESCALATION_HOURS sem um novo lembrete recente: reenvia aviso a fila/observadores."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ESCALATION_HOURS)
    rows = db.scalars(select(Ticket).where(Ticket.status == "aguardando_orca", Ticket.internal.is_(False), Ticket.updated_at <= cutoff,
                                           (Ticket.escalated_at.is_(None)) | (Ticket.escalated_at <= cutoff)).limit(limit)).all()
    n = 0
    for t in rows:
        extra = f"Aberto por {t.created_by_name or 'cliente'} e sem resposta da equipe desde {t.updated_at:%d/%m %H:%M}."
        notify(db, t, "lembrete", extra_text=extra)
        t.escalated_at = datetime.now(timezone.utc)
        n += 1
    if n:
        db.commit()
    if n == limit:
        log.warning("escalonamento de chamados: atingiu o limite de %d nesta execucao, pode haver mais chamados vencidos", limit)
    return n
