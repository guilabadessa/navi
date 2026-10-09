"""Geracao de relatorio (KPIs + graficos + PDF). Nao conhece WhatsApp/e-mail: entrega fica em delivery_service."""
import base64
import hashlib
import io
import json
from calendar import monthrange
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from weasyprint import HTML  # noqa: E402

from .. import settings_store as S  # noqa: E402
from ..config import get_settings  # noqa: E402
from ..models import SEVERITIES, Client, Event, Report, ReportRun, ZbxHost  # noqa: E402
from . import factory, kpi_service, live_events, services_service  # noqa: E402
from .notification_service import fmt_duration, tz  # noqa: E402

APP = Path(__file__).resolve().parent.parent
ASSETS = APP / "assets"
NAVY, BLUE, RED = "#071a5a", "#1e73f8", "#bd1723"
SEV_COLORS = {"Não classificado": "#97aab3", "Informação": "#7499ff", "Atenção": "#e0a800", "Média": "#f08a24",
              "Alta": "#e45959", "Desastre": "#bd1723"}
LH_DEFAULT = {"company": "Orca TI", "cnpj": "", "address": "", "phone": "", "site": "orcati.com.br",
              "text": "Relatório gerado automaticamente pela plataforma NAVI — Inteligência operacional Orca TI."}


def letterhead(db: Session) -> dict:
    try:
        v = json.loads(S.get(db, "letterhead.orca", "") or "{}")
    except ValueError:
        v = {}
    return {**LH_DEFAULT, **v}


def period_label(a: datetime, b: datetime) -> str:
    z = tz()
    return f"{a.astimezone(z):%d/%m/%Y} a {(b - timedelta(seconds=1)).astimezone(z):%d/%m/%Y}"


def resolve_period(mode: str, days: int | None = None, ref: datetime | None = None) -> tuple[datetime, datetime]:
    z = tz()
    now = (ref or datetime.now(timezone.utc)).astimezone(z)
    today0 = datetime.combine(now.date(), time.min, z)
    if mode == "prev_day":
        a, b = today0 - timedelta(days=1), today0
    elif mode == "prev_week":
        mon = today0 - timedelta(days=today0.weekday())
        a, b = mon - timedelta(days=7), mon
    elif mode == "prev_month":
        first = today0.replace(day=1)
        last_prev = first - timedelta(days=1)
        a, b = last_prev.replace(day=1), first
    elif mode == "last_n_days":
        a, b = today0 - timedelta(days=days or 7), today0
    else:
        raise ValueError(f"modo de período inválido: {mode}")
    return a.astimezone(timezone.utc), b.astimezone(timezone.utc)


def universe_hosts(db: Session, rep: Report, client: Client | None) -> list[ZbxHost]:
    """Hosts do relatorio. Com cliente, so entram hosts QUE O CLIENTE TEM HOJE: selecoes antigas guardadas no relatorio
    (host/grupo desvinculado depois) sao descartadas e o relatorio e atualizado."""
    ids, gids = set(rep.host_ids or []), set(rep.group_ids or [])
    if client:
        from ..routers.clients import client_hosts
        mine = {h.hostid: h for h in client_hosts(db, client)}
        cur_g = {g.zbx_groupid for g in client.groups}
        ids, gids = {i for i in ids if i in mine}, {g for g in gids if g in cur_g}
        if sorted(ids) != sorted(rep.host_ids or []) or sorted(gids) != sorted(rep.group_ids or []):
            rep.host_ids, rep.group_ids = sorted(ids), sorted(gids)  # limpa o lixo guardado
            db.flush()
        if not ids and not gids:
            return sorted(mine.values(), key=lambda h: (h.name or "").lower())
        return [h for h in mine.values() if h.hostid in ids or (gids and set(h.group_ids or []) & gids)]
    q = select(ZbxHost).where(ZbxHost.active.is_(True))
    return [h for h in db.scalars(q) if h.hostid in ids or (gids and set(h.group_ids or []) & gids)]


def _chart_png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def make_charts(k: dict) -> list[str]:
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    out = []
    hosts = [h for h in k["by_host"] if h["downtime_s"] > 0][:12]
    if hosts:
        fig, ax = plt.subplots(figsize=(8, max(2.2, 0.38 * len(hosts) + 0.8)))
        ax.barh([h["host"][:38] for h in reversed(hosts)], [h["downtime_s"] / 3600 for h in reversed(hosts)], color=BLUE)
        ax.set_xlabel("Horas indisponíveis")
        ax.set_title("Indisponibilidade por host (top 12)", loc="left", color=NAVY, fontweight="bold")
        out.append(_chart_png(fig))
    sev = k["by_severity"]
    if sev:
        fig, ax = plt.subplots(figsize=(8, 2.6))
        ax.bar([s["key"] for s in sev], [s["incidents"] for s in sev], color=[SEV_COLORS.get(s["key"], BLUE) for s in sev])
        ax.set_title("Incidentes por severidade", loc="left", color=NAVY, fontweight="bold")
        out.append(_chart_png(fig))
    days = k["by_day"]
    if days:
        fig, ax = plt.subplots(figsize=(8, 2.6))
        ax.bar(list(days.keys()), list(days.values()), color=NAVY)
        ax.set_title("Incidentes por dia", loc="left", color=NAVY, fontweight="bold")
        step = max(1, len(days) // 12)
        ax.set_xticks(list(days.keys())[::step])
        ax.tick_params(axis="x", rotation=45, labelsize=7)
        out.append(_chart_png(fig))
    return out


def build(db: Session, rep: Report, start: datetime, end: datetime) -> tuple[dict, list, list[ZbxHost], Client | None]:
    """Eventos vem AO VIVO da API do Zabbix (nada e armazenado alem do PDF final)."""
    client = db.get(Client, rep.client_id) if rep.client_id else None
    hosts = universe_hosts(db, rep, client)
    host_ids = [h.hostid for h in hosts]
    events = live_events.fetch(db, factory.zabbix(db), host_ids, start, end, rep.client_id)
    if rep.severities:
        events = [e for e in events if e.severity in rep.severities]
    for needle, attr in ((rep.triggers, "trigger_name"), (rep.items, "item_name")):
        if needle:
            events = [e for e in events if any(n.lower() in (getattr(e, attr) or "").lower() for n in needle)]
    if not rep.include_resolved:
        events = [e for e in events if e.status != "RESOLVED"]
    if not rep.include_open:
        events = [e for e in events if e.status == "RESOLVED"]
    from . import maintenance_service
    k = kpi_service.compute(events, [{"hostid": h.hostid, "name": h.name, "ip": h.ip} for h in hosts], start, end,
                            None, exclude=maintenance_service.exclusions(db, rep.client_id, start, end))
    return k, events, hosts, client


def dur2(sec) -> str:
    """Duracao curta: apenas as 2 unidades mais significativas (cabe nos cartoes)."""
    if sec is None:
        return "—"
    sec = int(sec)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = [(d, "d"), (h, "h"), (m, "min"), (s, "s")]
    parts = [f"{v}{u}" for v, u in parts if v]
    return " ".join(parts[:2]) if parts else "0s"


def summary_text(k: dict, client_name: str, period: str) -> str:
    s = k["summary"]
    if not s["incidents"]:
        return f"No período {period}, não foram registrados incidentes para {client_name}. Disponibilidade de {_n(s['availability'])}%."
    b = s["biggest"]
    t = (f"No período {period}, {client_name} registrou {s['incidents']} incidente(s) em {s['hosts_affected']} de "
         f"{s['hosts_total']} host(s), totalizando {fmt_duration(s['downtime_s'])} de indisponibilidade. ")
    if b:
        t += f"O maior incidente ocorreu em {b['host']} ({b['trigger']}) e durou {fmt_duration(b['duration_s'])}. "
    if s["open"]:
        t += f"{s['open']} incidente(s) permanecem em aberto. "
    return t


def resolve_modules(db: Session, rep: Report, client: Client | None) -> list[str]:
    """Modulos do relatorio: os escolhidos que o cliente realmente tem; sem escolha = tudo que o cliente tem.
    Relatorio geral (sem cliente) e sempre de infraestrutura."""
    if not client:
        return ["infra"]
    have = services_service.active_list(services_service.of_client(db, client))
    mods = [m for m in (rep.modules or have) if m in have]
    if not mods:
        raise ValueError("O cliente não possui o(s) serviço(s) selecionado(s) (infraestrutura, backup ou endpoints) associado(s) ao cadastro.")
    return mods


def period_incidents(db: Session, client_id: int, kind: str, start: datetime, end: datetime, z) -> dict:
    """Ocorrencias (eventos NAVI de backup/estacoes) que tocaram o periodo."""
    evs = list(db.scalars(select(Event).where(Event.kind == kind, Event.client_id == client_id, Event.started_at < end,
                                              (Event.recovered_at.is_(None)) | (Event.recovered_at > start)).order_by(Event.started_at)))
    fmt = lambda d: d.astimezone(z).strftime("%d/%m/%Y %H:%M") if d else "—"  # noqa: E731
    rows = [{"name": e.host or "—", "what": e.trigger_name or "—", "sev": e.severity, "start": fmt(e.started_at),
             "end": fmt(e.recovered_at) if e.recovered_at else None, "dur": e.duration_s} for e in evs[:80]]
    return {"total": len(evs), "open": sum(1 for e in evs if e.status == "PROBLEM"), "rows": rows}


COLORS = {"ok": "#16a34a", "warn": "#d97706", "bad": "#bd1723", "mut": "#8791b0"}


def _dist(counter: dict, tone: dict) -> list[dict]:
    """Distribuicao para a barra empilhada: [{label, n, pct, color}] (so o que existe)."""
    tot = sum(counter.values()) or 1
    return [{"label": k, "n": n, "pct": round(100 * n / tot, 1), "color": COLORS[tone.get(k, "mut")]} for k, n in counter.items() if n]


def backup_section(db: Session, client_id: int | None, z, start=None, end=None) -> dict | None:
    """Backup (Acronis) dos itens do cliente: situacao atual + estatisticas; None se o cliente nao tem tenant associado."""
    if not client_id:
        return None
    from collections import Counter

    from ..models import ExtAsset, ExtTenant
    from ..routers.protection import asset_status
    from . import protection_service as P
    tids = list(db.scalars(select(ExtTenant.id).where(ExtTenant.client_id == client_id, ExtTenant.source == "acronis")))
    if not tids:
        return None
    c, now = P.cfg(db), datetime.now(timezone.utc)
    names = {"machine": "Servidor", "database": "Banco de dados", "mailbox": "E-mail", "drive": "OneDrive", "site": "SharePoint", "team": "Teams"}
    rows, oldest = [], None
    for a in db.scalars(select(ExtAsset).where(ExtAsset.ext_tenant_id.in_(tids), ExtAsset.active.is_(True), ExtAsset.ignored.is_(False)).order_by(ExtAsset.name)):
        st = asset_status(a, c, now)
        if st == "sem dados":
            continue
        rows.append({"name": a.name, "type": names.get(a.type, a.type or "—"), "status": "Protegido" if st == "ok" else st.capitalize(),
                     "last": a.last_success_at.astimezone(z).strftime("%d/%m/%Y %H:%M") if a.last_success_at else "—", "ok": st == "ok"})
        if a.last_success_at and (oldest is None or a.last_success_at < oldest[1]):
            oldest = (a.name, a.last_success_at)
    if not rows:
        return None
    n_ok = sum(1 for r in rows if r["ok"])
    rows.sort(key=lambda r: (r["ok"], r["name"].lower()))  # itens com atencao primeiro
    return {"rows": rows[:120], "total": len(rows), "ok": n_ok, "problems": len(rows) - n_ok, "pct": round(100 * n_ok / len(rows), 1),
            "dist": _dist(Counter(r["status"] for r in rows), {"Protegido": "ok"} | {k: "bad" for k in ("Falha", "Offline", "Sem backup")}),
            "types": sorted(Counter(r["type"] for r in rows).items(), key=lambda x: -x[1]),
            "oldest": {"name": oldest[0], "at": oldest[1].astimezone(z).strftime("%d/%m/%Y %H:%M")} if oldest else None,
            "inc": period_incidents(db, client_id, "backup", start, end, z) if start else None}


def endpoint_section(db: Session, client_id: int | None, z, start=None, end=None) -> dict | None:
    """Endpoints do cliente (FortiClient EMS e/ou protecao do Acronis): situacao atual + estatisticas; None se nao houver."""
    if not client_id:
        return None
    from collections import Counter

    from . import protection_service as P
    raw = P.endpoint_rows(db, client_id)
    if not raw:
        return None
    fmt = lambda d: d.astimezone(z).strftime("%d/%m/%Y %H:%M") if d else "—"  # noqa: E731
    rows = [{"name": r["name"], "user": r["user"] or "—", "source": r["source"], "techs": ", ".join(r["techs"]), "status": r["status"].capitalize(), "ok": r["ok"], "last": fmt(r["last"])} for r in raw]
    n_ok = sum(1 for r in rows if r["ok"])
    rows.sort(key=lambda r: (r["ok"], r["name"].lower()))
    tone = {"Online": "ok", "Offline": "mut", "Atenção": "warn", "Assinaturas": "warn"}
    techs = Counter(t for r in raw for t in r["techs"])
    return {"total": len(rows), "online": sum(1 for r in rows if r["status"] == "Online"), "ok": n_ok, "problems": len(rows) - n_ok,
            "pct": round(100 * n_ok / len(rows), 1), "dist": _dist(Counter(r["status"] for r in rows), {**tone, **{k: "bad" for k in ("Sem contato", "Antivírus off", "Quarentena")}}),
            "techs": techs.most_common(), "sources": sorted({r["source"] for r in rows}), "rows": rows[:100],
            "inc": period_incidents(db, client_id, "endpoint", start, end, z) if start else None}


def _n(v) -> str:
    return f"{v:.3f}".replace(".", ",")


def highlights(mods, k, backup, endpoints, infra_on) -> list[dict]:
    """Pontos de atencao e boas noticias para a capa (apenas dos servicos incluidos)."""
    out = []
    if infra_on:
        s = k["summary"]
        out.append({"tone": "ok" if s["availability"] >= 99 else "warn" if s["availability"] >= 95 else "bad",
                    "text": f"Disponibilidade geral dos equipamentos de {_n(s['availability'])}% no período, com {s['incidents']} incidente(s)."})
        if s["open"]:
            out.append({"tone": "warn", "text": f"{s['open']} incidente(s) de infraestrutura ainda em aberto."})
        if s["biggest"]:
            out.append({"tone": "mut", "text": f"Maior incidente: {s['biggest']['host']} — {s['biggest']['trigger']} ({fmt_duration(s['biggest']['duration_s'])})."})
        rec = [h for h in k["by_host"] if h["incidents"] >= 3][:3]
        if rec:
            out.append({"tone": "warn", "text": "Hosts reincidentes: " + "; ".join(f"{h['host']} ({h['incidents']})" for h in rec) + "."})
    if backup:
        if backup["problems"]:
            names = ", ".join(r["name"] for r in backup["rows"] if not r["ok"])[:160]
            out.append({"tone": "bad", "text": f"{backup['problems']} de {backup['total']} item(ns) de backup requerem atenção: {names}."})
        else:
            out.append({"tone": "ok", "text": f"Todos os {backup['total']} itens de backup estão protegidos e em dia."})
    if endpoints:
        if endpoints["problems"]:
            out.append({"tone": "warn", "text": f"{endpoints['problems']} de {endpoints['total']} endpoint(s) com pendência (sem contato, antivírus desligado ou assinaturas)."})
        else:
            out.append({"tone": "ok", "text": f"Todos os {endpoints['total']} endpoints estão em conformidade."})
    return out[:6]


def compare_text(k: dict, prev: dict | None, plabel: str) -> str:
    """Comparativo com o periodo anterior de mesma duracao + hosts reincidentes."""
    out = []
    if prev:
        a, b = k["summary"], prev["summary"]
        n = lambda v, sign=False: (f"{v:+.3f}" if sign else f"{v:.3f}").replace(".", ",")  # noqa: E731
        da = round(a["availability"] - b["availability"], 3)
        di = a["incidents"] - b["incidents"]
        tend = "melhora" if da > 0 else "queda" if da < 0 else "estabilidade"
        out.append(f"Comparado ao período anterior ({plabel}), houve {tend} de disponibilidade "
                   f"({n(a['availability'])}% contra {n(b['availability'])}%; {n(da, True)} p.p.) e "
                   f"{'aumento' if di > 0 else 'redução' if di < 0 else 'manutenção'} de incidentes "
                   f"({a['incidents']} contra {b['incidents']}).")
    rec = [h for h in k["by_host"] if h["incidents"] >= 3][:5]
    if rec:
        out.append("Hosts reincidentes (3 ou mais incidentes no período): " + "; ".join(f"{h['host']} ({h['incidents']})" for h in rec) + ".")
    return " ".join(out)


KEEP_RUNS_PER_CLIENT = 2


def prune_runs(db: Session, client_id: int | None, keep: int = KEEP_RUNS_PER_CLIENT) -> int:
    """Mantem apenas os `keep` PDFs mais recentes por cliente (apaga arquivo e registro)."""
    cond = ReportRun.client_id == client_id if client_id is not None else ReportRun.client_id.is_(None)
    runs = list(db.scalars(select(ReportRun).where(cond).order_by(ReportRun.generated_at.desc(), ReportRun.id.desc())))
    n = 0
    for r in runs[keep:]:
        if r.file_path:
            Path(r.file_path).unlink(missing_ok=True)
        db.delete(r)
        n += 1
    db.commit()
    return n


def generate(db: Session, rep: Report, user: str | None, start: datetime | None = None, end: datetime | None = None,
             name_suffix: str = "") -> ReportRun:
    start = start or rep.period_start
    end = end or rep.period_end
    if not (start and end):
        raise ValueError("Período não definido")
    run = ReportRun(report_id=rep.id, client_id=rep.client_id, name=rep.name, period_start=start, period_end=end,
                    generated_by=user, status="running")
    db.add(run)
    db.flush()
    try:
        client = db.get(Client, rep.client_id) if rep.client_id else None
        mods = resolve_modules(db, rep, client)
        infra_on = "infra" in mods
        if infra_on:
            k, events, hosts, client = build(db, rep, start, end)
        else:  # cliente so de backup/estacoes: nao consulta o Zabbix
            k, events, hosts = kpi_service.compute([], [], start, end, None), [], []
        cname = client.trade_name if client else "Todos os clientes"
        plabel = period_label(start, end)
        prev = None
        try:
            prev = build(db, rep, start - (end - start), start)[0] if infra_on else None  # periodo anterior (consulta ao vivo no Zabbix)
        except Exception:  # noqa: BLE001
            prev = None
        cmp_text = compare_text(k, prev, period_label(start - (end - start), start))
        MAX_ROWS = 150  # PDF legivel e rapido; resumos por host/trigger cobrem 100% dos eventos
        rows = sorted(sorted(events, key=lambda e: -(e.duration_s or 0))[:MAX_ROWS], key=lambda e: e.started_at)
        env = Environment(loader=FileSystemLoader(str(APP / "templates")), autoescape=select_autoescape(["html"]))
        z = tz()
        backup = backup_section(db, rep.client_id, z, start, end) if "backup" in mods else None
        endpoints = endpoint_section(db, rep.client_id, z, start, end) if "endpoint" in mods else None
        title = ("Relatório de Disponibilidade" if mods == ["infra"] else
                 "Relatório de Backup" if mods == ["backup"] else "Relatório de Endpoints" if mods == ["endpoint"] else
                 "Relatório de Serviços Gerenciados")
        html = env.get_template("report.html").render(hl=highlights(mods, k, backup, endpoints, infra_on), backup=backup, endpoints=endpoints, infra_on=infra_on, mods=[services_service.NAMES[m] for m in mods],
            report_title=title,
            assets=str(ASSETS), report_name=rep.name, client_name=cname, cnpj=rep.cnpj or (client.cnpj if client else None),
            client_logo=(client.logo_path if client and client.logo_path and Path(client.logo_path).exists() else None),
            period_label=plabel, generated_at=datetime.now(z).strftime("%d/%m/%Y %H:%M"), lh=letterhead(db),
            s=k["summary"], k=k, kpis_on=rep.include_kpis, charts=make_charts(k) if (rep.include_charts and infra_on) else [],
            rows=rows, total_rows=len(events), truncated=len(events) > MAX_ROWS, notes=rep.notes,
            summary_text=summary_text(k, cname, plabel) if infra_on else '', cmp_text=cmp_text, cmp_main=cmp_text.split(" Hosts reincidentes")[0],
            pct=lambda v: "—" if v is None else f"{v:.3f}%".replace(".", ","),
            dur=lambda v: fmt_duration(v) if v is not None else "—", dur2=dur2,
            dt=lambda d: d.astimezone(z).strftime("%d/%m/%Y %H:%M") if d else "—",
            sevname=lambda n: SEVERITIES.get(n, str(n)))
        pdf = HTML(string=html, base_url=str(APP)).write_pdf()
        folder = Path(get_settings().NAVI_STORAGE) / "reports" / (f"c{rep.client_id}" if rep.client_id else "all") / f"{start:%Y-%m}"
        folder.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{rep.name}{name_suffix}")[:60]
        path = folder / f"{safe}_{start:%Y%m%d}-{end:%Y%m%d}_{datetime.now():%H%M%S}.pdf"
        path.write_bytes(pdf)
        run.file_path, run.size, run.sha256 = str(path), len(pdf), hashlib.sha256(pdf).hexdigest()
        run.kpis, run.status = (k["summary"] if infra_on else None), "ok"
        db.commit()
        prune_runs(db, rep.client_id)
    except Exception as e:  # noqa: BLE001
        run.status, run.error = "error", str(e)[:2000]
        db.commit()
        raise
    db.commit()
    return run
