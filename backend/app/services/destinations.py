"""Destinos de comunicacao do cliente: UM so lugar define para onde vai cada tipo de mensagem.
Os destinos vem do cadastro do cliente (aba Alertas); o e-mail da aba Dados e so contato e NUNCA recebe envios."""
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


def alert_emails(client: Client | None) -> tuple[str | None, str | None]:
    """Destino de e-mail do cliente (alertas, relatorios e rotinas): os e-mails da aba Alertas.
    Compatibilidade: cadastros antigos que so tem 'e-mails de relatorio' continuam funcionando."""
    if not client:
        return None, None
    for v, origin in ((client.alert_emails, "aba Alertas"), (client.report_emails, "e-mails de relatório (cadastro antigo)")):
        if v and v.strip():
            return v, origin
    return None, None


def report_emails(client: Client | None) -> str | None:
    """Relatorios: e-mails exclusivos de relatorio, se houver; senao os da aba Alertas."""
    if not client:
        return None
    return (client.report_emails or "").strip() or alert_emails(client)[0]


def describe(client: Client | None) -> dict:
    """Resumo dos destinos para exibir em Rotinas, Relatorios e Alertas."""
    wa, wa_kind = wa_target(client)
    al, al_origin = alert_emails(client)
    return {"client": client.trade_name if client else None, "wa": wa, "wa_kind": wa_kind, "report_emails": report_emails(client),
            "alert_emails": al, "alert_emails_origin": al_origin}
