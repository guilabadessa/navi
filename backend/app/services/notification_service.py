"""Regras de alerta -> despachos (dispatches) -> envio via Evolution. Mensagens por template."""
import fnmatch
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import SEVERITIES, AlertRule, Client, Dispatch, Event, MessageTemplate
from .email_service import split_addrs
from .evolution_service import normalize_target

ALERT_WINDOW_S = 20 * 60  # igual a event_service.ALERT_WINDOW

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


def _wa_dest(rule: AlertRule | None, client: Client | None) -> str | None:
    if rule and rule.dest_jid:
        return rule.dest_jid
    return (client.whatsapp_group_jid or client.whatsapp) if client else None


def _mail_dest(rule: AlertRule | None, client: Client | None) -> str | None:
    if rule and rule.email_to:
        return rule.email_to
    return (client.alert_emails or client.report_emails or client.email) if client else None


def _rule_miss(r: AlertRule, ev: Event) -> list[str]:
    """Motivos pelos quais a regra NAO se aplica ao evento (lista vazia = aplica)."""
    miss = []
    if not _match(r.host_pattern, ev.host):
        miss.append(f"host não contém “{r.host_pattern}”")
    if not _match(r.trigger_pattern, ev.trigger_name):
        miss.append(f"trigger não contém “{r.trigger_pattern}”")
    if r.severities:
        if ev.severity not in r.severities:
            miss.append(f"severidade {SEVERITIES.get(ev.severity)} fora de [{', '.join(SEVERITIES.get(x, str(x)) for x in r.severities)}]")
    elif ev.severity < r.min_severity:
        miss.append(f"severidade {SEVERITIES.get(ev.severity)} abaixo do mínimo ({SEVERITIES.get(r.min_severity)})")
    return miss


def _rules_for(db: Session, client_id: int | None) -> list[AlertRule]:
    return db.scalars(select(AlertRule).where(
        AlertRule.enabled.is_(True), AlertRule.on_problem.is_(True),
        (AlertRule.client_id == client_id) | (AlertRule.client_id.is_(None)))).all()


def plan_problem(db: Session, ev: Event):
    """Cria despachos pendentes (WhatsApp e/ou e-mail) para um novo evento PROBLEM."""
    client = db.get(Client, ev.client_id) if ev.client_id else None
    now = datetime.now(timezone.utc)
    if client and client.maintenance_until and client.maintenance_until > now:
        return 0
    if client and not _in_hours(client.wa_hours, now):
        return 0
    planned: set = set()
    n = 0

    def add(channel: str, dest: str | None, rule: AlertRule | None, tpl: int | None, delay: int) -> int:
        if not dest:
            return 0
        # evita envio duplicado ao mesmo destino (compara o numero ja normalizado / o conjunto de e-mails)
        key = (channel, normalize_target(dest) if channel == "whatsapp" else frozenset(a.lower() for a in split_addrs(dest)))
        if key in planned:
            return 0
        planned.add(key)
        db.add(Dispatch(event_id=ev.id, rule_id=rule.id if rule else None, kind="problem", channel=channel, dest_jid=dest,
                        template_id=tpl, due_at=now + timedelta(seconds=delay or 0)))
        return 1

    for r in _rules_for(db, ev.client_id):
        if _rule_miss(r, ev):
            continue
        if r.notify_whatsapp:
            n += add("whatsapp", _wa_dest(r, client), r, r.problem_template_id, r.delay_s)
        if r.notify_email:
            n += add("email", _mail_dest(r, client), r, None, r.delay_s)
    if not n and client and ev.severity >= client.wa_min_severity:  # padrao do cliente
        if client.wa_enabled:
            n += add("whatsapp", _wa_dest(None, client), None, client.wa_problem_template_id, client.wa_delay_s)
        if client.mail_enabled:
            n += add("email", _mail_dest(None, client), None, None, client.wa_delay_s)
    return n


def plan_recovery(db: Session, ev: Event):
    """Cancela envios pendentes (oscilacao) e agenda a recuperacao para cada canal ja notificado."""
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
        quote = (rule.quote_recovery if rule else True) and d.channel == "whatsapp"
        db.add(Dispatch(event_id=ev.id, rule_id=d.rule_id, kind="recovery", channel=d.channel, dest_jid=d.dest_jid,
                        template_id=rec_tpl, quote=quote, due_at=datetime.now(timezone.utc)))
        n += 1
    return n


SEV_COLORS = {0: "#8aa0ab", 1: "#6a90f5", 2: "#d9a400", 3: "#ee8620", 4: "#e04e4e", 5: "#bd1723"}


def email_ctx(ev: Event, client: Client | None, kind: str, test: bool = False) -> tuple[str, dict]:
    """(assunto, contexto do template 'alert'). Para clientes usa SOMENTE o nome fantasia."""
    cname = client.trade_name if client else "—"
    sev = SEVERITIES.get(ev.severity, str(ev.severity))
    rec = kind == "recovery"
    dur = ev.duration_s if ev.duration_s is not None else int((datetime.now(timezone.utc) - ev.started_at).total_seconds())
    rows = [("Cliente", cname), ("Host", ev.host or "—"), ("IP", ev.ip or "—"), ("Problema", ev.trigger_name or "—"), ("Item", ev.item_name or "—")]
    if ev.opdata:
        rows.append(("Valor", ev.opdata))
    rows.append(("Início", fmt_dt(ev.started_at)))
    if rec:
        rows += [("Recuperação", fmt_dt(ev.recovered_at)), ("Indisponibilidade", fmt_duration(dur))]
    prefix = "[TESTE] " if test else ""
    subject = (f"{prefix}[RESTABELECIDO] {cname} — {ev.host}" if rec else f"{prefix}[ALERTA {sev.upper()}] {cname} — {ev.host}")
    ctx = {"title": ("Serviço restabelecido" if rec else f"Alerta — {sev}"), "tag": "Alerta · NAVI", "subtitle": f"{cname} · {ev.host}",
           "preheader": subject, "rows": rows, "badge": ("RESTABELECIDO" if rec else sev.upper()),
           "badge_color": "#16a34a" if rec else SEV_COLORS.get(ev.severity, "#1e73f8"), "test": test}
    return subject, ctx


def process_due(db: Session, evo, limit: int = 20) -> int:
    """Envia despachos vencidos (WhatsApp ou e-mail). Retorna a quantidade processada."""
    from . import mailer
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
        d.attempts += 1
        try:
            if d.channel == "email":
                subject, ctx = email_ctx(ev, client, d.kind)
                mailer.send(db, "alert", d.dest_jid, subject, ctx)
                d.text = subject
                d.status, d.sent_at, d.error = "sent", datetime.now(timezone.utc), None
            else:
                tpl = _template(db, d.template_id, d.kind)
                body = tpl.body if tpl else (DEFAULT_PROBLEM if d.kind == "problem" else DEFAULT_RECOVERY)
                d.text = render(body, ev, client)
                quoted_id = quoted_text = None
                if d.kind == "recovery" and d.quote and ev.wa_message_id:
                    quoted_id = ev.wa_message_id
                    orig = db.scalar(select(Dispatch).where(Dispatch.event_id == ev.id, Dispatch.kind == "problem", Dispatch.channel == "whatsapp",
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
                if d.kind == "problem" and d.channel == "whatsapp":
                    ev.wa_status = "failed"
            else:
                d.due_at = now + timedelta(seconds=30 * d.attempts)
        done += 1
        db.commit()
    return done


def sample_event(db: Session, rule: AlertRule, client: Client | None) -> Event:
    """Evento de exemplo para o teste: usa o mais recente que a regra pegaria; senao um sintetico (nunca gravado)."""
    q = select(Event).order_by(Event.started_at.desc()).limit(300)
    for e in db.scalars(q):
        if (rule.client_id is None or e.client_id == rule.client_id) and not _rule_miss(rule, e):
            return e
    return Event(zbx_eventid="0", host=rule.host_pattern.strip("*") if rule.host_pattern else "Host de Exemplo", ip="10.0.0.1",
                 trigger_name=(f"Link {rule.trigger_pattern.strip('*')}" if rule.trigger_pattern else "ICMP Ping: Link Indisponível"),
                 item_name="icmpping", severity=max(rule.min_severity or 0, 4), status="PROBLEM", started_at=datetime.now(timezone.utc),
                 opdata="Exemplo")


def test_rule(db: Session, evo, rule: AlertRule, to_whatsapp: str | None = None, to_email: str | None = None) -> dict:
    """Envia um alerta de TESTE (identificado como tal) pelos canais da regra. Nao cria incidente nem despacho."""
    from . import mailer
    client = db.get(Client, rule.client_id) if rule.client_id else None
    ev = sample_event(db, rule, client)
    client = client or (db.get(Client, ev.client_id) if ev.client_id else None) or Client(trade_name="Cliente Exemplo")
    out = {}
    if rule.notify_whatsapp:
        dest = to_whatsapp or _wa_dest(rule, client if client.id else None)
        if not dest:
            out["whatsapp"] = {"ok": False, "detail": "Sem destino: informe o grupo/celular na regra, cadastre no cliente ou preencha o campo de teste."}
        else:
            tpl = _template(db, rule.problem_template_id, "problem")
            text = "🧪 *TESTE DE ALERTA* — mensagem de teste, não é um incidente real.\n\n" + render(tpl.body if tpl else DEFAULT_PROBLEM, ev, client)
            try:
                evo.send_text(dest, text)
                out["whatsapp"] = {"ok": True, "detail": f"Enviado para {dest}"}
            except Exception as e:  # noqa: BLE001
                out["whatsapp"] = {"ok": False, "detail": str(e)[:300]}
    if rule.notify_email:
        dest = to_email or _mail_dest(rule, client if client.id else None)
        if not dest:
            out["email"] = {"ok": False, "detail": "Sem destino: informe e-mails na regra, cadastre no cliente ou preencha o campo de teste."}
        else:
            try:
                subject, ctx = email_ctx(ev, client, "problem", test=True)
                mailer.send(db, "alert", dest, subject, ctx)
                out["email"] = {"ok": True, "detail": f"Enviado para {dest}"}
            except Exception as e:  # noqa: BLE001
                out["email"] = {"ok": False, "detail": str(e)[:300]}
    if not out:
        out["aviso"] = {"ok": False, "detail": "Nenhum canal marcado na regra (WhatsApp/E-mail)."}
    out["evento_usado"] = {"host": ev.host, "trigger": ev.trigger_name, "severidade": SEVERITIES.get(ev.severity)}
    return out


def explain(db: Session, ev: Event) -> dict:
    """Diagnostico: por que este evento gerou (ou nao) alerta. Nao altera nada."""
    now = datetime.now(timezone.utc)
    checks = []

    def add(label, ok, detail):
        checks.append({"label": label, "ok": ok, "detail": detail})

    client = db.get(Client, ev.client_id) if ev.client_id else None
    blocked = False
    if client:
        add("Cliente", True, client.trade_name)
    else:
        grp = ", ".join(ev.group_names or []) or "sem grupo"
        add("Cliente", False, f"O host não pertence a nenhum cliente da NAVI (grupos: {grp}). Associe o host group a um cliente em Clientes → Host Groups. "
                              "Regras sem cliente só enviam se tiverem destino próprio.")
    if client and client.maintenance_until and client.maintenance_until > now:
        add("Manutenção", False, f"Cliente em manutenção até {fmt_dt(client.maintenance_until)}.")
        blocked = True
    elif client:
        add("Manutenção", True, "Fora de manutenção.")
    if client and client.wa_hours:
        ok = _in_hours(client.wa_hours, ev.created_at)
        add("Horário", ok, f"Janela de envio: {client.wa_hours}.")
        blocked = blocked or not ok
    age = (ev.created_at - ev.started_at).total_seconds() if ev.created_at and ev.started_at else 0
    if age > ALERT_WINDOW_S:
        add("Registro do evento", False, f"O evento foi registrado {int(age // 60)} min após iniciar (limite {ALERT_WINDOW_S // 60} min): eventos antigos não geram alerta.")
        blocked = True
    matched = False
    rules = _rules_for(db, ev.client_id)
    for r in rules:
        miss = _rule_miss(r, ev)
        chans = []
        if not miss:
            if r.notify_whatsapp:
                d = _wa_dest(r, client)
                chans.append(f"WhatsApp → {d}" if d else None)
            if r.notify_email:
                d = _mail_dest(r, client)
                chans.append(f"E-mail → {d}" if d else None)
            if not any(chans):
                miss.append("sem destino (cadastre grupo/celular/e-mail no cliente ou informe na regra)")
        add(f"Regra “{r.name}”", not miss, ("Atende — enviaria: " + "; ".join(c for c in chans if c)) if not miss else "; ".join(miss).capitalize() + ".")
        matched = matched or not miss
    if not rules:
        add("Regras personalizadas", True, "Nenhuma regra aplicável; vale a configuração padrão do cliente.")
    if client and not matched:
        miss, chans = [], []
        if ev.severity < client.wa_min_severity:
            miss.append(f"severidade {SEVERITIES.get(ev.severity)} abaixo do mínimo do cliente ({SEVERITIES.get(client.wa_min_severity)})")
        if not (client.wa_enabled or client.mail_enabled):
            miss.append("alertas por WhatsApp e por e-mail estão desligados no cliente")
        if client.wa_enabled:
            (chans if (client.whatsapp_group_jid or client.whatsapp) else miss).append(
                f"WhatsApp → {client.whatsapp_group_jid or client.whatsapp}" if (client.whatsapp_group_jid or client.whatsapp) else "WhatsApp ligado mas o cliente não tem grupo nem celular")
        if client.mail_enabled:
            d = _mail_dest(None, client)
            (chans if d else miss).append(f"E-mail → {d}" if d else "E-mail ligado mas o cliente não tem e-mail de alerta")
        ok = not miss and bool(chans)
        add("Padrão do cliente", ok, ("Atende — enviaria: " + "; ".join(chans)) if ok else "; ".join(miss).capitalize() + ".")
        matched = ok
    ds = db.scalars(select(Dispatch).where(Dispatch.event_id == ev.id).order_by(Dispatch.id)).all()
    return {"will_alert": matched and not blocked, "checks": checks,
            "dispatches": [{"kind": d.kind, "channel": d.channel, "status": d.status, "dest": d.dest_jid, "error": d.error} for d in ds]}
