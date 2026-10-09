"""Destinos de comunicacao do cliente: UM so lugar define para onde vai cada tipo de mensagem."""
from ..models import Client


def wa_target(client: Client | None) -> tuple[str | None, str | None]:
    """(destino, tipo): grupo de WhatsApp do cliente; sem grupo, o celular cadastrado."""
    if not client:
        return None, None
    if client.whatsapp_group_jid:
        return client.whatsapp_group_jid, "grupo"
    if client.whatsapp:
        return client.whatsapp, "celular"
    return None, None


def report_emails(client: Client | None) -> str | None:
    return (client.report_emails or None) if client else None


def alert_emails(client: Client | None) -> tuple[str | None, str | None]:
    """Alertas por e-mail: alert_emails; senao e-mails de relatorio; senao o e-mail principal do cadastro."""
    if not client:
        return None, None
    for v, origin in ((client.alert_emails, "e-mails de alerta"), (client.report_emails, "e-mails de relatório"), (client.email, "e-mail principal")):
        if v:
            return v, origin
    return None, None


def describe(client: Client | None) -> dict:
    """Resumo dos destinos para exibir em Rotinas, Relatorios e Alertas."""
    wa, wa_kind = wa_target(client)
    al, al_origin = alert_emails(client)
    return {"client": client.trade_name if client else None, "wa": wa, "wa_kind": wa_kind, "report_emails": report_emails(client),
            "alert_emails": al, "alert_emails_origin": al_origin}
