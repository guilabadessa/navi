"""Servicos contratados por cliente, deduzidos do que esta ligado a ele: infraestrutura (hosts/grupos do Zabbix),
backup (tenant Acronis) e estacoes (site FortiClient EMS). Um cliente pode ter qualquer combinacao."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Client, CloudAccount, ExtTenant

MODULES = ("infra", "backup", "endpoint", "cloud")
NAMES = {"infra": "Infraestrutura", "backup": "Backup", "endpoint": "Endpoints", "cloud": "Cloud Orca"}
_SRC = {"acronis": "backup", "ems": "endpoint"}


def of_clients(db: Session, clients: list[Client]) -> dict[int, dict]:
    """{client_id: {"infra": bool, "backup": bool, "endpoint": bool}} com uma unica consulta aos tenants."""
    from . import protection_service as P
    linked: dict[int, set] = {}
    for t in db.scalars(select(ExtTenant).where(ExtTenant.client_id.is_not(None), ExtTenant.active.is_(True))):
        linked.setdefault(t.client_id, set()).add(_SRC.get(t.source))
        if t.source == "acronis" and any(P.license_flags(t)[k] for k in ("security", "management", "dlp")):
            linked[t.client_id].add("endpoint")  # Acronis com EDR/antimalware, RMM ou DLP tambem e endpoint
    cloud = set(db.scalars(select(CloudAccount.client_id).where(CloudAccount.enabled.is_(True))))
    return {c.id: {"infra": bool(c.hosts or c.groups), "backup": "backup" in linked.get(c.id, ()), "endpoint": "endpoint" in linked.get(c.id, ()), "cloud": c.id in cloud}
            for c in clients}


def of_client(db: Session, c: Client) -> dict:
    return of_clients(db, [c])[c.id]


def active_list(svc: dict) -> list[str]:
    return [m for m in MODULES if svc.get(m)]


def protection_counts(db: Session) -> dict[int, dict]:
    """Por cliente: itens de backup/estacoes monitorados e quantos estao com problema (mesmos criterios das telas de protecao)."""
    from datetime import datetime, timezone

    from ..models import ExtAsset
    from ..routers.protection import asset_status
    from . import protection_service as P
    now, pc = datetime.now(timezone.utc), P.cfg(db)
    tens = {t.id: t for t in db.scalars(select(ExtTenant).where(ExtTenant.client_id.is_not(None)))}
    out: dict[int, dict] = {}
    for a in db.scalars(select(ExtAsset).where(ExtAsset.active.is_(True), ExtAsset.ignored.is_(False), ExtAsset.ext_tenant_id.in_(list(tens) or [0]))):
        r = out.setdefault(tens[a.ext_tenant_id].client_id, {"backup_items": 0, "backup_bad": 0, "endpoint_items": 0, "endpoint_bad": 0})
        if a.source == "acronis":
            r["backup_items"] += 1
            r["backup_bad"] += asset_status(a, pc, now) in ("falha", "sem backup", "offline")
        else:
            r["endpoint_items"] += 1
            r["endpoint_bad"] += P.ems_status(a, pc["ems_offline_days"], now) in ("sem contato", "antivírus off", "assinaturas", "quarentena", "atenção")
    return out
