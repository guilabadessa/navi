"""Integracao com o WA-AKG (gateway WhatsApp). Mesma interface do EvolutionService: quem chama nao sabe qual provedor esta ativo."""
import re
from urllib.parse import quote

import httpx

from .evolution_service import EvolutionError, _br_alternative, normalize_target


class WaAkgError(EvolutionError):
    pass


def to_jid(v: str) -> str:
    """Destino normalizado (telefone BR / grupo) em JID do WhatsApp."""
    t = normalize_target(v)
    if "@" in t:
        return t
    if re.fullmatch(r"\d+-\d+", t):
        return t + "@g.us"
    return t + "@s.whatsapp.net"


class WaAkgService:
    def __init__(self, base_url: str, session: str, api_key: str, timeout: float = 30.0, transport: httpx.BaseTransport | None = None):
        self.base = (base_url or "").rstrip("/")
        self.session = session or ""
        self.key = api_key or ""
        self._c = httpx.Client(timeout=timeout, headers={"X-API-Key": self.key}, transport=transport)

    def _require(self):
        if not (self.base and self.session and self.key):
            raise WaAkgError("WA-AKG não configurado (URL/sessão/API key)")

    def _req(self, method: str, path: str, **kw) -> dict:
        self._require()
        try:
            r = self._c.request(method, f"{self.base}/api{path}", **kw)
        except httpx.HTTPError as e:
            raise WaAkgError(f"Falha de conexão: {e}") from e
        if r.status_code >= 300:
            raise WaAkgError(f"HTTP {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError:
            return {}

    def _msg_path(self, jid: str, tail: str) -> str:
        return f"/messages/{quote(self.session, safe='')}/{quote(jid, safe='')}/{tail}"

    @staticmethod
    def message_id(resp: dict) -> str | None:
        d = resp.get("data") or {}
        return ((d.get("key") or {}).get("id")) or resp.get("messageId") or resp.get("id")

    def _send_to(self, number: str, build) -> dict:
        """Envia normalizando o destino; se o numero nao existir no WhatsApp, tenta a variacao do 9o digito."""
        target = normalize_target(number)
        try:
            return build(to_jid(target))
        except WaAkgError as e:
            alt = _br_alternative(target) if "exist" in str(e).lower() else None
            if not alt:
                raise
            return build(to_jid(alt))

    def send_text(self, number: str, text: str, quoted_id: str | None = None, quoted_text: str | None = None) -> dict:
        body = {"message": {"text": text}}

        def build(jid: str) -> dict:
            if quoted_id:
                try:
                    return self._req("POST", self._msg_path(jid, f"{quote(quoted_id, safe='')}/reply"), json={**body, "fromMe": True})
                except WaAkgError:
                    pass  # fallback: envia sem resposta citada
            return self._req("POST", self._msg_path(jid, "send"), json=body)

        return self._send_to(number, build)

    def send_document(self, number: str, pdf_bytes: bytes, filename: str, caption: str = "") -> dict:
        def build(jid: str) -> dict:
            return self._req("POST", self._msg_path(jid, "media"), data={"type": "document", "caption": caption},
                             files={"file": (filename, pdf_bytes, "application/pdf")})

        return self._send_to(number, build)

    def send_media(self, number: str, data: bytes, filename: str, mimetype: str, caption: str = "") -> dict:
        kind = "image" if mimetype.startswith("image/") else "document"

        def build(jid: str) -> dict:
            return self._req("POST", self._msg_path(jid, "media"), data={"type": kind, "caption": caption},
                             files={"file": (filename, data, mimetype)})

        return self._send_to(number, build)

    def status(self) -> dict:
        body = self._req("GET", f"/sessions/{quote(self.session, safe='')}")
        d = body.get("data") if isinstance(body.get("data"), dict) else body  # v1.6.3 aninha em data; a doc nao
        return {"state": "open" if str(d.get("status", "")).lower() == "connected" else "close", "raw": body}

    def qr(self) -> dict:
        try:
            body = self._req("GET", f"/sessions/{quote(self.session, safe='')}/qr")
        except WaAkgError:
            return {"qr": None, "base64": None}
        d = {**(body.get("data") or {}), **{k: v for k, v in body.items() if k in ("qr", "base64")}}  # v1.6.3 devolve no topo; a doc diz dentro de data
        return {"qr": d.get("qr"), "base64": d.get("base64")}
