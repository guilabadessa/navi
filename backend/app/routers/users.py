from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import User
from ..schemas import UserIn
from ..security import hash_password, require
from ..services import mailer
from ..util import to_dict

router = APIRouter(prefix="/users", tags=["users"])
ROLE_NAMES = {"ADMIN": "Administrador", "GESTOR": "Gestor", "ANALISTA_NOC": "Analista NOC", "VISUALIZADOR": "Visualizador"}


def _send_access(db, u: User, password: str, reset: bool) -> str:
    """Envia os dados de acesso. Falha de e-mail nao desfaz a criacao do usuario. A senha nunca e registrada em log."""
    try:
        mailer.send(db, "new_user", u.email, "Redefinição de acesso à NAVI — Orca TI" if reset else "Seu acesso à NAVI — Orca TI",
                    mailer.new_user_ctx(u.name, u.email, password, ROLE_NAMES.get(u.role, u.role), reset))
        return f"enviado para {u.email}"
    except Exception as e:  # noqa: BLE001
        return f"erro: {str(e)[:200]}"
EX = {"password_hash"}


@router.get("")
def list_users(db: Session = Depends(get_db), _=Depends(require("users.manage"))):
    return [to_dict(u, EX) for u in db.scalars(select(User).order_by(User.name))]


@router.post("")
def create_user(body: UserIn, request: Request, db: Session = Depends(get_db), me=Depends(require("users.manage"))):
    if not body.password:
        raise HTTPException(422, "Senha obrigatória")
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "E-mail já cadastrado")
    u = User(email=body.email.lower(), name=body.name, role=body.role, active=body.active,
             password_hash=hash_password(body.password), must_change_password=True)
    db.add(u)
    db.flush()
    audit.log(db, request, "user_create", "user", u.id, detail={"email": u.email, "role": u.role})
    db.commit()
    return {**to_dict(u, EX), "email_status": _send_access(db, u, body.password, False) if body.send_email else None}


@router.put("/{uid}")
def update_user(uid: int, body: UserIn, request: Request, db: Session = Depends(get_db), me=Depends(require("users.manage"))):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    if u.id == me.id and (not body.active or body.role != "ADMIN"):
        raise HTTPException(400, "Você não pode remover seu próprio acesso de administrador")
    u.name, u.role, u.active = body.name, body.role, body.active
    if body.password:
        u.password_hash, u.must_change_password = hash_password(body.password), True
    audit.log(db, request, "user_update", "user", u.id, detail={"role": u.role, "active": u.active, "pwd": bool(body.password)})
    db.commit()
    return {**to_dict(u, EX), "email_status": _send_access(db, u, body.password, True) if (body.send_email and body.password) else None}
