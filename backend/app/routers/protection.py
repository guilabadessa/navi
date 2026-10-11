"""Backup (Acronis) e endpoints (EMS): painel, associacao de tenants a clientes, configuracao e testes."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, settings_store as S
from ..db import get_db
from ..models import INCIDENT_MIN_SEV, Client, Event, ExtAsset, ExtTenant
from ..security import current_user, require
from ..security import RateLimiter, user_has
from ..services import factory, protection_service as P
from ..util import NO_CLIENT, by_client, titlecase, to_dict

router = APIRouter(prefix="/protection", tags=["protection"])


def asset_status(a: ExtAsset, c: dict, now: datetime) -> str:
    if a.ignored:
        return "ignorado"
    # estacao de trabalho desligada fora do expediente e normal: so servidor (24x7) fica "offline"
    if a.online is False and a.offline_since and (now - a.offline_since) > timedelta(minutes=c["offline_min"]) and P.machine_role(a) == "server":
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
        ids = {t.id for t in tenants if (t.client_id is None if client_id == NO_CLIENT else t.client_id == client_id)}
        assets = [a for a in assets if a.ext_tenant_id in ids]
    rows = []
    actions = S.get(db, "acronis.actions") == "1"
    for a in assets:
        t = tmap.get(a.ext_tenant_id)
        st_ = asset_status(a, c, now)
        rows.append({"techs": (a.meta or {}).get("techs") or [], "can_run": bool(actions and a.type == "machine" and (a.meta or {}).get("policy_id") and st_ in ("falha", "sem backup")),
                     "id": a.id, "name": a.name, "type": a.type, "tenant": titlecase(t.name) if t else None, "client_id": t.client_id if t else None,
                     "client": cn.get(t.client_id) if t else None, "policy": a.policy_name,
                     "last_success_at": a.last_success_at.isoformat() if a.last_success_at else None,
                     "last_failure_at": a.last_failure_at.isoformat() if a.last_failure_at else None, "last_result": a.last_result,
                     "online": a.online, "ignored": a.ignored, "role": P.machine_role(a), "status": asset_status(a, c, now)})
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("ok", "falha", "sem backup", "offline", "sem dados", "ignorado")}
    ev_stmt = select(Event).where(Event.kind == "backup", Event.status == "PROBLEM", Event.severity >= INCIDENT_MIN_SEV).order_by(Event.severity.desc(), Event.started_at)
    if client_id:
        ev_stmt = ev_stmt.where(by_client(Event.client_id, client_id))
    alerts = [to_dict(e) | {"client_name": cn.get(e.client_id)} for e in db.scalars(ev_stmt)]
    cnt_assets = {}
    for a in assets:
        cnt_assets[a.ext_tenant_id] = cnt_assets.get(a.ext_tenant_id, 0) + 1
    return {"counts": counts, "assets": rows, "alerts": alerts,
            "tenants": [{"id": t.id, "name": titlecase(t.name), "client_id": t.client_id, "client_name": cn.get(t.client_id), "enabled": t.enabled,
                         "assets": cnt_assets.get(t.id, 0), "ignored": bool((t.info or {}).get("ignored")),
                         "services": [s["label"] for s in ((t.info or {}).get("services") or [])]} for t in tenants],
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


class RoleIn(BaseModel):
    role: str = Field(pattern="^(server|workstation|auto)$")


@router.put("/assets/{aid}/role")
def set_role(aid: int, body: RoleIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    """Servidor (24x7: offline e problema) ou estacao (desligada fora do expediente: offline nao e problema). 'auto' volta a deduzir."""
    a = db.get(ExtAsset, aid)
    if not a:
        raise HTTPException(404)
    m = dict(a.meta or {})
    if body.role == "auto":
        m.pop("role", None)
    else:
        m["role"] = body.role
    a.meta = m
    audit.log(db, request, "protection_asset_role", "ext_asset", aid, detail={"name": a.name, "role": body.role})
    db.commit()
    return {"ok": True, "role": P.machine_role(a)}


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
    acronis2_url: str = ""
    acronis2_client_id: str = ""
    acronis2_secret: str | None = None
    acronis2_enabled: bool = True
    acronis_actions: bool = False  # permite o botao "Executar backup agora" (unica escrita feita no Acronis)


@router.get("/config")
def get_cfg(db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    c = P.cfg(db)
    return {"acronis_url": S.get(db, "acronis.url"), "acronis_client_id": S.get(db, "acronis.client_id"), "acronis_secret_set": bool(S.get(db, "acronis.secret")),
            "acronis2_url": S.get(db, "acronis2.url"), "acronis2_client_id": S.get(db, "acronis2.client_id"), "acronis2_secret_set": bool(S.get(db, "acronis2.secret")),
            "acronis2_enabled": S.get(db, "protection.acronis2_enabled") != "0", "acronis_enabled": c["acronis_enabled"], "acronis_actions": S.get(db, "acronis.actions") == "1", "stale_h": c["stale_h"], "offline_min": c["offline_min"],
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
    S.put(db, "acronis2.url", body.acronis2_url.strip().rstrip("/"), em)
    S.put(db, "acronis2.client_id", body.acronis2_client_id.strip(), em)
    if body.acronis2_secret:
        S.put(db, "acronis2.secret", body.acronis2_secret.strip(), em)
    S.put(db, "protection.acronis2_enabled", "1" if body.acronis2_enabled else "0", em)
    S.put(db, "acronis.actions", "1" if body.acronis_actions else "0", em)
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
        if source == "acronis2":
            return {"ok": True, "detail": factory.acronis2(db).test()}
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
        res = P.sync_acronis(db)
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
        ids = {t.id for t in tenants if (t.client_id is None if client_id == NO_CLIENT else t.client_id == client_id)}
        assets = [a for a in assets if a.ext_tenant_id in ids]
    rows = []
    for a in assets:
        t, m = tmap.get(a.ext_tenant_id), (a.meta or {})
        rows.append({"id": a.id, "name": a.name, "site": t.name if t else None, "client_id": t.client_id if t else None, "client": cn.get(t.client_id) if t else None,
                     "os": m.get("os"), "user": m.get("user"), "ip": m.get("ip"), "fct_version": m.get("fct_version"), "policy": a.policy_name,
                     "online": a.online, "last_contact": a.last_success_at.isoformat() if a.last_success_at else None, "ignored": a.ignored, "role": P.machine_role(a),
                     "av_enabled": m.get("av_enabled"), "sig_ok": m.get("sig_ok"), "health_errors": m.get("health_errors", 0), "events": m.get("events") or {}, "vuln_sev": m.get("vuln_sev"),
                     "status": P.ems_status(a, days, now)})
    counts: dict = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    stmt = select(Event).where(Event.kind == "endpoint", Event.status == "PROBLEM", Event.severity >= INCIDENT_MIN_SEV).order_by(Event.severity.desc(), Event.started_at)
    if client_id:
        stmt = stmt.where(by_client(Event.client_id, client_id))
    return {"counts": counts, "total": len(rows), "online": sum(1 for r in rows if r["online"]), "assets": rows,
            "alerts": [to_dict(e) | {"client_name": cn.get(e.client_id)} for e in db.scalars(stmt)],
            "tenants": [{"id": t.id, "name": t.name, "client_id": t.client_id, "client_name": cn.get(t.client_id), "enabled": True, "ignored": bool((t.info or {}).get("ignored")),
                         "assets": sum(1 for a in assets if a.ext_tenant_id == t.id)} for t in tenants],
            "offline_days": days, "blocked": S.get(db, "ems.auth_blocked") == "1"}


# ---------------- visao por cliente (telas do cliente e portal) ----------------
@router.get("/tenants")
def list_tenants(db: Session = Depends(get_db), _=Depends(require("clients.view"))):
    """Clientes do Acronis e sites do EMS (para associar ao cliente no cadastro)."""
    cn = dict(db.execute(select(Client.id, Client.trade_name)).all())
    n = dict(db.execute(select(ExtAsset.ext_tenant_id, func.count()).where(ExtAsset.active.is_(True)).group_by(ExtAsset.ext_tenant_id)).all())
    return [{"id": t.id, "source": t.source, "dc": (t.info or {}).get("dc", "br") if t.source == "acronis" else None, "name": titlecase(t.name), "client_id": t.client_id, "client_name": cn.get(t.client_id), "assets": n.get(t.id, 0)}
            for t in db.scalars(select(ExtTenant).where(ExtTenant.active.is_(True)).order_by(ExtTenant.source, ExtTenant.name))]


class IgnoreTenantIn(BaseModel):
    ignored: bool


@router.put("/tenants/{tid}/ignore")
def ignore_tenant(tid: int, body: IgnoreTenantIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    """Marca um cliente do Acronis/site do EMS como "nao precisa de cliente" (ex.: site Default vazio): some do aviso de pendencias."""
    t = db.get(ExtTenant, tid)
    if not t:
        raise HTTPException(404)
    t.info = {**(t.info or {}), "ignored": body.ignored}
    audit.log(db, request, "protection_ignore_tenant", "ext_tenant", tid, detail={"tenant": t.name, "ignored": body.ignored})
    db.commit()
    return {"ok": True}


_run_limiter = RateLimiter(1, 600)  # um disparo por item a cada 10 minutos


def do_run_backup(db: Session, request: Request, a: ExtAsset | None, who: str = "") -> dict:
    """Nucleo do botao "Executar backup agora" (usado pelo painel e pelo portal): valida, limita, executa e audita."""
    if S.get(db, "acronis.actions") != "1":
        raise HTTPException(409, "A execução de backups pela NAVI está desativada. Um administrador pode habilitar em Configurações → Acronis.")
    pid = (a.meta or {}).get("policy_id") if a else None
    if not a or a.source != P.SRC or a.type != "machine" or not pid:
        raise HTTPException(422, "Este item não permite execução manual (só máquinas com plano de backup conhecido).")
    key = f"a{a.id}"
    if _run_limiter.blocked(key):
        raise HTTPException(429, "Um backup já foi solicitado para este item há poucos minutos. Aguarde antes de repetir.")
    try:
        res = factory.acronis_for(db, (a.meta or {}).get("dc")).run_policy(pid, a.ext_id)
    except Exception as e:  # noqa: BLE001
        audit.log(db, request, "backup_run", "ext_asset", a.id, result="falha", detail={"item": a.name, "origem": who, "error": str(e)[:200]})
        db.commit()
        raise HTTPException(502, f"O Acronis recusou a execução: {str(e)[:200]}") from None
    _run_limiter.hit(key)
    audit.log(db, request, "backup_run", "ext_asset", a.id, detail={"item": a.name, "plano": a.policy_name, "status": res["status"], "origem": who})
    db.commit()
    return {"ok": True, "detail": f"Backup solicitado ao Acronis para {a.name}. O resultado aparece aqui na próxima sincronização."}


@router.post("/assets/{aid}/run-backup")
def run_backup(aid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("protection.run"))):
    """Executa o plano de backup do item agora (Acronis). Exige habilitar a acao em Configuracoes e permissao protection.run."""
    return do_run_backup(db, request, db.get(ExtAsset, aid), "painel")


@router.get("/client/{cid}")
def client_view(cid: int, db: Session = Depends(get_db), _=Depends(require("clients.view"))):
    """Tudo de Acronis/EMS de UM cliente: servicos contratados, backup, endpoints e alertas (tela do cliente)."""
    return client_protection(db, cid, admin=True)


def client_protection(db: Session, cid: int, admin: bool = False) -> dict:
    now, c = datetime.now(timezone.utc), P.cfg(db)
    tens = list(db.scalars(select(ExtTenant).where(ExtTenant.client_id == cid, ExtTenant.active.is_(True))))
    ac_ids = [t.id for t in tens if t.source == P.SRC]
    names = {"machine": "Máquina", "database": "Banco de dados", "mailbox": "Caixa de e-mail", "drive": "OneDrive", "site": "SharePoint", "team": "Teams"}
    actions = S.get(db, "acronis.actions") == "1"
    backups = []
    if ac_ids:
        for a in db.scalars(select(ExtAsset).where(ExtAsset.ext_tenant_id.in_(ac_ids), ExtAsset.active.is_(True), ExtAsset.ignored.is_(False)).order_by(ExtAsset.name)):
            st = asset_status(a, c, now)
            backups.append({"id": a.id, "name": a.name, "type": a.type, "type_label": names.get(a.type, a.type), "status": st, "policy": a.policy_name,
                            "last_success_at": a.last_success_at.isoformat() if a.last_success_at else None,
                            "last_failure_at": a.last_failure_at.isoformat() if a.last_failure_at else None, "online": a.online,
                            "techs": (a.meta or {}).get("techs") or [],
                            "can_run": bool(actions and a.type == "machine" and (a.meta or {}).get("policy_id") and st in ("falha", "sem backup"))})
    services = []
    for t in tens:
        if t.source == P.SRC:
            services += [{**s, "tenant": titlecase(t.name)} for s in ((t.info or {}).get("services") or [])]
    eps = [{**r, "last": r["last"].isoformat() if r["last"] else None} for r in P.endpoint_rows(db, cid)]
    return {"backups": backups, "endpoints": eps, "services": services, "actions": actions,
            "tenants": [{"id": t.id, "source": t.source, "name": titlecase(t.name)} for t in tens]}
