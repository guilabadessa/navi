"""Monta os servicos a partir das configuracoes (painel > .env)."""
from sqlalchemy.orm import Session

from .. import settings_store as S
from .acronis_service import AcronisService
from .email_service import EmailService
from .ems_service import EmsService
from .evolution_service import EvolutionService
from .zabbix_service import ZabbixService


def zabbix(db: Session) -> ZabbixService:
    return ZabbixService(S.get(db, "zabbix.url"), S.get(db, "zabbix.token"))


def evolution(db: Session) -> EvolutionService:
    return EvolutionService(S.get(db, "evolution.url"), S.get(db, "evolution.instance"), S.get(db, "evolution.api_key"))


def email(db: Session) -> EmailService:
    return EmailService(S.get(db, "smtp.host"), int(S.get(db, "smtp.port", "587") or 587), S.get(db, "smtp.user"),
                        S.get(db, "smtp.password"), S.get(db, "smtp.from"), S.get(db, "smtp.from_name", "NOC Orca TI"))


def acronis(db: Session) -> AcronisService:
    return AcronisService(S.get(db, "acronis.url"), S.get(db, "acronis.client_id"), S.get(db, "acronis.secret"))


def ems(db: Session) -> EmsService:
    return EmsService(S.get(db, "ems.host"), int(S.get(db, "ems.port", "443") or 443), S.get(db, "ems.user"), S.get(db, "ems.password"))
