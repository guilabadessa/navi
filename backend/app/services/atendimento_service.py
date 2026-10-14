"""Atendimento por WhatsApp: menu, filas por setor e acoes do analista. Envio sempre pelo gateway (WA-AKG)."""
import copy
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..models import Client, WaConversation, WaMessage
from . import flow_engine as E, flow_service as FS, ticket_service as TS
from .wa_akg_service import WaAkgError, WaAkgService

log = logging.getLogger("navi.atendimento")
QUEUES = ("comercial", "financeiro", "suporte", "geral")
LABEL = {"comercial": "Comercial", "financeiro": "Financeiro", "suporte": "Suporte", "geral": "Atendimento geral"}
DEFAULT_CFG = {
    "greeting": "Bem-vindo à Orca TI.\nPara falar com o comercial, digite 1.\nPara o financeiro, digite 2.\nPara o suporte, digite 3.\nOu aguarde para ser atendido.",
    "menu_timeout_min": 2,
    "wait_alert_min": 5,
    "closing_message": "Atendimento encerrado. Obrigado pelo contato com a Orca TI!",
    "queues": {q: {"alert_enabled": False, "alert_to": []} for q in QUEUES},
}


def now():
    return datetime.now(timezone.utc)


def cfg(db: Session) -> dict:
    """Configuracao salva sobre o padrao (campo a campo, inclusive por fila)."""
    try:
        saved = json.loads(S.get(db, "atendimento.config") or "{}")
    except ValueError:
        saved = {}
    out = {**DEFAULT_CFG, **{k: v for k, v in saved.items() if k in DEFAULT_CFG and k != "queues"}}
    out["queues"] = {q: {**DEFAULT_CFG["queues"][q], **((saved.get("queues") or {}).get(q) or {})} for q in QUEUES}
    return out


def is_individual(jid: str) -> bool:
    return (jid or "").endswith(("@s.whatsapp.net", "@lid"))


def phone_key(v: str) -> str | None:
    """DDD + 8 ultimos digitos: casa o mesmo telefone com/sem 55 e com/sem o 9o digito. None para grupo."""
    if not v or v.endswith("@g.us"):
        return None
    d = re.sub(r"\D", "", v.split("@")[0])
    if d.startswith("55") and len(d) >= 12:
        d = d[2:]
    return d[:2] + d[-8:] if len(d) >= 10 else None


def match_client(db: Session, jid: str) -> Client | None:
    key = phone_key(jid)
    if not key or jid.endswith("@lid"):
        return None
    found = [c for c in db.scalars(select(Client).where(Client.whatsapp.is_not(None))).all() if phone_key(c.whatsapp or "") == key]
    return found[0] if len(found) == 1 else None


def open_conversation(db: Session, jid: str) -> WaConversation | None:
    return db.scalar(select(WaConversation).where(WaConversation.jid == jid, WaConversation.state != "encerrada")
                     .order_by(WaConversation.id.desc()).limit(1))


def _record_out(db: Session, conv: WaConversation, text: str, resp: dict | None, user_id: int | None = None,
                failed: bool = False, mtype: str = "TEXT") -> WaMessage:
    ext = (WaAkgService.message_id(resp) if resp else None) or "navi-" + uuid.uuid4().hex
    existing = db.scalar(select(WaMessage).where(WaMessage.external_id == ext))
    if existing is not None:  # o eco do webhook chegou antes de gravarmos
        existing.conversation_id, existing.sent_by = conv.id, user_id
        return existing
    m = WaMessage(external_id=ext, session="", jid=conv.jid, direction="out", type=mtype, text=text, sent_by=user_id,
                  failed=failed, conversation_id=conv.id)
    db.add(m)
    return m


def _say(db: Session, conv: WaConversation, gw, text: str) -> None:
    """Resposta automatica do NAVI ao cliente."""
    try:
        _record_out(db, conv, text, gw.send_text(conv.jid, text))
    except Exception as e:  # noqa: BLE001
        log.warning("atendimento: falha ao responder %s: %s", conv.jid, e)


def _alert(db: Session, conv: WaConversation, gw) -> None:
    q = cfg(db)["queues"].get(conv.queue) or {}
    if not q.get("alert_enabled") or not q.get("alert_to"):
        return
    n = db.scalar(select(func.count()).select_from(WaConversation).where(WaConversation.state == "aguardando", WaConversation.queue == conv.queue)) or 0
    client = db.get(Client, conv.client_id) if conv.client_id else None
    who = (conv.push_name or conv.jid.split("@")[0]) + (f" ({client.trade_name})" if client else "")
    text = f"🔔 Fila {LABEL[conv.queue]}: {who} aguardando atendimento · {n} na fila"
    for dest in q["alert_to"]:
        try:
            gw.send_text(dest, text)
        except Exception as e:  # noqa: BLE001
            log.warning("atendimento: falha no aviso para %s: %s", dest, e)


def _enqueue(db: Session, conv: WaConversation, queue: str, gw) -> None:
    conv.state, conv.queue, conv.queued_at = "aguardando", queue, now()
    _say(db, conv, gw, f"Você está na fila do {LABEL[queue]}. Em instantes um analista vai te atender.")
    _alert(db, conv, gw)


class RealHost(E.Host):
    """Efeitos reais do fluxo: responde pelo WhatsApp, acha o cliente, abre o chamado e avisa."""
    def __init__(self, db: Session, conv: WaConversation, gw):
        self.db, self.conv, self.gw = db, conv, gw

    def say(self, text):
        if text.strip():
            _say(self.db, self.conv, self.gw, text)

    def find_client(self, digits):
        return FS.cnpj_client(self.db, digits)

    def link_client(self, client):
        self.conv.client_id = client["id"]

    def create_ticket(self, subject, body, priority, queue_id):
        if not self.conv.client_id:
            return None
        try:
            t = TS.create_from_whatsapp(self.db, self.conv.client_id, subject, body, self.conv.jid.split("@")[0], self.conv.push_name, priority, queue_id)
            return {"number": t.number}
        except Exception:  # noqa: BLE001
            self.db.rollback()
            log.exception("atendimento: falha ao abrir chamado pelo fluxo")
            return None

    def notify(self, dests, text):
        for d in dests:
            try:
                self.gw.send_text(d, text)
            except Exception as e:  # noqa: BLE001
                log.warning("atendimento: falha no aviso para %s: %s", d, e)


def _apply(db: Session, conv: WaConversation, state: E.State, out: E.Outcome, gw) -> None:
    """Grava no estado da conversa o resultado da execucao do fluxo."""
    if out.kind == "waiting":
        conv.state, conv.flow_node = "menu", state.node
        state.vars["_t"] = out.timeout_min
        if out.prompted:
            conv.menu_sent_at = now()
    elif out.kind == "enqueue":
        conv.flow_node = None
        _enqueue(db, conv, out.queue if out.queue in QUEUES else "geral", gw)
    else:  # end: atendimento resolvido pelo proprio fluxo (ex.: chamado aberto)
        conv.state, conv.flow_node, conv.closed_at, conv.unread = "encerrada", None, now(), 0
    conv.flow_vars = copy.deepcopy(state.vars)


def _flow(db: Session) -> E.Flow:
    c = cfg(db)
    return E.Flow(FS.load_flow(db, c["greeting"], int(c["menu_timeout_min"]))[0])


def handle_inbound(db: Session, msg: WaMessage, gw) -> WaConversation | None:
    """Decide o que fazer com uma mensagem gravada. Saidas e grupos nunca abrem conversa."""
    if not is_individual(msg.jid):
        return None
    conv = open_conversation(db, msg.jid)
    if msg.direction == "out":
        if conv is not None:
            msg.conversation_id = conv.id
            conv.last_message_at = now()
        return None
    if conv is None:
        client = match_client(db, msg.jid)
        conv = WaConversation(jid=msg.jid, push_name=msg.push_name, client_id=client.id if client else None, state="menu",
                              queue="geral", menu_sent_at=now(), menu_tries=0, unread=0)
        db.add(conv)
        db.flush()
        state = E.State(vars={"nome": msg.push_name or "", "telefone": conv.jid.split("@")[0], **({"cliente": client.trade_name, "client_id": client.id} if client else {})})
        _apply(db, conv, state, E.start(_flow(db), state, RealHost(db, conv, gw)), gw)
    elif conv.state == "menu":
        state = E.State(node=conv.flow_node, vars=copy.deepcopy(conv.flow_vars or {}))
        _apply(db, conv, state, E.answer(_flow(db), state, msg.text, RealHost(db, conv, gw)), gw)
    else:
        conv.unread = (conv.unread or 0) + 1
    msg.conversation_id = conv.id
    conv.last_message_at = now()
    if msg.push_name:
        conv.push_name = msg.push_name
    return conv


def tick(db: Session, gw) -> int:
    """Conversa esperando resposta no fluxo ha mais que o tempo do passo (padrao `menu_timeout_min`): segue a saida de timeout."""
    padrao = int(cfg(db)["menu_timeout_min"])
    flow, n = _flow(db), 0
    for conv in db.scalars(select(WaConversation).where(WaConversation.state == "menu")).all():
        state = E.State(node=conv.flow_node, vars=copy.deepcopy(conv.flow_vars or {}))
        limite = now() - timedelta(minutes=int(state.vars.get("_t") or padrao))
        if conv.menu_sent_at is None or conv.menu_sent_at >= limite:
            continue
        _apply(db, conv, state, E.timeout(flow, state, RealHost(db, conv, gw)), gw)
        n += 1
    return n


def assume(db: Session, conv_id: int, user_id: int) -> bool:
    """Atomico: so quem chegar primeiro assume uma conversa que ainda esta aguardando."""
    r = db.execute(update(WaConversation).where(WaConversation.id == conv_id, WaConversation.state == "aguardando")
                   .values(state="atendendo", assigned_to=user_id, assumed_at=now(), unread=0))
    return r.rowcount == 1


def transfer(db: Session, conv: WaConversation, user_id: int | None, queue: str | None, gw=None) -> None:
    if queue and queue in QUEUES:
        conv.queue = queue
    if user_id:
        conv.state, conv.assigned_to, conv.assumed_at = "atendendo", user_id, now()
    else:  # volta para a fila do setor
        conv.state, conv.assigned_to, conv.queued_at = "aguardando", None, now()
        if gw is not None:
            _alert(db, conv, gw)


def close(db: Session, conv: WaConversation, user_id: int, send_closing: bool, gw) -> None:
    conv.state, conv.closed_at, conv.closed_by, conv.unread = "encerrada", now(), user_id, 0
    if send_closing:
        _say(db, conv, gw, cfg(db)["closing_message"])


def send(db: Session, conv: WaConversation, user_id: int, text: str, gw) -> WaMessage:
    try:
        resp = gw.send_text(conv.jid, text)
    except WaAkgError:
        _record_out(db, conv, text, None, user_id, failed=True)
        raise
    conv.last_message_at = now()
    return _record_out(db, conv, text, resp, user_id)


def send_media(db: Session, conv: WaConversation, user_id: int, data: bytes, filename: str, mime: str, caption: str, gw) -> WaMessage:
    mtype = "IMAGE" if mime.startswith("image/") else "DOCUMENT"
    try:
        resp = gw.send_media(conv.jid, data, filename, mime, caption)
    except WaAkgError:
        _record_out(db, conv, caption or filename, None, user_id, failed=True, mtype=mtype)
        raise
    conv.last_message_at = now()
    return _record_out(db, conv, caption or filename, resp, user_id, mtype=mtype)
