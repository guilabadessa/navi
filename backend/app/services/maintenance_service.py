"""Janelas de manutencao: expandem em intervalos concretos (UTC). Usadas para suprimir alertas e descontar do SLA."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import MaintenanceWindow


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().NAVI_TZ)


def expand(w, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Intervalos da janela 'w' que tocam [start, end]. Aceita qualquer objeto com os campos do modelo."""
    out = []
    if w.kind == "once":
        if w.start_at and w.end_at and w.end_at > w.start_at and w.end_at > start and w.start_at < end:
            out.append((w.start_at, w.end_at))
        return out
    try:
        hh, mm = (w.start_time or "00:00").split(":")
        t0 = time(int(hh), int(mm))
    except ValueError:
        return out
    dur = timedelta(minutes=w.duration_min or 0)
    if dur <= timedelta(0) or not w.weekdays:
        return out
    tz = _tz()
    day = (start.astimezone(tz) - timedelta(days=1)).date()
    last = (end.astimezone(tz) + timedelta(days=1)).date()
    while day <= last:
        if day.weekday() in w.weekdays:
            s = datetime.combine(day, t0, tzinfo=tz).astimezone(timezone.utc)
            e = s + dur
            if e > start and s < end:
                out.append((s, e))
        day += timedelta(days=1)
    return out


def _windows(db: Session, client_id: int | None) -> list[MaintenanceWindow]:
    stmt = select(MaintenanceWindow).where(MaintenanceWindow.enabled.is_(True))
    stmt = stmt.where(MaintenanceWindow.client_id.is_(None) | (MaintenanceWindow.client_id == client_id)) if client_id else stmt.where(MaintenanceWindow.client_id.is_(None))
    return list(db.scalars(stmt))


def intervals(db: Session, client_id: int | None, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    out = []
    for w in _windows(db, client_id):
        out += expand(w, start, end)
    return sorted(out)


def exclusions(db: Session, client_id: int | None, start: datetime, end: datetime) -> list[tuple[float, float]]:
    """Intervalos (epoch) para descontar do SLA."""
    return [(a.timestamp(), b.timestamp()) for a, b in intervals(db, client_id, start, end)]


def active(db: Session, client_id: int | None, at: datetime | None = None) -> tuple[datetime, datetime] | None:
    at = at or datetime.now(timezone.utc)
    for a, b in intervals(db, client_id, at - timedelta(minutes=1), at + timedelta(minutes=1)):
        if a <= at < b:
            return a, b
    return None
