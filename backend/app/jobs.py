"""Rotinas do worker. Cada rotina grava status em job_status (ultima execucao, proxima, erro, habilitada)."""
import logging
import os
import subprocess
import time as _t
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import delete, select

from . import scheduling, settings_store as S
from .config import get_settings
from .db import SessionLocal
from .models import (AuditLog, Dispatch, Event, HealthCheck, JobStatus, Report, ReportRun, Schedule, SyncRun)
from .services import delivery_service, event_service, factory, notification_service, report_service, sync_service

log = logging.getLogger("navi.jobs")
JOBS = {
    # name: (label, interval_s)
    "sync_inventory": ("Sincronização Zabbix (grupos e hosts)", 600),
    "poll_events": ("Processamento de eventos", 30),
    "dispatch_alerts": ("Envio de alertas", 10),
    "run_schedules": ("Geração/envio de relatórios agendados", 60),
    "health_checks": ("Health checks", 120),
    "cleanup": ("Limpeza de dados", 86400),
    "backup": ("Backup do banco NAVI", 86400),
}


def tracked(name):
    def deco(fn):
        def run():
            db = SessionLocal()
            t0 = _t.time()
            job = db.get(JobStatus, name)
            if job is None:
                label, itv = JOBS[name]
                job = JobStatus(name=name, label=label, interval_s=itv)
                db.add(job)
                db.commit()
            if not job.enabled:
                db.close()
                return
            try:
                fn(db)
                job.status, job.error = "ok", None
            except Exception as e:  # noqa: BLE001
                db.rollback()
                job = db.get(JobStatus, name)
                job.status, job.error = "error", f"{type(e).__name__}: {e}"[:1500]
                log.warning("job %s falhou: %s", name, e)
            job.last_run = datetime.now(timezone.utc)
            job.next_run = job.last_run + timedelta(seconds=job.interval_s or 0)
            job.last_duration_ms = int((_t.time() - t0) * 1000)
            db.commit()
            db.close()
        run.__name__ = name
        return run
    return deco


def _zabbix_ready(db) -> bool:
    return bool(S.get(db, "zabbix.token"))


@tracked("sync_inventory")
def sync_inventory(db):
    if _zabbix_ready(db):
        sync_service.sync_inventory(db, factory.zabbix(db))


@tracked("poll_events")
def poll_events(db):
    if _zabbix_ready(db):
        event_service.poll(db, factory.zabbix(db))


@tracked("dispatch_alerts")
def dispatch_alerts(db):
    if db.scalar(select(Dispatch.id).where(Dispatch.status == "pending", Dispatch.due_at <= datetime.now(timezone.utc)).limit(1)):
        notification_service.process_due(db, factory.evolution(db))


@tracked("run_schedules")
def run_schedules(db):
    now = datetime.now(timezone.utc)
    due = db.scalars(select(Schedule).where(Schedule.enabled.is_(True), Schedule.next_run <= now)).all()
    for s in due:
        try:
            rep = db.get(Report, s.report_id)
            a, b = report_service.resolve_period(s.period_mode, s.period_days)
            run = report_service.generate(db, rep, "rotina", a, b, name_suffix="_auto")
            delivery_service.deliver(db, run, rep, wa_dest=s.wa_dest, email_to=s.email_to, cc=s.email_cc,
                                     bcc=s.email_bcc, subject=s.subject)
            s.last_status = f"ok · WA: {run.wa_status or '-'} · E-mail: {run.email_status or '-'}"[:250]
        except Exception as e:  # noqa: BLE001
            db.rollback()
            s = db.get(Schedule, s.id)
            s.last_status = f"erro: {e}"[:250]
        s.last_run = now
        s.next_run = scheduling.next_run(s, now)
        db.commit()


@tracked("health_checks")
def health_checks(db):
    def put(name, ok, detail):
        h = db.get(HealthCheck, name) or HealthCheck(name=name)
        h.ok, h.detail, h.checked_at = ok, str(detail)[:500], datetime.now(timezone.utc)
        db.merge(h)
    try:
        z = factory.zabbix(db)
        v = z.version()
        if not S.get(db, "zabbix.token"):
            raise RuntimeError(f"Zabbix {v} acessível, mas o token da API não está configurado")
        z.call("hostgroup.get", {"limit": 1, "output": ["groupid"]})
        put("zabbix", True, f"Zabbix {v}")
    except Exception as e:  # noqa: BLE001
        put("zabbix", False, e)
    try:
        st = factory.evolution(db).status()
        state = (st.get("instance") or st).get("state", "ok")
        put("evolution", state in ("open", "ok"), f"estado: {state}")
    except Exception as e:  # noqa: BLE001
        put("evolution", False, e)
    try:
        factory.email(db).test()
        put("email", True, "SMTP autenticado")
    except Exception as e:  # noqa: BLE001
        put("email", False, e)
    put("navi", True, "operacional")
    db.commit()


@tracked("cleanup")
def cleanup(db):
    now = datetime.now(timezone.utc)
    ret = int(os.environ.get("NAVI_EVENT_RETENTION_DAYS", "90"))
    # eventos resolvidos alem da retencao saem da NAVI (consulta historica e feita ao vivo no Zabbix)
    db.execute(delete(Event).where(Event.status == "RESOLVED", Event.started_at < now - timedelta(days=ret)))
    db.execute(delete(Dispatch).where(Dispatch.created_at < now - timedelta(days=ret)))
    db.execute(delete(SyncRun).where(SyncRun.started_at < now - timedelta(days=30)))
    db.execute(delete(AuditLog).where(AuditLog.ts < now - timedelta(days=730)))
    # PDFs orfaos (sem registro) e excedentes por cliente
    for cid in {r for r in db.scalars(select(ReportRun.client_id).distinct())}:
        report_service.prune_runs(db, cid)
    known = {p for p in db.scalars(select(ReportRun.file_path)) if p}
    root = Path(get_settings().NAVI_STORAGE) / "reports"
    if root.exists():
        for f in root.rglob("*.pdf"):
            if str(f) not in known:
                f.unlink(missing_ok=True)
    # tmp de relatorios
    tmp = Path(get_settings().NAVI_STORAGE) / "tmp"
    if tmp.exists():
        for f in tmp.iterdir():
            if f.is_file() and f.stat().st_mtime < _t.time() - 86400:
                f.unlink(missing_ok=True)


@tracked("backup")
def backup(db):
    st = get_settings()
    out = Path(st.NAVI_STORAGE).parent / "backups"
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"navi_{datetime.now():%Y%m%d_%H%M}.sql.gz"
    env = {**os.environ, "PGPASSWORD": st.NAVI_DB_PASSWORD, "PGSSLMODE": st.NAVI_DB_SSLMODE}
    cmd = f"pg_dump -h {st.NAVI_DB_HOST} -p {st.NAVI_DB_PORT} -U {st.NAVI_DB_USER} {st.NAVI_DB_NAME} | gzip > {f}"
    r = subprocess.run(["bash", "-c", "set -o pipefail; " + cmd], env=env, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        f.unlink(missing_ok=True)
        raise RuntimeError(r.stderr[-400:])
    for old in sorted(out.glob("navi_*.sql.gz"))[:-7]:
        old.unlink(missing_ok=True)


def start():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    sch = BlockingScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120})
    for name, fn in [("sync_inventory", sync_inventory), ("poll_events", poll_events),
                     ("dispatch_alerts", dispatch_alerts), ("run_schedules", run_schedules),
                     ("health_checks", health_checks), ("cleanup", cleanup), ("backup", backup)]:
        sch.add_job(fn, "interval", seconds=JOBS[name][1], id=name,
                    next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5 + 3 * list(JOBS).index(name)))
    log.info("worker NAVI iniciado com %d rotinas", len(JOBS))
    sch.start()
