"""Configuracoes editaveis no painel. Valores secretos ficam cifrados no banco;
.env serve de valor inicial (fallback)."""
import threading
import time

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Setting
from .security import decrypt, encrypt

SECRET_KEYS = {"acronis.secret", "acronis2.secret", "ems.api_key", "ems.password", "zabbix.token", "evolution.api_key", "smtp.password", "webhook.token", "llm.api_key", "contaazul.client_secret", "contaazul.access_token", "contaazul.refresh_token", "push.vapid_private"}


def _env_default(key: str) -> str:
    s = get_settings()
    return {
        "zabbix.url": s.ZABBIX_URL, "zabbix.token": s.ZABBIX_API_TOKEN,
        "evolution.url": s.EVOLUTION_API_URL, "evolution.instance": s.EVOLUTION_INSTANCE,
        "evolution.api_key": s.EVOLUTION_API_KEY,
        "smtp.host": s.SMTP_HOST, "smtp.port": str(s.SMTP_PORT), "smtp.user": s.SMTP_USER,
        "smtp.password": s.SMTP_PASSWORD, "smtp.from": s.SMTP_FROM,
        "webhook.token": s.NAVI_WEBHOOK_TOKEN,
        "acronis.url": s.ACRONIS_URL, "acronis.client_id": s.ACRONIS_CLIENT_ID, "acronis.secret": s.ACRONIS_CLIENT_SECRET,
        "ems.host": s.EMS_HOST, "ems.port": str(s.EMS_PORT), "ems.api_key": s.EMS_API_KEY,
        "llm.provider": s.NAVI_LLM_PROVIDER, "llm.api_key": s.NAVI_LLM_API_KEY,
    }.get(key, "")


# Cache em memoria (nenhuma copia extra no banco): uma unica fotografia da tabela por processo, trocada por
# inteira a cada TTL ou assim que este processo grava. Chaves da Conta Azul ficam fora: o refresh token gira e
# o processo errado nao pode ler valor velho.
_TTL = 20
_NOCACHE = ("contaazul.",)
_snap: dict[str, tuple[str | None, bool]] = {}
_snap_at = 0.0
_lock = threading.Lock()


def invalidate():
    global _snap_at
    _snap_at = 0.0


def _row(db: Session, key: str):
    global _snap, _snap_at
    if key.startswith(_NOCACHE) or db.info.get("settings_dirty"):  # gravacao pendente nesta sessao: le direto do banco
        r = db.get(Setting, key)
        return (r.value, r.is_secret) if r is not None else None
    if time.monotonic() - _snap_at > _TTL:
        with _lock:
            if time.monotonic() - _snap_at > _TTL:
                _snap = {k: (v, bool(sec)) for k, v, sec in db.execute(select(Setting.key, Setting.value, Setting.is_secret))}
                _snap_at = time.monotonic()
    return _snap.get(key)


@event.listens_for(Session, "after_commit")
def _drop_cache_after_commit(session):
    if session.info.pop("settings_dirty", False):
        invalidate()


@event.listens_for(Session, "after_rollback")
def _clear_dirty(session):
    session.info.pop("settings_dirty", None)


def get(db: Session, key: str, default: str | None = None) -> str:
    row = _row(db, key)
    if row is not None and row[0] not in (None, ""):
        return decrypt(row[0]) if row[1] else row[0]
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
    db.info["settings_dirty"] = True
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
