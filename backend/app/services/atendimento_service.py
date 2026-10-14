"""Atendimento por WhatsApp: menu, filas por setor e acoes do analista. Envio sempre pelo gateway (WA-AKG)."""
import copy
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..models import Client, WaConversation, WaMessage, WaQueue
from . import flow_engine as E, flow_service as FS, ticket_service as TS
from .wa_akg_service import WaAkgError, WaAkgService

log = logging.getLogger("navi.atendimento")
FALLBACK = "geral"  # fila do sistema: nunca some (destino quando a fila pedida nao existe mais)
SEED_QUEUES = (("comercial", "Comercial", "#1e73f8"), ("financeiro", "Financeiro", "#0f8b8d"), ("suporte", "Suporte", "#7b3fe4"), ("geral", "Geral", "#6b7a99"))
DEFAULT_CFG = {
    "greeting": "Bem-vindo à Orca TI.\nPara falar com o comercial, digite 1.\nPara o financeiro, digite 2.\nPara o suporte, digite 3.\nOu aguarde para ser atendido.",
    "menu_timeout_min": 2,
    "wait_alert_min": 5,
    "closing_message": "Atendimento encerrado. Obrigado pelo contato com a Orca TI!",
    "inactivity_hours": 24,  # sem mensagens de ninguem por tanto tempo, o atendimento e encerrado (0 desliga)
    "inactivity_message": "Encerramos este atendimento por falta de interação. Se precisar, é só enviar uma nova mensagem. 👋",
    "quick_replies": [{"title": "Vou verificar", "text": "Olá! Vou verificar isso para você e já retorno."},
                      {"title": "Pedir print", "text": "Pode nos enviar um print ou foto da tela com o erro, por favor?"},
                      {"title": "Aguarde um instante", "text": "Só um instante, estou analisando."}],
}


def now():
    return datetime.now(timezone.utc)


def cfg(db: Session) -> dict:
    """Configuracao salva sobre o padrao (campo a campo)."""
    try:
        saved = json.loads(S.get(db, "atendimento.config") or "{}")
    except ValueError:
        saved = {}
    return {**DEFAULT_CFG, **{k: v for k, v in saved.items() if k in DEFAULT_CFG}}


def queue_map(db: Session) -> dict:
    """slug -> fila (linhas de `wa_queues`, em ordem). Sem linhas (banco novo/testes), valem as filas padrao sem avisos."""
    rows = list(db.scalars(select(WaQueue).order_by(WaQueue.sort, WaQueue.id)).all())
    if rows:
        return {q.slug: q for q in rows}
    return {s: SimpleNamespace(slug=s, name=n, color=c, active=True, system=s == FALLBACK, alert_enabled=False, alert_to=[], wait_alert_min=None)
            for s, n, c in SEED_QUEUES}


def queue_ok(db: Session, slug: str | None) -> str:
    """Slug utilizavel (existe e esta ativa) ou a fila geral."""
    q = queue_map(db).get(slug or "")
    return slug if q is not None and q.active else FALLBACK


def qname(db: Session, slug: str) -> str:
    q = queue_map(db).get(slug)
    return q.name if q is not None else slug


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


def event(db: Session, conv: WaConversation, text: str) -> None:
    """Linha do tempo da conversa (assumiu, transferiu, entrou na fila...). Nunca vai ao cliente nem conta como nao lida."""
    db.add(WaMessage(external_id="ev-" + uuid.uuid4().hex, session="", jid=conv.jid, direction="sys", type="EVENT", text=text, conversation_id=conv.id))


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
    q = queue_map(db).get(conv.queue)
    if q is None or not q.alert_enabled or not q.alert_to:
        return
    n = db.scalar(select(func.count()).select_from(WaConversation).where(WaConversation.state == "aguardando", WaConversation.queue == conv.queue)) or 0
    client = db.get(Client, conv.client_id) if conv.client_id else None
    who = (conv.contact_name or conv.push_name or conv.jid.split("@")[0]) + (f" ({client.trade_name})" if client else "")
    text = f"🔔 Fila {q.name}: {who} aguardando atendimento · {n} na fila"
    for dest in q.alert_to:
        try:
            gw.send_text(dest, text)
        except Exception as e:  # noqa: BLE001
            log.warning("atendimento: falha no aviso para %s: %s", dest, e)


def _enqueue(db: Session, conv: WaConversation, queue: str, gw) -> None:
    queue = queue_ok(db, queue)
    conv.state, conv.queue, conv.queued_at = "aguardando", queue, now()
    event(db, conv, f"Entrou na fila {qname(db, queue)}")
    _say(db, conv, gw, f"Você está na fila do {qname(db, queue)}. Em instantes um analista vai te atender.")
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
        _enqueue(db, conv, out.queue, gw)
    else:  # end: atendimento resolvido pelo proprio fluxo (ex.: chamado aberto)
        conv.state, conv.flow_node, conv.closed_at, conv.unread, conv.closed_reason = "encerrada", None, now(), 0, "fluxo"
        event(db, conv, "Atendimento resolvido pelo fluxo")
    conv.flow_vars = copy.deepcopy(state.vars)


def _flow(db: Session) -> E.Flow:
    c = cfg(db)
    return E.Flow(FS.load_flow(db, c["greeting"], int(c["menu_timeout_min"]), list(queue_map(db)))[0])  # inclui filas inativas: o motor cai na geral


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
        event(db, conv, "Conversa iniciada")
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


def close_inactive(db: Session, gw) -> int:
    """Encerra conversas em fila ou em atendimento sem nenhuma mensagem (de ninguem) ha `inactivity_hours`."""
    c = cfg(db)
    horas = int(c.get("inactivity_hours") or 0)
    if horas <= 0:
        return 0
    limite = now() - timedelta(hours=horas)
    rows = db.scalars(select(WaConversation).where(WaConversation.state.in_(("aguardando", "atendendo")),
                                                   func.coalesce(WaConversation.last_message_at, WaConversation.created_at) < limite)).all()
    for conv in rows:
        conv.state, conv.closed_at, conv.closed_by, conv.unread, conv.flow_node = "encerrada", now(), None, 0, None
        conv.closed_reason = "inatividade"
        event(db, conv, f"Encerrado por inatividade (sem mensagens há {horas} h)")
        if c.get("inactivity_message"):
            _say(db, conv, gw, c["inactivity_message"])
    return len(rows)


def assume(db: Session, conv_id: int, user_id: int) -> bool:
    """Atomico: so quem chegar primeiro assume uma conversa que ainda esta aguardando."""
    r = db.execute(update(WaConversation).where(WaConversation.id == conv_id, WaConversation.state == "aguardando")
                   .values(state="atendendo", assigned_to=user_id, assumed_at=now(), unread=0))
    return r.rowcount == 1


def transfer(db: Session, conv: WaConversation, user_id: int | None, queue: str | None, gw=None) -> None:
    if queue and queue in queue_map(db):
        conv.queue = queue
    if user_id:
        conv.state, conv.assigned_to, conv.assumed_at = "atendendo", user_id, now()
    else:  # volta para a fila do setor
        conv.state, conv.assigned_to, conv.queued_at = "aguardando", None, now()
        if gw is not None:
            _alert(db, conv, gw)


def close(db: Session, conv: WaConversation, user_id: int, send_closing: bool, gw) -> None:
    conv.state, conv.closed_at, conv.closed_by, conv.unread, conv.closed_reason = "encerrada", now(), user_id, 0, "analista"
    event(db, conv, "Atendimento encerrado pelo analista")
    if send_closing:
        _say(db, conv, gw, cfg(db)["closing_message"])


def send(db: Session, conv: WaConversation, user_id: int, text: str, gw) -> WaMessage:
    try:
        resp = gw.send_text(conv.jid, text)
    except WaAkgError:
        _record_out(db, conv, text, None, user_id, failed=True)
        raise
    conv.last_message_at = now()
    if conv.first_response_at is None:
        conv.first_response_at = now()
    return _record_out(db, conv, text, resp, user_id)


def send_media(db: Session, conv: WaConversation, user_id: int, data: bytes, filename: str, mime: str, caption: str, gw) -> WaMessage:
    mtype = "IMAGE" if mime.startswith("image/") else "DOCUMENT"
    try:
        resp = gw.send_media(conv.jid, data, filename, mime, caption)
    except WaAkgError:
        _record_out(db, conv, caption or filename, None, user_id, failed=True, mtype=mtype)
        raise
    conv.last_message_at = now()
    if conv.first_response_at is None:
        conv.first_response_at = now()
    return _record_out(db, conv, caption or filename, resp, user_id, mtype=mtype)
