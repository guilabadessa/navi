"""Fluxo de atendimento: fluxo padrao, validacao ao salvar, persistencia e simulador."""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Client, WaFlow
from . import flow_engine as E

QUEUES = ("comercial", "financeiro", "suporte", "geral")
NODE_TYPES = ("start", "message", "menu", "ask", "lookup_client", "condition", "create_ticket", "notify", "enqueue", "end")
FIXED = {"start": ["next"], "message": ["next"], "notify": ["next"], "ask": ["ok", "invalid", "timeout", "back"], "lookup_client": ["found", "retry", "not_found"],
         "condition": ["true", "false"], "create_ticket": ["next", "error"], "enqueue": [], "end": []}
REQUIRED = {"start": ["next"], "message": ["next"], "notify": ["next"], "ask": ["ok"], "lookup_client": ["found", "not_found"],
            "condition": ["true", "false"], "create_ticket": ["next"]}
MAX_NODES = 100


def _n(id, type, x, y, **data):
    return {"id": id, "type": type, "x": x, "y": y, "data": data}


def _e(s, t, h="next"):
    return {"id": f"{s}:{h}", "source": s, "target": t, "handle": h}


def default_flow(greeting: str, timeout_min: int = 2) -> dict:
    nodes = [
        _n("start", "start", 0, 260),
        _n("menu", "menu", 200, 240, text=greeting, options=[{"key": "1", "label": "Comercial", "aliases": "um"}, {"key": "2", "label": "Financeiro", "aliases": "dois"},
                                                            {"key": "3", "label": "Suporte", "aliases": "tres,três"}], timeout_min=timeout_min, max_invalid=1),
        _n("q_com", "enqueue", 520, 0, queue="comercial"),
        _n("fin_ask", "ask", 520, 150, text="Para o financeiro, informe o CNPJ da sua empresa (somente números).\nPara voltar ao menu, digite 0.", var="cnpj", validate="cnpj", max_attempts=2),
        _n("fin_lookup", "lookup_client", 800, 150, var="cnpj", max_tries=2),
        _n("fin_retry", "message", 800, 300, text="Não localizei esse CNPJ no nosso cadastro. Vamos tentar mais uma vez."),
        _n("fin_hello", "message", 1080, 130, text="Olá, {cliente}! Vou te encaminhar ao financeiro."),
        _n("q_fin", "enqueue", 1340, 130, queue="financeiro"),
        _n("no_cnpj", "message", 1080, 420, text="Não consegui identificar o seu cadastro. Vou te encaminhar ao comercial."),
        _n("sup_ask", "ask", 520, 560, text="Para o suporte, informe o CNPJ da sua empresa (somente números).\nPara voltar ao menu, digite 0.", var="cnpj", validate="cnpj", max_attempts=2),
        _n("sup_lookup", "lookup_client", 800, 560, var="cnpj", max_tries=2),
        _n("sup_retry", "message", 800, 710, text="Não localizei esse CNPJ no nosso cadastro. Vamos tentar mais uma vez."),
        _n("sup_menu", "menu", 1080, 540, text="Olá, {cliente}! Como podemos ajudar?\n1 - Falar com um analista\n2 - Abrir um chamado\n0 - Voltar ao menu principal",
           options=[{"key": "1", "label": "Falar com analista", "aliases": "um,analista"}, {"key": "2", "label": "Abrir chamado", "aliases": "dois,chamado"},
                    {"key": "0", "label": "Voltar ao menu", "aliases": "voltar,menu"}], timeout_min=3, max_invalid=1),
        _n("q_sup", "enqueue", 1380, 540, queue="suporte"),
        _n("tk_ask", "ask", 1380, 680, text="Descreva o problema ou a solicitação (ou digite 0 para voltar):", var="descricao", validate="text", min_len=10, max_attempts=2,
           retry_text="Preciso de um pouco mais de detalhes. Descreva o problema ou a solicitação:"),
        _n("tk_create", "create_ticket", 1660, 680, subject="Suporte via WhatsApp - {cliente}", body="{descricao}\n\nAberto por {nome} ({telefone}) pelo atendimento do WhatsApp.", priority="media"),
        _n("tk_done", "message", 1940, 680, text="Chamado #{chamado} aberto! Nossa equipe vai retornar por aqui."),
        _n("tk_after", "menu", 2220, 660, text="Posso ajudar em mais alguma coisa?\n1 - Voltar ao menu principal\n2 - Encerrar o atendimento",
           options=[{"key": "1", "label": "Voltar ao menu", "aliases": "voltar,menu,sim"}, {"key": "2", "label": "Encerrar", "aliases": "encerrar,nao,não"}], timeout_min=3, max_invalid=1),
        _n("bye", "end", 2520, 700, text="Atendimento encerrado. Obrigado pelo contato com a Orca TI!"),
        _n("tk_err", "message", 1940, 840, text="Não consegui abrir o chamado agora. Vou te passar para um analista."),
    ]
    edges = [
        _e("start", "menu"), _e("menu", "q_com", "opt:1"), _e("menu", "fin_ask", "opt:2"), _e("menu", "sup_ask", "opt:3"),
        _e("fin_ask", "fin_lookup", "ok"), _e("fin_ask", "no_cnpj", "invalid"), _e("fin_lookup", "fin_hello", "found"), _e("fin_lookup", "fin_retry", "retry"),
        _e("fin_retry", "fin_ask"), _e("fin_lookup", "no_cnpj", "not_found"), _e("fin_hello", "q_fin"), _e("no_cnpj", "q_com"),
        _e("sup_ask", "sup_lookup", "ok"), _e("sup_ask", "no_cnpj", "invalid"), _e("sup_lookup", "sup_menu", "found"), _e("sup_lookup", "sup_retry", "retry"),
        _e("sup_retry", "sup_ask"), _e("sup_lookup", "no_cnpj", "not_found"), _e("sup_menu", "q_sup", "opt:1"), _e("sup_menu", "tk_ask", "opt:2"),
        _e("tk_ask", "tk_create", "ok"), _e("tk_ask", "q_sup", "invalid"), _e("tk_create", "tk_done"), _e("tk_create", "tk_err", "error"), _e("tk_err", "q_sup"),
        _e("tk_done", "tk_after"), _e("tk_after", "menu", "opt:1"), _e("tk_after", "bye", "opt:2"), _e("tk_after", "bye", "timeout"), _e("tk_after", "bye", "invalid"),
        _e("fin_ask", "menu", "back"), _e("sup_ask", "menu", "back"), _e("tk_ask", "sup_menu", "back"), _e("sup_menu", "menu", "opt:0"),
    ]
    return {"nodes": nodes, "edges": edges}


def _outputs(node: dict) -> list[str]:
    if node.get("type") == "menu":
        return ["opt:" + str(o.get("key")) for o in (node.get("data") or {}).get("options", [])] + ["invalid", "timeout"]
    return FIXED.get(node.get("type"), [])


def validate_flow(defn: dict, queues=None) -> list[dict]:
    """Lista de erros `{node, msg}`; vazia = valido."""
    valid_queues = tuple(queues) if queues is not None else QUEUES
    errs: list[dict] = []
    err = lambda node, msg: errs.append({"node": node, "msg": msg})  # noqa: E731
    nodes, edges = (defn or {}).get("nodes"), (defn or {}).get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return [{"node": None, "msg": "Fluxo inválido."}]
    if len(nodes) > MAX_NODES:
        return [{"node": None, "msg": f"Fluxo com mais de {MAX_NODES} passos."}]
    ids = [n.get("id") for n in nodes]
    if len(set(ids)) != len(ids) or any(not i for i in ids):
        return [{"node": None, "msg": "Há passos com identificador repetido ou vazio."}]
    by = {n["id"]: n for n in nodes}
    if sum(1 for n in nodes if n.get("type") == "start") != 1:
        err(None, "O fluxo precisa ter exatamente um passo de início.")
    used: dict[tuple, str] = {}
    for ed in edges:
        s, t, h = ed.get("source"), ed.get("target"), ed.get("handle") or "next"
        if s not in by or t not in by:
            err(None, "Há uma ligação para um passo que não existe.")
            continue
        if h not in _outputs(by[s]):
            err(s, f"Saída “{h}” não existe neste passo.")
            continue
        if (s, h) in used:
            err(s, f"A saída “{h}” está ligada a mais de um destino.")
        used[(s, h)] = t
    for n in nodes:
        t, d, i = n.get("type"), n.get("data") or {}, n["id"]
        if t not in NODE_TYPES:
            err(i, f"Tipo de passo desconhecido: {t}.")
            continue
        need = REQUIRED.get(t, [])
        if t == "menu":
            keys = [str(o.get("key", "")).strip() for o in d.get("options", [])]
            if not keys or any(not k for k in keys) or len(set(keys)) != len(keys):
                err(i, "O menu precisa de ao menos uma opção, com teclas únicas e não vazias.")
            need = ["opt:" + k for k in keys]
        for h in need:
            if (i, h) not in used:
                err(i, f"Falta ligar a saída “{h}”.")
        if t in ("message", "menu", "ask") and not str(d.get("text", "")).strip():
            err(i, "O texto é obrigatório.")
        if t == "ask" and d.get("validate", "any") not in ("cnpj", "text", "any"):
            err(i, "Validação inválida.")
        if t == "ask" and not str(d.get("var", "")).strip():
            err(i, "Informe o nome da variável que guarda a resposta.")
        if t == "lookup_client" and not str(d.get("var", "")).strip():
            err(i, "Informe a variável que contém o CNPJ.")
        if t == "enqueue" and d.get("queue") not in valid_queues:
            err(i, "Escolha uma fila existente e ativa.")
        if t == "condition" and d.get("op") not in ("empty", "not_empty", "equals"):
            err(i, "Escolha a condição.")
        if t == "create_ticket" and not str(d.get("subject", "")).strip():
            err(i, "O assunto do chamado é obrigatório.")
    # laco infinito: ciclo formado so por passos automaticos (sem esperar o cliente)
    auto = {i for i, n in by.items() if n.get("type") in E.AUTO}
    graph: dict[str, list[str]] = {i: [] for i in auto}
    for (s, _h), t in used.items():
        if s in auto and t in auto:
            graph[s].append(t)
    state: dict[str, int] = {}

    def dfs(u: str) -> bool:
        state[u] = 1
        for v in graph[u]:
            if state.get(v) == 1 or (state.get(v) is None and dfs(v)):
                return True
        state[u] = 2
        return False

    for u in graph:
        if state.get(u) is None and dfs(u):
            err(u, "Este passo faz parte de um laço sem espera pelo cliente (o fluxo giraria sem parar).")
            break
    return errs


def cnpj_client(db: Session, digits: str) -> dict | None:
    if len(digits) != 14:
        return None
    c = db.scalar(select(Client).where(func.regexp_replace(Client.cnpj, "[^0-9]", "", "g") == digits).order_by(Client.id).limit(1))
    return {"id": c.id, "name": c.trade_name} if c else None


def load_flow(db: Session, greeting: str, timeout_min: int = 2, queues=None) -> tuple[dict, bool]:
    """(definicao, e_padrao). Fluxo salvo invalido nunca e usado: cai no padrao."""
    row = db.scalar(select(WaFlow).order_by(WaFlow.id.desc()).limit(1))
    if row is not None and not validate_flow(row.definition, queues):
        return row.definition, False
    return default_flow(greeting, timeout_min), True


def save_flow(db: Session, defn: dict, user: str | None) -> None:
    row = db.scalar(select(WaFlow).order_by(WaFlow.id.desc()).limit(1))
    if row is None:
        db.add(WaFlow(definition=defn, updated_by=user))
    else:
        row.definition, row.updated_by, row.updated_at = defn, user, datetime.now(timezone.utc)


def reset_flow(db: Session) -> None:
    for row in db.scalars(select(WaFlow)).all():
        db.delete(row)


class SimHost(E.Host):
    """Simulador: consulta o cliente de verdade (leitura), mas chamado e avisos sao so descritos."""
    def __init__(self, db: Session, transcript: list):
        self.db, self.t = db, transcript

    def say(self, text): self.t.append({"from": "bot", "text": text})
    def find_client(self, digits): return cnpj_client(self.db, digits)
    def link_client(self, client): self.t.append({"from": "sistema", "text": f"Cliente vinculado: {client['name']}"})

    def create_ticket(self, subject, body, priority, queue_id):
        self.t.append({"from": "sistema", "text": f"[simulação] Chamado criado: {subject}"})
        return {"number": "SIM-1"}

    def notify(self, dests, text): self.t.append({"from": "sistema", "text": f"[simulação] Aviso para {', '.join(dests) or '—'}: {text}"})


def simulate(db: Session, defn: dict, inputs: list[str], queues=None) -> dict:
    errs = validate_flow(defn, queues)
    if errs:
        return {"errors": errs, "transcript": [], "outcome": None}
    t: list[dict] = []
    host, flow, st = SimHost(db, t), E.Flow(defn), E.State(vars={"nome": "Contato Teste", "telefone": "5514999990000"})
    out = E.start(flow, st, host)
    for text in inputs:
        if out.kind != "waiting":
            break
        t.append({"from": "cliente", "text": text})
        out = E.answer(flow, st, text, host)
    if out.kind == "enqueue":
        t.append({"from": "sistema", "text": f"→ Fila {out.queue}"})
    elif out.kind == "end":
        t.append({"from": "sistema", "text": "→ Atendimento encerrado"})
    return {"errors": [], "transcript": t, "outcome": {"kind": out.kind, "queue": out.queue}}
