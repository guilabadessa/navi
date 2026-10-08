"""Dados iniciais idempotentes: usuario admin (senha via env, hash Argon2), templates padrao, rotinas."""
import logging

from sqlalchemy import func, select

from .config import get_settings
from .db import session_scope
from .jobs import JOBS
from .models import JobStatus, MessageTemplate, User
from .security import hash_password
from .services.notification_service import DEFAULT_PROBLEM, DEFAULT_RECOVERY

log = logging.getLogger("navi.seed")


def run():
    st = get_settings()
    with session_scope() as db:
        if not db.scalar(select(func.count()).select_from(User)):
            if not st.NAVI_ADMIN_INITIAL_PASSWORD:
                log.warning("NAVI_ADMIN_INITIAL_PASSWORD vazio: usuário admin NÃO criado")
            else:
                db.add(User(email=st.NAVI_ADMIN_EMAIL.lower(), name="Administrador NAVI", role="ADMIN",
                            password_hash=hash_password(st.NAVI_ADMIN_INITIAL_PASSWORD)))
                log.info("usuário admin criado: %s", st.NAVI_ADMIN_EMAIL)
        if not db.scalar(select(func.count()).select_from(MessageTemplate)):
            db.add(MessageTemplate(name="Alerta padrão Orca TI", kind="problem", body=DEFAULT_PROBLEM, is_default=True))
            db.add(MessageTemplate(name="Recuperação padrão Orca TI", kind="recovery", body=DEFAULT_RECOVERY, is_default=True))
        for name, (label, itv) in JOBS.items():
            if not db.get(JobStatus, name):
                db.add(JobStatus(name=name, label=label, interval_s=itv))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
