"""Integracao com a Evolution API (WhatsApp). Nada de WhatsApp fica no gerador de relatorios."""
import base64
import re

import httpx


class EvolutionError(Exception):
    pass


def normalize_target(v: str) -> str:
    """Grupo (JID/ID longo) permanece; telefone brasileiro (10/11 digitos) ganha o codigo do pais 55."""
    v = (v or "").strip()
    if "@" in v:
        return v
    if re.fullmatch(r"\d+-\d+", v):  # id de grupo antigo
        return v + "@g.us"
    d = re.sub(r"\D", "", v)
    if len(d) >= 15:  # ids de grupo (ex.: 120363...)
        return d + "@g.us"
    if len(d) in (10, 11):
        d = "55" + d
    return d


def _br_alternative(number: str) -> str | None:
    """Variacao do 9o digito (celulares BR): 55+DDD+9+8 digitos <-> 55+DDD+8 digitos."""
    if "@" in number or not number.startswith("55"):
        return None
    if len(number) == 13:
        return number[:4] + number[5:]
    if len(number) == 12:
        return number[:4] + "9" + number[4:]
    return None


class EvolutionService:
    def __init__(self, base_url: str, instance: str, api_key: str, timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self.instance = instance
        self.key = api_key
        self._c = httpx.Client(timeout=timeout, headers={"apikey": api_key, "Content-Type": "application/json"})

    def _post(self, path: str, payload: dict) -> dict:
        if not (self.base and self.instance and self.key):
            raise EvolutionError("Evolution API não configurada (URL/instância/API key)")
        try:
            r = self._c.post(f"{self.base}{path}/{self.instance}", json=payload)
        except httpx.HTTPError as e:
            raise EvolutionError(f"Falha de conexão: {e}") from e
        if r.status_code >= 300:
            raise EvolutionError(f"HTTP {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError:
            return {}

    @staticmethod
    def message_id(resp: dict) -> str | None:
        return ((resp.get("key") or {}).get("id")) or resp.get("messageId") or resp.get("id")

    def _send(self, path: str, number: str, payload: dict) -> dict:
        """Envia normalizando o destino; se o numero nao existir no WhatsApp, tenta a variacao do 9o digito."""
        number = normalize_target(number)
        try:
            return self._post(path, {**payload, "number": number})
        except EvolutionError as e:
            alt = _br_alternative(number) if '"exists":false' in str(e).replace(" ", "") else None
            if not alt:
                raise
            return self._post(path, {**payload, "number": alt})

    def send_text(self, number: str, text: str, quoted_id: str | None = None, quoted_text: str | None = None) -> dict:
        payload = {"text": text}
        if quoted_id:
            jid = normalize_target(number)
            jid = jid if "@" in jid else f"{jid}@s.whatsapp.net"
            q = {**payload, "quoted": {"key": {"id": quoted_id, "remoteJid": jid, "fromMe": True},
                                       "message": {"conversation": quoted_text or ""}}}
            try:
                return self._send("/message/sendText", number, q)
            except EvolutionError:
                pass  # fallback: envia sem resposta
        return self._send("/message/sendText", number, payload)

    def send_document(self, number: str, pdf_bytes: bytes, filename: str, caption: str = "") -> dict:
        return self._send("/message/sendMedia", number, {
            "mediatype": "document", "mimetype": "application/pdf", "caption": caption,
            "fileName": filename, "media": base64.b64encode(pdf_bytes).decode()})

    def status(self) -> dict:
        if not (self.base and self.instance and self.key):
            raise EvolutionError("Evolution API não configurada")
        try:
            r = self._c.get(f"{self.base}/instance/connectionState/{self.instance}")
        except httpx.HTTPError as e:
            raise EvolutionError(f"Falha de conexão: {e}") from e
        if r.status_code >= 300:
            raise EvolutionError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json()
