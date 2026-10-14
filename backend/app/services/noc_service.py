"""Configuracao do NOC (destinos internos), escalonamento de alertas, agrupamento (tempestade) e resumo diario."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..config import get_settings
from ..models import INCIDENT_MIN_SEV, SEVERITIES, Client, Dispatch, Event, HealthCheck, JobStatus
from . import commlog
from .email_service import split_addrs
from .wa_common import normalize_target

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
    before = (S.get(db, "digest.enabled") == "1", S.get(db, "digest.time") or "")
    for k, v in m.items():
        S.put(db, k, v, user)
    # ao ativar/alterar o horario, o resumo de HOJE nao dispara na hora se o horario ja passou (so a partir de amanha ou do proximo horario)
    if m["digest.enabled"] == "1" and before != (True, m["digest.time"]) and validate_time(m["digest.time"]):
        now_local = datetime.now(ZoneInfo(get_settings().NAVI_TZ))
        if now_local.strftime("%H:%M") >= m["digest.time"]:
            S.put(db, "digest.last", now_local.strftime("%Y-%m-%d"), user)


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
# Objetivo: so o que ainda esta quebrado agora (Media, Alta e Desastre). Sem historico, sem estatistica de envios.
SEV_ICON = {5: "🔴", 4: "🟠", 3: "🟡", 2: "🔵", 1: "⚪", 0: "⚪"}
MAX_LINES = 25


def digest_data(db: Session) -> dict:
    from . import maintenance_service
    now = datetime.now(timezone.utc)
    clients_all = {c.id: c for c in db.scalars(select(Client))}
    evs = list(db.scalars(select(Event).where(Event.status == "PROBLEM", Event.severity >= INCIDENT_MIN_SEV)
                          .order_by(Event.severity.desc(), Event.started_at)))
    maint, quiet = [], {}

    def in_maint(cid) -> bool:
        if cid not in quiet:
            c = clients_all.get(cid)
            quiet[cid] = bool(cid and ((c and c.maintenance_until and c.maintenance_until > now) or maintenance_service.active(db, cid, now)))
            if quiet[cid] and c:
                maint.append(c.trade_name)
        return quiet[cid]

    by_sev: dict[int, int] = {}
    groups: dict[str, dict] = {}
    for e in evs:
        if in_maint(e.client_id):
            continue
        by_sev[e.severity] = by_sev.get(e.severity, 0) + 1
        c = clients_all.get(e.client_id)
        g = groups.setdefault(c.trade_name if c else "Sem cliente associado", {"name": c.trade_name if c else "Sem cliente associado", "worst": 0, "items": []})
        g["worst"] = max(g["worst"], e.severity)
        g["items"].append({"sev": e.severity, "kind": e.kind or "infra", "host": e.host or "—", "text": (e.trigger_name or "—")[:90]})
    clients = sorted(groups.values(), key=lambda r: (-r["worst"], -len(r["items"]), r["name"].lower()))
    plat = []
    stale = [j.label or j.name for j in db.scalars(select(JobStatus)) if j.last_run and j.interval_s and (now - j.last_run).total_seconds() > max(j.interval_s * 4, 180)]
    bad = [h.name for h in db.scalars(select(HealthCheck)) if not h.ok]
    if stale:
        plat.append("rotinas com atraso: " + ", ".join(stale))
    if bad:
        plat.append("integrações com falha: " + ", ".join(bad))
    total = sum(by_sev.values())
    worst = max(by_sev, default=-1)
    return {"now": now, "open": total, "by_sev": by_sev, "clients": clients, "maint": sorted(set(maint)), "platform": plat,
            "status": "crit" if worst >= 4 else "warn" if total else "ok"}


def _plural(n: int) -> str:
    return f"{n} incidente em aberto" if n == 1 else f"{n} incidentes em aberto"


def digest_text(d: dict, day: str, tzname: str = "America/Sao_Paulo") -> list[str]:
    """Mensagem unica de WhatsApp (e texto puro do e-mail): so incidentes que ainda existem, agrupados por cliente."""
    if d["status"] == "ok":
        L = ["🟢 *Tudo em ordem:* nenhum incidente em aberto"]
    else:
        L = [f"{SEV_ICON[max(d['by_sev'])]} *{_plural(d['open'])}*",
             "   " + " · ".join(f"{SEVERITIES.get(s)}: {n}" for s, n in sorted(d["by_sev"].items(), reverse=True))]
        shown = 0
        for r in d["clients"]:
            if shown >= MAX_LINES:
                break
            L += ["", f"🏢 *{r['name']}*"]
            for it in r["items"]:
                if shown >= MAX_LINES:
                    break
                L.append(f"   {SEV_ICON.get(it['sev'], '')} {it['host']} — {it['text']}")
                shown += 1
        if d["open"] > shown:
            L += ["", f"… e mais {d['open'] - shown} incidente(s) no painel"]
    if d["maint"]:
        L += ["", "🛠️ *Em manutenção:* " + ", ".join(d["maint"][:8])]
    if d["platform"]:
        L += ["", "⚠️ *Plataforma:* " + "; ".join(d["platform"])]
    return L


def digest_ctx(d: dict, day: str) -> dict:
    """Contexto do e-mail (template digest.html): mesmo conteudo da mensagem de WhatsApp."""
    from .notification_service import SEV_COLORS
    st = {"crit": ("ATENÇÃO", "#bd1723"), "warn": ("EM OBSERVAÇÃO", "#e0a800"), "ok": ("TUDO EM ORDEM", "#16a34a")}[d["status"]]
    shown, groups = 0, []
    for r in d["clients"]:
        items = r["items"][: max(0, MAX_LINES - shown)]
        if not items:
            break
        shown += len(items)
        groups.append({"name": r["name"], "items": [{**i, "color": SEV_COLORS.get(i["sev"], "#667090"), "label": SEVERITIES.get(i["sev"])} for i in items]})
    return {"title": f"Resumo diário do NOC — {day}", "tag": "NOC · NAVI", "subtitle": "Incidentes em aberto agora",
            "preheader": _plural(d["open"]) if d["open"] else "Nenhum incidente em aberto",
            "status_label": st[0], "status_color": st[1], "open": d["open"],
            "sev": [{"label": SEVERITIES.get(s), "n": n, "color": SEV_COLORS.get(s, "#667090")} for s, n in sorted(d["by_sev"].items(), reverse=True)],
            "groups": groups, "more": max(0, d["open"] - shown), "maint": d["maint"][:10], "platform": d["platform"],
            "plain": "\n".join(l.replace("*", "") for l in digest_text(d, day))}


def send_digest(db: Session, evo, manual: bool = False) -> str:
    """Uma unica mensagem de WhatsApp e um unico e-mail (para todos os destinatarios do NOC)."""
    from . import mailer
    c = cfg(db)
    if not (c["noc_wa"] or c["noc_emails"]):
        return "Configure o grupo de WhatsApp e/ou os e-mails do NOC."
    tz = ZoneInfo(get_settings().NAVI_TZ)
    day = datetime.now(tz).strftime("%d/%m/%Y")
    d = digest_data(db)
    res = []
    if c["noc_emails"]:
        try:
            mailer.send(db, "digest", c["noc_emails"], f"{'[TESTE] ' if manual else ''}Resumo diário do NOC — {day} · {d['open']} em aberto" if d['open'] else f"{'[TESTE] ' if manual else ''}Resumo diário do NOC — {day} · tudo em ordem", digest_ctx(d, day))
            res.append("e-mail ok")
        except Exception as e:  # noqa: BLE001
            res.append(f"e-mail erro: {str(e)[:80]}")
    if c["noc_wa"]:
        try:
            evo.send_text(c["noc_wa"], f"📋 *RESUMO DIÁRIO DO NOC — {day}*" + ("  _(teste)_" if manual else "") + "\n\n" + "\n".join(digest_text(d, day)))
            res.append("WhatsApp ok")
            commlog.record("whatsapp", "Resumo diário do NOC", c["noc_wa"], "sent")
        except Exception as e:  # noqa: BLE001
            res.append(f"WhatsApp erro: {str(e)[:80]}")
            commlog.record("whatsapp", "Resumo diário do NOC", c["noc_wa"], "failed", str(e))
    return " · ".join(res)


def digest_due(db: Session, now_local: datetime | None = None) -> bool:
    c = cfg(db)
    if not c["digest_enabled"] or not (c["noc_wa"] or c["noc_emails"]) or not validate_time(c["digest_time"]):
        return False
    now_local = now_local or datetime.now(ZoneInfo(get_settings().NAVI_TZ))
    # janela de 60 min a partir do horario (cobre um reinicio do worker, sem enviar tarde da noite)
    start = datetime.strptime(c["digest_time"], "%H:%M")
    mins = now_local.hour * 60 + now_local.minute - (start.hour * 60 + start.minute)
    return 0 <= mins < 60 and c["digest_last"] != now_local.strftime("%Y-%m-%d")
