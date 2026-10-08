"""Configuracoes editaveis no painel. Valores secretos ficam cifrados no banco;
.env serve de valor inicial (fallback)."""
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Setting
from .security import decrypt, encrypt

SECRET_KEYS = {"zabbix.token", "evolution.api_key", "smtp.password", "webhook.token", "llm.api_key"}


def _env_default(key: str) -> str:
    s = get_settings()
    return {
        "zabbix.url": s.ZABBIX_URL, "zabbix.token": s.ZABBIX_API_TOKEN,
        "evolution.url": s.EVOLUTION_API_URL, "evolution.instance": s.EVOLUTION_INSTANCE,
        "evolution.api_key": s.EVOLUTION_API_KEY,
        "smtp.host": s.SMTP_HOST, "smtp.port": str(s.SMTP_PORT), "smtp.user": s.SMTP_USER,
        "smtp.password": s.SMTP_PASSWORD, "smtp.from": s.SMTP_FROM,
        "webhook.token": s.NAVI_WEBHOOK_TOKEN,
        "llm.provider": s.NAVI_LLM_PROVIDER, "llm.api_key": s.NAVI_LLM_API_KEY,
    }.get(key, "")


def get(db: Session, key: str, default: str | None = None) -> str:
    row = db.get(Setting, key)
    if row is not None and row.value not in (None, ""):
        return decrypt(row.value) if row.is_secret else row.value
    d = _env_default(key)
    return d if d != "" else (default or "")


def put(db: Session, key: str, value: str, user: str | None = None):
    row = db.get(Setting, key)
    secret = key in SECRET_KEYS
    stored = encrypt(value) if (secret and value) else value
    if row is None:
        db.add(Setting(key=key, value=stored, is_secret=secret, updated_by=user))
    else:
        row.value, row.is_secret, row.updated_by = stored, secret, user
    db.flush()


def get_many(db: Session, prefix: str, keys: list[str], mask_secrets=True) -> dict:
    out = {}
    for k in keys:
        full = f"{prefix}.{k}"
        v = get(db, full)
        if mask_secrets and full in SECRET_KEYS:
            out[k] = {"set": bool(v)}
        else:
            out[k] = v
    return out
