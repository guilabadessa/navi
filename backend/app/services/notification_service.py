"""Regras de alerta -> despachos (dispatches) -> envio via Evolution. Mensagens por template."""
import fnmatch
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import SEVERITIES, AlertRule, Client, Dispatch, Event, MessageTemplate

DEFAULT_PROBLEM = """🚨 *ALERTA — {SEVERIDADE}*

🏢 {CLIENTE}

🌐 {HOST}
📍 IP: {HOST.IP}

*Problema:*
{TRIGGER.NAME}

*Item:*
{ITEM.NAME}

📊 *Valor:* {OPDATA}

🕐 *Início:*
{EVENT.DATE} {EVENT.TIME}"""

DEFAULT_RECOVERY = """✅ *RESTABELECIDO*

🏢 {CLIENTE}

🌐 {HOST}
📍 IP: {HOST.IP}

*Problema:*
{TRIGGER.NAME}

🕐 *Queda:*
{PROBLEM.TIME}

🟢 *Retorno:*
{RECOVERY.TIME}

⏱️ *Indisponibilidade:*
{DURATION}"""


def tz():
    return ZoneInfo(get_settings().NAVI_TZ)


def fmt_dt(d: datetime | None) -> str:
    return d.astimezone(tz()).strftime("%d/%m/%Y %H:%M:%S") if d else "-"


def fmt_duration(sec: int | None) -> str:
    if sec is None:
        return "-"
    sec = int(sec)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}min")
    if s or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


def render(body: str, ev: Event, client: Client | None) -> str:
    started = ev.started_at
    rec = ev.recovered_at
    dur = ev.duration_s if ev.duration_s is not None else int((datetime.now(timezone.utc) - started).total_seconds())
    tags = ", ".join(f"{t.get('tag')}:{t.get('value')}" if t.get("value") else t.get("tag", "") for t in (ev.tags or []))
    m = {
        "{CLIENTE}": client.trade_name if client else "-", "{HOST}": ev.host or "-", "{HOST.IP}": ev.ip or "-",
        "{TRIGGER.NAME}": ev.trigger_name or "-", "{ITEM.NAME}": ev.item_name or "-",
        "{EVENT.DATE}": started.astimezone(tz()).strftime("%d/%m/%Y"), "{EVENT.TIME}": started.astimezone(tz()).strftime("%H:%M:%S"),
        "{SEVERIDADE}": SEVERITIES.get(ev.severity, str(ev.severity)).upper(), "{OPDATA}": ev.opdata or "-",
        "{DURATION}": fmt_duration(dur), "{PROBLEM.TIME}": fmt_dt(started), "{RECOVERY.TIME}": fmt_dt(rec),
        "{TAGS}": tags or "-", "{EVENT.ID}": ev.zbx_eventid,
    }
    for k, v in m.items():
        body = body.replace(k, str(v))
    return body


def _match(pattern: str | None, value: str | None) -> bool:
    if not pattern:
        return True
    p = pattern.lower()
    if "*" not in p and "?" not in p:
        p = f"*{p}*"
    return fnmatch.fnmatch((value or "").lower(), p)


def _in_hours(spec: str | None, now: datetime) -> bool:
    if not spec or "-" not in spec:
        return True
    try:
        a, b = spec.split("-")
        t = now.astimezone(tz()).strftime("%H:%M")
        return (a <= t <= b) if a <= b else (t >= a or t <= b)
    except ValueError:
        return True


def _template(db: Session, tid: int | None, kind: str) -> MessageTemplate | None:
    if tid:
        t = db.get(MessageTemplate, tid)
        if t:
            return t
    return db.scalar(select(MessageTemplate).where(MessageTemplate.kind == kind, MessageTemplate.is_default.is_(True)))


def plan_problem(db: Session, ev: Event):
    """Cria despachos pendentes para um novo evento PROBLEM."""
    client = db.get(Client, ev.client_id) if ev.client_id else None
    now = datetime.now(timezone.utc)
    if client and client.maintenance_until and client.maintenance_until > now:
        return 0
    rules = db.scalars(select(AlertRule).where(
        AlertRule.enabled.is_(True), AlertRule.on_problem.is_(True),
        (AlertRule.client_id == ev.client_id) | (AlertRule.client_id.is_(None)))).all()
    planned = set()
    n = 0
    for r in rules:
        if r.client_id is None and not client and not r.dest_jid:
            continue
        if not (_match(r.host_pattern, ev.host) and _match(r.trigger_pattern, ev.trigger_name)):
            continue
        if r.severities:
            if ev.severity not in r.severities:
                continue
        elif ev.severity < r.min_severity:
            continue
        dest = r.dest_jid or (client.whatsapp_group_jid if client else None)
        if not dest or (dest, "problem") in planned:
            continue
        if client and not _in_hours(client.wa_hours, now):
            continue
        planned.add((dest, "problem"))
        db.add(Dispatch(event_id=ev.id, rule_id=r.id, kind="problem", dest_jid=dest, template_id=r.problem_template_id,
                        due_at=now + timedelta(seconds=r.delay_s or 0)))
        n += 1
    if not n and client and client.wa_enabled and client.whatsapp_group_jid and ev.severity >= client.wa_min_severity \
            and _in_hours(client.wa_hours, now):
        db.add(Dispatch(event_id=ev.id, rule_id=None, kind="problem", dest_jid=client.whatsapp_group_jid,
                        template_id=client.wa_problem_template_id, due_at=now + timedelta(seconds=client.wa_delay_s or 0)))
        n += 1
    return n


def plan_recovery(db: Session, ev: Event):
    """Cancela envios pendentes (flap) e agenda recovery para os problemas ja enviados."""
    client = db.get(Client, ev.client_id) if ev.client_id else None
    sent = db.scalars(select(Dispatch).where(Dispatch.event_id == ev.id, Dispatch.kind == "problem")).all()
    n = 0
    for d in sent:
        if d.status == "pending":
            d.status, d.error = "skipped", "Recuperado antes do atraso configurado"
            continue
        if d.status != "sent":
            continue
        rule = db.get(AlertRule, d.rule_id) if d.rule_id else None
        if rule is not None and not rule.on_recovery:
            continue
        if rule is None and client is not None and not client.wa_send_recovery:
            continue
        rec_tpl = rule.recovery_template_id if rule else (client.wa_recovery_template_id if client else None)
        quote = rule.quote_recovery if rule else True
        db.add(Dispatch(event_id=ev.id, rule_id=d.rule_id, kind="recovery", dest_jid=d.dest_jid, template_id=rec_tpl,
                        quote=quote, due_at=datetime.now(timezone.utc)))
        n += 1
    return n


def process_due(db: Session, evo, limit: int = 20) -> int:
    """Envia despachos vencidos. Retorna quantidade processada."""
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(Dispatch).where(Dispatch.status == "pending", Dispatch.due_at <= now)
                      .order_by(Dispatch.due_at).limit(limit).with_for_update(skip_locked=True)).all()
    done = 0
    for d in rows:
        ev = db.get(Event, d.event_id)
        client = db.get(Client, ev.client_id) if ev and ev.client_id else None
        if not ev:
            d.status, d.error = "skipped", "Evento removido"
            continue
        if d.kind == "problem" and ev.status == "RESOLVED":
            d.status, d.error = "skipped", "Evento já recuperado"
            continue
        tpl = _template(db, d.template_id, d.kind)
        body = tpl.body if tpl else (DEFAULT_PROBLEM if d.kind == "problem" else DEFAULT_RECOVERY)
        d.text = render(body, ev, client)
        d.attempts += 1
        try:
            quoted_id = quoted_text = None
            if d.kind == "recovery" and d.quote and ev.wa_message_id:
                quoted_id = ev.wa_message_id
                orig = db.scalar(select(Dispatch).where(Dispatch.event_id == ev.id, Dispatch.kind == "problem",
                                                        Dispatch.status == "sent", Dispatch.dest_jid == d.dest_jid))
                quoted_text = orig.text if orig else ""
            resp = evo.send_text(d.dest_jid, d.text, quoted_id, quoted_text)
            d.status, d.sent_at, d.message_id, d.error = "sent", datetime.now(timezone.utc), evo.message_id(resp), None
            if d.kind == "problem":
                ev.wa_message_id, ev.wa_sent_at, ev.wa_status = d.message_id, d.sent_at, "sent"
            else:
                ev.wa_status = "recovered"
        except Exception as e:  # noqa: BLE001
            d.error = str(e)[:1000]
            if d.attempts >= 4:
                d.status = "failed"
                if d.kind == "problem":
                    ev.wa_status = "failed"
            else:
                d.due_at = now + timedelta(seconds=30 * d.attempts)
        done += 1
        db.commit()
    return done
