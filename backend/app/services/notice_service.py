"""Avisos opcionais por e-mail aos usuarios do portal (cada cliente liga/desliga):
 - boleto a vencer (3 dias antes e no dia) para quem tem a permissao de financeiro;
 - resumo mensal de disponibilidade e financeiro para todos os usuarios do portal."""
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import portal_access as PA
from ..config import get_settings
from ..models import Client, Event, FinDoc, FinNotice, User
from . import kpi_service, maintenance_service, mailer

log = logging.getLogger("navi.notices")
MESES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _brl(v) -> str:
    return f"R$ {float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _day(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _eligible(db: Session, c: Client, finance: bool) -> list[User]:
    return [u for u in PA.users_of(db, c.id) if u.active and not u.invite_pending and u.email
            and (not finance or "portal.finance" in (u.extra_perms or []))]


def _portal_url() -> str:
    return get_settings().NAVI_PUBLIC_URL


def boleto_mail(c: Client, rows: list[tuple[str, FinDoc]], name: str) -> tuple[str, dict]:
    lines = [f"• {_day(d.due_date)} · {_brl((d.amount or 0) - (d.paid or 0))} · {(d.description or 'Cobrança')[:70]}" for _, d in rows]
    when = "vence em 3 dias" if all(k == "boleto_d3" for k, _ in rows) else "vence hoje" if all(k == "boleto_d0" for k, _ in rows) else "tem vencimentos próximos"
    paras = [f"Você tem cobrança(s) de {c.trade_name} que {when}:", "\n".join(lines),
             "Para abrir o boleto ou a fatura, acesse o financeiro no portal. Se o pagamento já foi feito, desconsidere esta mensagem."]
    return f"Lembrete de vencimento · {c.trade_name}", mailer.notice_ctx("Lembrete de vencimento", paras, highlight=_brl(sum((d.amount or 0) - (d.paid or 0) for _, d in rows)),
                                                                        greeting=f"Olá, {name.split()[0]}!", button_url=_portal_url(), button_label="Abrir o financeiro")


def send_boletos(db: Session, today: date | None = None, only_to: str | None = None, force: bool = False) -> dict:
    """only_to: envia SOMENTE para este endereco (teste) e nao registra o aviso."""
    today = today or date.today()
    sent = 0
    for c in db.scalars(select(Client).where(Client.status == "ativo", Client.notify_boleto.is_(True) if not only_to else True, Client.ca_person_id.is_not(None))):
        docs = list(db.scalars(select(FinDoc).where(FinDoc.client_id == c.id, FinDoc.kind == "titulo", FinDoc.status.in_(["aberto", "vencido"]),
                                                    FinDoc.due_date.in_([today, today + timedelta(days=3)]))))
        if not docs:
            continue
        for u in _eligible(db, c, True) if not only_to else [None]:
            rows = []
            for d in docs:
                k = "boleto_d0" if d.due_date == today else "boleto_d3"
                if u is None or not db.scalar(select(FinNotice.id).where(FinNotice.user_id == u.id, FinNotice.kind == k, FinNotice.ref == str(d.id))):
                    rows.append((k, d))
            if not rows:
                continue
            to = only_to or u.email
            subj, ctx = boleto_mail(c, rows, (u.name if u else "equipe"))
            try:
                mailer.send(db, "notice", to, ("[TESTE] " if only_to else "") + subj, ctx)
            except Exception as e:  # noqa: BLE001
                log.warning("aviso de boleto para %s: %s", to, e)
                continue
            if u is not None:
                for k, d in rows:
                    db.add(FinNotice(user_id=u.id, client_id=c.id, kind=k, ref=str(d.id)))
                db.commit()
            sent += 1
            if only_to:
                return {"sent": sent}
    return {"sent": sent}


def monthly_ctx(db: Session, c: Client, u: User | None, year: int, month: int) -> tuple[str, dict]:
    from ..routers.clients import client_hosts
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
    evs = list(db.scalars(select(Event).where(Event.kind == "infra", Event.client_id == c.id, Event.started_at < end,
                                              (Event.recovered_at.is_(None)) | (Event.recovered_at > start))))
    hosts = client_hosts(db, c)
    k = kpi_service.compute(evs, [{"hostid": h.hostid, "name": h.name, "ip": h.ip} for h in hosts], start, end, c.sla_target,
                            exclude=maintenance_service.exclusions(db, c.id, start, end))
    msev = u.portal_min_sev if u else 4
    inc = [e for e in evs if (e.severity or 0) >= msev and start <= e.started_at < end]
    sm = k["summary"]
    ok = sm.get("sla_met")
    paras = [f"Segue o resumo de {MESES[month]} de {year} do ambiente de {c.trade_name}.",
             f"• Disponibilidade: {sm.get('availability'):.3f}% (SLA contratado {c.sla_target:g}%) — {'meta atingida' if ok else 'abaixo da meta' if ok is False else 'sem dados suficientes'}" if sm.get("availability") is not None else "• Disponibilidade: sem dados no período",
             f"• Incidentes de severidade alta ou superior: {len(inc)}"]
    if u is not None and "portal.finance" in (u.extra_perms or []) or u is None:
        openl = list(db.scalars(select(FinDoc).where(FinDoc.client_id == c.id, FinDoc.kind == "titulo", FinDoc.status.in_(["aberto", "vencido"]))))
        if openl:
            od = [d for d in openl if d.status == "vencido"]
            paras.append(f"• Financeiro: {_brl(sum((d.amount or 0) - (d.paid or 0) for d in openl))} em aberto" + (f", dos quais {_brl(sum((d.amount or 0) - (d.paid or 0) for d in od))} vencidos." if od else "."))
    paras.append("O detalhe completo (hosts, incidentes, backup e relatórios) está no portal.")
    return f"Resumo de {MESES[month]}/{year} · {c.trade_name}", mailer.notice_ctx(f"Resumo de {MESES[month]} de {year}", paras, greeting=f"Olá, {(u.name if u else 'equipe').split()[0]}!",
                                                                              button_url=_portal_url(), button_label="Abrir o portal")


def send_monthly(db: Session, today: date | None = None, only_to: str | None = None, only_client: int | None = None) -> dict:
    today = today or date.today()
    if not only_to and not (2 <= today.day <= 6):  # envia nos primeiros dias do mes, uma unica vez por pessoa
        return {"sent": 0}
    py, pm = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    ref, sent = f"{py:04d}-{pm:02d}", 0
    q = select(Client).where(Client.status == "ativo")
    q = q.where(Client.id == only_client) if only_client else q.where(Client.notify_monthly.is_(True))
    for c in db.scalars(q):
        for u in _eligible(db, c, False) if not only_to else [None]:
            if u is not None and db.scalar(select(FinNotice.id).where(FinNotice.user_id == u.id, FinNotice.kind == "mensal", FinNotice.ref == ref)):
                continue
            subj, ctx = monthly_ctx(db, c, u, py, pm)
            try:
                mailer.send(db, "notice", only_to or u.email, ("[TESTE] " if only_to else "") + subj, ctx)
            except Exception as e:  # noqa: BLE001
                log.warning("resumo mensal para %s: %s", only_to or u.email, e)
                continue
            if u is not None:
                db.add(FinNotice(user_id=u.id, client_id=c.id, kind="mensal", ref=ref))
                db.commit()
            sent += 1
    return {"sent": sent}
