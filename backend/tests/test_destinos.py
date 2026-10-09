"""Destinos de envio: de onde vem cada endereco e o que a rotina realmente usa."""
from types import SimpleNamespace as NS

from app.routers.routines import _resolve
from app.services import destinations as D


def _c(**kw):
    base = dict(trade_name="Cli", whatsapp=None, whatsapp_group_jid=None, report_emails=None, alert_emails=None, email=None)
    return NS(**(base | kw))


def test_whatsapp_prefere_grupo_depois_celular():
    assert D.wa_target(_c(whatsapp_group_jid="1@g.us", whatsapp="5517999")) == ("1@g.us", "grupo")
    assert D.wa_target(_c(whatsapp="5517999")) == ("5517999", "celular")
    assert D.wa_target(_c()) == (None, None) and D.wa_target(None) == (None, None)


def test_email_de_alerta_cai_para_relatorio_e_depois_principal():
    assert D.alert_emails(_c(alert_emails="a@x", report_emails="r@x", email="p@x")) == ("a@x", "e-mails de alerta")
    assert D.alert_emails(_c(report_emails="r@x", email="p@x"))[0] == "r@x"
    assert D.alert_emails(_c(email="p@x"))[0] == "p@x" and D.alert_emails(_c()) == (None, None)


def test_relatorio_usa_somente_emails_de_relatorio():
    assert D.report_emails(_c(alert_emails="a@x", email="p@x")) is None
    assert D.report_emails(_c(report_emails="r@x")) == "r@x"


def test_rotina_mostra_destino_real_e_avisa_quando_falta():
    s = NS(wa_dest="client", email_to="client")
    ok = _resolve(s, _c(whatsapp_group_jid="1@g.us", report_emails="r@x"))
    assert ok["wa"] == "1@g.us" and ok["email"] == "r@x" and not ok["warnings"]
    vazio = _resolve(s, _c())
    assert len(vazio["warnings"]) == 2
    manual = _resolve(NS(wa_dest=None, email_to="fixo@x"), _c())
    assert manual["email"] == "fixo@x" and manual["wa"] is None and not manual["warnings"]
    assert _resolve(NS(wa_dest=None, email_to=None), _c())["warnings"]
