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


_SMALL = {"de", "da", "do", "das", "dos", "e"}
_ACR = {"TI", "TD", "SA", "S/A", "ME", "EPP", "SP", "BH", "RJ", "VPN", "SD", "WAN", "NOC", "SLA", "EMS", "ERP", "TV", "CPD"}


def titlecase(s: str | None) -> str | None:
    """Padroniza nomes: so a primeira letra de cada palavra maiuscula (Labadessa Engenharia, Cocal Comercio).
    Mantem siglas conhecidas (TI, S/A...) e palavras com numeros (B2B); de/da/do/das/dos/e ficam minusculas."""
    import re
    if not s or not s.strip():
        return s
    out, first = [], True
    for tok in re.split(r"(\s+|[-/&().,])", s.strip()):
        if not tok or re.fullmatch(r"\s+|[-/&().,]", tok):
            out.append(" " if tok.isspace() else tok)
            continue
        up = tok.upper()
        if any(ch.isdigit() for ch in tok) or up in _ACR:
            w = up
        elif not first and tok.lower() in _SMALL:
            w = tok.lower()
        else:
            w = tok.capitalize()
        out.append(w)
        first = False
    return re.sub(r"\s+", " ", "".join(out))


def like(q: str) -> str:
    """Padrao ILIKE com %/_ do usuario tratados como texto (a busca '%' nao casa com tudo)."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# Origem do evento (tecnologia) e como chamar o "host" em cada uma
KIND_LABEL = {"infra": "Infraestrutura", "backup": "Backup", "endpoint": "Endpoint", "cloud": "Cloud Orca"}
ITEM_LABEL = {"infra": "Host", "backup": "Item de backup", "endpoint": "Endpoint", "cloud": "Máquina"}
