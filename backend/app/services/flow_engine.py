"""Motor puro do fluxo de atendimento: percorre o grafo sobre um estado. Os efeitos (responder, achar cliente, abrir
chamado, avisar) passam por um `Host`, entao o mesmo motor serve ao atendimento real e ao simulador."""
import re
from dataclasses import dataclass, field

MAX_STEPS = 40
WAITING = ("menu", "ask")
AUTO = ("start", "message", "notify", "lookup_client", "condition", "create_ticket")
TERMINAL = ("enqueue", "end")
FALLBACK_QUEUE = "geral"
_VAR = re.compile(r"\{(\w+)\}")


def render(text: str, vars: dict) -> str:
    return _VAR.sub(lambda m: str(vars.get(m.group(1), "") or ""), text or "")


def cnpj_digits(v: str) -> str:
    return re.sub(r"\D", "", v or "")


def cnpj_valid(v: str) -> bool:
    d = cnpj_digits(v)
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for n in (12, 13):
        w = list(range(n - 7, 1, -1)) + list(range(9, 1, -1))
        s = sum(int(d[i]) * w[i] for i in range(n))
        if int(d[n]) != (0 if s % 11 < 2 else 11 - s % 11):
            return False
    return True


class Host:
    """Efeitos colaterais do fluxo. A implementacao real fala com o WhatsApp e o banco; o simulador so registra."""
    def say(self, text: str) -> None: ...
    def find_client(self, digits: str) -> dict | None: return None  # {"id", "name"}
    def link_client(self, client: dict) -> None: ...
    def create_ticket(self, subject: str, body: str, priority: str, queue_id: int | None) -> dict | None: return None  # {"number"}
    def notify(self, dests: list[str], text: str) -> None: ...


@dataclass
class State:
    node: str | None = None
    vars: dict = field(default_factory=dict)

    @property
    def counters(self) -> dict:
        return self.vars.setdefault("_c", {})


@dataclass
class Outcome:
    kind: str  # waiting | enqueue | end
    queue: str | None = None
    timeout_min: int | None = None
    prompted: bool = False


class Flow:
    def __init__(self, defn: dict):
        self.nodes = {n["id"]: n for n in (defn or {}).get("nodes", [])}
        self.edges = {(e["source"], e.get("handle") or "next"): e["target"] for e in (defn or {}).get("edges", [])}

    def start_id(self) -> str | None:
        return next((i for i, n in self.nodes.items() if n.get("type") == "start"), None)

    def go(self, node_id: str, handle: str) -> str | None:
        return self.edges.get((node_id, handle))


def _geral() -> Outcome:
    return Outcome("enqueue", FALLBACK_QUEUE)


def _enter_wait(node: dict, state: State, host: Host) -> Outcome:
    d = node.get("data") or {}
    state.node = node["id"]
    state.counters[node["id"]] = 0
    host.say(render(d.get("text", ""), state.vars))
    return Outcome("waiting", timeout_min=d.get("timeout_min"), prompted=True)


def run(flow: Flow, state: State, host: Host, node_id: str | None) -> Outcome:
    """Executa a partir de `node_id` ate parar em espera, fila ou fim."""
    for _ in range(MAX_STEPS):
        node = flow.nodes.get(node_id) if node_id else None
        if node is None:
            return _geral()
        t, d = node.get("type"), node.get("data") or {}
        nxt = None
        if t in WAITING:
            return _enter_wait(node, state, host)
        if t == "enqueue":
            return Outcome("enqueue", d.get("queue") or FALLBACK_QUEUE)
        if t == "end":
            if d.get("text"):
                host.say(render(d["text"], state.vars))
            return Outcome("end")
        if t == "start":
            nxt = flow.go(node["id"], "next")
        elif t == "message":
            host.say(render(d.get("text", ""), state.vars))
            nxt = flow.go(node["id"], "next")
        elif t == "notify":
            host.notify([x for x in d.get("to", []) if x], render(d.get("text", ""), state.vars))
            nxt = flow.go(node["id"], "next")
        elif t == "condition":
            v = str(state.vars.get(d.get("var", ""), "") or "")
            ok = {"empty": not v, "not_empty": bool(v), "equals": v.strip().lower() == str(d.get("value", "")).strip().lower()}.get(d.get("op"), False)
            nxt = flow.go(node["id"], "true" if ok else "false")
        elif t == "lookup_client":
            client = host.find_client(cnpj_digits(str(state.vars.get(d.get("var", "cnpj"), ""))))
            if client:
                state.vars.update(cliente=client["name"], client_id=client["id"])
                host.link_client(client)
                nxt = flow.go(node["id"], "found")
            else:
                k = "lk:" + node["id"]
                state.counters[k] = state.counters.get(k, 0) + 1
                retry = flow.go(node["id"], "retry")
                nxt = retry if retry and state.counters[k] < int(d.get("max_tries") or 2) else flow.go(node["id"], "not_found")
        elif t == "create_ticket":
            res = host.create_ticket(render(d.get("subject", ""), state.vars), render(d.get("body", ""), state.vars),
                                     d.get("priority") or "media", d.get("queue_id"))
            if res:
                state.vars["chamado"] = res["number"]
                nxt = flow.go(node["id"], "next")
            else:
                nxt = flow.go(node["id"], "error")
        else:
            return _geral()
        node_id = nxt
    return _geral()  # estourou o limite de passos: nunca deixa o cliente sem destino


def start(flow: Flow, state: State, host: Host) -> Outcome:
    return run(flow, state, host, flow.start_id())


def answer(flow: Flow, state: State, text: str, host: Host) -> Outcome:
    node = flow.nodes.get(state.node or "")
    if node is None or node.get("type") not in WAITING:
        return _geral()
    d, text = node.get("data") or {}, (text or "").strip()
    nid = node["id"]
    if node["type"] == "menu":
        low = text.lower()
        for o in d.get("options", []):
            keys = [str(o.get("key", "")).lower()] + [a.strip().lower() for a in str(o.get("aliases", "")).split(",") if a.strip()]
            if low in keys:
                return run(flow, state, host, flow.go(nid, "opt:" + str(o["key"])))
        state.counters[nid] = state.counters.get(nid, 0) + 1
        if state.counters[nid] <= int(d.get("max_invalid", 1)):
            host.say(render(d.get("text", ""), state.vars))
            return Outcome("waiting", timeout_min=d.get("timeout_min"), prompted=True)
        return run(flow, state, host, flow.go(nid, "invalid"))
    if text.lower() in ("0", "voltar", "menu") and flow.go(nid, "back"):  # saida opcional: o cliente desiste e volta
        return run(flow, state, host, flow.go(nid, "back"))
    kind = d.get("validate", "any")
    ok = cnpj_valid(text) if kind == "cnpj" else len(text) >= int(d.get("min_len") or 1)
    if ok:
        state.vars[d.get("var") or "resposta"] = cnpj_digits(text) if kind == "cnpj" else text
        return run(flow, state, host, flow.go(nid, "ok"))
    state.counters[nid] = state.counters.get(nid, 0) + 1
    if state.counters[nid] < int(d.get("max_attempts") or 2):
        host.say(render(d.get("retry_text") or ("Não consegui validar a informação. " + d.get("text", "")), state.vars))
        return Outcome("waiting", timeout_min=d.get("timeout_min"), prompted=True)
    return run(flow, state, host, flow.go(nid, "invalid"))


def timeout(flow: Flow, state: State, host: Host) -> Outcome:
    node = flow.nodes.get(state.node or "")
    if node is None or node.get("type") not in WAITING:
        return _geral()
    return run(flow, state, host, flow.go(node["id"], "timeout"))
