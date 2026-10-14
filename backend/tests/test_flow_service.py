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


CL = {"11222333000181": {"id": 5, "name": "Echoes"}}


def test_padrao_suporte_abre_chamado_e_pergunta_se_pode_encerrar():
    r = _sim(["3", "11222333000181", "2", "Estamos sem internet no escritório"], CL)
    assert r["outcome"]["kind"] == "waiting" and any("#SIM-1" in x["text"] for x in r["transcript"])
    assert "mais alguma coisa" in r["transcript"][-1]["text"]
    assert _sim(["3", "11222333000181", "2", "Estamos sem internet no escritório", "2"], CL)["outcome"]["kind"] == "end"


def test_padrao_depois_do_chamado_pode_voltar_ao_menu_principal():
    r = _sim(["3", "11222333000181", "2", "Estamos sem internet no escritório", "1"], CL)
    assert r["outcome"]["kind"] == "waiting" and r["transcript"][-1]["text"] == "Menu"  # reenvia o menu principal


def test_padrao_voltar_ao_menu_nas_perguntas_e_no_submenu():
    for ins in (["2", "0"], ["3", "0"], ["3", "11222333000181", "0"]):
        r = _sim(ins, CL)
        assert r["outcome"]["kind"] == "waiting" and r["transcript"][-1]["text"] == "Menu", ins
    r = _sim(["3", "11222333000181", "2", "0"], CL)  # da descricao volta ao submenu do suporte
    assert "Voltar ao menu principal" in r["transcript"][-1]["text"]


def test_padrao_depois_do_chamado_sem_resposta_ou_invalida_encerra():
    base = ["3", "11222333000181", "2", "Estamos sem internet no escritório"]
    assert _sim(base + ["x", "y"], CL)["outcome"]["kind"] == "end"


def test_padrao_suporte_analista_e_descricao_curta():
    cl = {"11222333000181": {"id": 5, "name": "Echoes"}}
    assert _sim(["3", "11222333000181", "1"], cl)["outcome"]["queue"] == "suporte"
    assert _sim(["3", "11222333000181", "2", "ruim", "x"], cl)["outcome"]["queue"] == "suporte"  # descricao curta duas vezes -> analista


def test_simulador_nao_roda_fluxo_invalido():
    r = F.simulate(MagicMock(), {"nodes": [], "edges": []}, [])
    assert r["errors"] and r["transcript"] == []


def test_validador_dos_novos_passos():
    d = D()
    d["nodes"] += [{"id": "h", "type": "hours", "x": 0, "y": 0, "data": {}}, {"id": "v", "type": "set_var", "x": 0, "y": 0, "data": {"var": "1x"}}, {"id": "t", "type": "tag", "x": 0, "y": 0, "data": {}}]
    msgs = " | ".join(f"{x['node']}:{x['msg']}" for x in F.validate_flow(d))
    assert "h:Falta ligar a saída “open”" in msgs and "h:Falta ligar a saída “closed”" in msgs
    assert "v:Informe o nome da variável" in msgs and "t:Escolha a etiqueta" in msgs


def test_horario_de_atendimento_em_brasilia():
    from datetime import datetime, timezone
    from app.services import atendimento_service as A
    c = A.DEFAULT_CFG
    seg_10h = datetime(2026, 10, 12, 13, 0, tzinfo=timezone.utc)   # segunda 10:00 BRT
    seg_19h = datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc)   # segunda 19:00 BRT
    sab_10h = datetime(2026, 10, 17, 13, 0, tzinfo=timezone.utc)
    assert A.is_open(c, seg_10h) and not A.is_open(c, seg_19h) and not A.is_open(c, sab_10h)


def test_simulador_fora_do_horario():
    d = {"nodes": [{"id": "s", "type": "start", "x": 0, "y": 0, "data": {}}, {"id": "h", "type": "hours", "x": 0, "y": 0, "data": {}},
                   {"id": "a", "type": "enqueue", "x": 0, "y": 0, "data": {"queue": "comercial"}}, {"id": "m", "type": "message", "x": 0, "y": 0, "data": {"text": "Fora do horário"}},
                   {"id": "g", "type": "enqueue", "x": 0, "y": 0, "data": {"queue": "geral"}}],
         "edges": [{"source": "s", "target": "h", "handle": "next"}, {"source": "h", "target": "a", "handle": "open"}, {"source": "h", "target": "m", "handle": "closed"}, {"source": "m", "target": "g", "handle": "next"}]}
    assert F.simulate(MagicMock(), d, [])["outcome"]["queue"] == "comercial"
    assert F.simulate(MagicMock(), d, [], open_now=False)["outcome"]["queue"] == "geral"


def test_salvar_fluxo_guarda_versao_e_poda_as_antigas():
    db = MagicMock()
    db.scalars.side_effect = [MagicMock(all=lambda: [3, 2]), MagicMock(first=lambda: None)]
    db.scalar.return_value = None
    db.get.side_effect = lambda model, i: MagicMock(id=i)
    F.save_flow(db, D(), "a@x.com")
    adds = [c.args[0].__class__.__name__ for c in db.add.call_args_list]
    assert adds[0] == "WaFlowVersion" and "WaFlow" in adds
    assert db.delete.call_count == 2  # passou do limite de versoes
