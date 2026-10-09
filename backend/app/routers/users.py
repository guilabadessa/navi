from datetime import datetime, timezone
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..models import Client, User
from ..schemas import UserIn
from ..security import EXTRA_PERMS, hash_password, make_invite_token, require, user_has
from ..services import mailer
from ..util import titlecase, to_dict

router = APIRouter(prefix="/users", tags=["users"])
ROLE_NAMES = {"ADMIN": "Administrador", "GESTOR": "Gestor", "ANALISTA_NOC": "Analista NOC", "VISUALIZADOR": "Visualizador",
              "CLIENTE": "Cliente (portal)"}
EX = {"password_hash"}


def invite_link(u: User) -> str:
    return get_settings().NAVI_PUBLIC_URL.rstrip("/") + "/convite/" + make_invite_token(u)


def send_invite(db: Session, u: User, reset: bool = False) -> str:
    """Envia o link de definicao de senha. Falha de e-mail nao desfaz a criacao. O link nunca e registrado em log."""
    client = db.get(Client, u.client_id) if u.client_id else None
    try:
        subject = "Redefinição de acesso à NAVI" if reset else ("Convite para o portal NAVI" if client else "Convite de acesso à NAVI — Orca TI")
        mailer.send(db, "invite", u.email, subject,
                    mailer.invite_ctx(u.name, ROLE_NAMES.get(u.role, u.role), invite_link(u), reset, client.trade_name if client else None))
        return f"enviado para {u.email}"
    except Exception as e:  # noqa: BLE001
        return f"erro: {str(e)[:200]}"


def _extras(body: UserIn, me: User, current: list | None = None) -> list[str]:
    """Permissoes extras validas para o perfil. Quem nao pode ver o financeiro nao concede nem retira acesso a ele."""
    want = [p for p in dict.fromkeys(body.extra_perms) if p in EXTRA_PERMS and ((p == "portal.finance") == (body.role == "CLIENTE"))]
    fin = {"portal.finance", "finance.view"}
    if not user_has(me, "finance.view"):
        want = [p for p in want if p not in fin] + [p for p in (current or []) if p in fin and p not in want and ((p == "portal.finance") == (body.role == "CLIENTE"))]
    return want


def _check(db: Session, body: UserIn) -> int | None:
    if body.role == "CLIENTE":
        if not body.client_id or not db.get(Client, body.client_id):
            raise HTTPException(422, "Selecione o cliente que este usuário poderá acompanhar")
        return body.client_id
    return None


@router.get("")
def list_users(db: Session = Depends(get_db), _=Depends(require("users.manage"))):
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    return [{**to_dict(u, EX), "client_name": names.get(u.client_id)} for u in db.scalars(select(User).order_by(User.name))]


@router.post("")
def create_user(body: UserIn, request: Request, db: Session = Depends(get_db), me=Depends(require("users.manage"))):
    body.name = titlecase(body.name)
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "E-mail já cadastrado")
    cid = _check(db, body)
    # senha aleatoria inutilizavel: o acesso so existe depois que a pessoa define a propria senha pelo convite
    u = User(email=body.email.lower(), name=body.name, role=body.role, active=body.active, client_id=cid,
             password_hash=hash_password(secrets.token_urlsafe(48)), must_change_password=False,
             invite_pending=True, invited_at=datetime.now(timezone.utc), extra_perms=_extras(body, me))
    db.add(u)
    db.flush()
    audit.log(db, request, "user_invite", "user", u.id, detail={"email": u.email, "role": u.role, "client_id": cid})
    db.commit()
    return {**to_dict(u, EX), "email_status": send_invite(db, u)}


@router.put("/{uid}")
def update_user(uid: int, body: UserIn, request: Request, db: Session = Depends(get_db), me=Depends(require("users.manage"))):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    if u.id == me.id and (not body.active or body.role != "ADMIN"):
        raise HTTPException(400, "Você não pode remover seu próprio acesso de administrador")
    u.client_id = _check(db, body)
    body.name = titlecase(body.name)
    u.name, u.role, u.active = body.name, body.role, body.active
    u.extra_perms = _extras(body, me, u.extra_perms)
    audit.log(db, request, "user_update", "user", u.id, detail={"role": u.role, "active": u.active, "client_id": u.client_id, "extra_perms": u.extra_perms})
    db.commit()
    return to_dict(u, EX)


@router.post("/{uid}/invite")
def resend_invite(uid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("users.manage"))):
    """Reenvia o convite (pendente) ou envia um link de redefinicao de senha (usuario ja ativo)."""
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    if not u.active:
        raise HTTPException(400, "Usuário inativo")
    if u.invite_pending:
        u.invited_at = datetime.now(timezone.utc)
    audit.log(db, request, "user_resend_invite", "user", u.id, detail={"reset": not u.invite_pending})
    db.commit()
    return {"email_status": send_invite(db, u, reset=not u.invite_pending)}


@router.delete("/{uid}")
def delete_user(uid: int, request: Request, db: Session = Depends(get_db), me=Depends(require("users.manage"))):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    if u.id == me.id:
        raise HTTPException(400, "Você não pode excluir o seu próprio usuário")
    if u.role == "ADMIN" and u.active and (db.scalar(select(func.count()).select_from(User).where(User.role == "ADMIN", User.active.is_(True))) or 0) <= 1:
        raise HTTPException(400, "Não é possível excluir o último administrador ativo")
    email = u.email
    db.delete(u)
    audit.log(db, request, "user_delete", "user", uid, detail={"email": email})
    db.commit()
    return {"ok": True}
