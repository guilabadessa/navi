"""Firebase Cloud Messaging (HTTP v1) sem SDK: token OAuth2 via JWT da conta de servico (RS256) + envio."""
import base64
import json
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

_tok: dict = {"v": None, "exp": 0.0}


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def access_token(sa: dict) -> str:
    if _tok["v"] and _tok["exp"] > time.time() + 60:
        return _tok["v"]
    now = int(time.time())
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/firebase.messaging",
                              "aud": sa["token_uri"], "iat": now, "exp": now + 3600}).encode())
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = key.sign(f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    r = httpx.post(sa["token_uri"], data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": f"{head}.{claims}.{_b64(sig)}"}, timeout=15)
    r.raise_for_status()
    j = r.json()
    _tok["v"], _tok["exp"] = j["access_token"], time.time() + int(j.get("expires_in", 3600))
    return _tok["v"]


def send(sa: dict, token: str, data: dict) -> str:
    """'ok' | 'gone' (token invalido/expirado: remover) | 'error'."""
    msg = {"token": token, "notification": {"title": data["title"], "body": data.get("body", "")},
           "data": {"url": data.get("url", "/cliente/")},
           "android": {"priority": "HIGH", "notification": {"tag": data.get("tag", "navi")}}}
    r = httpx.post(f"https://fcm.googleapis.com/v1/projects/{sa['project_id']}/messages:send",
                   headers={"Authorization": "Bearer " + access_token(sa)}, json={"message": msg}, timeout=15)
    if r.status_code == 200:
        return "ok"
    if r.status_code == 404 or "UNREGISTERED" in r.text or "INVALID_ARGUMENT" in r.text:
        return "gone"
    return "error"
