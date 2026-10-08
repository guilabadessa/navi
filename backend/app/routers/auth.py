from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas import AcceptInviteIn, ForgotIn, LoginIn, PasswordChange
from ..security import (COOKIE, PERMS, RateLimiter, user_perms, read_invite_token, client_ip, current_user, hash_password, login_limiter, make_session, needs_rehash,
                        read_session, verify_password)

router = APIRouter(prefix="/auth", tags=["auth"])
_forgot_limiter = RateLimiter(5, 900)
_invite_limiter = RateLimiter(10, 900)


def _me(u: User, csrf: str | None = None):
    perms = user_perms(u)
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "perms": sorted(perms),
            "must_change_password": u.must_change_password, "csrf": csrf, "client_id": u.client_id}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    key = f"{ip}|{body.email.lower()}"
    if login_limiter.blocked(key):
        audit.log(db, request, "login", "auth", result="bloqueado", detail={"email": body.email})
        db.commit()
        raise HTTPException(429, "Muitas tentativas. Aguarde 15 minutos.")
    u = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not u or not u.active or not verify_password(body.password, u.password_hash):
        login_limiter.hit(key)
        audit.log(db, request, "login", "auth", result="falha", detail={"email": body.email})
        db.commit()
        raise HTTPException(401, "E-mail ou senha inválidos")
    login_limiter.reset(key)
    if needs_rehash(u.password_hash):
        u.password_hash = hash_password(body.password)
    u.last_login = datetime.now(timezone.utc)
    token, csrf = make_session(u.id)
    st = get_settings()
    response.set_cookie(COOKIE, token, httponly=True, secure=st.NAVI_COOKIE_SECURE, samesite="lax",
                        max_age=st.NAVI_SESSION_HOURS * 3600, path=st.NAVI_BASE_PATH)
    audit.log(db, request, "login", "auth", u.id, user=u)
    db.commit()
    return _me(u, csrf)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    sess = read_session(request.cookies.get(COOKIE))
    u = db.get(User, sess["uid"]) if sess else None
    if u:
        audit.log(db, request, "logout", "auth", u.id, user=u)
        db.commit()
    response.delete_cookie(COOKIE, path=get_settings().NAVI_BASE_PATH)
    return {"ok": True}


@router.get("/me")
def me(request: Request, user: User = Depends(current_user)):
    sess = read_session(request.cookies.get(COOKIE))
    return _me(user, sess["csrf"])


@router.post("/change-password")
def change_password(body: PasswordChange, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        audit.log(db, request, "change_password", "user", user.id, result="falha")
        db.commit()
        raise HTTPException(400, "Senha atual incorreta")
    user.password_hash, user.must_change_password = hash_password(body.new_password), False
    audit.log(db, request, "change_password", "user", user.id)
    db.commit()
    return {"ok": True}


@router.get("/invite/{token}")
def invite_info(token: str, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if _invite_limiter.blocked(ip):
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")
    u = read_invite_token(token, db)
    if not u:
        _invite_limiter.hit(ip)
        raise HTTPException(410, "Este link expirou ou já foi utilizado. Peça um novo convite ao administrador.")
    return {"name": u.name, "email": u.email, "pending": u.invite_pending}


@router.post("/accept-invite")
def accept_invite(body: AcceptInviteIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if _invite_limiter.blocked(ip):
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")
    u = read_invite_token(body.token, db)
    if not u:
        _invite_limiter.hit(ip)
        raise HTTPException(410, "Este link expirou ou já foi utilizado. Peça um novo convite ao administrador.")
    u.password_hash = hash_password(body.password)  # muda o carimbo: o link nao pode ser reutilizado
    u.invite_pending, u.must_change_password = False, False
    u.last_login = datetime.now(timezone.utc)
    token, csrf = make_session(u.id)
    st = get_settings()
    response.set_cookie(COOKIE, token, httponly=True, secure=st.NAVI_COOKIE_SECURE, samesite="lax",
                        max_age=st.NAVI_SESSION_HOURS * 3600, path=st.NAVI_BASE_PATH)
    audit.log(db, request, "invite_accept", "user", u.id, user=u)
    db.commit()
    return _me(u, csrf)


@router.post("/forgot")
def forgot(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    """Resposta sempre igual (nao revela se o e-mail existe)."""
    ip = client_ip(request)
    if _forgot_limiter.blocked(ip):
        raise HTTPException(429, "Muitas solicitações. Aguarde alguns minutos.")
    _forgot_limiter.hit(ip)
    u = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if u and u.active:
        from .users import send_invite
        send_invite(db, u, reset=not u.invite_pending)
        audit.log(db, request, "forgot_password", "user", u.id, user=u)
        db.commit()
    return {"ok": True}
