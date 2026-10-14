from app.services import flow_engine as E


class FakeHost(E.Host):
    def __init__(self, clients=None, ticket=True):
        self.said, self.notified, self.tickets, self.linked = [], [], [], []
        self.clients, self.ticket_ok = clients or {}, ticket

    def say(self, text): self.said.append(text)
    def find_client(self, digits): return self.clients.get(digits)
    def link_client(self, c): self.linked.append(c)
    def notify(self, dests, text): self.notified.append((dests, text))

    def create_ticket(self, subject, body, priority, queue_id):
        if not self.ticket_ok:
            return None
        self.tickets.append((subject, body, priority, queue_id))
        return {"number": 1042}


def n(id, type, **data): return {"id": id, "type": type, "data": data}
def e(s, t, h="next"): return {"id": f"{s}-{h}", "source": s, "target": t, "handle": h}
def flow(nodes, edges): return E.Flow({"nodes": nodes, "edges": edges})


def test_cnpj_valido_e_invalido():
    assert E.cnpj_valid("11.222.333/0001-81") and E.cnpj_valid("11222333000181")
    assert not E.cnpj_valid("11.222.333/0001-82") and not E.cnpj_valid("11111111111111") and not E.cnpj_valid("abc") and not E.cnpj_valid("")


def test_render_variaveis_desconhecidas_viram_vazio():
    assert E.render("Oi {nome} {x}!", {"nome": "Ana"}) == "Oi Ana !"


def test_mensagem_encadeada_ate_a_fila():
    f = flow([n("s", "start"), n("m", "message", text="Oi {nome}"), n("q", "enqueue", queue="suporte")], [e("s", "m"), e("m", "q")])
    h, st = FakeHost(), E.State(vars={"nome": "Ana"})
    o = E.start(f, st, h)
    assert o.kind == "enqueue" and o.queue == "suporte" and h.said == ["Oi Ana"]


def _menu_flow():
    return flow([n("s", "start"), n("m", "menu", text="Digite 1 ou 2", options=[{"key": "1", "aliases": "um"}, {"key": "2"}], timeout_min=3),
                 n("a", "enqueue", queue="comercial"), n("b", "enqueue", queue="financeiro")],
                [e("s", "m"), e("m", "a", "opt:1"), e("m", "b", "opt:2")])


def test_menu_espera_e_segue_a_opcao_inclusive_alias():
    f, h, st = _menu_flow(), FakeHost(), E.State()
    o = E.start(f, st, h)
    assert o.kind == "waiting" and o.timeout_min == 3 and st.node == "m" and h.said == ["Digite 1 ou 2"]
    assert E.answer(f, st, " UM ", h).queue == "comercial"
    st2 = E.State(node="m")
    assert E.answer(f, st2, "2", h).queue == "financeiro"


def test_menu_invalido_repete_uma_vez_e_depois_cai_na_fila_geral():
    f, h, st = _menu_flow(), FakeHost(), E.State()
    E.start(f, st, h)
    assert E.answer(f, st, "blabla", h).kind == "waiting" and len(h.said) == 2
    o = E.answer(f, st, "blabla", h)
    assert o.kind == "enqueue" and o.queue == "geral"


def test_menu_invalido_segue_saida_invalid_quando_ligada():
    f = flow([n("m", "menu", text="x", options=[{"key": "1"}]), n("s", "start"), n("q", "enqueue", queue="suporte"), n("z", "enqueue", queue="comercial")],
             [e("s", "m"), e("m", "q", "opt:1"), e("m", "z", "invalid")])
    st, h = E.State(), FakeHost()
    E.start(f, st, h)
    E.answer(f, st, "?", h)
    assert E.answer(f, st, "?", h).queue == "comercial"


def test_timeout_segue_saida_ou_cai_na_geral():
    f = flow([n("s", "start"), n("m", "menu", text="x", options=[{"key": "1"}]), n("q", "enqueue", queue="suporte"), n("t", "enqueue", queue="comercial")],
             [e("s", "m"), e("m", "q", "opt:1"), e("m", "t", "timeout")])
    st = E.State(); E.start(f, st, FakeHost())
    assert E.timeout(f, st, FakeHost()).queue == "comercial"
    f2 = flow([n("s", "start"), n("m", "menu", text="x", options=[{"key": "1"}]), n("q", "enqueue", queue="suporte")], [e("s", "m"), e("m", "q", "opt:1")])
    st2 = E.State(); E.start(f2, st2, FakeHost())
    assert E.timeout(f2, st2, FakeHost()).queue == "geral"


def _cnpj_flow():
    return flow([n("s", "start"), n("a", "ask", text="Qual o CNPJ?", var="cnpj", validate="cnpj", max_attempts=2),
                 n("l", "lookup_client", var="cnpj", max_tries=2), n("ok", "enqueue", queue="financeiro"),
                 n("r", "message", text="Não localizei, tente de novo."), n("nf", "message", text="Vou te passar ao comercial."),
                 n("com", "enqueue", queue="comercial")],
                [e("s", "a"), e("a", "l", "ok"), e("a", "nf", "invalid"), e("l", "ok", "found"), e("l", "r", "retry"), e("r", "a"), e("l", "nf", "not_found"), e("nf", "com")])


def test_cnpj_achado_vincula_cliente_e_vai_para_fila():
    h = FakeHost(clients={"11222333000181": {"id": 5, "name": "Echoes"}})
    f, st = _cnpj_flow(), E.State()
    E.start(f, st, h)
    o = E.answer(f, st, "11.222.333/0001-81", h)
    assert o.queue == "financeiro" and st.vars["cliente"] == "Echoes" and h.linked == [{"id": 5, "name": "Echoes"}]


def test_cnpj_invalido_pede_de_novo_e_depois_vai_ao_comercial():
    h, f, st = FakeHost(), _cnpj_flow(), E.State()
    E.start(f, st, h)
    assert E.answer(f, st, "123", h).kind == "waiting"
    o = E.answer(f, st, "abc", h)
    assert o.queue == "comercial" and "comercial" in h.said[-1]


def test_cnpj_valido_inexistente_tenta_de_novo_uma_vez_e_vai_ao_comercial():
    h, f, st = FakeHost(), _cnpj_flow(), E.State()
    E.start(f, st, h)
    o = E.answer(f, st, "11222333000181", h)  # nao existe: retry -> mensagem -> pergunta de novo
    assert o.kind == "waiting" and "Não localizei" in h.said[1]
    o = E.answer(f, st, "11222333000181", h)
    assert o.queue == "comercial"


def test_condicao_e_chamado_e_fim():
    f = flow([n("s", "start"), n("c", "condition", var="client_id", op="not_empty"), n("t", "create_ticket", subject="Suporte {nome}", body="{descricao}", priority="alta", queue_id=3),
              n("end", "end", text="Chamado {chamado} aberto"), n("q", "enqueue", queue="geral")],
             [e("s", "c"), e("c", "t", "true"), e("c", "q", "false"), e("t", "end"), e("t", "q", "error")])
    h = FakeHost()
    o = E.start(f, E.State(vars={"client_id": 1, "nome": "Ana", "descricao": "sem rede"}), h)
    assert o.kind == "end" and h.said == ["Chamado 1042 aberto"] and h.tickets == [("Suporte Ana", "sem rede", "alta", 3)]
    assert E.start(f, E.State(), FakeHost()).queue == "geral"  # sem cliente vinculado
    assert E.start(f, E.State(vars={"client_id": 1}), FakeHost(ticket=False)).queue == "geral"  # falha ao abrir o chamado


def test_notify_envia_aos_destinos():
    f = flow([n("s", "start"), n("n", "notify", to=["120@g.us", ""], text="Fila {nome}"), n("q", "enqueue", queue="suporte")], [e("s", "n"), e("n", "q")])
    h = FakeHost(); E.start(f, E.State(vars={"nome": "Ana"}), h)
    assert h.notified == [(["120@g.us"], "Fila Ana")]


def test_no_ausente_laco_e_estado_invalido_caem_na_fila_geral():
    assert E.start(flow([], []), E.State(), FakeHost()).queue == "geral"
    laco = flow([n("s", "start"), n("m", "message", text="x")], [e("s", "m"), e("m", "m")])
    assert E.start(laco, E.State(), FakeHost()).queue == "geral"
    assert E.answer(_menu_flow(), E.State(node="sumiu"), "1", FakeHost()).queue == "geral"
    semsaida = flow([n("s", "start")], [])
    assert E.start(semsaida, E.State(), FakeHost()).queue == "geral"


def test_horario_set_var_e_etiqueta():
    f = flow([n("s", "start"), n("h", "hours"), n("v", "set_var", var="origem", value="whats {nome}"), n("t", "tag", tag="VIP"), n("a", "enqueue", queue="comercial"), n("f", "message", text="Fechado"), n("q", "enqueue", queue="geral")],
             [e("s", "h"), e("h", "v", "open"), e("h", "f", "closed"), e("v", "t"), e("t", "a"), e("f", "q")])

    class H(FakeHost):
        def __init__(self, aberto): super().__init__(); self.aberto, self.tags = aberto, []
        def is_open(self): return self.aberto
        def add_tag(self, tag): self.tags.append(tag)

    h, st = H(True), E.State(vars={"nome": "Ana"})
    assert E.start(f, st, h).queue == "comercial" and st.vars["origem"] == "whats Ana" and h.tags == ["VIP"]
    h2 = H(False)
    assert E.start(f, E.State(), h2).queue == "geral" and h2.said == ["Fechado"] and h2.tags == []
