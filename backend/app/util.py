from datetime import datetime

from sqlalchemy import inspect


def to_dict(obj, exclude: set[str] | None = None) -> dict:
    exclude = exclude or set()
    out = {}
    for c in inspect(obj).mapper.column_attrs:
        if c.key in exclude:
            continue
        v = getattr(obj, c.key)
        out[c.key] = v.isoformat() if isinstance(v, datetime) else v
    return out


def parse_dt(v: str | None):
    if not v:
        return None
    return datetime.fromisoformat(v.replace("Z", "+00:00"))
