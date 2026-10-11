"""Web Push: chaves VAPID, inscricoes e envio de incidentes (Media+) aos usuarios inscritos."""
import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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
REC_AGE = timedelta(minutes=60)  # recuperacao so e avisada ate 1h depois
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
    """Cliente: so incidentes dos seus clientes e a partir da sua severidade minima. Equipe: todos, a partir da minima escolhida."""
    low = max(getattr(u, "push_min_sev", None) or INCIDENT_MIN_SEV, INCIDENT_MIN_SEV)
    if not u.active or (ev.severity or 0) < low:
        return False
    if u.role == "CLIENTE":
        return ev.client_id in PA.client_ids(db, u) and (ev.severity or 0) >= max(u.portal_min_sev or 4, INCIDENT_MIN_SEV)
    return True


def in_quiet(u: User, now_local: datetime) -> bool:
    a, b = getattr(u, "push_quiet_start", None), getattr(u, "push_quiet_end", None)
    if a is None or b is None or a == b:
        return False
    h = now_local.hour
    return a <= h < b if a < b else (h >= a or h < b)


def in_maintenance(db: Session, ev: Event, now: datetime) -> bool:
    """Mesmas regras de manutencao dos alertas de WhatsApp/e-mail (cliente em manutencao ou janela ativa)."""
    from . import maintenance_service
    c = db.get(Client, ev.client_id) if ev.client_id else None
    return bool((c and c.maintenance_until and c.maintenance_until > now) or maintenance_service.active(db, ev.client_id, now))


def payload(db: Session, ev: Event, u: User | None = None, recovered: bool = False) -> dict:
    c = db.get(Client, ev.client_id) if ev.client_id else None
    sev = "Resolvido" if recovered else SEVERITIES.get(ev.severity, "")
    title = f"{sev} · {c.name}" if c else sev
    # equipe abre o detalhe do incidente; o cliente cai no proprio portal
    url = "/cliente/" if (u is not None and u.role == "CLIENTE") else f"/cliente/eventos?open={ev.id}"
    return {"title": title, "body": f"{ev.host or ''}: {ev.trigger_name or ''}".strip(": ")[:180], "url": url, "tag": f"ev-{ev.id}"}


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


def _deliver(db: Session, subs: list[PushSub], uid: int, data: dict) -> bool:
    ok = False
    for x in [x for x in subs if x.user_id == uid]:
        ok = send(db, x, data) or ok
    return ok


def notify_new(db: Session) -> int:
    subs = list(db.scalars(select(PushSub)))
    if not subs:
        return 0
    now = datetime.now(timezone.utc)
    evs = list(db.scalars(select(Event).where(Event.status == "PROBLEM", Event.severity >= INCIDENT_MIN_SEV, Event.started_at >= now - MAX_AGE)
                          .order_by(Event.started_at).limit(MAX_PER_RUN)))
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({s.user_id for s in subs})))}
    local = now.astimezone(ZoneInfo("America/Sao_Paulo"))
    sent = 0
    for ev in evs:
        maint = in_maintenance(db, ev, now)
        for uid in {s.user_id for s in subs}:
            u = users.get(uid)
            if not u or not wants(db, u, ev) or db.get(PushSent, (ev.id, uid)):
                continue
            quiet = in_quiet(u, local) and (ev.severity or 0) < 5  # Desastre fura o horario silencioso
            if maint or quiet:
                db.add(PushSent(event_id=ev.id, user_id=uid, delivered=False, rec_sent=True))  # tratado: nao avisa depois
                continue
            ok = _deliver(db, subs, uid, payload(db, ev, u))
            db.add(PushSent(event_id=ev.id, user_id=uid))  # marca mesmo se falhou: nao insiste em aparelho morto
            sent += ok
        db.commit()
    return sent


def notify_recovered(db: Session) -> int:
    """Avisa (uma vez) quem recebeu o push do incidente quando ele for resolvido, se a pessoa quiser."""
    now = datetime.now(timezone.utc)
    rows = list(db.execute(select(PushSent, Event).join(Event, Event.id == PushSent.event_id)
                           .where(PushSent.delivered.is_(True), PushSent.rec_sent.is_(False), Event.status != "PROBLEM",
                                  Event.recovered_at >= now - REC_AGE).limit(MAX_PER_RUN * 3)))
    if not rows:
        return 0
    subs = list(db.scalars(select(PushSub)))
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r[0].user_id for r in rows})))}
    sent = 0
    for ps, ev in rows:
        u = users.get(ps.user_id)
        ps.rec_sent = True
        if u and u.active and getattr(u, "push_recovery", True) and any(x.user_id == u.id for x in subs):
            sent += _deliver(db, subs, u.id, payload(db, ev, u, recovered=True))
    db.commit()
    return sent
