"""Integracao com a Evolution API (WhatsApp). Nada de WhatsApp fica no gerador de relatorios."""
import base64

import httpx


class EvolutionError(Exception):
    pass


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

    def send_text(self, number: str, text: str, quoted_id: str | None = None, quoted_text: str | None = None) -> dict:
        payload = {"number": number, "text": text}
        if quoted_id:
            payload["quoted"] = {"key": {"id": quoted_id, "remoteJid": number, "fromMe": True},
                                 "message": {"conversation": quoted_text or ""}}
            try:
                return self._post("/message/sendText", payload)
            except EvolutionError:
                payload.pop("quoted")  # fallback: envia sem resposta
        return self._post("/message/sendText", payload)

    def send_document(self, number: str, pdf_bytes: bytes, filename: str, caption: str = "") -> dict:
        return self._post("/message/sendMedia", {
            "number": number, "mediatype": "document", "mimetype": "application/pdf", "caption": caption,
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
