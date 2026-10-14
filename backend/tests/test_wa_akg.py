import json

import httpx
import pytest

from app.services.wa_akg_service import WaAkgError, WaAkgService, to_jid


def svc(handler):
    return WaAkgService("http://wa:3000", "orca", "wag_key", transport=httpx.MockTransport(handler))


def test_to_jid_telefone_grupo_e_jid_pronto():
    assert to_jid("(14) 99999-9999") == "5514999999999@s.whatsapp.net"
    assert to_jid("1433334444") == "551433334444@s.whatsapp.net"
    assert to_jid("120363025246125486") == "120363025246125486@g.us"
    assert to_jid("12345-678") == "12345-678@g.us"
    assert to_jid("5514999999999@s.whatsapp.net") == "5514999999999@s.whatsapp.net"
    assert to_jid("120363@g.us") == "120363@g.us"


def test_send_text_monta_requisicao_e_devolve_resposta():
    seen = {}

    def h(req: httpx.Request):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers["x-api-key"], json.loads(req.content)
        return httpx.Response(200, json={"status": True, "data": {"key": {"id": "3EB0AA", "remoteJid": "x"}}})

    r = svc(h).send_text("(14) 99999-9999", "oi")
    assert seen["url"] == "http://wa:3000/api/messages/orca/5514999999999%40s.whatsapp.net/send"
    assert seen["key"] == "wag_key" and seen["body"] == {"message": {"text": "oi"}}
    assert WaAkgService.message_id(r) == "3EB0AA"


def test_send_text_tenta_variacao_do_nono_digito_quando_numero_nao_existe():
    urls = []

    def h(req: httpx.Request):
        urls.append(req.url.path)
        if len(urls) == 1:
            return httpx.Response(400, json={"status": False, "message": "number not exists on WhatsApp"})
        return httpx.Response(200, json={"status": True, "data": {"key": {"id": "OK"}}})

    r = svc(h).send_text("14999999999", "oi")
    assert "5514999999999" in urls[0] and "551499999999@" in urls[1]
    assert WaAkgService.message_id(r) == "OK"


def test_send_text_citado_usa_reply_e_cai_para_envio_simples():
    paths = []

    def h(req: httpx.Request):
        paths.append(req.url.path)
        if req.url.path.endswith("/reply"):
            return httpx.Response(500, json={"status": False})
        return httpx.Response(200, json={"status": True, "data": {"key": {"id": "S"}}})

    r = svc(h).send_text("5514999999999", "oi", quoted_id="ABC", quoted_text="antes")
    assert paths[0].endswith("/ABC/reply") and paths[1].endswith("/send")
    assert WaAkgService.message_id(r) == "S"


def test_erro_http_e_conexao_viram_waakgerror():
    with pytest.raises(WaAkgError, match="HTTP 503"):
        svc(lambda r: httpx.Response(503, text="not ready")).send_text("5514999999999", "x")

    def boom(req):
        raise httpx.ConnectError("down")

    with pytest.raises(WaAkgError, match="conexão"):
        svc(boom).send_text("5514999999999", "x")


def test_sem_configuracao_levanta_erro_claro():
    with pytest.raises(WaAkgError, match="não configurado"):
        WaAkgService("", "", "").send_text("5514999999999", "x")


def test_send_document_envia_multipart():
    seen = {}

    def h(req: httpx.Request):
        seen["path"], seen["ct"] = req.url.path, req.headers["content-type"]
        return httpx.Response(200, json={"status": True, "data": {"key": {"id": "D1"}}})

    r = svc(h).send_document("5514999999999", b"%PDF-1.4", "rel.pdf", "segue")
    assert seen["path"].endswith("/media") and seen["ct"].startswith("multipart/form-data")
    assert WaAkgService.message_id(r) == "D1"


def test_status_mapeia_connected_para_open():
    assert svc(lambda r: httpx.Response(200, json={"status": "Connected", "hasInstance": True})).status()["state"] == "open"
    assert svc(lambda r: httpx.Response(200, json={"status": "Disconnected"})).status()["state"] == "close"
    assert svc(lambda r: httpx.Response(200, json={"status": True, "data": {"status": "CONNECTED"}})).status()["state"] == "open"


def test_qr_le_codigo_da_sessao():
    s = svc(lambda r: httpx.Response(200, json={"status": True, "data": {"qr": "2@abc", "base64": "data:image/png;base64,xx"}}))
    assert s.qr() == {"qr": "2@abc", "base64": "data:image/png;base64,xx"}
    assert svc(lambda r: httpx.Response(404, json={"status": False})).qr() == {"qr": None, "base64": None}


from unittest.mock import patch

from app.services import factory
from app.services.evolution_service import EvolutionService


def _cfg(values):
    return lambda db, key, default=None: values.get(key, default or "")


def test_factory_padrao_e_evolution():
    with patch.object(factory.S, "get", side_effect=_cfg({"evolution.url": "http://e", "evolution.instance": "i", "evolution.api_key": "k"})):
        assert isinstance(factory.whatsapp(None), EvolutionService)
        assert isinstance(factory.evolution(None), EvolutionService)


def test_factory_escolhe_wa_akg_quando_configurado():
    cfg = {"whatsapp.provider": "wa_akg", "wa_akg.url": "http://wa:3000", "wa_akg.session": "orca", "wa_akg.api_key": "wag_x"}
    with patch.object(factory.S, "get", side_effect=_cfg(cfg)):
        s = factory.evolution(None)
        assert isinstance(s, WaAkgService) and s.session == "orca" and s.base == "http://wa:3000"


import hashlib
import hmac
from unittest.mock import MagicMock

from app.services import wa_inbound as W


def sign(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def test_verify_signature_valida_e_rejeita():
    raw = b'{"event":"message.received"}'
    assert W.verify_signature("seg", raw, sign("seg", raw))
    assert not W.verify_signature("seg", raw, sign("outro", raw))
    assert not W.verify_signature("seg", raw, "")
    assert not W.verify_signature("", raw, sign("", raw))  # segredo nao configurado: nunca aceita
    assert not W.verify_signature("seg", raw + b" ", sign("seg", raw))


MSG = {"event": "message.received", "sessionId": "orca",
       "data": {"key": {"id": "AB12", "remoteJid": "5514999999999@s.whatsapp.net", "fromMe": False}, "pushName": "Budi",
                "type": "TEXT", "content": "oi", "fileUrl": None, "caption": None}}


def test_parse_mensagem_recebida():
    p = W.parse_payload(MSG)
    assert p == {"external_id": "AB12", "session": "orca", "jid": "5514999999999@s.whatsapp.net", "direction": "in",
                 "type": "TEXT", "text": "oi", "media_ref": None, "push_name": "Budi"}


def test_parse_mensagem_enviada_e_midia_sem_texto():
    sent = {**MSG, "event": "message.sent", "data": {**MSG["data"], "key": {**MSG["data"]["key"], "fromMe": True}}}
    assert W.parse_payload(sent)["direction"] == "out"
    img = {**MSG, "data": {**MSG["data"], "type": "IMAGE", "content": None, "caption": "foto", "fileUrl": "/media/x"}}
    p = W.parse_payload(img)
    assert p["text"] == "foto" and p["media_ref"] == "/media/x"
    mudo = {**MSG, "data": {**MSG["data"], "type": "AUDIO", "content": None, "caption": None}}
    assert W.parse_payload(mudo)["text"] == ""


def test_parse_ignora_o_que_nao_e_mensagem_ou_vem_incompleto():
    assert W.parse_payload({"event": "connection.update", "data": {}}) is None
    assert W.parse_payload({"event": "message.received", "data": {"key": {}}}) is None
    assert W.parse_payload({"event": "message.received"}) is None
    assert W.parse_payload({}) is None


def test_store_inbound_grava_e_ignora_duplicada():
    db = MagicMock()
    db.scalar.return_value = None
    parsed = W.parse_payload(MSG)
    m = W.store_inbound(db, parsed)
    assert m.external_id == "AB12" and m.direction == "in"
    db.add.assert_called_once()
    db.reset_mock()
    db.scalar.return_value = 7  # ja existe
    assert W.store_inbound(db, parsed) is None
    db.add.assert_not_called()


from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app


def _client(secret="seg"):
    db = MagicMock()
    db.scalar.return_value = None
    app.dependency_overrides[get_db] = lambda: db
    patcher = patch("app.routers.whatsapp_r.S.get", side_effect=lambda d, k, default=None: secret if k == "wa_akg.webhook_secret" else (default or ""))
    patcher.start()
    return TestClient(app), db, patcher


def test_webhook_sem_assinatura_ou_assinatura_errada_da_401_e_nao_grava():
    c, db, p = _client()
    try:
        body = json.dumps(MSG).encode()
        assert c.post("/cliente/api/wa/webhook", content=body).status_code == 401
        assert c.post("/cliente/api/wa/webhook", content=body, headers={"X-Webhook-Signature": sign("errado", body)}).status_code == 401
        assert not [x for x in db.add.call_args_list if x.args[0].__class__.__name__ == "WaMessage"]  # so a auditoria da recusa e gravada
    finally:
        p.stop(); app.dependency_overrides.clear()


def test_webhook_valido_grava_e_evento_irrelevante_da_200_sem_gravar():
    c, db, p = _client()
    try:
        body = json.dumps(MSG).encode()
        r = c.post("/cliente/api/wa/webhook", content=body, headers={"X-Webhook-Signature": sign("seg", body)})
        assert r.status_code == 200 and r.json() == {"ok": True, "stored": True}
        db.add.assert_called_once()
        db.reset_mock()
        outro = json.dumps({"event": "connection.update", "data": {}}).encode()
        r = c.post("/cliente/api/wa/webhook", content=outro, headers={"X-Webhook-Signature": sign("seg", outro)})
        assert r.status_code == 200 and r.json() == {"ok": True, "stored": False}
        db.add.assert_not_called()
        lixo = b"nao e json"
        assert c.post("/cliente/api/wa/webhook", content=lixo, headers={"X-Webhook-Signature": sign("seg", lixo)}).status_code == 200
    finally:
        p.stop(); app.dependency_overrides.clear()


def test_teste_e_qr_usam_o_wa_akg_mesmo_com_evolution_ativa():
    from app.routers import whatsapp_r as R
    cfg = {"wa_akg.url": "http://wa:3000", "wa_akg.session": "orca", "wa_akg.api_key": "wag_x", "whatsapp.provider": "evolution"}
    with patch.object(R.S, "get", side_effect=_cfg(cfg)):
        g = R._gateway(None)
    assert isinstance(g, WaAkgService) and g.session == "orca"


def test_qr_no_topo_da_resposta_como_a_v163_devolve():
    s = svc(lambda r: httpx.Response(200, json={"success": True, "qr": "2@xyz", "base64": "data:image/png;base64,yy"}))
    assert s.qr() == {"qr": "2@xyz", "base64": "data:image/png;base64,yy"}
