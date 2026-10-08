"""Reclassificacao local de severidade (sem alterar nada no Zabbix)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Event, SeverityRule
from .notification_service import _match


def rules(db: Session) -> list[SeverityRule]:
    return list(db.scalars(select(SeverityRule).where(SeverityRule.enabled.is_(True)).order_by(SeverityRule.id)))


def effective(rs: list[SeverityRule], host: str | None, trigger: str | None, sev: int) -> int:
    """Aplica a primeira regra que combina; nunca rebaixa a severidade."""
    for r in rs:
        if sev <= (r.from_max or 0) and _match(r.host_pattern, host) and _match(r.trigger_pattern, trigger) and (r.host_pattern or r.trigger_pattern):
            return max(sev, r.severity)
    return sev


def reapply(db: Session) -> int:
    """Reclassifica eventos ja gravados que ainda estao abaixo do alvo. Retorna quantos mudaram."""
    rs = rules(db)
    n = 0
    for ev in db.scalars(select(Event)):
        new = effective(rs, ev.host, ev.trigger_name, ev.severity or 0)
        if new != ev.severity:
            ev.severity, n = new, n + 1
    db.commit()
    return n
