"""Web Push: chaves VAPID, inscricoes e envio de incidentes (Media+) aos usuarios inscritos."""
import base64
import json
import logging
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import portal_access as PA
from .. import settings_store as S
from . import fcm
from ..models import INCIDENT_MIN_SEV, SEVERITIES, Client, Event, PushSent, PushSub, User

log = logging.getLogger("navi.push")
MAX_AGE = timedelta(minutes=30)  # incidente mais antigo que isso nao gera push (evita rajada apos pausa/implantacao)
MAX_PER_RUN = 20


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def vapid_keys(db: Session) -> tuple[str, str]:
    """(privada em base64url de 32 bytes, publica em base64url de 65 bytes); gera e grava na primeira vez."""
    priv, pub = S.get(db, "push.vapid_private"), S.get(db, "push.vapid_public")
    if priv and pub:
        return priv, pub
    k = ec.generate_private_key(ec.SECP256R1())
    priv = _b64(k.private_numbers().private_value.to_bytes(32, "big"))
    pub = _b64(k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    S.put(db, "push.vapid_private", priv)
    S.put(db, "push.vapid_public", pub)
    db.commit()
    return priv, pub


def wants(db: Session, u: User, ev: Event) -> bool:
    """Cliente: so incidentes dos seus clientes e a partir da sua severidade minima. Equipe: todos os incidentes."""
    if not u.active or (ev.severity or 0) < INCIDENT_MIN_SEV:
        return False
    if u.role == "CLIENTE":
        return ev.client_id in PA.client_ids(db, u) and (ev.severity or 0) >= max(u.portal_min_sev or 4, INCIDENT_MIN_SEV)
    return True


def payload(db: Session, ev: Event) -> dict:
    c = db.get(Client, ev.client_id) if ev.client_id else None
    sev = SEVERITIES.get(ev.severity, "")
    title = f"{sev} · {c.name}" if c else sev
    return {"title": title, "body": f"{ev.host or ''}: {ev.trigger_name or ''}".strip(": ")[:180], "url": "/cliente/", "tag": f"ev-{ev.id}"}


def send(db: Session, sub: PushSub, data: dict) -> bool:
    """True se entregue ao servico de push. Inscricao expirada (404/410) e removida."""
    if sub.endpoint.startswith("fcm:"):
        return _send_fcm(db, sub, data)
    from pywebpush import WebPushException, webpush
    priv, _ = vapid_keys(db)
    try:
        webpush({"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}, json.dumps(data),
                vapid_private_key=priv, vapid_claims={"sub": "mailto:noc@orcati.com.br"}, ttl=3600)
        sub.last_ok = datetime.now(timezone.utc)
        return True
    except WebPushException as e:
        code = getattr(e.response, "status_code", None)
        if code in (404, 410):
            db.delete(sub)
        else:
            log.warning("push falhou (%s): %s", code, str(e)[:200])
        return False


def _send_fcm(db: Session, sub: PushSub, data: dict) -> bool:
    raw = S.get(db, "push.fcm_sa")
    if not raw:
        return False
    try:
        res = fcm.send(json.loads(raw), sub.endpoint[4:], data)
    except Exception as e:  # noqa: BLE001
        log.warning("fcm falhou: %s", str(e)[:200])
        return False
    if res == "gone":
        db.delete(sub)
    elif res == "ok":
        sub.last_ok = datetime.now(timezone.utc)
    return res == "ok"


def notify_new(db: Session) -> int:
    subs = list(db.scalars(select(PushSub)))
    if not subs:
        return 0
    since = datetime.now(timezone.utc) - MAX_AGE
    evs = list(db.scalars(select(Event).where(Event.status == "PROBLEM", Event.severity >= INCIDENT_MIN_SEV, Event.started_at >= since)
                          .order_by(Event.started_at).limit(MAX_PER_RUN)))
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({s.user_id for s in subs})))}
    sent = 0
    for ev in evs:
        data = None
        for uid in {s.user_id for s in subs}:
            u = users.get(uid)
            if not u or not wants(db, u, ev) or db.get(PushSent, (ev.id, uid)):
                continue
            data = data or payload(db, ev)
            ok = False
            for s in [s for s in subs if s.user_id == uid]:
                ok = send(db, s, data) or ok
            db.add(PushSent(event_id=ev.id, user_id=uid))  # marca mesmo se falhou: nao insiste em aparelho morto
            sent += ok
        db.commit()
    return sent
