"""Monta os servicos a partir das configuracoes (painel > .env)."""
from sqlalchemy.orm import Session

from .. import settings_store as S
from .acronis_service import AcronisService
from .email_service import EmailService
from .ems_service import EmsService
from .wa_akg_service import WaAkgService
from .zabbix_service import ZabbixService


def zabbix(db: Session) -> ZabbixService:
    return ZabbixService(S.get(db, "zabbix.url"), S.get(db, "zabbix.token"))


def whatsapp(db: Session) -> WaAkgService:
    """Gateway de WhatsApp (WA-AKG): alertas, relatorios, avisos de chamado e atendimento."""
    return WaAkgService(S.get(db, "wa_akg.url"), S.get(db, "wa_akg.session"), S.get(db, "wa_akg.api_key"))


def email(db: Session) -> EmailService:
    return EmailService(S.get(db, "smtp.host"), int(S.get(db, "smtp.port", "587") or 587), S.get(db, "smtp.user"),
                        S.get(db, "smtp.password"), S.get(db, "smtp.from"), S.get(db, "smtp.from_name", "NOC Orca TI"))


def acronis(db: Session) -> AcronisService:
    return AcronisService(S.get(db, "acronis.url"), S.get(db, "acronis.client_id"), S.get(db, "acronis.secret"))


def acronis2(db: Session) -> AcronisService:
    """Segundo datacenter do Acronis (ex.: Phoenix/EUA)."""
    return AcronisService(S.get(db, "acronis2.url"), S.get(db, "acronis2.client_id"), S.get(db, "acronis2.secret"))


def acronis_all(db: Session) -> list[tuple[str, AcronisService]]:
    """Todos os datacenters configurados: [("br", svc), ("us", svc)]."""
    out = []
    for dc, svc, on in (("br", acronis(db), True), ("us", acronis2(db), S.get(db, "protection.acronis2_enabled") != "0")):
        if svc.configured and on:
            out.append((dc, svc))
    return out


def acronis_for(db: Session, dc: str | None) -> AcronisService:
    return acronis2(db) if dc == "us" else acronis(db)


def ems(db: Session) -> EmsService:
    return EmsService(S.get(db, "ems.host"), int(S.get(db, "ems.port", "443") or 443), S.get(db, "ems.user"), S.get(db, "ems.password"))
