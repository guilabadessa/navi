from calendar import monthrange
from datetime import datetime, time, timedelta, timezone

from .models import Schedule
from .services.notification_service import tz


def next_run(s: Schedule, after: datetime | None = None) -> datetime:
    z = tz()
    now = (after or datetime.now(timezone.utc)).astimezone(z)
    hh, mm = (int(x) for x in (s.run_time or "08:00").split(":"))
    t = time(hh, mm)
    if s.frequency == "daily":
        c = datetime.combine(now.date(), t, z)
        if c <= now:
            c += timedelta(days=1)
    elif s.frequency == "weekly":
        wd = s.weekday if s.weekday is not None else 0
        c = datetime.combine(now.date() + timedelta(days=(wd - now.weekday()) % 7), t, z)
        if c <= now:
            c += timedelta(days=7)
    elif s.frequency == "monthly":
        day = s.month_day or 1

        def mk(y, m):
            return datetime.combine(datetime(y, m, min(day, monthrange(y, m)[1])).date(), t, z)
        c = mk(now.year, now.month)
        if c <= now:
            y, m = (now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1)
            c = mk(y, m)
    else:  # custom: a cada N dias
        base = s.last_run.astimezone(z) if s.last_run else now
        c = datetime.combine(base.date() + timedelta(days=s.interval_days or 1), t, z)
        if c <= now:
            c = datetime.combine(now.date() + timedelta(days=1), t, z)
    return c.astimezone(timezone.utc)
