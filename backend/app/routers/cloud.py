"""Cloud Orca (BRASCLOUD): vinculo da conta do cliente, consulta das maquinas e ligar/desligar/reiniciar (painel e portal)."""
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Client, CloudAccount, CloudVm, User
from ..security import RateLimiter, current_user, encrypt, require, user_has
from ..services import cloud_service as CS
from .portal import _client_for, require_any_portal

router = APIRouter(tags=["cloud"])
_power_limiter = RateLimiter(1, 45)  # uma acao por maquina a cada 45 s (evita cliques repetidos)
_cache: dict[int, tuple[float, dict]] = {}


def _acc(db: Session, cid: int, must: bool = True) -> CloudAccount | None:
    a = db.scalar(select(CloudAccount).where(CloudAccount.client_id == cid))
    if must and (not a or not a.enabled):
        raise HTTPException(404, "Este cliente não tem a Cloud Orca vinculada.")
    return a


def _overview(db: Session, acc: CloudAccount, fresh: bool = False) -> dict:
    hit = _cache.get(acc.id)
    if hit and not fresh and time.time() - hit[0] < 15:
        return hit[1]
    try:
        cl = CS.Cloud.for_account(db, acc)
        data = {"instances": cl.instances(), "quotas": cl.quotas()}
        acc.last_ok, acc.last_error = datetime.now(timezone.utc), None
    except CS.CloudError as e:
        acc.last_error = str(e)[:500]
        db.commit()
        raise HTTPException(502, str(e)) from None
    db.commit()
    for v in data["instances"]:
        rb = CS.reboot_state(v["uuid"])
        if rb:
            v["reboot"] = rb
    _cache[acc.id] = (time.time(), data)
    return data


def _info(a: CloudAccount | None) -> dict:
    return {"linked": bool(a), "enabled": bool(a and a.enabled), "label": a.label if a else None, "owner": a.owner if a else None,
            "last_ok": a.last_ok.isoformat() if a and a.last_ok else None, "last_error": a.last_error if a else None}


# ---------------- painel (equipe) ----------------
class CloudIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=300)
    secret_key: str | None = Field(default=None, max_length=300)
    enabled: bool = True
    label: str | None = Field(default=None, max_length=255)


@router.get("/cloud/clients/{cid}")
def get_cfg(cid: int, db: Session = Depends(get_db), _=Depends(require("clients.view"))):
    return _info(_acc(db, cid, must=False))


@router.put("/cloud/clients/{cid}")
def put_cfg(cid: int, body: CloudIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    if not db.get(Client, cid):
        raise HTTPException(404)
    a = _acc(db, cid, must=False)
    if (body.api_key or body.secret_key) and not (body.api_key and body.secret_key):
        raise HTTPException(422, "Informe a chave de API e o segredo juntos.")
    if not a and not body.api_key:
        raise HTTPException(422, "Informe a chave de API e o segredo.")
    if body.api_key:  # chave nova: so grava se a nuvem aceitar
        try:
            cl = CS.Cloud(CS.base_url(db), body.api_key.strip(), body.secret_key.strip())
            vms = cl.instances()
        except CS.CloudError as e:
            raise HTTPException(422, str(e)) from None
        if not a:
            a = CloudAccount(client_id=cid, api_key="", secret_key="")
            db.add(a)
        a.api_key, a.secret_key = encrypt(body.api_key.strip()), encrypt(body.secret_key.strip())
        a.owner = next((v["owner"] for v in vms if v.get("owner")), a.owner)
        a.last_ok, a.last_error = datetime.now(timezone.utc), None
    a.enabled, a.label = body.enabled, (body.label or None)
    _cache.pop(a.id or 0, None)
    audit.log(db, request, "cloud_link", "client", cid, detail={"chave_trocada": bool(body.api_key), "enabled": body.enabled})
    db.commit()
    return _info(a)


@router.delete("/cloud/clients/{cid}")
def del_cfg(cid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    a = _acc(db, cid, must=False)
    if a:
        db.delete(a)
        audit.log(db, request, "cloud_unlink", "client", cid)
        db.commit()
    return {"ok": True}


@router.get("/cloud/clients/{cid}/overview")
def overview(cid: int, fresh: bool = False, db: Session = Depends(get_db), user=Depends(require("clients.view"))):
    return {**_overview(db, _acc(db, cid), fresh), "can_run": user_has(user, "cloud.run"), "staff": True}


class PowerIn(BaseModel):
    action: str = Field(pattern="^(start|stop|reboot|force-stop)$")


def _do_power(db: Session, request: Request, acc: CloudAccount, uuid: str, action: str, who: str, bg: BackgroundTasks):
    cl = CS.Cloud.for_account(db, acc)
    try:
        vms = {v["uuid"]: v for v in cl.instances()}  # a maquina precisa pertencer a conta deste cliente
    except CS.CloudError as e:
        raise HTTPException(502, str(e)) from None
    vm = vms.get(uuid)
    if not vm:
        raise HTTPException(404, "Máquina não encontrada na conta deste cliente.")
    if _power_limiter.blocked(uuid):
        raise HTTPException(429, "Já houve uma ação nesta máquina há instantes. Aguarde alguns segundos.")
    st = vm["state"]
    if action == "start" and st == "RUNNING":
        raise HTTPException(409, "A máquina já está ligada.")
    if action in ("stop", "force-stop") and st in ("STOPPED", "SHUTOFF"):
        raise HTTPException(409, "A máquina já está desligada.")
    if action == "reboot" and st != "RUNNING":
        raise HTTPException(409, "Só é possível reiniciar uma máquina ligada.")
    _power_limiter.hit(uuid)
    row = db.scalar(select(CloudVm).where(CloudVm.uuid == uuid))
    if row:  # desligada/reiniciada pela NAVI: nao e incidente
        if action in ("stop", "force-stop"):
            row.expected_off = True
        elif action == "start":
            row.expected_off = False
        else:
            row.expected_off, row.grace_until = False, datetime.now(timezone.utc) + timedelta(minutes=10)
    try:
        if action == "reboot":
            bg.add_task(CS.reboot, cl, uuid)
        else:
            cl.power(action, uuid)
    except CS.CloudError as e:
        audit.log(db, request, "cloud_power", "cloud_vm", uuid, result="falha", detail={"vm": vm["name"], "acao": action, "origem": who, "erro": str(e)[:200]})
        db.commit()
        raise HTTPException(502, str(e)) from None
    _cache.pop(acc.id, None)
    audit.log(db, request, "cloud_power", "cloud_vm", uuid, detail={"vm": vm["name"], "acao": action, "origem": who})
    db.commit()
    label = {"start": "ligar", "stop": "desligar", "force-stop": "desligar (forçado)", "reboot": "reiniciar"}[action]
    return {"ok": True, "detail": f"Pedido de {label} enviado para {vm['name']}. O estado atualiza em instantes."}


@router.post("/cloud/clients/{cid}/instances/{uuid}/power")
def power(cid: int, uuid: str, body: PowerIn, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db), user=Depends(require("cloud.run"))):
    if user.role == "CLIENTE":  # o cliente usa somente as rotas do portal (restritas ao proprio cliente)
        raise HTTPException(403, "Sem permissão")
    return _do_power(db, request, _acc(db, cid), uuid, body.action, f"painel:{user.email}", bg)


# ---------------- portal do cliente ----------------
@router.get("/portal/cloud")
def portal_overview(client_id: int | None = None, fresh: bool = False, db: Session = Depends(get_db), user: User = Depends(require_any_portal)):
    c = _client_for(db, user, client_id)
    return {**_overview(db, _acc(db, c.id), fresh), "can_run": user_has(user, "cloud.run"), "staff": user.role != "CLIENTE"}


@router.post("/portal/cloud/{uuid}/power")
def portal_power(uuid: str, body: PowerIn, request: Request, bg: BackgroundTasks, client_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(require("cloud.run"))):
    c = _client_for(db, user, client_id)
    if body.action == "force-stop" and user.role == "CLIENTE":
        raise HTTPException(403, "Desligamento forçado só pela equipe da Orca.")
    return _do_power(db, request, _acc(db, c.id), uuid, body.action, f"portal:{user.email}", bg)


# ---------------- visao global (monitoramento) ----------------
@router.get("/cloud/vms")
def all_vms(db: Session = Depends(get_db), user=Depends(require("monitoring.view"))):
    """Todas as maquinas da Cloud Orca de todos os clientes (copia do worker, atualizada a cada 2 min)."""
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    accs = {a.client_id: a for a in db.scalars(select(CloudAccount))}
    rows = [{"uuid": v.uuid, "client_id": v.client_id, "client": names.get(v.client_id), "name": v.name, "state": v.state, "zone": v.zone, "cpu": v.cpu, "ram_mb": v.ram_mb, "disk_gb": v.disk_gb,
             "ip": v.ip, "os": v.os, "since": v.state_since.isoformat() if v.state_since else None, "expected_off": v.expected_off, "ignored": v.ignored}
            for v in db.scalars(select(CloudVm).where(CloudVm.active.is_(True)).order_by(CloudVm.client_id, CloudVm.name))]
    return {"vms": rows, "can_run": user_has(user, "cloud.run"),
            "accounts": [{"client_id": cid, "client": names.get(cid), "enabled": a.enabled, "owner": a.owner, "last_ok": a.last_ok.isoformat() if a.last_ok else None, "last_error": a.last_error, "fails": a.fails}
                         for cid, a in accs.items()]}


class IgnoreIn(BaseModel):
    ignored: bool


@router.put("/cloud/vms/{uuid}/ignore")
def ignore_vm(uuid: str, body: IgnoreIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    v = db.scalar(select(CloudVm).where(CloudVm.uuid == uuid))
    if not v:
        raise HTTPException(404)
    v.ignored = body.ignored
    audit.log(db, request, "cloud_vm_ignore", "cloud_vm", uuid, detail={"vm": v.name, "ignored": body.ignored})
    db.commit()
    return {"ok": True}
