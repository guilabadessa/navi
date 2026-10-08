import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

_ph = PasswordHasher()
COOKIE = "navi_session"

# ---- Permissoes granulares por perfil -------------------------------------------------
PERMS = {
    "ADMIN": {"*"},
    "GESTOR": {"dashboard.view", "clients.view", "clients.edit", "monitoring.view", "events.view", "events.edit",
               "alerts.view", "alerts.edit", "reports.view", "reports.edit", "reports.send", "routines.view",
               "routines.edit", "sla.view", "whatsapp.view", "email.view", "navi.use", "settings.view"},
    "ANALISTA_NOC": {"dashboard.view", "clients.view", "monitoring.view", "events.view", "events.edit",
                     "alerts.view", "alerts.edit", "reports.view", "reports.edit", "reports.send", "routines.view",
                     "sla.view", "whatsapp.view", "email.view", "navi.use"},
    "VISUALIZADOR": {"dashboard.view", "clients.view", "monitoring.view", "events.view", "alerts.view",
                     "reports.view", "routines.view", "sla.view", "navi.use"},
    "CLIENTE": {"portal.view"},  # ve somente os dados do proprio cliente, pelo portal
}


def has_perm(role: str, perm: str) -> bool:
    p = PERMS.get(role, set())
    return "*" in p or perm in p


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, h: str) -> bool:
    try:
        return _ph.verify(h, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(h: str) -> bool:
    return _ph.check_needs_rehash(h)


# ---- Cifra de segredos guardados no banco (Fernet derivado da NAVI_SECRET_KEY) -------
def _fernet() -> Fernet:
    k = hashlib.sha256(("navi-settings|" + get_settings().NAVI_SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(k))


def encrypt(v: str) -> str:
    return _fernet().encrypt(v.encode()).decode()


def decrypt(v: str) -> str:
    try:
        return _fernet().decrypt(v.encode()).decode()
    except InvalidToken:
        return ""


# ---- Convites / redefinicao de senha: token assinado, expira e vale uma unica vez ------
INVITE_HOURS = 72


def _inv() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().NAVI_SECRET_KEY, salt="navi-invite")


def make_invite_token(user: User) -> str:
    # o "carimbo" do hash atual invalida o link assim que a senha e definida
    return _inv().dumps({"uid": user.id, "fp": user.password_hash[-12:]})


def read_invite_token(token: str, db: Session) -> User | None:
    try:
        d = _inv().loads(token, max_age=INVITE_HOURS * 3600)
    except BadSignature:
        return None
    u = db.get(User, d.get("uid"))
    if not u or not u.active or u.password_hash[-12:] != d.get("fp"):
        return None
    return u


# ---- Sessao (cookie assinado, HttpOnly, SameSite) + CSRF ------------------------------
def _ser() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().NAVI_SECRET_KEY, salt="navi-session")


def make_session(user_id: int) -> tuple[str, str]:
    csrf = secrets.token_urlsafe(24)
    return _ser().dumps({"uid": user_id, "csrf": csrf}), csrf


def read_session(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        return _ser().loads(token, max_age=get_settings().NAVI_SESSION_HOURS * 3600)
    except BadSignature:
        return None


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "-"


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    sess = read_session(request.cookies.get(COOKIE))
    if not sess:
        raise HTTPException(401, "Não autenticado")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(sent, sess.get("csrf", "")):
            raise HTTPException(403, "CSRF inválido")
    user = db.get(User, sess["uid"])
    if not user or not user.active:
        raise HTTPException(401, "Usuário inativo")
    request.state.user = user
    return user


def require(perm: str):
    def dep(user: User = Depends(current_user)) -> User:
        if not has_perm(user.role, perm):
            raise HTTPException(403, "Sem permissão")
        return user
    return dep


# ---- Rate limiting simples (em memoria, por processo) ---------------------------------
class RateLimiter:
    def __init__(self, max_hits: int, window_s: int):
        self.max, self.win = max_hits, window_s
        self.hits: dict[str, list[float]] = defaultdict(list)

    def _prune(self, key):
        t = time.time()
        self.hits[key] = [x for x in self.hits[key] if t - x < self.win]

    def blocked(self, key: str) -> bool:
        self._prune(key)
        return len(self.hits[key]) >= self.max

    def hit(self, key: str):
        self._prune(key)
        self.hits[key].append(time.time())

    def reset(self, key: str):
        self.hits.pop(key, None)


login_limiter = RateLimiter(max_hits=5, window_s=900)
api_limiter = RateLimiter(max_hits=600, window_s=60)
