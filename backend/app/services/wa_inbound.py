"""Recepcao de mensagens do WA-AKG: valida assinatura, interpreta o payload e grava (idempotente)."""
import hashlib
import hmac
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import WaMessage

log = logging.getLogger("navi.whatsapp")
EVENTS = {"message.received": "in", "message.sent": "out"}


def verify_signature(secret: str, raw: bytes, header: str) -> bool:
    """`X-Webhook-Signature: sha256=<hex>` = HMAC-SHA256(secret, corpo bruto). Sem segredo configurado, nunca aceita."""
    if not secret or not header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())


def parse_payload(payload: dict) -> dict | None:
    """Devolve os campos a gravar, ou None se o evento nao for mensagem ou vier incompleto."""
    if payload.get("event") not in EVENTS:
        return None
    d = payload.get("data") or {}
    key = d.get("key") or {}
    ext, jid = key.get("id"), key.get("remoteJid") or d.get("from")
    if not ext or not jid:
        return None
    return {"external_id": str(ext), "session": str(payload.get("sessionId") or ""), "jid": jid,
            "direction": "out" if key.get("fromMe") else "in", "type": d.get("type") or "TEXT",
            "text": d.get("content") or d.get("caption") or "", "media_ref": d.get("fileUrl"), "push_name": d.get("pushName")}


def store_inbound(db: Session, parsed: dict) -> WaMessage | None:
    """Grava a mensagem; None se ja existir (o WA-AKG pode reentregar o mesmo webhook)."""
    if db.scalar(select(WaMessage.id).where(WaMessage.external_id == parsed["external_id"])):
        return None
    m = WaMessage(**parsed)
    db.add(m)
    return m


def on_inbound(db: Session, msg: WaMessage) -> None:
    """Entrega a mensagem ao atendimento (menu/fila). Erro ali nunca derruba o webhook: o gateway reentregaria."""
    log.info("whatsapp %s %s (%s)", msg.direction, msg.jid, msg.type)
    try:
        from . import atendimento_service, factory
        atendimento_service.handle_inbound(db, msg, factory.wa_akg(db))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("atendimento: falha ao tratar mensagem de %s", msg.jid)
