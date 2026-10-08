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
from . import factory, kpi_service, live_events  # noqa: E402
from .notification_service import fmt_duration, tz  # noqa: E402

APP = Path(__file__).resolve().parent.parent
ASSETS = APP / "assets"
NAVY, BLUE, RED = "#071a5a", "#1e73f8", "#bd1723"
SEV_COLORS = {"Não classificado": "#97aab3", "Informação": "#7499ff", "Atenção": "#e0a800", "Média": "#f08a24",
              "Alta": "#e45959", "Desastre": "#bd1723"}
LH_DEFAULT = {"company": "Orca TI", "cnpj": "", "address": "", "phone": "", "site": "orcati.com.br",
              "text": "Relatório gerado automaticamente pela plataforma NAVI — Navegação, Orientação e Assistência."}


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
    ids = set(rep.host_ids or [])
    gids = set(rep.group_ids or [])
    if not ids and not gids and client:
        ids |= {h.zbx_hostid for h in client.hosts}
        gids |= {g.zbx_groupid for g in client.groups}
    q = select(ZbxHost).where(ZbxHost.active.is_(True))
    out = []
    for h in db.scalars(q):
        if h.hostid in ids or (gids and set(h.group_ids or []) & gids):
            out.append(h)
    return out


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
                            client.sla_target if client else None, exclude=maintenance_service.exclusions(db, rep.client_id, start, end))
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
        return f"No período {period}, não foram registrados incidentes para {client_name}. Disponibilidade de {s['availability']:.3f}%."
    b = s["biggest"]
    t = (f"No período {period}, {client_name} registrou {s['incidents']} incidente(s) em {s['hosts_affected']} de "
         f"{s['hosts_total']} host(s), totalizando {fmt_duration(s['downtime_s'])} de indisponibilidade. ")
    if b:
        t += f"O maior incidente ocorreu em {b['host']} ({b['trigger']}) e durou {fmt_duration(b['duration_s'])}. "
    if s["open"]:
        t += f"{s['open']} incidente(s) permanecem em aberto. "
    return t


def backup_section(db: Session, client_id: int | None, z) -> dict | None:
    """Situacao atual do backup (Acronis) dos itens do cliente; None se o cliente nao tem tenant associado."""
    if not client_id:
        return None
    from ..models import ExtAsset, ExtTenant
    from ..routers.protection import asset_status
    from . import protection_service as P
    tids = list(db.scalars(select(ExtTenant.id).where(ExtTenant.client_id == client_id, ExtTenant.source == "acronis")))
    if not tids:
        return None
    c, now = P.cfg(db), datetime.now(timezone.utc)
    names = {"machine": "Servidor", "database": "Banco de dados", "mailbox": "E-mail", "drive": "OneDrive", "site": "SharePoint", "team": "Teams"}
    rows = []
    for a in db.scalars(select(ExtAsset).where(ExtAsset.ext_tenant_id.in_(tids), ExtAsset.active.is_(True), ExtAsset.ignored.is_(False)).order_by(ExtAsset.name)):
        st = asset_status(a, c, now)
        if st == "sem dados":
            continue
        rows.append({"name": a.name, "type": names.get(a.type, a.type), "status": "Protegido" if st == "ok" else st.capitalize(),
                     "last": a.last_success_at.astimezone(z).strftime("%d/%m/%Y %H:%M") if a.last_success_at else "—", "ok": st == "ok"})
    if not rows:
        return None
    return {"rows": rows[:120], "total": len(rows), "ok": sum(1 for r in rows if r["ok"]), "problems": sum(1 for r in rows if not r["ok"])}


def endpoint_section(db: Session, client_id: int | None, z) -> dict | None:
    """Situacao atual das estacoes (FortiClient EMS) do cliente; None se nao houver site associado."""
    if not client_id:
        return None
    from ..models import ExtAsset, ExtTenant
    from . import protection_service as P
    tids = list(db.scalars(select(ExtTenant.id).where(ExtTenant.client_id == client_id, ExtTenant.source == "ems")))
    if not tids:
        return None
    days, now = P.cfg(db)["ems_offline_days"], datetime.now(timezone.utc)
    rows = []
    for a in db.scalars(select(ExtAsset).where(ExtAsset.ext_tenant_id.in_(tids), ExtAsset.active.is_(True), ExtAsset.ignored.is_(False)).order_by(ExtAsset.name)):
        st = P.ems_status(a, days, now)
        rows.append({"name": a.name, "user": (a.meta or {}).get("user") or "—", "status": st, "ok": st in ("online", "offline"),
                     "last": a.last_success_at.astimezone(z).strftime("%d/%m/%Y %H:%M") if a.last_success_at else "—"})
    if not rows:
        return None
    attention = [r for r in rows if not r["ok"]]
    return {"total": len(rows), "online": sum(1 for r in rows if r["status"] == "online"), "problems": len(attention),
            "rows": (attention + [r for r in rows if r["ok"]])[:80]}


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
        k, events, hosts, client = build(db, rep, start, end)
        cname = client.trade_name if client else "Todos os clientes"
        plabel = period_label(start, end)
        prev = None
        try:
            prev = build(db, rep, start - (end - start), start)[0]  # periodo anterior (consulta ao vivo no Zabbix)
        except Exception:  # noqa: BLE001
            prev = None
        cmp_text = compare_text(k, prev, period_label(start - (end - start), start))
        MAX_ROWS = 150  # PDF legivel e rapido; resumos por host/trigger cobrem 100% dos eventos
        rows = sorted(sorted(events, key=lambda e: -(e.duration_s or 0))[:MAX_ROWS], key=lambda e: e.started_at)
        env = Environment(loader=FileSystemLoader(str(APP / "templates")), autoescape=select_autoescape(["html"]))
        z = tz()
        backup = backup_section(db, rep.client_id, z)
        endpoints = endpoint_section(db, rep.client_id, z)
        html = env.get_template("report.html").render(backup=backup, endpoints=endpoints,
            assets=str(ASSETS), report_name=rep.name, client_name=cname, cnpj=rep.cnpj or (client.cnpj if client else None),
            client_logo=(client.logo_path if client and client.logo_path and Path(client.logo_path).exists() else None),
            period_label=plabel, generated_at=datetime.now(z).strftime("%d/%m/%Y %H:%M"), lh=letterhead(db),
            s=k["summary"], k=k, kpis_on=rep.include_kpis, charts=make_charts(k) if rep.include_charts else [],
            rows=rows, total_rows=len(events), truncated=len(events) > MAX_ROWS, notes=rep.notes,
            summary_text=summary_text(k, cname, plabel), cmp_text=cmp_text,
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
        run.kpis, run.status = k["summary"], "ok"
        db.commit()
        prune_runs(db, rep.client_id)
    except Exception as e:  # noqa: BLE001
        run.status, run.error = "error", str(e)[:2000]
        db.commit()
        raise
    db.commit()
    return run
