import json

import pytest
from datetime import datetime, timedelta, timezone
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


def test_is_individual_ignora_grupo_e_status():
    assert A.is_individual("5514999999999@s.whatsapp.net") and A.is_individual("1785@lid")
    assert not A.is_individual("1203@g.us") and not A.is_individual("status@broadcast")


@pytest.fixture(autouse=True)
def _fluxo_padrao(monkeypatch):
    monkeypatch.setattr(A.FS, "load_flow", lambda db, g, t: (A.FS.default_flow(g, t), True))


def _conv(state="menu", tries=0, queue="geral"):
    return WaConversation(id=1, jid="5514999999999@s.whatsapp.net", state=state, queue=queue, menu_tries=tries, unread=0,
                          flow_node="menu" if state == "menu" else None, flow_vars={"_c": {"menu": tries}})


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
    cfg["queues"]["comercial"] = cfg["queues"]["suporte"]
    A.handle_inbound(_db(conv), _msg("1"), gw)
    assert conv.state == "aguardando" and conv.queue == "comercial" and conv.queued_at is not None
    destinos = [c.args[0] for c in gw.send_text.call_args_list]
    assert "120363@g.us" in destinos and "14999990000" in destinos and "5514999999999@s.whatsapp.net" in destinos


def test_aviso_desligado_nao_envia_para_destinos(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    conv, gw = _conv(), MagicMock()
    A.handle_inbound(_db(conv), _msg("1"), gw)
    assert [c.args[0] for c in gw.send_text.call_args_list] == ["5514999999999@s.whatsapp.net"]


def test_falha_no_aviso_nao_quebra_o_fluxo(monkeypatch):
    cfg = {**A.DEFAULT_CFG, "queues": {**A.DEFAULT_CFG["queues"], "suporte": {"alert_enabled": True, "alert_to": ["x@g.us"]}}}
    monkeypatch.setattr(A, "cfg", lambda d: cfg)
    conv, gw = _conv(), MagicMock()
    gw.send_text.side_effect = [None, RuntimeError("fora")]
    cfg["queues"]["comercial"] = cfg["queues"]["suporte"]
    A.handle_inbound(_db(conv), _msg("1"), gw)
    assert conv.state == "aguardando"


def test_opcao_invalida_repete_uma_vez_e_depois_vai_para_geral(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    conv, gw = _conv(tries=0), MagicMock()
    A.handle_inbound(_db(conv), _msg("blabla"), gw)
    assert conv.state == "menu" and conv.flow_vars["_c"]["menu"] == 1
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
    conv.menu_sent_at = datetime.now(timezone.utc) - timedelta(minutes=5)
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


# ---- API ----
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.security import current_user


_patches = []


def _api(role="ANALISTA_NOC", db=None):
    from unittest.mock import patch
    db = db or MagicMock()
    p = patch.object(A, "cfg", lambda d: A.DEFAULT_CFG)  # S.get nao funciona com banco simulado
    p.start()
    _patches.append(p)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: NS(id=7, email="a@x.com", name="Ana", role=role, active=True, extra_perms=[])
    return TestClient(app), db


def _done():
    app.dependency_overrides.clear()
    while _patches:
        _patches.pop().stop()


def test_api_sem_permissao_da_403():
    c, _ = _api("CLIENTE")
    try:
        assert c.get("/cliente/api/atendimento/queues").status_code == 403
        c2, _ = _api("VISUALIZADOR")
        assert c2.get("/cliente/api/atendimento/queues").status_code in (200, 500)  # ver pode
        assert c2.post("/cliente/api/atendimento/conversations/1/assume").status_code == 403
        assert c2.put("/cliente/api/atendimento/config", json={}).status_code in (403, 422)
    finally:
        _done()


def test_assumir_devolve_409_quando_outro_chegou_primeiro(monkeypatch):
    c, db = _api()
    db.get.return_value = _conv("aguardando")
    monkeypatch.setattr(A, "assume", lambda d, i, u: False)
    try:
        assert c.post("/cliente/api/atendimento/conversations/1/assume").status_code == 409
    finally:
        _done()


def test_enviar_falha_do_gateway_da_502_e_guarda_a_mensagem(monkeypatch):
    from app.services.wa_akg_service import WaAkgError
    c, db = _api()
    db.get.return_value = _conv("atendendo")
    db.scalar.return_value = None
    monkeypatch.setattr("app.services.factory.wa_akg", lambda d: MagicMock(send_text=MagicMock(side_effect=WaAkgError("fora"))))
    try:
        r = c.post("/cliente/api/atendimento/conversations/1/send", json={"text": "ola"})
        assert r.status_code == 502 and db.commit.called
        assert db.add.call_args.args[0].failed is True
    finally:
        _done()


def test_enviar_em_conversa_encerrada_da_409():
    c, db = _api()
    db.get.return_value = _conv("encerrada")
    try:
        assert c.post("/cliente/api/atendimento/conversations/1/send", json={"text": "ola"}).status_code == 409
        assert c.post("/cliente/api/atendimento/conversations/1/send", json={"text": ""}).status_code == 422
    finally:
        _done()


def test_transferir_exige_destino_e_rejeita_cliente_como_analista():
    c, db = _api()
    db.get.side_effect = lambda model, i: _conv("atendendo") if model.__name__ == "WaConversation" else NS(id=9, active=True, role="CLIENTE")
    try:
        assert c.post("/cliente/api/atendimento/conversations/1/transfer", json={}).status_code == 422
        assert c.post("/cliente/api/atendimento/conversations/1/transfer", json={"user_id": 9}).status_code == 422
        assert c.post("/cliente/api/atendimento/conversations/1/transfer", json={"queue": "bogus"}).status_code == 422
    finally:
        _done()


def test_config_so_admin_edita_e_grava_json(monkeypatch):
    saved = {}
    monkeypatch.setattr("app.routers.atendimento.S.put", lambda db, k, v, user=None: saved.setdefault(k, v))
    body = {"greeting": "Oi", "menu_timeout_min": 3, "wait_alert_min": 5, "closing_message": "Tchau",
            "queues": {"suporte": {"alert_enabled": True, "alert_to": [" 120@g.us ", ""]}, "xpto": {"alert_enabled": True, "alert_to": []}}}
    c, _ = _api("ANALISTA_NOC")
    try:
        assert c.put("/cliente/api/atendimento/config", json=body).status_code == 403
        c, _ = _api("ADMIN")
        r = c.put("/cliente/api/atendimento/config", json=body)
        assert r.status_code == 200
        gravado = json.loads(saved["atendimento.config"])
        assert gravado["queues"] == {"suporte": {"alert_enabled": True, "alert_to": ["120@g.us"]}}
        assert c.put("/cliente/api/atendimento/config", json={**body, "menu_timeout_min": 0}).status_code == 422
    finally:
        _done()


def test_opcao_3_pede_cnpj_e_guarda_o_estado_do_fluxo(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    conv, gw = _conv(), MagicMock()
    A.handle_inbound(_db(conv), _msg("3"), gw)
    assert conv.state == "menu" and conv.flow_node == "sup_ask" and "CNPJ" in gw.send_text.call_args.args[1]


def test_cnpj_achado_vincula_o_cliente_e_mostra_o_menu_do_suporte(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    monkeypatch.setattr(A.FS, "cnpj_client", lambda db, d: {"id": 9, "name": "Echoes"})
    conv, gw = _conv(), MagicMock()
    conv.flow_node = "sup_ask"
    A.handle_inbound(_db(conv), _msg("11.222.333/0001-81"), gw)
    assert conv.client_id == 9 and conv.flow_node == "sup_menu" and "Echoes" in gw.send_text.call_args.args[1]


def test_chamado_pelo_fluxo_encerra_a_conversa_e_responde_o_codigo(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    monkeypatch.setattr(A.TS, "create_from_whatsapp", lambda *a, **k: MagicMock(number=1042))
    conv, gw = _conv(), MagicMock()
    conv.flow_node, conv.client_id, conv.flow_vars = "tk_ask", 9, {"cliente": "Echoes", "nome": "Joao", "telefone": "5514999999999", "cnpj": "x"}
    A.handle_inbound(_db(conv), _msg("Estamos sem internet no escritorio"), gw)
    assert conv.state == "encerrada" and "#1042" in gw.send_text.call_args.args[1]


def test_flow_com_no_removido_manda_para_fila_geral(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    conv, gw = _conv(), MagicMock()
    conv.flow_node = "no_que_sumiu"
    A.handle_inbound(_db(conv), _msg("1"), gw)
    assert conv.state == "aguardando" and conv.queue == "geral"


def test_api_fluxo_valida_salva_e_simula(monkeypatch):
    from app.services import flow_service as FS
    saved = {}
    monkeypatch.setattr(FS, "save_flow", lambda db, d, u: saved.setdefault("d", d))
    monkeypatch.setattr(FS, "cnpj_client", lambda db, d: None)
    d = FS.default_flow("Menu")
    c, db = _api("ADMIN")
    try:
        assert c.post("/cliente/api/atendimento/flow/validate", json={"definition": d}).json() == {"errors": []}
        assert c.put("/cliente/api/atendimento/flow", json={"definition": d}).status_code == 200 and saved["d"] == d
        ruim = {"nodes": [], "edges": []}
        r = c.put("/cliente/api/atendimento/flow", json={"definition": ruim})
        assert r.status_code == 422 and "início" in r.json()["detail"]
        r = c.post("/cliente/api/atendimento/flow/simulate", json={"definition": d, "inputs": ["1"]}).json()
        assert r["outcome"] == {"kind": "enqueue", "queue": "comercial"}
        c2, _ = _api("ANALISTA_NOC")
        assert c2.put("/cliente/api/atendimento/flow", json={"definition": d}).status_code == 403
        assert c2.post("/cliente/api/atendimento/flow/reset").status_code == 403
    finally:
        _done()
