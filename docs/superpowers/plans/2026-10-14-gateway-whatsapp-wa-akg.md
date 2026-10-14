# Gateway WhatsApp (WA-AKG) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Colocar o WA-AKG no ar como gateway único de WhatsApp do NAVI (envio dos alertas/avisos + recepção de mensagens armazenadas), com chave de troca para voltar à Evolution.

**Architecture:** `WaAkgService` implementa a mesma interface do `EvolutionService`; `factory.evolution(db)` passa a escolher o provedor por `whatsapp.provider`. Um webhook assinado (HMAC-SHA256) grava mensagens em `wa_messages` e chama um gancho vazio `on_inbound` (B e C se plugam depois). O WA-AKG roda em Docker nesta máquina com MariaDB próprio.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + httpx (backend), React/Vite (Configurações), Docker Compose, WA-AKG v1.6.3 (Next.js + Baileys + Prisma/MySQL), MariaDB 10.11.

**Spec:** `docs/superpowers/specs/2026-10-14-gateway-whatsapp-wa-akg-design.md`

## Global Constraints

- Tag do WA-AKG fixada em `v1.6.3`, nunca `main`.
- WA-AKG e MariaDB só em rede interna do compose; porta do WA-AKG apenas em `127.0.0.1:3100`; MariaDB sem porta publicada.
- Segredos só em `/opt/noc/.env` (ignorado pelo git) e no `settings` cifrado; nunca retornados pela API.
- Provedor padrão continua `evolution` até a troca manual (rollback = voltar a configuração).
- Webhook sem assinatura válida responde 401 e nada é gravado.
- Textos de UI e mensagens em português (pt-BR), como o resto do NAVI.
- Testes rodam no container: `docker run --rm --entrypoint sh -v /opt/noc/backend/app:/app/app:ro -v /opt/noc/backend/tests:/app/tests:ro -w /app navi:latest -c 'pip install -q -r requirements-dev.txt >/dev/null 2>&1; python -m pytest tests -q -p no:cacheprovider'`. Chamado abaixo de `PYTEST`.
- Frontend valida com: `docker run --rm -v /opt/noc/frontend:/src:ro node:20-alpine sh -c 'cp -r /src /fe && cd /fe && npm run build 2>&1 | tail -6'`. Chamado abaixo de `FEBUILD`.

## Review Focus

1. Webhook reentregue (mesmo `key.id`): não duplica linha em `wa_messages`.
2. Webhook com corpo válido mas sem cabeçalho de assinatura, ou com segredo não configurado: 401 (nunca aceita "sem segredo").
3. Evento que não é mensagem (`connection.update`, `message.status`) ou payload sem `key.id`: responde 200 e ignora, sem erro 500 (o WA-AKG reentregaria).
4. Mensagem sem texto (imagem/áudio, `content` nulo): grava com texto vazio, sem quebrar.
5. Telefone brasileiro com/sem 9º dígito e grupos (`@g.us`, `120363...`): JID correto no envio.

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `backend/app/services/wa_akg_service.py` (novo) | Cliente HTTP do WA-AKG: `to_jid`, `send_text`, `send_document`, `message_id`, `status`, `qr` |
| `backend/app/services/wa_inbound.py` (novo) | `verify_signature`, `parse_payload`, `store_inbound`, `on_inbound` (gancho) |
| `backend/app/routers/whatsapp_r.py` (novo) | `POST /wa/webhook`, `GET/PUT /wa/settings`, `POST /wa/test`, `GET /wa/qr` |
| `backend/app/models.py` | modelo `WaMessage` |
| `backend/alembic/versions/0028_wa_messages.py` (novo) | tabela `wa_messages` |
| `backend/app/services/factory.py` | `whatsapp(db)` escolhe provedor; `evolution(db)` vira alias |
| `backend/app/settings_store.py` | segredos `wa_akg.api_key`, `wa_akg.webhook_secret` |
| `backend/app/main.py` | registra o router; webhook fora do rate limit |
| `backend/tests/test_wa_akg.py` (novo) | testes do serviço, da assinatura/parse/armazenamento e da factory |
| `frontend/src/pages/Settings.jsx` | aba "WhatsApp (WA-AKG)" |
| `docker-compose.yml` | serviços `wa-akg-db` e `wa-akg` |
| `docs/superpowers/runbooks/wa-akg-setup.md` (novo) | passo a passo de pareamento, API key e webhook |

---

### Task 1: WaAkgService

**Files:**
- Create: `backend/app/services/wa_akg_service.py`
- Test: `backend/tests/test_wa_akg.py`

**Interfaces:**
- Produces: `WaAkgError(EvolutionError)`; `to_jid(v: str) -> str`; `class WaAkgService(base_url: str, session: str, api_key: str, timeout: float = 30.0, transport: httpx.BaseTransport | None = None)` com `send_text(number, text, quoted_id=None, quoted_text=None) -> dict`, `send_document(number, pdf_bytes, filename, caption="") -> dict`, `message_id(resp) -> str | None` (staticmethod), `status() -> dict` (`{"state": "open" | "close" | ..., "raw": ...}`), `qr() -> dict` (`{"qr": str|None, "base64": str|None}`).
- Consumes: `normalize_target`, `_br_alternative`, `EvolutionError` de `app/services/evolution_service.py`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_wa_akg.py
import json

import httpx
import pytest

from app.services.wa_akg_service import WaAkgError, WaAkgService, to_jid


def svc(handler):
    return WaAkgService("http://wa:3000", "orca", "wag_key", transport=httpx.MockTransport(handler))


def test_to_jid_telefone_grupo_e_jid_pronto():
    assert to_jid("(14) 99999-9999") == "5514999999999@s.whatsapp.net"
    assert to_jid("1433334444") == "551433334444@s.whatsapp.net"
    assert to_jid("120363025246125486") == "120363025246125486@g.us"
    assert to_jid("12345-678") == "12345-678@g.us"
    assert to_jid("5514999999999@s.whatsapp.net") == "5514999999999@s.whatsapp.net"
    assert to_jid("120363@g.us") == "120363@g.us"


def test_send_text_monta_requisicao_e_devolve_resposta():
    seen = {}

    def h(req: httpx.Request):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers["x-api-key"], json.loads(req.content)
        return httpx.Response(200, json={"status": True, "data": {"key": {"id": "3EB0AA", "remoteJid": "x"}}})

    r = svc(h).send_text("(14) 99999-9999", "oi")
    assert seen["url"] == "http://wa:3000/api/messages/orca/5514999999999%40s.whatsapp.net/send"
    assert seen["key"] == "wag_key" and seen["body"] == {"message": {"text": "oi"}}
    assert WaAkgService.message_id(r) == "3EB0AA"


def test_send_text_tenta_variacao_do_nono_digito_quando_numero_nao_existe():
    urls = []

    def h(req: httpx.Request):
        urls.append(req.url.path)
        if len(urls) == 1:
            return httpx.Response(400, json={"status": False, "message": "number not exists on WhatsApp"})
        return httpx.Response(200, json={"status": True, "data": {"key": {"id": "OK"}}})

    r = svc(h).send_text("14999999999", "oi")
    assert "5514999999999" in urls[0] and "551499999999@" in urls[1]
    assert WaAkgService.message_id(r) == "OK"


def test_send_text_citado_usa_reply_e_cai_para_envio_simples():
    paths = []

    def h(req: httpx.Request):
        paths.append(req.url.path)
        if req.url.path.endswith("/reply"):
            return httpx.Response(500, json={"status": False})
        return httpx.Response(200, json={"status": True, "data": {"key": {"id": "S"}}})

    r = svc(h).send_text("5514999999999", "oi", quoted_id="ABC", quoted_text="antes")
    assert paths[0].endswith("/ABC/reply") and paths[1].endswith("/send")
    assert WaAkgService.message_id(r) == "S"


def test_erro_http_e_conexao_viram_waakgerror():
    with pytest.raises(WaAkgError, match="HTTP 503"):
        svc(lambda r: httpx.Response(503, text="not ready")).send_text("5514999999999", "x")

    def boom(req):
        raise httpx.ConnectError("down")

    with pytest.raises(WaAkgError, match="conexão"):
        svc(boom).send_text("5514999999999", "x")


def test_sem_configuracao_levanta_erro_claro():
    with pytest.raises(WaAkgError, match="não configurado"):
        WaAkgService("", "", "").send_text("5514999999999", "x")


def test_send_document_envia_multipart():
    seen = {}

    def h(req: httpx.Request):
        seen["path"], seen["ct"] = req.url.path, req.headers["content-type"]
        return httpx.Response(200, json={"status": True, "data": {"key": {"id": "D1"}}})

    r = svc(h).send_document("5514999999999", b"%PDF-1.4", "rel.pdf", "segue")
    assert seen["path"].endswith("/media") and seen["ct"].startswith("multipart/form-data")
    assert WaAkgService.message_id(r) == "D1"


def test_status_mapeia_connected_para_open():
    assert svc(lambda r: httpx.Response(200, json={"status": "Connected", "hasInstance": True})).status()["state"] == "open"
    assert svc(lambda r: httpx.Response(200, json={"status": "Disconnected"})).status()["state"] == "close"


def test_qr_le_codigo_da_sessao():
    s = svc(lambda r: httpx.Response(200, json={"status": True, "data": {"qr": "2@abc", "base64": "data:image/png;base64,xx"}}))
    assert s.qr() == {"qr": "2@abc", "base64": "data:image/png;base64,xx"}
    assert svc(lambda r: httpx.Response(404, json={"status": False})).qr() == {"qr": None, "base64": None}
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTEST` (ou só o arquivo, trocando `tests` por `tests/test_wa_akg.py`)
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.wa_akg_service'`

- [ ] **Step 3: Implement**

```python
# backend/app/services/wa_akg_service.py
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

    def status(self) -> dict:
        d = self._req("GET", f"/sessions/{quote(self.session, safe='')}")
        return {"state": "open" if str(d.get("status", "")).lower() == "connected" else "close", "raw": d}

    def qr(self) -> dict:
        try:
            d = self._req("GET", f"/sessions/{quote(self.session, safe='')}/qr").get("data") or {}
        except WaAkgError:
            return {"qr": None, "base64": None}
        return {"qr": d.get("qr"), "base64": d.get("base64")}
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTEST`
Expected: todos os testes de `test_wa_akg.py` PASS e o restante da suíte continua verde.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/wa_akg_service.py backend/tests/test_wa_akg.py
git commit -m "whatsapp: adaptador WaAkgService com a mesma interface da Evolution"
```

---

### Task 2: Escolha do provedor na factory

**Files:**
- Modify: `backend/app/services/factory.py:16-17`, `backend/app/settings_store.py:14`
- Test: `backend/tests/test_wa_akg.py`

**Interfaces:**
- Consumes: `WaAkgService`, `EvolutionService`, `settings_store.get`.
- Produces: `factory.whatsapp(db)` → `EvolutionService | WaAkgService`; `factory.evolution(db)` continua existindo e devolve o mesmo que `whatsapp(db)` (os 10 chamadores não mudam). Chaves de settings: `whatsapp.provider` (`evolution` padrão | `wa_akg`), `wa_akg.url`, `wa_akg.session`, `wa_akg.api_key` (segredo), `wa_akg.webhook_secret` (segredo).

- [ ] **Step 1: Write the failing test**

```python
# acrescentar em backend/tests/test_wa_akg.py
from unittest.mock import patch

from app.services import factory
from app.services.evolution_service import EvolutionService


def _cfg(values):
    return lambda db, key, default=None: values.get(key, default or "")


def test_factory_padrao_e_evolution():
    with patch.object(factory.S, "get", side_effect=_cfg({"evolution.url": "http://e", "evolution.instance": "i", "evolution.api_key": "k"})):
        assert isinstance(factory.whatsapp(None), EvolutionService)
        assert isinstance(factory.evolution(None), EvolutionService)


def test_factory_escolhe_wa_akg_quando_configurado():
    cfg = {"whatsapp.provider": "wa_akg", "wa_akg.url": "http://wa:3000", "wa_akg.session": "orca", "wa_akg.api_key": "wag_x"}
    with patch.object(factory.S, "get", side_effect=_cfg(cfg)):
        s = factory.evolution(None)
        assert isinstance(s, WaAkgService) and s.session == "orca" and s.base == "http://wa:3000"
```

- [ ] **Step 2: Run to verify it fails** — `PYTEST` → FAIL (`module 'app.services.factory' has no attribute 'whatsapp'`).

- [ ] **Step 3: Implement**

Em `factory.py`, adicionar o import `from .wa_akg_service import WaAkgService` e substituir a função `evolution`:

```python
def whatsapp(db: Session) -> EvolutionService | WaAkgService:
    """Provedor de WhatsApp ativo (`whatsapp.provider`): evolution (padrao) ou wa_akg. Mesma interface nos dois."""
    if S.get(db, "whatsapp.provider", "evolution") == "wa_akg":
        return WaAkgService(S.get(db, "wa_akg.url"), S.get(db, "wa_akg.session"), S.get(db, "wa_akg.api_key"))
    return EvolutionService(S.get(db, "evolution.url"), S.get(db, "evolution.instance"), S.get(db, "evolution.api_key"))


def evolution(db: Session) -> EvolutionService | WaAkgService:
    """Nome legado: todos os chamadores antigos recebem o provedor ativo."""
    return whatsapp(db)
```

Em `settings_store.py`, acrescentar `"wa_akg.api_key", "wa_akg.webhook_secret"` ao conjunto `SECRET_KEYS`.

- [ ] **Step 4: Run to verify it passes** — `PYTEST` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/factory.py backend/app/settings_store.py backend/tests/test_wa_akg.py
git commit -m "whatsapp: factory escolhe o provedor (evolution ou wa_akg) por configuracao"
```

---

### Task 3: Tabela wa_messages e recepção (assinatura, parse, armazenamento)

**Files:**
- Modify: `backend/app/models.py` (após `TicketAttachment`)
- Create: `backend/alembic/versions/0028_wa_messages.py`, `backend/app/services/wa_inbound.py`
- Test: `backend/tests/test_wa_akg.py`

**Interfaces:**
- Produces: `WaMessage` (colunas `id` BigInteger pk, `external_id` str(128) único, `session` str(64), `jid` str(128) index, `direction` str(3) `in|out`, `type` str(24), `text` Text, `media_ref` str(512) nulo, `push_name` str(255) nulo, `created_at`); `verify_signature(secret: str, raw: bytes, header: str) -> bool`; `parse_payload(payload: dict) -> dict | None`; `store_inbound(db, parsed: dict) -> WaMessage | None` (None se duplicada); `on_inbound(db, msg: WaMessage) -> None` (gancho vazio).

- [ ] **Step 1: Write the failing tests**

```python
# acrescentar em backend/tests/test_wa_akg.py
import hashlib
import hmac
from unittest.mock import MagicMock

from app.services import wa_inbound as W


def sign(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def test_verify_signature_valida_e_rejeita():
    raw = b'{"event":"message.received"}'
    assert W.verify_signature("seg", raw, sign("seg", raw))
    assert not W.verify_signature("seg", raw, sign("outro", raw))
    assert not W.verify_signature("seg", raw, "")
    assert not W.verify_signature("", raw, sign("", raw))  # segredo nao configurado: nunca aceita
    assert not W.verify_signature("seg", raw + b" ", sign("seg", raw))


MSG = {"event": "message.received", "sessionId": "orca",
       "data": {"key": {"id": "AB12", "remoteJid": "5514999999999@s.whatsapp.net", "fromMe": False}, "pushName": "Budi",
                "type": "TEXT", "content": "oi", "fileUrl": None, "caption": None}}


def test_parse_mensagem_recebida():
    p = W.parse_payload(MSG)
    assert p == {"external_id": "AB12", "session": "orca", "jid": "5514999999999@s.whatsapp.net", "direction": "in",
                 "type": "TEXT", "text": "oi", "media_ref": None, "push_name": "Budi"}


def test_parse_mensagem_enviada_e_midia_sem_texto():
    sent = {**MSG, "event": "message.sent", "data": {**MSG["data"], "key": {**MSG["data"]["key"], "fromMe": True}}}
    assert W.parse_payload(sent)["direction"] == "out"
    img = {**MSG, "data": {**MSG["data"], "type": "IMAGE", "content": None, "caption": "foto", "fileUrl": "/media/x"}}
    p = W.parse_payload(img)
    assert p["text"] == "foto" and p["media_ref"] == "/media/x"
    mudo = {**MSG, "data": {**MSG["data"], "type": "AUDIO", "content": None, "caption": None}}
    assert W.parse_payload(mudo)["text"] == ""


def test_parse_ignora_o_que_nao_e_mensagem_ou_vem_incompleto():
    assert W.parse_payload({"event": "connection.update", "data": {}}) is None
    assert W.parse_payload({"event": "message.received", "data": {"key": {}}}) is None
    assert W.parse_payload({"event": "message.received"}) is None
    assert W.parse_payload({}) is None


def test_store_inbound_grava_e_ignora_duplicada():
    db = MagicMock()
    db.scalar.return_value = None
    parsed = W.parse_payload(MSG)
    m = W.store_inbound(db, parsed)
    assert m.external_id == "AB12" and m.direction == "in"
    db.add.assert_called_once()
    db.reset_mock()
    db.scalar.return_value = 7  # ja existe
    assert W.store_inbound(db, parsed) is None
    db.add.assert_not_called()
```

- [ ] **Step 2: Run to verify it fails** — `PYTEST` → FAIL (`No module named 'app.services.wa_inbound'`).

- [ ] **Step 3: Implement**

Modelo em `models.py`:

```python
class WaMessage(Base):
    """Mensagem de WhatsApp recebida/enviada pelo gateway (base das conversas e da fila de atendimento)."""
    __tablename__ = "wa_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True)
    session: Mapped[str] = mapped_column(String(64))
    jid: Mapped[str] = mapped_column(String(128), index=True)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    type: Mapped[str] = mapped_column(String(24), default="TEXT")
    text: Mapped[str] = mapped_column(Text, default="")
    media_ref: Mapped[str | None] = mapped_column(String(512))
    push_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
```

Migração:

```python
# backend/alembic/versions/0028_wa_messages.py
"""WhatsApp: mensagens recebidas/enviadas pelo gateway (WA-AKG).

Revision ID: 0028
Revises: 0027
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wa_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("external_id", sa.String(128), nullable=False, unique=True),
        sa.Column("session", sa.String(64), nullable=False),
        sa.Column("jid", sa.String(128), nullable=False),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("type", sa.String(24), nullable=False, server_default="TEXT"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("media_ref", sa.String(512)),
        sa.Column("push_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_wa_messages_jid", "wa_messages", ["jid"])
    op.create_index("ix_wa_messages_created_at", "wa_messages", ["created_at"])


def downgrade():
    op.drop_table("wa_messages")
```

Serviço:

```python
# backend/app/services/wa_inbound.py
"""Recepcao de mensagens do WA-AKG: valida assinatura, interpreta o payload e grava (idempotente)."""
import hashlib
import hmac
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import WaMessage

log = logging.getLogger("navi.whatsapp")
EVENTS = {"message.received": "in", "message.sent": "out"}


def verify_signature(secret: str, raw: bytes, header: str) -> bool:
    """`X-Webhook-Signature: sha256=<hex>` = HMAC-SHA256(secret, corpo bruto). Sem segredo configurado, nunca aceita."""
    if not secret or not header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())


def parse_payload(payload: dict) -> dict | None:
    """Devolve os campos a gravar, ou None se o evento nao for mensagem ou vier incompleto."""
    if payload.get("event") not in EVENTS:
        return None
    d = payload.get("data") or {}
    key = d.get("key") or {}
    ext, jid = key.get("id"), key.get("remoteJid") or d.get("from")
    if not ext or not jid:
        return None
    return {"external_id": str(ext), "session": str(payload.get("sessionId") or ""), "jid": jid,
            "direction": "out" if key.get("fromMe") else "in", "type": d.get("type") or "TEXT",
            "text": d.get("content") or d.get("caption") or "", "media_ref": d.get("fileUrl"), "push_name": d.get("pushName")}


def store_inbound(db: Session, parsed: dict) -> WaMessage | None:
    """Grava a mensagem; None se ja existir (o WA-AKG pode reentregar o mesmo webhook)."""
    if db.scalar(select(WaMessage.id).where(WaMessage.external_id == parsed["external_id"])):
        return None
    m = WaMessage(**parsed)
    db.add(m)
    return m


def on_inbound(db: Session, msg: WaMessage) -> None:
    """Gancho para o atendimento (fila) e o motor de fluxo (sub-projetos B e C). Por ora so registra."""
    log.info("whatsapp %s %s (%s)", msg.direction, msg.jid, msg.type)
```

- [ ] **Step 4: Run to verify it passes** — `PYTEST` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0028_wa_messages.py backend/app/services/wa_inbound.py backend/tests/test_wa_akg.py
git commit -m "whatsapp: tabela wa_messages e recepcao com assinatura, parse e deduplicacao"
```

---

### Task 4: Router (webhook, configurações, teste, QR) e registro

**Files:**
- Create: `backend/app/routers/whatsapp_r.py`
- Modify: `backend/app/main.py:13`, `backend/app/main.py:29`, `backend/app/main.py:48-50`
- Test: `backend/tests/test_wa_akg.py`

**Interfaces:**
- Consumes: `wa_inbound.*`, `factory.whatsapp`, `settings_store`, `audit.log`, `require("settings.view" | "settings.edit")`.
- Produces: `POST /api/wa/webhook` (sem sessão de usuário; assinatura obrigatória; 401 sem ela; 200 `{"ok": true, "stored": bool}`); `GET /api/wa/settings`; `PUT /api/wa/settings`; `POST /api/wa/test`; `GET /api/wa/qr`.

- [ ] **Step 1: Write the failing test** (rota via `TestClient`, sem banco: sobrescreve `get_db`)

```python
# acrescentar em backend/tests/test_wa_akg.py
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app


def _client(secret="seg"):
    db = MagicMock()
    db.scalar.return_value = None
    app.dependency_overrides[get_db] = lambda: db
    patcher = patch("app.routers.whatsapp_r.S.get", side_effect=lambda d, k, default=None: secret if k == "wa_akg.webhook_secret" else (default or ""))
    patcher.start()
    return TestClient(app), db, patcher


def test_webhook_sem_assinatura_ou_assinatura_errada_da_401_e_nao_grava():
    c, db, p = _client()
    try:
        body = json.dumps(MSG).encode()
        assert c.post("/cliente/api/wa/webhook", content=body).status_code == 401
        assert c.post("/cliente/api/wa/webhook", content=body, headers={"X-Webhook-Signature": sign("errado", body)}).status_code == 401
        db.add.assert_not_called()
    finally:
        p.stop(); app.dependency_overrides.clear()


def test_webhook_valido_grava_e_evento_irrelevante_da_200_sem_gravar():
    c, db, p = _client()
    try:
        body = json.dumps(MSG).encode()
        r = c.post("/cliente/api/wa/webhook", content=body, headers={"X-Webhook-Signature": sign("seg", body)})
        assert r.status_code == 200 and r.json() == {"ok": True, "stored": True}
        db.add.assert_called_once()
        db.reset_mock()
        outro = json.dumps({"event": "connection.update", "data": {}}).encode()
        r = c.post("/cliente/api/wa/webhook", content=outro, headers={"X-Webhook-Signature": sign("seg", outro)})
        assert r.status_code == 200 and r.json() == {"ok": True, "stored": False}
        db.add.assert_not_called()
        lixo = b"nao e json"
        assert c.post("/cliente/api/wa/webhook", content=lixo, headers={"X-Webhook-Signature": sign("seg", lixo)}).status_code == 200
    finally:
        p.stop(); app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify it fails** — `PYTEST` → FAIL (404 nas rotas).

- [ ] **Step 3: Implement**

```python
# backend/app/routers/whatsapp_r.py
"""WhatsApp (WA-AKG): webhook de entrada assinado e configuracao do provedor. Token/segredos nunca saem na API."""
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, settings_store as S
from ..db import get_db
from ..security import require
from ..services import factory, wa_inbound

router = APIRouter(prefix="/wa", tags=["whatsapp"])


@router.post("/webhook")
async def webhook(request: Request, x_webhook_signature: str = Header(default=""), db: Session = Depends(get_db)):
    raw = await request.body()
    if not wa_inbound.verify_signature(S.get(db, "wa_akg.webhook_secret"), raw, x_webhook_signature):
        audit.log(db, request, "wa_webhook", "whatsapp", result="negado")
        db.commit()
        raise HTTPException(401, "Assinatura inválida")
    try:
        payload = json.loads(raw)
    except ValueError:
        return {"ok": True, "stored": False}  # corpo ilegivel: 200 para o gateway nao reentregar para sempre
    parsed = wa_inbound.parse_payload(payload) if isinstance(payload, dict) else None
    if not parsed:
        return {"ok": True, "stored": False}
    msg = wa_inbound.store_inbound(db, parsed)
    if msg is not None:
        db.commit()
        wa_inbound.on_inbound(db, msg)
    return {"ok": True, "stored": msg is not None}


class WaSettingsIn(BaseModel):
    provider: str = Field(pattern="^(evolution|wa_akg)$")
    url: str = Field(max_length=512)
    session: str = Field(max_length=64)
    api_key: str | None = None
    webhook_secret: str | None = None


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    return {"provider": S.get(db, "whatsapp.provider", "evolution"), "url": S.get(db, "wa_akg.url"), "session": S.get(db, "wa_akg.session"),
            "api_key_set": bool(S.get(db, "wa_akg.api_key")), "webhook_secret_set": bool(S.get(db, "wa_akg.webhook_secret")),
            "webhook_path": "/cliente/api/wa/webhook"}


@router.put("/settings")
def put_settings(body: WaSettingsIn, request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    S.put(db, "whatsapp.provider", body.provider, me.email)
    S.put(db, "wa_akg.url", body.url.strip(), me.email)
    S.put(db, "wa_akg.session", body.session.strip(), me.email)
    if body.api_key:
        S.put(db, "wa_akg.api_key", body.api_key, me.email)
    if body.webhook_secret:
        S.put(db, "wa_akg.webhook_secret", body.webhook_secret, me.email)
    audit.log(db, request, "settings_whatsapp", "settings", detail={"provedor": body.provider, "url": body.url, "sessao": body.session,
                                                                    "key_changed": bool(body.api_key), "secret_changed": bool(body.webhook_secret)})
    db.commit()
    return {"ok": True}


@router.post("/test")
def test(request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    try:
        st = factory.whatsapp(db).status()
        res = {"ok": True, "detail": f"Conectado: {json.dumps(st)[:200]}"}
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "detail": str(e)}
    audit.log(db, request, "wa_test", "settings", result="ok" if res["ok"] else "falha")
    db.commit()
    return res


@router.get("/qr")
def qr(db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    svc = factory.whatsapp(db)
    if not hasattr(svc, "qr"):
        raise HTTPException(422, "O provedor ativo não usa QR code por aqui.")
    return svc.qr()
```

`main.py`: acrescentar `whatsapp_r` ao import de `.routers`, à tupla de `include_router`, e trocar a condição do rate limit por `not request.url.path.endswith(("/webhook/zabbix", "/wa/webhook"))`.

- [ ] **Step 4: Run to verify it passes** — `PYTEST` → PASS (suíte completa).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/whatsapp_r.py backend/app/main.py backend/tests/test_wa_akg.py
git commit -m "whatsapp: webhook assinado, configuracoes, teste e QR do WA-AKG"
```

---

### Task 5: Aba "WhatsApp (WA-AKG)" nas Configurações

**Files:**
- Modify: `frontend/src/pages/Settings.jsx` (novo componente após `EvoTab`; item de aba; render)

**Interfaces:**
- Consumes: `GET/PUT /wa/settings`, `POST /wa/test`, `GET /wa/qr`; componentes `Card`, `Field`, `Pill`, `Loading`, `Save`, `useLoad`, `useToast` já importados no arquivo.

- [ ] **Step 1: Add the component** (inserir logo depois de `EvoTab`)

```jsx
function WaAkgTab({ edit }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/wa/settings'), []); const [res, setRes] = useState(null); const [qr, setQr] = useState(null)
  const [f, setF] = useState({ provider: 'evolution', url: '', session: '', api_key: '', webhook_secret: '' })
  useEffect(() => { if (data) setF(x => ({ ...x, provider: data.provider, url: data.url, session: data.session })) }, [data])
  if (!data) return <Loading />
  return <Card title="WhatsApp — WA-AKG (gateway)">
    <Field label="PROVEDOR ATIVO" hint="Troque para WA-AKG somente depois do pareamento e do teste. Voltar para Evolution é imediato."><select value={f.provider} onChange={e => setF({ ...f, provider: e.target.value })}><option value="evolution">Evolution API (atual)</option><option value="wa_akg">WA-AKG</option></select></Field>
    <div className="row r2"><Field label="URL BASE" hint="Rede interna: http://wa-akg:3000"><input value={f.url} onChange={e => setF({ ...f, url: e.target.value })} placeholder="http://wa-akg:3000" /></Field><Field label="SESSÃO"><input value={f.session} onChange={e => setF({ ...f, session: e.target.value })} placeholder="orca" /></Field></div>
    <div className="row r2"><Field label="API KEY" hint={data.api_key_set ? 'Configurada (oculta). Preencha somente para substituir.' : 'Não configurada.'}><input type="password" autoComplete="off" value={f.api_key} onChange={e => setF({ ...f, api_key: e.target.value })} /></Field>
      <Field label="SEGREDO DO WEBHOOK" hint={data.webhook_secret_set ? 'Configurado (oculto). Preencha somente para substituir.' : 'Não configurado: mensagens recebidas serão recusadas.'}><input type="password" autoComplete="off" value={f.webhook_secret} onChange={e => setF({ ...f, webhook_secret: e.target.value })} /></Field></div>
    <p className="sub" style={{ marginBottom: 10 }}>URL do webhook para cadastrar no WA-AKG (rede interna): <code>http://api:8100{data.webhook_path}</code> · evento <code>message.received</code> e <code>message.sent</code>.</p>
    {res && <div style={{ marginBottom: 10 }}><Pill tone={res.ok ? 'ok' : 'bad'}>{res.ok ? 'Conectada' : 'Falha'}</Pill> <span className="sub">{res.detail}</span></div>}
    {qr && (qr.base64 ? <img alt="QR code do WhatsApp" src={qr.base64} style={{ width: 220, height: 220, marginBottom: 10 }} /> : <p className="sub">Sem QR no momento (sessão já conectada ou ainda iniciando).</p>)}
    {edit && <><Save onClick={async () => { try { await put('/wa/settings', { ...f, api_key: f.api_key || null, webhook_secret: f.webhook_secret || null }); setF({ ...f, api_key: '', webhook_secret: '' }); toast('Salvo'); reload() } catch (e) { toast(e.message, true) } }}
      test={async () => setRes(await post('/wa/test'))} />
      <button className="btn" style={{ marginTop: 8 }} onClick={async () => { try { setQr(await get('/wa/qr')) } catch (e) { toast(e.message, true) } }}>Mostrar QR code para parear</button></>}</Card>
}
```

- [ ] **Step 2: Wire the tab** — em `tabs={[...]}` incluir `['wa', 'WhatsApp (WA-AKG)']` logo após `['evo', 'Evolution API']`, e no render `{tab === 'wa' && <WaAkgTab edit={edit} />}` ao lado do `EvoTab`.

- [ ] **Step 3: Verify build** — `FEBUILD` → termina com `✓ built in`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Settings.jsx
git commit -m "whatsapp: aba de configuracao do WA-AKG (provedor, chaves, teste e QR)"
```

---

### Task 6: Infraestrutura — compose, segredos, swap e runbook

**Files:**
- Modify: `docker-compose.yml`, `/opt/noc/.env` (não versionado)
- Create: `docs/superpowers/runbooks/wa-akg-setup.md`

**Interfaces:**
- Produces: containers `wa-akg-db` e `wa-akg` na rede do compose; `wa-akg` acessível por `http://wa-akg:3000` dentro da rede e `127.0.0.1:3100` no host.

- [ ] **Step 1: Segredos** — gerar e anexar ao `.env` (confirmar antes que `.env` está no `.gitignore`: já está):

```bash
cd /opt/noc
{ echo "WA_AKG_DB_PASSWORD=$(openssl rand -hex 16)"; echo "WA_AKG_AUTH_SECRET=$(openssl rand -base64 32)";
  echo "WA_AKG_ADMIN_EMAIL=ti@orcati.com.br"; echo "WA_AKG_ADMIN_PASSWORD=$(openssl rand -base64 18)";
  echo "WA_AKG_SWAGGER_PASSWORD=$(openssl rand -base64 18)"; } >> .env
git check-ignore .env
```
Expected: `.env` listado pelo `git check-ignore`.

- [ ] **Step 2: Serviços no `docker-compose.yml`** (sob `services:`, e adicionar `volumes:` ao final se ainda não existir bloco)

```yaml
  wa-akg-db:
    image: mariadb:10.11
    restart: unless-stopped
    environment:
      MARIADB_ROOT_PASSWORD: ${WA_AKG_DB_PASSWORD}
      MARIADB_DATABASE: wa_akg
    command: ["--innodb-buffer-pool-size=64M", "--max-connections=40", "--performance-schema=OFF"]
    volumes:
      - wa_akg_db:/var/lib/mysql
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 10s
      timeout: 5s
      retries: 10
    mem_limit: 256m
    logging:
      driver: json-file
      options: {max-size: "10m", max-file: "3"}

  wa-akg:
    build:
      context: https://github.com/mrifqidaffaaditya/WA-AKG.git#v1.6.3
    image: wa-akg:1.6.3
    restart: unless-stopped
    depends_on:
      wa-akg-db:
        condition: service_healthy
    environment:
      DATABASE_URL: mysql://root:${WA_AKG_DB_PASSWORD}@wa-akg-db:3306/wa_akg
      AUTH_SECRET: ${WA_AKG_AUTH_SECRET}
      BASE_URL: http://127.0.0.1:3100
      NEXTAUTH_URL: http://127.0.0.1:3100
      NODE_ENV: production
      PORT: "3000"
      HOSTNAME: 0.0.0.0
      NEXT_PUBLIC_APP_URL: http://127.0.0.1:3100
      NEXT_PUBLIC_API_URL: http://127.0.0.1:3100/api
      BAILEYS_LOG_LEVEL: error
      NEXT_PUBLIC_SWAGGER_ENABLED: "false"
      NEXT_PUBLIC_SWAGGER_PASSWORD: ${WA_AKG_SWAGGER_PASSWORD}
      TZ: America/Sao_Paulo
      ADMIN_EMAIL: ${WA_AKG_ADMIN_EMAIL}
      ADMIN_PASSWORD: ${WA_AKG_ADMIN_PASSWORD}
      NODE_OPTIONS: --max-old-space-size=450
    ports:
      - "127.0.0.1:3100:3000"
    volumes:
      - wa_akg_data:/app/data
      - wa_akg_uploads:/app/uploads
    mem_limit: 700m
    logging:
      driver: json-file
      options: {max-size: "10m", max-file: "3"}

volumes:
  wa_akg_db:
  wa_akg_data:
  wa_akg_uploads:
```

Validar: `docker compose config -q && echo ok` → `ok`.

- [ ] **Step 3: Swapfile temporário para o build** (a máquina não tem swap; o build do Next.js passa de 1,5 GB)

```bash
fallocate -l 3G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && swapon --show
```
Expected: `/swapfile` listado com 3G. Remover depois do aumento de RAM: `swapoff /swapfile && rm /swapfile`.

- [ ] **Step 4: Build e subida** (fora do horário de pico)

```bash
cd /opt/noc && docker compose build wa-akg 2>&1 | tail -15 && docker compose up -d wa-akg-db wa-akg && sleep 60 && docker compose ps && curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3100/
```
Expected: build termina sem erro, ambos `Up`, `curl` devolve `200` ou `307`. Conferir que `api`/`worker` continuam `Up` e `free -m` mostra memória disponível > 300 MB; se o NAVI sofrer, `docker compose stop wa-akg` imediatamente.

- [ ] **Step 5: Runbook** — criar `docs/superpowers/runbooks/wa-akg-setup.md` com: (1) acessar o painel por túnel SSH (`ssh -L 3100:127.0.0.1:3100 servidor` e abrir `http://127.0.0.1:3100`), login com `WA_AKG_ADMIN_EMAIL`/`WA_AKG_ADMIN_PASSWORD` do `.env`; (2) Settings > API Keys: gerar chave `wag_...`; (3) criar a sessão `orca` e ler o QR com o número novo (WhatsApp > Aparelhos conectados) ou usar o botão de QR do NAVI; (4) cadastrar o webhook `http://api:8100/cliente/api/wa/webhook` com secret e eventos `message.received`, `message.sent`; (5) no NAVI, Configurações > WhatsApp (WA-AKG): URL `http://wa-akg:3000`, sessão `orca`, API key e o mesmo secret; (6) adicionar o número novo aos grupos de aviso; (7) rollback: provedor de volta para Evolution; (8) remover o swapfile após subir a RAM.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml docs/superpowers/runbooks/wa-akg-setup.md
git commit -m "whatsapp: servicos wa-akg e wa-akg-db no compose e runbook de pareamento"
```

---

### Task 7: Deploy do NAVI, pareamento e troca

**Files:** nenhum (operação). Requer o **número novo** em mãos para ler o QR.

- [ ] **Step 1: Deploy do NAVI** — `cd /opt/noc && docker compose build api && docker compose up -d api worker && sleep 25 && curl -fsS http://127.0.0.1:8100/cliente/api/health` → `{"status":"ok"}`; `docker exec -e PYTHONPATH=/app navi-api-1 alembic current` → `0028 (head)`.
- [ ] **Step 2: Seguir o runbook** (API key, sessão `orca`, QR, webhook, configurações no NAVI) ainda com **provedor = Evolution**.
- [ ] **Step 3: Teste de envio pelo WA-AKG sem trocar o provedor** — na aba WhatsApp (WA-AKG), "Testar conexão" deve mostrar `Conectada`; enviar uma mensagem do celular pessoal para o número novo e conferir `docker exec navi-api-1 sh -c 'cd /app && PYTHONPATH=/app python -c "from app.db import SessionLocal; from sqlalchemy import text; print(SessionLocal().execute(text(\"select direction,jid,text from wa_messages order by id desc limit 3\")).all())"'`.
- [ ] **Step 4: Trocar `Provedor ativo` para WA-AKG**, salvar, e disparar um teste de alerta/aviso real (Alertas > teste, ou "Testar canal do NOC") — a mensagem deve chegar do número novo.
- [ ] **Step 5: Observação** — manter a Evolution configurada por 1 semana; reverter pelo mesmo seletor se algo falhar.
- [ ] **Step 6: Commit/registro** — nada a commitar; registrar no runbook a data da troca.

---

## Self-Review

- **Cobertura da spec:** container+MariaDB (T6), adaptador e interface (T1), troca por factory (T2), webhook com assinatura/dedup/ignorar eventos (T3–T4), tabela (T3), configurações+QR+teste (T4–T5), monitoramento (reaproveita `health_checks` via `status()` — `state: open|close` compatível com `jobs.py:212-216`), migração e rollback (T7), segurança (T4/T6), testes (T1–T4).
- **Sem placeholders:** todo passo de código tem código; passos de operação têm comandos e resultado esperado.
- **Consistência de tipos:** `WaAkgService(base_url, session, api_key, transport)`, `message_id` estático, `status()["state"]`, `qr()`; `verify_signature(secret, raw, header)`, `parse_payload`, `store_inbound`, `on_inbound`; chaves de settings iguais em T2, T4 e T5.
- **Review Focus coberto:** (1) T3 `test_store_inbound_grava_e_ignora_duplicada`; (2) T3/T4 assinatura vazia, ausente e segredo não configurado; (3) T3/T4 eventos irrelevantes e corpo inválido; (4) T3 mídia sem texto; (5) T1 `to_jid` e 9º dígito.
- **Riscos de execução a observar:** o build do Next.js pode estourar a memória (mitigado com swap e `NODE_OPTIONS`; se falhar, o build tem de ser feito com `docker compose stop worker` temporariamente); o login/ADMIN do WA-AKG depende do script `setup-admin.js` da imagem; a API do WA-AKG pode diferir da documentação (por isso o teste real de envio/recepção na T7 antes da troca).
