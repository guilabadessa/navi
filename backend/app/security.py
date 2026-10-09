import base64
import hashlib
import hmac
import ipaddress
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
               "routines.edit", "whatsapp.view", "email.view", "navi.use", "protection.run", "cloud.run"},
    "ANALISTA_NOC": {"dashboard.view", "clients.view", "monitoring.view", "events.view", "events.edit",
                     "alerts.view", "alerts.edit", "reports.view", "reports.edit", "reports.send", "routines.view",
                     "whatsapp.view", "email.view", "navi.use", "protection.run", "cloud.run"},
    "VISUALIZADOR": {"dashboard.view", "clients.view", "monitoring.view", "events.view", "alerts.view",
                     "reports.view", "routines.view", "navi.use"},
    "CLIENTE": {"portal.view", "portal.run", "cloud.run"},  # ve somente os dados do proprio cliente, pelo portal
}


# Permissoes que podem ser concedidas a um usuario alem das do perfil
EXTRA_PERMS = {
    "portal.finance": "Portal: financeiro do cliente (títulos, boletos e notas fiscais)",
    "finance.view": "Equipe: ver o financeiro dos clientes (Conta Azul)",
}


def has_perm(role: str, perm: str) -> bool:
    p = PERMS.get(role, set())
    return "*" in p or perm in p


def user_perms(user) -> set[str]:
    p = set(PERMS.get(user.role, set()))
    # portal.finance so faz sentido para o perfil CLIENTE; finance.view so para a equipe
    for x in (getattr(user, "extra_perms", None) or []):
        if x in EXTRA_PERMS and ((x == "portal.finance") == (user.role == "CLIENTE")):
            p.add(x)
    return p


def user_has(user, perm: str) -> bool:
    p = user_perms(user)
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


def make_oauth_state(user_id: int) -> str:
    """'state' do OAuth: prova que o retorno do login externo foi iniciado por um administrador da NAVI (vale 15 min)."""
    return URLSafeTimedSerializer(get_settings().NAVI_SECRET_KEY, salt="navi-oauth").dumps({"uid": user_id, "n": secrets.token_urlsafe(6)})


def read_oauth_state(state: str) -> int | None:
    try:
        return URLSafeTimedSerializer(get_settings().NAVI_SECRET_KEY, salt="navi-oauth").loads(state, max_age=900).get("uid")
    except BadSignature:
        return None


# ---- Sessao (cookie assinado, HttpOnly, SameSite) + CSRF ------------------------------
def _ser() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().NAVI_SECRET_KEY, salt="navi-session")


def make_session(user_id: int, fp: str | None = None) -> tuple[str, str]:
    """fp = carimbo do hash da senha: trocar/redefinir a senha invalida as sessoes antigas."""
    csrf = secrets.token_urlsafe(24)
    d = {"uid": user_id, "csrf": csrf}
    if fp:
        d["fp"] = fp
    return _ser().dumps(d), csrf


def read_session(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        return _ser().loads(token, max_age=get_settings().NAVI_SESSION_HOURS * 3600)
    except BadSignature:
        return None


_CF_NETS = [ipaddress.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20",
    "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32")]


def _is_cf(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in n for n in _CF_NETS)


def client_ip(request: Request) -> str:
    """IP real do cliente sem confiar em cabecalhos forjaveis: o Apache ACRESCENTA o IP de quem o acessou ao fim de X-Forwarded-For,
    entao so a ultima entrada e confiavel. Se esse par for a Cloudflare, vale o CF-Connecting-IP (que so ela define)."""
    peer = request.client.host if request.client else "-"
    xff = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
    last = xff[-1] if xff else peer
    if _is_cf(last):
        cf = request.headers.get("cf-connecting-ip", "").strip()
        if cf:
            return cf
    return last


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
    if sess.get("fp") and sess["fp"] != user.password_hash[-12:]:
        raise HTTPException(401, "Sessão expirada. Entre novamente.")
    request.state.user = user
    return user


def require(perm: str):
    def dep(user: User = Depends(current_user)) -> User:
        if not user_has(user, perm):
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
