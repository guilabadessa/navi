"""Backup (Acronis) e endpoints (EMS): painel, associacao de tenants a clientes, configuracao e testes."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, settings_store as S
from ..db import get_db
from ..models import Client, Event, ExtAsset, ExtTenant
from ..security import require
from ..services import factory, protection_service as P
from ..util import titlecase, to_dict

router = APIRouter(prefix="/protection", tags=["protection"])


def asset_status(a: ExtAsset, c: dict, now: datetime) -> str:
    if a.ignored:
        return "ignorado"
    if a.online is False and a.offline_since and (now - a.offline_since) > timedelta(minutes=c["offline_min"]):
        return "offline"
    if a.last_success_at and (now - a.last_success_at) > timedelta(hours=c["stale_h"]):
        return "sem backup"
    if a.last_failure_at and (not a.last_success_at or a.last_failure_at > a.last_success_at):
        return "falha"
    if a.last_success_at:
        return "ok"
    return "sem dados"


@router.get("/overview")
def overview(client_id: int | None = None, db: Session = Depends(get_db), _=Depends(require("monitoring.view"))):
    now = datetime.now(timezone.utc)
    c = P.cfg(db)
    cn = dict(db.execute(select(Client.id, Client.trade_name)).all())
    tenants = list(db.scalars(select(ExtTenant).where(ExtTenant.source == P.SRC, ExtTenant.active.is_(True)).order_by(ExtTenant.name)))
    tmap = {t.id: t for t in tenants}
    assets = list(db.scalars(select(ExtAsset).where(ExtAsset.source == P.SRC, ExtAsset.active.is_(True)).order_by(ExtAsset.name)))
    if client_id:
        ids = {t.id for t in tenants if t.client_id == client_id}
        assets = [a for a in assets if a.ext_tenant_id in ids]
    rows = []
    for a in assets:
        t = tmap.get(a.ext_tenant_id)
        rows.append({"id": a.id, "name": a.name, "type": a.type, "tenant": titlecase(t.name) if t else None, "client_id": t.client_id if t else None,
                     "client": cn.get(t.client_id) if t else None, "policy": a.policy_name,
                     "last_success_at": a.last_success_at.isoformat() if a.last_success_at else None,
                     "last_failure_at": a.last_failure_at.isoformat() if a.last_failure_at else None, "last_result": a.last_result,
                     "online": a.online, "ignored": a.ignored, "status": asset_status(a, c, now)})
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("ok", "falha", "sem backup", "offline", "sem dados", "ignorado")}
    ev_stmt = select(Event).where(Event.kind == "backup", Event.status == "PROBLEM").order_by(Event.severity.desc(), Event.started_at)
    if client_id:
        ev_stmt = ev_stmt.where(Event.client_id == client_id)
    alerts = [to_dict(e) | {"client_name": cn.get(e.client_id)} for e in db.scalars(ev_stmt)]
    cnt_assets = {}
    for a in assets:
        cnt_assets[a.ext_tenant_id] = cnt_assets.get(a.ext_tenant_id, 0) + 1
    return {"counts": counts, "assets": rows, "alerts": alerts,
            "tenants": [{"id": t.id, "name": titlecase(t.name), "client_id": t.client_id, "client_name": cn.get(t.client_id), "enabled": t.enabled,
                         "assets": cnt_assets.get(t.id, 0)} for t in tenants],
            "thresholds": c, "failed_24h": db.scalar(select(func.count()).select_from(ExtAsset).where(
                ExtAsset.source == P.SRC, ExtAsset.last_failure_at >= now - timedelta(hours=24))) or 0}


class MapIn(BaseModel):
    client_id: int | None = None


@router.put("/tenants/{tid}")
def map_tenant(tid: int, body: MapIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    t = db.get(ExtTenant, tid)
    if not t:
        raise HTTPException(404)
    if body.client_id is not None and not db.get(Client, body.client_id):
        raise HTTPException(422, "Cliente inválido")
    t.client_id = body.client_id
    audit.log(db, request, "protection_map_tenant", "ext_tenant", tid, detail={"tenant": t.name, "client_id": body.client_id})
    db.commit()
    return {"ok": True, "events_relinked": P.relink(db)}


class IgnoreIn(BaseModel):
    ignored: bool


@router.put("/assets/{aid}")
def ignore_asset(aid: int, body: IgnoreIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    a = db.get(ExtAsset, aid)
    if not a:
        raise HTTPException(404)
    a.ignored = body.ignored
    audit.log(db, request, "protection_ignore_asset", "ext_asset", aid, detail={"name": a.name, "ignored": body.ignored})
    db.commit()
    return {"ok": True}


class CfgIn(BaseModel):
    acronis_url: str = ""
    acronis_client_id: str = ""
    acronis_secret: str | None = None  # vazio = manter
    acronis_enabled: bool = True
    stale_h: int = 72
    offline_min: int = 240
    ems_host: str = ""
    ems_port: int = 443
    ems_offline_days: int = 7
    ems_user: str = ""
    ems_password: str | None = None
    ems_enabled: bool = False


@router.get("/config")
def get_cfg(db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    c = P.cfg(db)
    return {"acronis_url": S.get(db, "acronis.url"), "acronis_client_id": S.get(db, "acronis.client_id"), "acronis_secret_set": bool(S.get(db, "acronis.secret")),
            "acronis_enabled": c["acronis_enabled"], "stale_h": c["stale_h"], "offline_min": c["offline_min"],
            "ems_host": S.get(db, "ems.host"), "ems_port": int(S.get(db, "ems.port") or 443), "ems_offline_days": c["ems_offline_days"],
            "ems_blocked": S.get(db, "ems.auth_blocked") == "1",
            "ems_enabled": S.get(db, "ems.enabled") == "1", "ems_user": S.get(db, "ems.user"), "ems_password_set": bool(S.get(db, "ems.password"))}


@router.put("/config")
def put_cfg(body: CfgIn, request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    if not (1 <= body.stale_h <= 24 * 30) or not (5 <= body.offline_min <= 60 * 24 * 7):
        raise HTTPException(422, "Limites inválidos")
    em = me.email
    S.put(db, "acronis.url", body.acronis_url.strip().rstrip("/"), em)
    S.put(db, "acronis.client_id", body.acronis_client_id.strip(), em)
    if body.acronis_secret:
        S.put(db, "acronis.secret", body.acronis_secret.strip(), em)
    S.put(db, "protection.acronis_enabled", "1" if body.acronis_enabled else "0", em)
    S.put(db, "protection.stale_h", str(body.stale_h), em)
    S.put(db, "protection.offline_min", str(body.offline_min), em)
    S.put(db, "ems.host", body.ems_host.strip(), em)
    S.put(db, "ems.port", str(body.ems_port), em)
    S.put(db, "protection.ems_offline_days", str(max(1, min(body.ems_offline_days, 365))), em)
    S.put(db, "ems.user", body.ems_user.strip(), em)
    if body.ems_password:
        S.put(db, "ems.password", body.ems_password, em)
        S.put(db, "ems.auth_blocked", "0", em)  # credenciais novas: libera uma nova tentativa de login
    S.put(db, "ems.enabled", "1" if body.ems_enabled else "0", em)
    audit.log(db, request, "protection_config", detail={"acronis": body.acronis_enabled, "ems": body.ems_enabled})
    db.commit()
    return {"ok": True}


@router.post("/test/{source}")
def test(source: str, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    try:
        if source == "acronis":
            return {"ok": True, "detail": factory.acronis(db).test()}
        if source == "ems":
            r = factory.ems(db).test()
            S.put(db, "ems.auth_blocked", "0")
            db.commit()
            return {"ok": True, "detail": r}
    except Exception as e:  # noqa: BLE001
        from ..services.ems_service import EmsAuthError
        if isinstance(e, EmsAuthError):
            S.put(db, "ems.auth_blocked", "1")  # nao insiste com senha recusada (evita bloquear o usuario no EMS)
            db.commit()
        return {"ok": False, "detail": str(e)[:300]}
    raise HTTPException(404)


@router.post("/sync/acronis")
def sync_now(request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    try:
        res = P.sync_acronis(db, factory.acronis(db))
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(502, f"Falha na sincronização: {str(e)[:300]}") from None
    audit.log(db, request, "protection_sync", detail=res)
    db.commit()
    return res


@router.post("/sync/ems")
def sync_ems_now(request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    if S.get(db, "ems.auth_blocked") == "1":
        raise HTTPException(409, "O EMS recusou o login anteriormente. Corrija usuário/senha em Configuração (e salve) para tentar de novo.")
    try:
        res = P.sync_ems(db, factory.ems(db))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Falha na sincronização: {str(e)[:300]}") from None
    audit.log(db, request, "protection_sync_ems", detail=res)
    db.commit()
    return res


@router.get("/ems")
def ems_overview(client_id: int | None = None, db: Session = Depends(get_db), _=Depends(require("monitoring.view"))):
    now = datetime.now(timezone.utc)
    days = P.cfg(db)["ems_offline_days"]
    cn = dict(db.execute(select(Client.id, Client.trade_name)).all())
    tenants = list(db.scalars(select(ExtTenant).where(ExtTenant.source == P.EMS, ExtTenant.active.is_(True)).order_by(ExtTenant.name)))
    tmap = {t.id: t for t in tenants}
    assets = list(db.scalars(select(ExtAsset).where(ExtAsset.source == P.EMS, ExtAsset.active.is_(True)).order_by(ExtAsset.name)))
    if client_id:
        ids = {t.id for t in tenants if t.client_id == client_id}
        assets = [a for a in assets if a.ext_tenant_id in ids]
    rows = []
    for a in assets:
        t, m = tmap.get(a.ext_tenant_id), (a.meta or {})
        rows.append({"id": a.id, "name": a.name, "site": t.name if t else None, "client_id": t.client_id if t else None, "client": cn.get(t.client_id) if t else None,
                     "os": m.get("os"), "user": m.get("user"), "ip": m.get("ip"), "fct_version": m.get("fct_version"), "policy": a.policy_name,
                     "online": a.online, "last_contact": a.last_success_at.isoformat() if a.last_success_at else None, "ignored": a.ignored,
                     "av_enabled": m.get("av_enabled"), "sig_ok": m.get("sig_ok"), "health_errors": m.get("health_errors", 0),
                     "status": P.ems_status(a, days, now)})
    counts: dict = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    stmt = select(Event).where(Event.kind == "endpoint", Event.status == "PROBLEM").order_by(Event.severity.desc(), Event.started_at)
    if client_id:
        stmt = stmt.where(Event.client_id == client_id)
    return {"counts": counts, "total": len(rows), "online": sum(1 for r in rows if r["online"]), "assets": rows,
            "alerts": [to_dict(e) | {"client_name": cn.get(e.client_id)} for e in db.scalars(stmt)],
            "tenants": [{"id": t.id, "name": t.name, "client_id": t.client_id, "client_name": cn.get(t.client_id), "enabled": True,
                         "assets": sum(1 for a in assets if a.ext_tenant_id == t.id)} for t in tenants],
            "offline_days": days, "blocked": S.get(db, "ems.auth_blocked") == "1"}
