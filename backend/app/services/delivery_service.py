"""Entrega de relatorios (WhatsApp + e-mail) — separada da geracao."""
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Client, Report, ReportRun, Schedule
from . import commlog, destinations, factory, mailer
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
    cid = client.id if client else None
    if wa == "client":  # atalho: grupo do cliente; se nao houver, o celular cadastrado
        wa = destinations.wa_target(client)[0]
    if wa_requested and not wa:
        run.wa_status = "não enviado: cliente sem grupo nem celular WhatsApp cadastrado"
        commlog.record("whatsapp", "Relatório", None, "failed", run.wa_status, rep.name, cid)
    if wa:
        try:
            factory.whatsapp(db).send_document(wa, data, fname, caption=(f"Segue anexo o relatório gerado automaticamente pela plataforma NAVI da Orca TI.\n\n"
                                                          f"🏢 *{cname}*\n📅 Período: {plabel}"))
            run.wa_status = "enviado"
            commlog.record("whatsapp", "Relatório", wa, "sent", None, rep.name, cid)
        except Exception as e:  # noqa: BLE001
            run.wa_status = f"erro: {str(e)[:200]}"
            commlog.record("whatsapp", "Relatório", wa, "failed", str(e), rep.name, cid)
    mail = email_to
    mail_requested = bool(mail)
    if mail == "client":  # atalho: e-mails de relatorio do cliente
        mail = destinations.report_emails(client)
    to = split_addrs(mail)
    if mail_requested and not to:
        run.email_status = "não enviado: cliente sem e-mail de relatório cadastrado"
        commlog.record("email", "Relatório", None, "failed", run.email_status, rep.name, cid)
    if to:
        subj = (subject or ("Relatório de Disponibilidade — {CLIENTE} — {PERIODO}" if run.kpis else "Relatório de Serviços — {CLIENTE} — {PERIODO}")).replace("{CLIENTE}", cname).replace("{PERIODO}", plabel)
        try:
            ctx = mailer.report_ctx(cname, plabel, rep.name, fname, run.kpis)
            mailer.send(db, "report", to, subj, ctx, cc, bcc, [(fname, data, "application/pdf")], client_id=cid)
            run.email_status = f"enviado para {', '.join(to)}"
        except Exception as e:  # noqa: BLE001
            run.email_status = f"erro: {str(e)[:200]}"
    db.commit()
    return run
