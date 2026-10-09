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
KIND_NAMES = {"infra": "Infraestrutura (Zabbix)", "backup": "Backup (Acronis)", "endpoint": "Estações (FortiClient EMS)"}
SEV_ICON = {5: "🔴", 4: "🟠", 3: "🟡", 2: "🔵", 1: "⚪", 0: "⚪"}


def _age(dt: datetime, now: datetime) -> str:
    m = int((now - dt).total_seconds() // 60)
    return f"{m} min" if m < 60 else f"{m // 60} h" if m < 2880 else f"{m // 1440} dias"


def digest_data(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    open_ev = list(db.scalars(select(Event).where(Event.status == "PROBLEM").order_by(Event.severity.desc(), Event.started_at)))
    by_sev: dict[int, int] = {}
    by_kind: dict[str, int] = {}
    clients: dict[str, dict] = {}
    for e in open_ev:
        by_sev[e.severity or 0] = by_sev.get(e.severity or 0, 0) + 1
        by_kind[e.kind or "infra"] = by_kind.get(e.kind or "infra", 0) + 1
        c = clients.setdefault(names.get(e.client_id) or "Sem cliente associado", {"infra": 0, "backup": 0, "endpoint": 0, "worst": 0, "top": None, "total": 0})
        c[e.kind or "infra"] += 1
        c["total"] += 1
        if (e.severity or 0) >= c["worst"]:
            c["worst"], c["top"] = e.severity or 0, f"{e.host}: {e.trigger_name}"
    rows = sorted(({"name": k, **v} for k, v in clients.items()), key=lambda r: (-r["worst"], -r["total"], r["name"].lower()))
    oldest = [{"host": e.host, "trigger": e.trigger_name, "client": names.get(e.client_id) or "Sem cliente", "sev": e.severity or 0, "age": _age(e.started_at, now)}
              for e in sorted(open_ev, key=lambda x: x.started_at)[:5]]
    ev24 = list(db.execute(select(Event.kind, func.count()).where(Event.started_at >= since).group_by(Event.kind)).all())
    rs24 = list(db.execute(select(Event.kind, func.count()).where(Event.recovered_at >= since).group_by(Event.kind)).all())
    disp = {}
    for ch, st, n in db.execute(select(Dispatch.channel, Dispatch.status, func.count()).where(Dispatch.created_at >= since).group_by(Dispatch.channel, Dispatch.status)).all():
        disp.setdefault(ch, {})[st] = n
    stale = [j.label or j.name for j in db.scalars(select(JobStatus)) if j.last_run and j.interval_s and (now - j.last_run).total_seconds() > max(j.interval_s * 4, 180)]
    bad = [h.name for h in db.scalars(select(HealthCheck)) if not h.ok]
    maint = [c.trade_name for c in db.scalars(select(Client).where(Client.maintenance_until > now))]
    worst = max(by_sev, default=-1)
    status = "crit" if worst >= 4 else "warn" if open_ev else "ok"
    return {"now": now, "open": len(open_ev), "by_sev": by_sev, "by_kind": by_kind, "clients": rows, "oldest": oldest,
            "new24": sum(n for _, n in ev24), "resolved24": sum(n for _, n in rs24), "new_by_kind": dict(ev24), "disp": disp,
            "stale": stale, "bad": bad, "maint": maint, "status": status, "no_client": clients.get("Sem cliente associado", {}).get("total", 0)}


def _sent(d: dict, ch: str) -> str:
    x = d["disp"].get(ch, {})
    return f"{x.get('sent', 0)} enviados · {x.get('failed', 0)} falhas · {x.get('skipped', 0)} ignorados"


def digest_text(d: dict, day: str, tzname: str = "America/Sao_Paulo") -> list[str]:
    """Mensagem unica de WhatsApp (e texto puro do e-mail): situacao, categorias, clientes, mais antigos, alertas e plataforma."""
    head = {"crit": "🔴 *Atenção: há problemas graves em aberto*", "warn": "🟡 *Há problemas em aberto, sem gravidade alta*", "ok": "🟢 *Tudo em ordem: nenhum problema em aberto*"}[d["status"]]
    L = [head, "", f"📊 *Em aberto agora:* {d['open']}"]
    if d["by_sev"]:
        L.append("   " + " · ".join(f"{SEV_ICON.get(s, '')} {SEVERITIES.get(s)}: {n}" for s, n in sorted(d["by_sev"].items(), reverse=True)))
    L += ["", "🗂️ *Por categoria*"]
    for k, nm in KIND_NAMES.items():
        L.append(f"   • {nm}: {d['by_kind'].get(k, 0)} em aberto · {d['new_by_kind'].get(k, 0)} novos nas últimas 24h")
    if d["clients"]:
        L += ["", f"🏢 *Por cliente* ({len(d['clients'])} com problemas)"]
        for r in d["clients"][:12]:
            parts = [f"{n} {lbl}" for n, lbl in ((r["infra"], "infra"), (r["backup"], "backup"), (r["endpoint"], "estações")) if n]
            L.append(f"   {SEV_ICON.get(r['worst'], '')} *{r['name']}* — {', '.join(parts)} (maior: {SEVERITIES.get(r['worst'])})")
        if len(d["clients"]) > 12:
            L.append(f"   … e mais {len(d['clients']) - 12} cliente(s)")
    if d["oldest"]:
        L += ["", "⏳ *Abertos há mais tempo*"] + [f"   • {o['client']} · {o['host']} — {(o['trigger'] or '')[:60]} ({o['age']})" for o in d["oldest"]]
    L += ["", f"📈 *Últimas 24h:* {d['new24']} novos · {d['resolved24']} resolvidos", f"📨 *Alertas enviados (24h)*",
          f"   • WhatsApp: {_sent(d, 'whatsapp')}", f"   • E-mail: {_sent(d, 'email')}"]
    if d["maint"]:
        L += ["", "🛠️ *Em manutenção agora:* " + ", ".join(d["maint"][:8])]
    plat = []
    if d["no_client"]:
        plat.append(f"{d['no_client']} problema(s) em hosts sem cliente associado")
    if d["stale"]:
        plat.append("rotinas com atraso: " + ", ".join(d["stale"]))
    if d["bad"]:
        plat.append("integrações com falha: " + ", ".join(d["bad"]))
    L += ["", "⚠️ *Plataforma:* " + "; ".join(plat)] if plat else ["", "✅ *Plataforma:* rotinas e integrações em dia"]
    return L


def digest_ctx(d: dict, day: str) -> dict:
    """Contexto do e-mail (template digest.html)."""
    from .notification_service import SEV_COLORS
    st = {"crit": ("ATENÇÃO", "#bd1723"), "warn": ("EM OBSERVAÇÃO", "#e0a800"), "ok": ("TUDO EM ORDEM", "#16a34a")}[d["status"]]
    return {"title": f"Resumo diário do NOC — {day}", "tag": "NOC · NAVI", "subtitle": "Situação consolidada de todos os clientes",
            "preheader": f"{d['open']} problema(s) em aberto · {d['new24']} novos e {d['resolved24']} resolvidos nas últimas 24h",
            "status_label": st[0], "status_color": st[1], "open": d["open"],
            "sev": [{"label": SEVERITIES.get(s), "n": n, "color": SEV_COLORS.get(s, "#667090")} for s, n in sorted(d["by_sev"].items(), reverse=True)],
            "kinds": [{"name": nm, "open": d["by_kind"].get(k, 0), "new": d["new_by_kind"].get(k, 0)} for k, nm in KIND_NAMES.items()],
            "clients": [{**r, "worst_label": SEVERITIES.get(r["worst"]), "color": SEV_COLORS.get(r["worst"], "#667090")} for r in d["clients"][:20]],
            "more_clients": max(0, len(d["clients"]) - 20), "oldest": d["oldest"], "new24": d["new24"], "resolved24": d["resolved24"],
            "wa": _sent(d, "whatsapp"), "mail": _sent(d, "email"), "maint": d["maint"][:10], "no_client": d["no_client"], "stale": d["stale"], "bad": d["bad"],
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
            mailer.send(db, "digest", c["noc_emails"], f"{'[TESTE] ' if manual else ''}Resumo diário do NOC — {day} · {d['open']} em aberto", digest_ctx(d, day))
            res.append("e-mail ok")
        except Exception as e:  # noqa: BLE001
            res.append(f"e-mail erro: {str(e)[:80]}")
    if c["noc_wa"]:
        try:
            evo.send_text(c["noc_wa"], f"📋 *RESUMO DIÁRIO DO NOC — {day}*" + ("  _(teste)_" if manual else "") + "\n\n" + "\n".join(digest_text(d, day)))
            res.append("WhatsApp ok")
        except Exception as e:  # noqa: BLE001
            res.append(f"WhatsApp erro: {str(e)[:80]}")
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
