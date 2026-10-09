"""Registro das comunicacoes (WhatsApp/e-mail) que nao sao alertas e dos destinos usados.
Grava em sessao propria: a falha fica registrada mesmo que a transacao de quem chamou seja desfeita. Nunca levanta erro."""
import logging

from ..db import SessionLocal
from ..models import CommLog

log = logging.getLogger(__name__)


def record(channel: str, kind: str, dest, status: str, error: str | None = None, subject: str | None = None, client_id: int | None = None):
    try:
        if isinstance(dest, (list, tuple)):
            dest = ", ".join(dest)
        with SessionLocal() as db:
            db.add(CommLog(channel=channel, kind=kind[:48], dest=(dest or None), subject=(subject or None) and subject[:300], status=status,
                           error=(error or None) and str(error)[:1000], client_id=client_id))
            db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("nao foi possivel registrar comunicacao: %s", e)
