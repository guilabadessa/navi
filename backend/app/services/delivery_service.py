"""Entrega de relatorios (WhatsApp + e-mail) — separada da geracao."""
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Client, Report, ReportRun, Schedule
from . import factory
from .email_service import split_addrs
from .report_service import period_label


def deliver(db: Session, run: ReportRun, rep: Report, wa_dest: str | None = None, email_to: str | None = None,
            cc: str | None = None, bcc: str | None = None, subject: str | None = None):
    client = db.get(Client, rep.client_id) if rep.client_id else None
    cname = client.trade_name if client else "Todos os clientes"
    plabel = period_label(run.period_start, run.period_end)
    data = Path(run.file_path).read_bytes()
    fname = Path(run.file_path).name
    # None = canal nao solicitado (nao envia); sem fallback para padroes do relatorio
    wa = wa_dest
    wa_requested = bool(wa)
    if wa == "client":  # atalho: grupo WhatsApp cadastrado no cliente
        wa = client.whatsapp_group_jid if client else None
    if wa_requested and not wa:
        run.wa_status = "não enviado: cliente sem grupo WhatsApp cadastrado"
    if wa:
        try:
            factory.evolution(db).send_document(wa, data, fname, caption=f"📊 *{rep.name}*\n🏢 {cname}\n📅 {plabel}")
            run.wa_status = "enviado"
        except Exception as e:  # noqa: BLE001
            run.wa_status = f"erro: {str(e)[:200]}"
    mail = email_to
    mail_requested = bool(mail)
    if mail == "client":  # atalho: e-mails de relatorio do cliente
        mail = client.report_emails if client else None
    to = split_addrs(mail)
    if mail_requested and not to:
        run.email_status = "não enviado: cliente sem e-mail de relatório cadastrado"
    if to:
        subj = (subject or "Relatório de Disponibilidade — {CLIENTE} — {PERIODO}").replace("{CLIENTE}", cname).replace("{PERIODO}", plabel)
        body = (f"Prezados,\n\nSegue em anexo o relatório \"{rep.name}\" de {cname}, referente ao período {plabel}.\n\n"
                f"Atenciosamente,\nNOC Orca TI")
        try:
            factory.email(db).send(to, subj, body, split_addrs(cc), split_addrs(bcc), [(fname, data, "application/pdf")])
            run.email_status = f"enviado para {', '.join(to)}"
        except Exception as e:  # noqa: BLE001
            run.email_status = f"erro: {str(e)[:200]}"
    db.commit()
    return run
