"""Configuracao do NOC (destinos internos), escalonamento de alertas, agrupamento (tempestade) e resumo diario."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..config import get_settings
from ..models import SEVERITIES, Client, Dispatch, Event, HealthCheck, JobStatus
from .email_service import split_addrs
from .evolution_service import normalize_target

DEFAULTS = {
    "noc.wa": "", "noc.emails": "",
    "escalation.enabled": "0", "escalation.minutes": "15", "escalation.min_severity": "4",
    "storm.enabled": "1", "storm.threshold": "3", "storm.hold_s": "15",
    "digest.enabled": "0", "digest.time": "08:00",
}


def cfg(db: Session) -> dict:
    g = lambda k: S.get(db, k) or DEFAULTS[k]  # noqa: E731
    return {
        "noc_wa": S.get(db, "noc.wa"), "noc_emails": S.get(db, "noc.emails"),
        "escalation_enabled": g("escalation.enabled") == "1", "escalation_minutes": int(g("escalation.minutes")),
        "escalation_min_severity": int(g("escalation.min_severity")),
        "storm_enabled": g("storm.enabled") == "1", "storm_threshold": int(g("storm.threshold")), "storm_hold_s": int(g("storm.hold_s")),
        "digest_enabled": g("digest.enabled") == "1", "digest_time": g("digest.time"),
        "digest_last": S.get(db, "digest.last"), "digest_status": S.get(db, "digest.status"),
    }


def save(db: Session, d: dict, user: str | None):
    m = {"noc.wa": d.get("noc_wa", ""), "noc.emails": d.get("noc_emails", ""),
         "escalation.enabled": "1" if d.get("escalation_enabled") else "0", "escalation.minutes": str(max(1, int(d.get("escalation_minutes", 15)))),
         "escalation.min_severity": str(int(d.get("escalation_min_severity", 4))),
         "storm.enabled": "1" if d.get("storm_enabled") else "0", "storm.threshold": str(max(2, int(d.get("storm_threshold", 3)))),
         "storm.hold_s": str(min(120, max(0, int(d.get("storm_hold_s", 15))))),
         "digest.enabled": "1" if d.get("digest_enabled") else "0", "digest.time": d.get("digest_time") or "08:00"}
    for k, v in m.items():
        S.put(db, k, v, user)


def validate_time(t: str) -> bool:
    try:
        hh, mm = t.split(":")
        return 0 <= int(hh) < 24 and 0 <= int(mm) < 60 and len(t) == 5
    except ValueError:
        return False


# ---------------- escalonamento ----------------
def escalation_candidates(events: list, existing: set, now: datetime, minutes: int, min_sev: int) -> list:
    """Eventos em aberto ha mais de 'minutes', sem escalonamento previo (puro: facil de testar)."""
    cutoff = now - timedelta(minutes=minutes)
    out = []
    for ev in events:
        if ev.status != "PROBLEM" or ev.id in existing or not ev.client_id or ev.acknowledged:
            continue
        if ev.started_at > cutoff or ev.started_at < now - timedelta(hours=24) or (ev.severity or 0) < min_sev:
            continue
        out.append(ev)
    return out


def escalate(db: Session) -> int:
    from . import maintenance_service
    c = cfg(db)
    if not c["escalation_enabled"] or not (c["noc_wa"] or c["noc_emails"]):
        return 0
    now = datetime.now(timezone.utc)
    evs = list(db.scalars(select(Event).where(Event.status == "PROBLEM", Event.client_id.is_not(None),
                                              Event.severity >= c["escalation_min_severity"], Event.started_at >= now - timedelta(hours=24))))
    done = set(db.scalars(select(Dispatch.event_id).where(Dispatch.kind == "escalation", Dispatch.event_id.in_([e.id for e in evs]))))
    n = 0
    for ev in escalation_candidates(evs, done, now, c["escalation_minutes"], c["escalation_min_severity"]):
        cl = db.get(Client, ev.client_id)
        if (cl and cl.maintenance_until and cl.maintenance_until > now) or maintenance_service.active(db, ev.client_id, now):
            continue
        if c["noc_wa"]:
            db.add(Dispatch(event_id=ev.id, kind="escalation", channel="whatsapp", dest_jid=c["noc_wa"], due_at=now))
            n += 1
        if c["noc_emails"]:
            db.add(Dispatch(event_id=ev.id, kind="escalation", channel="email", dest_jid=c["noc_emails"], due_at=now))
            n += 1
    db.commit()
    return n


# ---------------- agrupamento ----------------
def group_key(d: Dispatch, ev: Event) -> tuple:
    dest = normalize_target(d.dest_jid) if d.channel == "whatsapp" else ",".join(sorted(a.lower() for a in split_addrs(d.dest_jid)))
    return (d.kind, d.channel, dest, ev.client_id)


def pick_groups(items: list[tuple], threshold: int) -> tuple[list[list], list]:
    """items: [(dispatch, event)]. Retorna (grupos com >= threshold itens, restantes). Puro."""
    buckets: dict[tuple, list] = {}
    for d, ev in items:
        if d.kind in ("problem", "recovery", "escalation") and ev.client_id:
            buckets.setdefault(group_key(d, ev), []).append((d, ev))
    groups = [v for v in buckets.values() if len(v) >= threshold]
    taken = {id(d) for g in groups for d, _ in g}
    return groups, [(d, ev) for d, ev in items if id(d) not in taken]


def group_text(kind: str, client: Client | None, items: list[tuple], tzname: str) -> str:
    tz = ZoneInfo(tzname)
    cname = client.trade_name if client else "—"
    n = len(items)
    lines = []
    for _, ev in items[:15]:
        sev = SEVERITIES.get(ev.severity, "")
        hora = (ev.recovered_at if kind == "recovery" else ev.started_at)
        hora = hora.astimezone(tz).strftime("%H:%M") if hora else ""
        lines.append(f"• *{ev.host}* — {ev.trigger_name}" + (f" ({sev})" if kind == "problem" else "") + f" · {hora}")
    more = f"\n… e mais {n - 15}" if n > 15 else ""
    if kind == "escalation":
        return f"⏰ *ESCALONAMENTO — {n} problemas sem recuperação*\n🏢 *Cliente:* {cname}\n\n" + "\n".join(lines) + more
    if kind == "recovery":
        return f"✅ *{n} PROBLEMAS RESTABELECIDOS*\n🏢 *Cliente:* {cname}\n\n" + "\n".join(lines) + more
    worst = max((ev.severity or 0) for _, ev in items)
    return f"🚨 *ALERTA AGRUPADO — {n} problemas*\n🏢 *Cliente:* {cname}\n⚠️ *Maior severidade:* {SEVERITIES.get(worst)}\n\n" + "\n".join(lines) + more


def group_email(kind: str, client: Client | None, items: list[tuple], tzname: str) -> tuple[str, dict]:
    tz = ZoneInfo(tzname)
    cname = client.trade_name if client else "—"
    n = len(items)
    rec = kind == "recovery"
    worst = max((ev.severity or 0) for _, ev in items)
    rows = [("Cliente", cname), ("Resumo", f"{n} problema(s) {'restabelecido(s)' if rec else 'em aberto'}")]
    for _, ev in items[:30]:
        t = (ev.recovered_at if rec else ev.started_at)
        rows.append((ev.host or "—", f"{ev.trigger_name or ''} · {t.astimezone(tz).strftime('%d/%m %H:%M') if t else ''}"))
    esc = kind == "escalation"
    subject = f"[{'RESTABELECIDOS' if rec else 'ESCALONADOS' if esc else 'ALERTA AGRUPADO'}] {cname} — {n} problema(s)"
    from .notification_service import SEV_COLORS
    ctx = {"title": "Serviços restabelecidos" if rec else f"Escalonamento — {n} problemas sem recuperação" if esc else f"Alerta agrupado — {n} problemas", "tag": "Alerta · NAVI", "subtitle": cname,
           "preheader": subject, "rows": rows, "badge": "RESTABELECIDO" if rec else SEVERITIES.get(worst, "").upper(),
           "badge_color": "#16a34a" if rec else SEV_COLORS.get(worst, "#1e73f8"), "test": False}
    return subject, ctx


# ---------------- resumo diario ----------------
def digest_data(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    open_ev = list(db.scalars(select(Event).where(Event.status == "PROBLEM").order_by(Event.severity.desc(), Event.started_at)))
    by_client: dict[str, list] = {}
    for e in open_ev:
        by_client.setdefault(names.get(e.client_id, "Sem cliente"), []).append(e)
    sent = dict(db.execute(select(Dispatch.status, func.count()).where(Dispatch.created_at >= since).group_by(Dispatch.status)).all())
    new24 = db.scalar(select(func.count()).select_from(Event).where(Event.started_at >= since)) or 0
    res24 = db.scalar(select(func.count()).select_from(Event).where(Event.recovered_at >= since)) or 0
    stale = [j.label or j.name for j in db.scalars(select(JobStatus)) if j.last_run and j.interval_s and (now - j.last_run).total_seconds() > max(j.interval_s * 4, 180)]
    bad = [h.name for h in db.scalars(select(HealthCheck)) if not h.ok]
    return {"open": len(open_ev), "by_client": by_client, "new24": new24, "resolved24": res24, "sent": sent, "stale": stale, "bad": bad}


def digest_text(d: dict, day: str) -> list[str]:
    lines = [f"Problemas em aberto agora: {d['open']}"]
    for cname, evs in list(d["by_client"].items())[:10]:
        worst = max((e.severity or 0) for e in evs)
        lines.append(f"  • {cname}: {len(evs)} (maior: {SEVERITIES.get(worst)})")
    lines.append(f"Últimas 24h: {d['new24']} novos problemas, {d['resolved24']} resolvidos")
    lines.append(f"Alertas enviados: {d['sent'].get('sent', 0)} · falhas: {d['sent'].get('failed', 0)} · ignorados: {d['sent'].get('skipped', 0)}")
    if d["stale"]:
        lines.append("⚠ Rotinas com atraso: " + ", ".join(d["stale"]))
    if d["bad"]:
        lines.append("⚠ Integrações com falha: " + ", ".join(d["bad"]))
    return lines


def send_digest(db: Session, evo, manual: bool = False) -> str:
    from . import mailer
    c = cfg(db)
    if not (c["noc_wa"] or c["noc_emails"]):
        return "Configure o grupo de WhatsApp e/ou os e-mails do NOC."
    tz = ZoneInfo(get_settings().NAVI_TZ)
    day = datetime.now(tz).strftime("%d/%m/%Y")
    d = digest_data(db)
    lines = digest_text(d, day)
    res = []
    if c["noc_emails"]:
        try:
            mailer.send(db, "notice", c["noc_emails"], f"Resumo diário do NOC — {day}",
                        mailer.notice_ctx(f"Resumo diário do NOC — {day}", lines[1:], highlight=lines[0], greeting="Equipe NOC,"))
            res.append("e-mail ok")
        except Exception as e:  # noqa: BLE001
            res.append(f"e-mail erro: {str(e)[:80]}")
    if c["noc_wa"]:
        try:
            evo.send_text(c["noc_wa"], f"📋 *Resumo diário do NOC — {day}*\n\n" + "\n".join(lines))
            res.append("WhatsApp ok")
        except Exception as e:  # noqa: BLE001
            res.append(f"WhatsApp erro: {str(e)[:80]}")
    return " · ".join(res)


def digest_due(db: Session, now_local: datetime | None = None) -> bool:
    c = cfg(db)
    if not c["digest_enabled"] or not (c["noc_wa"] or c["noc_emails"]) or not validate_time(c["digest_time"]):
        return False
    now_local = now_local or datetime.now(ZoneInfo(get_settings().NAVI_TZ))
    return now_local.strftime("%H:%M") >= c["digest_time"] and c["digest_last"] != now_local.strftime("%Y-%m-%d")
