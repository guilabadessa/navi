import copy
from unittest.mock import MagicMock

from app.services import flow_service as F


def D(): return F.default_flow("Menu")


def errs_of(d): return F.validate_flow(d)


def test_fluxo_padrao_e_valido():
    assert errs_of(D()) == []


def test_validador_pega_cada_erro():
    d = D(); d["nodes"] = [n for n in d["nodes"] if n["id"] != "start"]
    assert any("início" in e["msg"] for e in errs_of(d))
    d = D(); d["edges"] = [e for e in d["edges"] if e["id"] != "menu:opt:1"]
    assert any(e["node"] == "menu" and "opt:1" in e["msg"] for e in errs_of(d))
    d = D(); d["edges"].append({"id": "x", "source": "menu", "target": "nao_existe", "handle": "opt:1"})
    assert any("não existe" in e["msg"] for e in errs_of(d))
    d = D(); d["edges"].append({"id": "x", "source": "q_com", "target": "menu", "handle": "next"})
    assert any(e["node"] == "q_com" for e in errs_of(d))
    d = D(); next(n for n in d["nodes"] if n["id"] == "q_com")["data"]["queue"] = "xx"
    assert any(e["node"] == "q_com" for e in errs_of(d))
    d = D(); next(n for n in d["nodes"] if n["id"] == "menu")["data"]["options"].append({"key": "1"})
    assert any("teclas únicas" in e["msg"] for e in errs_of(d))
    d = D(); d["nodes"].append(copy.deepcopy(d["nodes"][0]))
    assert errs_of(d)
    assert errs_of({}) and errs_of({"nodes": [], "edges": []})


def test_validador_recusa_laco_sem_espera():
    d = {"nodes": [{"id": "s", "type": "start", "data": {}}, {"id": "a", "type": "message", "data": {"text": "x"}}, {"id": "b", "type": "message", "data": {"text": "y"}}],
         "edges": [{"source": "s", "target": "a", "handle": "next"}, {"source": "a", "target": "b", "handle": "next"}, {"source": "b", "target": "a", "handle": "next"}]}
    assert any("laço" in e["msg"] for e in errs_of(d))


def test_laco_que_passa_por_pergunta_e_permitido():
    assert not any("laço" in e["msg"] for e in errs_of(D()))  # fin_retry volta para fin_ask (espera)


def _sim(inputs, clients=None):
    clients = clients or {}
    orig = F.cnpj_client
    F.cnpj_client = lambda db, digits: clients.get(digits)
    try:
        return F.simulate(MagicMock(), D(), inputs)
    finally:
        F.cnpj_client = orig


def test_padrao_comercial():
    r = _sim(["1"])
    assert r["outcome"] == {"kind": "enqueue", "queue": "comercial"}


def test_padrao_financeiro_cliente_achado():
    r = _sim(["2", "11.222.333/0001-81"], {"11222333000181": {"id": 5, "name": "Echoes"}})
    assert r["outcome"]["queue"] == "financeiro" and any("Echoes" in x["text"] for x in r["transcript"])


def test_padrao_financeiro_cnpj_inexistente_tenta_de_novo_e_vai_ao_comercial():
    r = _sim(["2", "11222333000181", "11222333000181"])
    assert r["outcome"]["queue"] == "comercial" and any("comercial" in x["text"] for x in r["transcript"])


def test_padrao_financeiro_cnpj_invalido_duas_vezes_vai_ao_comercial():
    assert _sim(["2", "123", "abc"])["outcome"]["queue"] == "comercial"


def test_padrao_suporte_abre_chamado():
    r = _sim(["3", "11222333000181", "2", "Estamos sem internet no escritório"], {"11222333000181": {"id": 5, "name": "Echoes"}})
    assert r["outcome"]["kind"] == "end" and any("SIM-1" in x["text"] or "#SIM-1" in x["text"] for x in r["transcript"])


def test_padrao_suporte_analista_e_descricao_curta():
    cl = {"11222333000181": {"id": 5, "name": "Echoes"}}
    assert _sim(["3", "11222333000181", "1"], cl)["outcome"]["queue"] == "suporte"
    assert _sim(["3", "11222333000181", "2", "ruim", "x"], cl)["outcome"]["queue"] == "suporte"  # descricao curta duas vezes -> analista


def test_simulador_nao_roda_fluxo_invalido():
    r = F.simulate(MagicMock(), {"nodes": [], "edges": []}, [])
    assert r["errors"] and r["transcript"] == []
