"""Silenciar alertas pela tela de Eventos: o evento continua registrado, mas nao gera mensagem (problema, recuperacao,
escalonamento nem resumo diario) enquanto houver um silencio valido para o host e/ou para o problema."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..models import Event, EventSilence, ExtAsset

SCOPES = ("host", "problem_host", "problem")


def now():
    return datetime.now(timezone.utc)


def active(db: Session, at: datetime | None = None) -> list[EventSilence]:
    t = at or now()
    return list(db.scalars(select(EventSilence).where(or_(EventSilence.until.is_(None), EventSilence.until > t)).order_by(EventSilence.id.desc())).all())


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def matches(s, ev) -> bool:
    """Todos os campos preenchidos no silencio precisam bater com o evento."""
    if s.kind and s.kind != (ev.kind or "infra"):
        return False
    if s.host and not _same(s.host, ev.host):
        return False
    if s.triggerid and s.triggerid != (ev.triggerid or ""):
        return False
    if s.trigger_name and not _same(s.trigger_name, ev.trigger_name):
        return False
    return bool(s.host or s.triggerid or s.trigger_name)


def match(db: Session, ev, sils: list | None = None):
    for s in (sils if sils is not None else active(db)):
        if matches(s, ev):
            return s
    return None


def clause(sils: list):
    """Condicao SQL 'o evento esta silenciado' (None se nao ha silencios)."""
    parts = []
    for s in sils:
        c = []
        if s.kind:
            c.append(Event.kind == s.kind)
        if s.host:
            c.append(func.lower(Event.host) == s.host.strip().lower())
        if s.triggerid:
            c.append(Event.triggerid == s.triggerid)
        if s.trigger_name:
            c.append(func.lower(Event.trigger_name) == s.trigger_name.strip().lower())
        if c:
            parts.append(and_(*c))
    return or_(*parts) if parts else None


def key_for(ev, scope: str) -> dict:
    """Campos do silencio para um evento e um escopo. ValueError se o evento nao tem o dado necessario."""
    if scope not in SCOPES:
        raise ValueError("Escopo inválido")
    out: dict = {"scope": scope, "kind": ev.kind or "infra"}
    if scope in ("host", "problem_host"):
        if not ev.host:
            raise ValueError("O evento não tem host")
        out["host"] = ev.host
    if scope in ("problem_host", "problem"):
        if ev.triggerid:
            out["triggerid"] = ev.triggerid
        elif ev.trigger_name:
            out["trigger_name"] = ev.trigger_name
        else:
            raise ValueError("O evento não tem identificação do problema")
    return out


def create(db: Session, ev, scope: str, hours: int | None, reason: str | None, user: str | None) -> EventSilence:
    k = key_for(ev, scope)
    until = now() + timedelta(hours=hours) if hours else None
    dup = next((s for s in active(db) if s.scope == k["scope"] and s.kind == k.get("kind") and _same(s.host, k.get("host")) and (s.triggerid or "") == (k.get("triggerid") or "")
                and _same(s.trigger_name, k.get("trigger_name"))), None)
    s = dup or EventSilence(**k, created_by=user)
    s.until, s.reason = until, (reason or "").strip()[:255] or None
    if dup is None:
        db.add(s)
    # silencio permanente do host de Backup/Endpoints = o mesmo "ignorar" que ja existe nessas telas
    if scope == "host" and until is None and (ev.kind or "") in ("backup", "endpoint") and ev.hostid and s.asset_id is None:
        a = db.scalar(select(ExtAsset).where(ExtAsset.ext_id == ev.hostid, ExtAsset.source == ev.source).limit(1))
        if a is not None and not a.ignored:
            a.ignored, s.asset_id = True, a.id
    db.flush()
    return s


def remove(db: Session, s: EventSilence) -> None:
    if s.asset_id:
        a = db.get(ExtAsset, s.asset_id)
        if a is not None:
            a.ignored = False
    db.delete(s)
