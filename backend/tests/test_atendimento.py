from unittest.mock import MagicMock

from app.models import WaConversation, WaMessage
from app.security import has_perm


def test_permissoes_atendimento():
    assert has_perm("ANALISTA_NOC", "atendimento.act") and has_perm("GESTOR", "atendimento.view")
    assert has_perm("VISUALIZADOR", "atendimento.view") and not has_perm("VISUALIZADOR", "atendimento.act")
    assert not has_perm("CLIENTE", "atendimento.view")


def test_modelo_conversa():
    c = WaConversation(jid="5514999999999@s.whatsapp.net", queue="geral", state="menu")
    assert c.state == "menu" and hasattr(WaMessage, "conversation_id") and hasattr(WaMessage, "sent_by")


from app.services import atendimento_service as A


def test_parse_option():
    assert A.parse_option(" 1 ") == "comercial" and A.parse_option("2") == "financeiro" and A.parse_option("três") == "suporte"
    assert A.parse_option("oi") is None and A.parse_option("12") is None and A.parse_option("") is None


def test_is_individual_ignora_grupo_e_status():
    assert A.is_individual("5514999999999@s.whatsapp.net") and A.is_individual("1785@lid")
    assert not A.is_individual("1203@g.us") and not A.is_individual("status@broadcast")


def _conv(state="menu", tries=0, queue="geral"):
    return WaConversation(id=1, jid="5514999999999@s.whatsapp.net", state=state, queue=queue, menu_tries=tries, unread=0)


def _msg(text="1", direction="in", jid="5514999999999@s.whatsapp.net"):
    return WaMessage(external_id="X", session="orca", jid=jid, direction=direction, type="TEXT", text=text, push_name="Joao")


def _db(open_conv=None):
    db = MagicMock()
    db.scalar.side_effect = lambda *a, **k: open_conv
    db.scalars.return_value.all.return_value = []
    return db


def test_primeira_mensagem_abre_menu_e_envia_saudacao(monkeypatch):
    db, gw = _db(None), MagicMock()
    monkeypatch.setattr(A, "match_client", lambda d, j: None)
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    c = A.handle_inbound(db, _msg("oi"), gw)
    assert c.state == "menu" and "digite 1" in gw.send_text.call_args.args[1]


def test_opcao_valida_vai_para_fila_e_avisa(monkeypatch):
    cfg = {**A.DEFAULT_CFG, "queues": {**A.DEFAULT_CFG["queues"], "suporte": {"alert_enabled": True, "alert_to": ["120363@g.us", "14999990000"]}}}
    monkeypatch.setattr(A, "cfg", lambda d: cfg)
    conv, gw = _conv(), MagicMock()
    A.handle_inbound(_db(conv), _msg("3"), gw)
    assert conv.state == "aguardando" and conv.queue == "suporte" and conv.queued_at is not None
    destinos = [c.args[0] for c in gw.send_text.call_args_list]
    assert "120363@g.us" in destinos and "14999990000" in destinos and "5514999999999@s.whatsapp.net" in destinos


def test_aviso_desligado_nao_envia_para_destinos(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    conv, gw = _conv(), MagicMock()
    A.handle_inbound(_db(conv), _msg("2"), gw)
    assert [c.args[0] for c in gw.send_text.call_args_list] == ["5514999999999@s.whatsapp.net"]


def test_falha_no_aviso_nao_quebra_o_fluxo(monkeypatch):
    cfg = {**A.DEFAULT_CFG, "queues": {**A.DEFAULT_CFG["queues"], "suporte": {"alert_enabled": True, "alert_to": ["x@g.us"]}}}
    monkeypatch.setattr(A, "cfg", lambda d: cfg)
    conv, gw = _conv(), MagicMock()
    gw.send_text.side_effect = [None, RuntimeError("fora")]
    A.handle_inbound(_db(conv), _msg("3"), gw)
    assert conv.state == "aguardando"


def test_opcao_invalida_repete_uma_vez_e_depois_vai_para_geral(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    conv, gw = _conv(tries=0), MagicMock()
    A.handle_inbound(_db(conv), _msg("blabla"), gw)
    assert conv.state == "menu" and conv.menu_tries == 1
    A.handle_inbound(_db(conv), _msg("blabla"), gw)
    assert conv.state == "aguardando" and conv.queue == "geral"


def test_mensagem_em_fila_incrementa_nao_lidas_e_nao_responde(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    conv, gw = _conv("aguardando"), MagicMock()
    A.handle_inbound(_db(conv), _msg("alguem ai?"), gw)
    assert conv.unread == 1 and not gw.send_text.called


def test_grupo_e_saida_nao_criam_conversa(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    gw = MagicMock()
    assert A.handle_inbound(_db(None), _msg("oi", jid="1203@g.us"), gw) is None
    assert A.handle_inbound(_db(None), _msg("oi", direction="out"), gw) is None
    assert not gw.send_text.called


def test_saida_do_celular_anexa_a_conversa_aberta(monkeypatch):
    conv = _conv("atendendo")
    m = _msg("oi cliente", direction="out")
    A.handle_inbound(_db(conv), m, MagicMock())
    assert m.conversation_id == 1


def test_tick_move_menu_vencido_para_geral(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    conv, gw = _conv(), MagicMock()
    db = _db(None)
    db.scalars.return_value.all.return_value = [conv]
    assert A.tick(db, gw) == 1 and conv.state == "aguardando" and conv.queue == "geral"


def test_assume_atomico():
    db = MagicMock()
    db.execute.return_value.rowcount = 1
    assert A.assume(db, 1, 7) is True
    db.execute.return_value.rowcount = 0
    assert A.assume(db, 1, 8) is False


def test_send_grava_falha_e_relevanta():
    from app.services.wa_akg_service import WaAkgError
    db, gw, conv = _db(None), MagicMock(), _conv("atendendo")
    gw.send_text.side_effect = WaAkgError("fora")
    try:
        A.send(db, conv, 5, "oi", gw)
        assert False
    except WaAkgError:
        pass
    salvo = db.add.call_args.args[0]
    assert salvo.failed is True and salvo.sent_by == 5 and salvo.text == "oi"


def test_phone_match_ignora_formatacao_e_55():
    assert A.phone_key("5514999991234@s.whatsapp.net") == A.phone_key("(14) 99999-1234") == "1499991234"
    assert A.phone_key("1203@g.us") is None


def test_on_inbound_chama_atendimento_e_engole_erro(monkeypatch):
    from app.services import wa_inbound
    chamado = {}
    monkeypatch.setattr("app.services.atendimento_service.handle_inbound", lambda db, m, gw: chamado.setdefault("ok", True))
    monkeypatch.setattr("app.services.factory.wa_akg", lambda db: MagicMock())
    db = MagicMock()
    wa_inbound.on_inbound(db, _msg("oi"))
    assert chamado["ok"] and db.commit.called
    monkeypatch.setattr("app.services.atendimento_service.handle_inbound", lambda db, m, gw: 1 / 0)
    db2 = MagicMock()
    wa_inbound.on_inbound(db2, _msg("oi"))  # nao levanta
    assert db2.rollback.called


def test_job_registrado():
    from app import jobs
    assert "atendimento_tick" in jobs.JOBS and callable(jobs.atendimento_tick)
