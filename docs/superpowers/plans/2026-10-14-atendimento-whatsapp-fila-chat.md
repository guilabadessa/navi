# Atendimento por WhatsApp (menu, filas, chat) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (execucao nativa, escolhida pelo usuario: "pode desenhar e implantar"). Steps usam checkbox.

**Goal:** Menu 1/2/3 por WhatsApp, filas por setor, monitor e chat do analista dentro do NAVI, com aviso por setor.

**Architecture:** `atendimento_service` (motor + acoes) chamado pelo gancho `wa_inbound.on_inbound` e por um job de 30 s; router `/atendimento` para a UI; pagina React `Atendimento.jsx` com consulta a cada 3 s. Envio sempre pelo WA-AKG (`factory.wa_akg`).

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, httpx, React/Vite. Testes com MagicMock (sem banco real), como o resto da suite.

**Spec:** `docs/superpowers/specs/2026-10-14-atendimento-whatsapp-fila-chat-design.md`

## Global Constraints
- Testes: `docker run --rm --entrypoint sh -v /opt/noc/backend/app:/app/app:ro -v /opt/noc/backend/tests:/app/tests:ro -w /app navi:latest -c 'pip install -q pytest >/dev/null 2>&1; python3 -m pytest tests -q -p no:cacheprovider'` (alias PYTEST). Frontend: build em `node:20-alpine`.
- Host sem `python`: usar `python3 -I`. Commits com `git -c user.email=guilherme@labadessa.com.br -c user.name=Guilherme` e rodape `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Textos de interface em portugues; comentarios curtos em portugues sem acento, como o codigo existente.
- Filas: `comercial`, `financeiro`, `suporte`, `geral`. Estados: `menu`, `aguardando`, `atendendo`, `encerrada`.
- Permissoes: `atendimento.view`, `atendimento.act` (ADMIN ja tem `*`; GESTOR e ANALISTA_NOC ganham as duas; VISUALIZADOR so `view`). Config exige `settings.edit`.

## Review Focus
- Cliente manda "oi" varias vezes em `menu`: nao reenviar o menu a cada "oi" (so conta tentativa se parece resposta; primeira mensagem apos o menu ja conta como tentativa invalida).
- Eco do webhook da propria resposta do NAVI/analista: nao duplicar mensagem nem reabrir conversa.
- Mensagem de grupo / status / numero proprio: nao cria conversa.
- Dois analistas assumindo ao mesmo tempo: o segundo recebe 409.
- Mensagem chega depois do encerramento: abre conversa nova (nao reabre a antiga).
- Gateway fora ao enviar: mensagem salva como `failed`, API responde 502 sem perder o texto.

---

### Task 1: Modelo, migration e permissoes
**Files:** Modify `backend/app/models.py` (WaMessage + novo WaConversation), `backend/app/security.py`; Create `backend/alembic/versions/0029_wa_conversations.py`; Test `backend/tests/test_atendimento.py`.
**Produces:** `WaConversation` (campos da spec); `WaMessage.conversation_id`, `.sent_by`, `.failed`.

- [ ] Step 1: teste de permissoes e modelo em `tests/test_atendimento.py`:
```python
from app.models import WaConversation, WaMessage
from app.security import has_perm

def test_permissoes_atendimento():
    assert has_perm("ANALISTA_NOC", "atendimento.act") and has_perm("GESTOR", "atendimento.view")
    assert has_perm("VISUALIZADOR", "atendimento.view") and not has_perm("VISUALIZADOR", "atendimento.act")
    assert not has_perm("CLIENTE", "atendimento.view")

def test_modelo_conversa():
    c = WaConversation(jid="5514999999999@s.whatsapp.net", queue="geral", state="menu")
    assert c.state == "menu" and hasattr(WaMessage, "conversation_id") and hasattr(WaMessage, "sent_by")
```
- [ ] Step 2: rodar PYTEST, ver falhar.
- [ ] Step 3: implementar. `WaConversation` com colunas: id BigInteger pk; jid String(128) index; push_name String(255); client_id FK clients.id nullable; queue String(16) default geral; state String(16) default menu index; assigned_to FK users.id nullable; menu_sent_at, queued_at, assumed_at, closed_at, last_message_at DateTime(tz) nullable; closed_by FK users.id nullable; menu_tries Integer default 0; unread Integer default 0; created_at. Em `WaMessage`: `conversation_id` BigInteger FK wa_conversations.id nullable index, `sent_by` Integer FK users.id nullable, `failed` Boolean default False. Migration 0029 cria a tabela e adiciona as 3 colunas (downgrade remove). `PERMS`: adicionar `"atendimento.view", "atendimento.act"` em GESTOR e ANALISTA_NOC e `"atendimento.view"` em VISUALIZADOR.
- [ ] Step 4: PYTEST passa. Step 5: commit "atendimento: modelo, migration 0029 e permissoes".

### Task 2: Motor do atendimento (service)
**Files:** Create `backend/app/services/atendimento_service.py`; Modify `backend/app/services/factory.py` (+`wa_akg(db)`), `backend/app/services/wa_akg_service.py` (+`send_media`); Test `tests/test_atendimento.py`.
**Interfaces (produz):**
- `QUEUES`, `LABEL`, `DEFAULT_CFG`, `cfg(db) -> dict`, `parse_option(text) -> str|None`, `is_individual(jid) -> bool`, `phone_digits(jid) -> str`
- `match_client(db, jid) -> Client|None`, `open_conversation(db, jid) -> WaConversation|None`
- `handle_inbound(db, msg, gw) -> WaConversation|None`, `tick(db, gw) -> int`
- `assume(db, conv_id, user_id) -> bool`, `transfer(db, conv, user_id, queue)`, `close(db, conv, user_id, send_closing, gw)`, `send(db, conv, user_id, text, gw) -> WaMessage` (levanta `WaAkgError` apos gravar `failed`), `send_media(db, conv, user_id, data, filename, mime, caption, gw)`
- `WaAkgService.send_media(number, data: bytes, filename: str, mimetype: str, caption: str = "") -> dict` (tipo `image` se mimetype comeca com image/, senao `document`).

- [ ] Step 1: testes (pure/mock):
```python
from unittest.mock import MagicMock
from app.services import atendimento_service as A

def test_parse_option():
    assert A.parse_option(" 1 ") == "comercial" and A.parse_option("2") == "financeiro" and A.parse_option("três") == "suporte"
    assert A.parse_option("oi") is None and A.parse_option("12") is None and A.parse_option("") is None

def test_is_individual_ignora_grupo_e_status():
    assert A.is_individual("5514999999999@s.whatsapp.net") and A.is_individual("1785@lid")
    assert not A.is_individual("1203@g.us") and not A.is_individual("status@broadcast")

def _conv(state="menu", tries=0, queue="geral"):
    c = A.WaConversation(id=1, jid="5514999999999@s.whatsapp.net", state=state, queue=queue, menu_tries=tries, unread=0)
    return c

def _msg(text="1", direction="in", jid="5514999999999@s.whatsapp.net"):
    return A.WaMessage(external_id="X", session="orca", jid=jid, direction=direction, type="TEXT", text=text, push_name="Joao")

def _db(open_conv=None, count=2):
    db = MagicMock()
    db.scalar.side_effect = lambda *a, **k: open_conv
    db.scalars.return_value.all.return_value = []
    return db

def test_primeira_mensagem_abre_menu_e_envia_saudacao(monkeypatch):
    db, gw = _db(None), MagicMock()
    monkeypatch.setattr(A, "match_client", lambda d, j: None)
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    c = A.handle_inbound(db, _msg("oi"), gw)
    assert c.state == "menu" and "digite 1" in gw.send_text.call_args.args[1]

def test_opcao_valida_vai_para_fila_e_avisa(monkeypatch):
    cfg = {**A.DEFAULT_CFG, "queues": {**A.DEFAULT_CFG["queues"], "suporte": {"alert_enabled": True, "alert_to": ["120363@g.us", "14999990000"]}}}
    monkeypatch.setattr(A, "cfg", lambda d: cfg)
    conv, gw = _conv(), MagicMock()
    db = _db(conv)
    A.handle_inbound(db, _msg("3"), gw)
    assert conv.state == "aguardando" and conv.queue == "suporte" and conv.queued_at is not None
    destinos = [c.args[0] for c in gw.send_text.call_args_list]
    assert "120363@g.us" in destinos and "14999990000" in destinos and "5514999999999@s.whatsapp.net" in destinos

def test_opcao_invalida_repete_uma_vez_e_depois_vai_para_geral(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    conv, gw = _conv(tries=0), MagicMock()
    A.handle_inbound(_db(conv), _msg("blabla"), gw)
    assert conv.state == "menu" and conv.menu_tries == 1
    A.handle_inbound(_db(conv), _msg("blabla"), gw)
    assert conv.state == "aguardando" and conv.queue == "geral"

def test_mensagem_em_fila_incrementa_nao_lidas_e_nao_responde(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    conv, gw = _conv("aguardando"), MagicMock()
    A.handle_inbound(_db(conv), _msg("alguem ai?"), gw)
    assert conv.unread == 1 and not gw.send_text.called

def test_grupo_e_saida_nao_criam_conversa(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    gw = MagicMock()
    assert A.handle_inbound(_db(None), _msg("oi", jid="1203@g.us"), gw) is None
    assert A.handle_inbound(_db(None), _msg("oi", direction="out"), gw) is None
    assert not gw.send_text.called

def test_tick_move_menu_vencido_para_geral(monkeypatch):
    monkeypatch.setattr(A, "cfg", lambda d: A.DEFAULT_CFG)
    conv, gw = _conv(), MagicMock()
    db = _db(None); db.scalars.return_value.all.return_value = [conv]
    assert A.tick(db, gw) == 1 and conv.state == "aguardando" and conv.queue == "geral"

def test_assume_atomico():
    db = MagicMock(); db.execute.return_value.rowcount = 1
    assert A.assume(db, 1, 7) is True
    db.execute.return_value.rowcount = 0
    assert A.assume(db, 1, 8) is False
```
- [ ] Step 2: PYTEST falha. Step 3: implementar o service. Pontos de implementacao:
  - `DEFAULT_CFG = {"greeting": "Bem-vindo à Orca TI.\nPara falar com o comercial, digite 1.\nPara o financeiro, digite 2.\nPara o suporte, digite 3.\nOu aguarde para ser atendido.", "menu_timeout_min": 2, "wait_alert_min": 5, "closing_message": "Atendimento encerrado. Obrigado pelo contato com a Orca TI!", "queues": {q: {"alert_enabled": False, "alert_to": []} for q in QUEUES}}`; `cfg(db)` faz merge do JSON em `S.get(db, "atendimento.config")` sobre o default (por fila tambem).
  - `parse_option`: texto `strip().lower()`; mapa `{"1","um"}->comercial`, `{"2","dois"}->financeiro`, `{"3","tres","três"}->suporte`.
  - `is_individual`: termina com `@s.whatsapp.net` ou `@lid`.
  - `handle_inbound`: saida (`direction=="out"`) ou nao individual -> None (apenas anexa `conversation_id` da conversa aberta, se existir, para saidas individuais). Sem conversa aberta: cria (`state=menu`, `menu_sent_at=now`, `match_client`), `db.add`, `db.flush()`, envia saudacao e retorna. Em `menu`: `parse_option` -> `_enqueue`; senao `menu_tries += 1`; se `menu_tries >= 2` -> `_enqueue(geral)`, senao reenvia saudacao. Em `aguardando/atendendo`: `unread += 1`. Sempre `msg.conversation_id = conv.id`, `conv.last_message_at = now`, `push_name`.
  - `_enqueue(db, conv, queue, gw)`: `state=aguardando`, `queue`, `queued_at=now`, confirma ao cliente ("Você está na fila do {LABEL}. Em instantes um analista vai te atender."), chama `_alert`.
  - `_alert`: so se `alert_enabled` e `alert_to`; texto "🔔 Fila {LABEL}: {nome} ({cliente}) aguardando · {n} na fila", n = `db.scalar(select(func.count())...)`; cada destino em try/except com `log.warning`.
  - `tick`: `db.scalars(select(WaConversation).where(state=="menu", menu_sent_at < now - timeout)).all()`; para cada, `_enqueue(geral)`; devolve quantidade.
  - `assume`: `db.execute(update(WaConversation).where(id==conv_id, state=="aguardando").values(state="atendendo", assigned_to=user_id, assumed_at=now, unread=0))`; `rowcount == 1`.
  - `send`: `gw.send_text(jid, text)`; grava `WaMessage(direction="out", external_id=message_id(resp) or "navi-"+uuid, sent_by=user_id, conversation_id=conv.id)`; se o `external_id` ja existir (eco chegou antes), apenas atualiza `sent_by` e `conversation_id`. Em `WaAkgError`: grava com `failed=True`, external_id `"navi-"+uuid`, e re-levanta.
  - `factory.wa_akg(db)` devolve `WaAkgService(S.get(db,"wa_akg.url"), S.get(db,"wa_akg.session"), S.get(db,"wa_akg.api_key"))`.
  - `send_media` do gateway: `self._req("POST", self._msg_path(jid, "media"), data={"type": kind, "caption": caption}, files={"file": (filename, data, mimetype)})` dentro de `_send_to`.
- [ ] Step 4: PYTEST passa. Step 5: commit "atendimento: motor do menu, filas e acoes".

### Task 3: Gancho do webhook e job
**Files:** Modify `backend/app/services/wa_inbound.py` (`on_inbound`), `backend/app/jobs.py`; Test `tests/test_atendimento.py`.
- [ ] Step 1: teste: `on_inbound` chama `atendimento_service.handle_inbound(db, msg, gw)` e commita; falha dentro do atendimento nao propaga (loga):
```python
def test_on_inbound_chama_atendimento_e_engole_erro(monkeypatch):
    from app.services import wa_inbound
    chamado = {}
    monkeypatch.setattr("app.services.atendimento_service.handle_inbound", lambda db, m, gw: chamado.setdefault("ok", True))
    monkeypatch.setattr("app.services.factory.wa_akg", lambda db: MagicMock())
    wa_inbound.on_inbound(MagicMock(), _msg("oi"))
    assert chamado["ok"]
    monkeypatch.setattr("app.services.atendimento_service.handle_inbound", lambda db, m, gw: 1 / 0)
    wa_inbound.on_inbound(MagicMock(), _msg("oi"))  # nao levanta
```
- [ ] Step 2: falha. Step 3: `on_inbound` faz imports locais, `try: handle_inbound(...); db.commit() except Exception: db.rollback(); log.exception(...)`. No `jobs.py`: `JOBS["atendimento_tick"] = ("Atendimento WhatsApp (menu sem resposta)", 30)` e funcao `@tracked("atendimento_tick") def atendimento_tick(db): atendimento_service.tick(db, factory.wa_akg(db)); db.commit()` (so quando `whatsapp.provider == "wa_akg"`).
- [ ] Step 4: PYTEST passa. Step 5: commit "atendimento: gancho do webhook e job de timeout do menu".

### Task 4: API do atendimento
**Files:** Create `backend/app/routers/atendimento.py`; Modify `backend/app/main.py` (importar, registrar na lista de routers), `backend/tests/test_security.py` (rotas protegidas); Test `tests/test_atendimento.py`.
**Endpoints** (prefixo `/atendimento`, `require("atendimento.view")` nos GET, `require("atendimento.act")` nas acoes, `settings.edit` no PUT de config): `GET /queues`, `GET /conversations?queue=&mine=&state=`, `GET /conversations/{id}/messages?since=`, `GET /messages/{id}/media`, `POST /conversations/{id}/assume|transfer|close|link-client|send|send-media`, `GET|PUT /config`. Saida da conversa: id, jid, nome, queue, state, assigned_to/assigned_name, client{id,name,cnpj}, unread, queued_at, wait_seconds, last_message_at, last_text.
- [ ] Step 1: testes: 401/403 sem permissao (usar o padrao de `test_security.py`), `assume` 409 quando `assume()` devolve False, `send` 502 quando o gateway falha, `queues` agrega contadores. Mock de `get_db` e `current_user` como em `tests/test_tickets.py`.
- [ ] Step 2: falha. Step 3: implementar; `assume/transfer/close/send` chamam `audit.log(db, request, "atendimento_<acao>", "whatsapp", ...)`; `send-media` limita 15 MB e aceita image/*, application/pdf, office; `messages` zera `unread` da conversa; `media` busca `{wa_akg.url}{media_ref}` com `X-API-Key` e devolve o corpo com o content-type (404 se sem media_ref).
- [ ] Step 4: PYTEST passa (suite inteira). Step 5: commit "atendimento: API de filas, conversas, chat e configuracao".

### Task 5: Tela Atendimento e configuracao
**Files:** Create `frontend/src/pages/Atendimento.jsx`; Modify `frontend/src/App.jsx` (rota `/atendimento`, item de menu `['/atendimento','Atendimento',MessageCircle,'atendimento.view']`), `frontend/src/pages/Settings.jsx` (aba "Atendimento").
- [ ] Step 1: pagina com: cartoes de fila (`GET /atendimento/queues`, vermelho acima de `wait_alert_min`), lista de conversas (filtro por fila / minhas), painel de chat (mensagens, entrada de texto, anexo, enviar; mensagens `failed` com botao Reenviar), painel do cliente (nome, CNPJ, vinculo manual por busca em `/clients`), botoes Assumir / Transferir (analista e/ou setor) / Encerrar. `setInterval` de 3 s para `queues`, `conversations` e `messages?since=`; limpar no unmount; som/titulo com contador quando ha aguardando.
- [ ] Step 2: aba de configuracao: saudacao, timeout do menu, minutos de alerta, mensagem de encerramento, e por setor: liga/desliga e lista de destinos (um por linha: numero ou ID de grupo). `GET/PUT /atendimento/config`.
- [ ] Step 3: build: `docker run --rm -v /opt/noc/frontend:/app -w /app node:20-alpine sh -c 'npm ci >/dev/null 2>&1; npm run build'` sem erros.
- [ ] Step 4: commit "atendimento: tela de filas e chat e aba de configuracao".

### Task 6: Implantacao e validacao real
- [ ] Step 1: `docker compose up -d --build api worker` (migration 0029 roda no start), health ok, `alembic current` = 0029.
- [ ] Step 2: configurar via API/ painel os destinos de aviso do setor Suporte (grupo de fila) e testar com o celular do usuario: "oi" -> menu; "3" -> confirmacao + aviso no grupo; responder pelo NAVI; anexo; encerrar.
- [ ] Step 3: testar enquete/lista do WA-AKG (`/poll`, `/list`) com o numero do usuario e registrar se o voto volta pelo webhook (decide a opcao de balao).
- [ ] Step 4: push da branch `feat/gateway-whatsapp-wa-akg` (ou nova `feat/atendimento-whatsapp`) e atualizar o runbook com a operacao do atendimento.
