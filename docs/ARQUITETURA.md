# NAVI — Arquitetura e operação

## Visão geral
```
Navegador ──HTTPS──> Cloudflare ──> Apache (orca-zabbix-app) ──/cliente──> 127.0.0.1:8100  [container api: FastAPI + SPA React]
                                                                           [container worker: APScheduler — mesmo código, mesmo banco]
                                   PostgreSQL (banco próprio da NAVI)      Zabbix (somente API, banco do Zabbix nunca é tocado)
Integrações (somente leitura): Zabbix · Acronis · FortiClient EMS · Conta Azul · Evolution API (envio) · SMTP (envio)
```
- **api** atende HTTP e o front (build estático em `/cliente/`). **worker** roda as rotinas (sincronizações, alertas, avisos, relatórios, backup).
- Segredos: `.env` (chmod 600) e tabela `settings` criptografada (Fernet derivado de `NAVI_SECRET_KEY`). Nunca vão para o git nem para o front.

## Camadas (backend/app)
| Camada | Papel |
|---|---|
| `routers/` | HTTP: valida entrada (pydantic), autoriza (`require("perm")`) e delega. Sem regra de negócio longa. |
| `services/` | Regras de negócio e integrações (`*_service.py`). `factory.py` monta os clientes das integrações. |
| `models.py` / `alembic/` | Modelagem e migrations (0001…0011, idempotentes, sempre com backup antes). |
| `security.py` | Sessão assinada + CSRF, perfis/permissões, permissões extras, IP real, rate limit. |
| `jobs.py` | Rotinas do worker (`tracked` registra status/erro de cada uma no painel). |

## Modelo de permissões
- Perfis: ADMIN (`*`), GESTOR, ANALISTA_NOC, VISUALIZADOR, CLIENTE (somente `portal.view`).
- Permissões extras por usuário (`users.extra_perms`): `finance.view` (equipe) e `portal.finance` (cliente).
- **Configurações/integrações: somente ADMIN.** O teste `tests/test_security.py` falha se surgir rota sem autenticação fora da lista de públicas, ou rota de escrita só com permissão de leitura.
- Isolamento entre clientes: usuário CLIENTE só enxerga os clientes de `users.client_id` + `user_clients`; trocar `client_id` na URL retorna 403.
- Sessão: cookie HttpOnly/SameSite=Lax + token CSRF; trocar a senha invalida as sessões antigas.

## Rotinas (worker)
`sync_inventory` 10 min · `poll_events` 30 s · `dispatch_alerts` 10 s · `sync_acronis` 5 min · `sync_ems` 10 min · `sync_finance` 30 min · `notices` 1 h (9h–16h) · `escalate` 1 min · `daily_digest` 1 min · `run_schedules` 1 min · `health_checks` 2 min · `cleanup` e `backup` diários. Falha de rotina aparece como banner no dashboard.

## Operação
- **Deploy:** `docker compose build api && docker compose up -d api worker` (o front é compilado na imagem). Migrations: `docker compose exec -w /app -e PYTHONPATH=/app api alembic upgrade head`.
- **Backup:** diário em `backups/navi-db/` (7 dias). Antes de mudança crítica: `pg_dump` manual. Restauração: `gunzip -c arquivo.sql.gz | psql …` (parar o worker antes).
- **Testes:** `cd backend && pip install -r requirements-dev.txt && PYTHONPATH=. pytest -q tests`. Teste de telas com dados reais: `tools/ui-smoke/README.md`.
- **Dependências:** o CI roda `pip-audit`; atualize `requirements.txt` com versões fixas e rode os testes + o smoke antes do deploy.
- **Rotação de segredos:** Acronis/EMS/Conta Azul/SMTP/Evolution em Configurações; `NAVI_SECRET_KEY` só com recriptografia dos segredos do banco.

## Pontos de atenção conhecidos
- Servidor único (decisão do negócio): backup só local; o worker e a API compartilham a mesma máquina.
- `client_hosts` carrega os hosts ativos e filtra em Python (ok até alguns milhares de hosts; depois, filtrar no SQL).
- Fatura do Conta Azul reúne boleto e nota: a API não entrega o PDF da nota separado.

## Cache de configurações e aceite de falhas
- `settings_store` mantém **uma única fotografia** da tabela `settings` em memória por processo (TTL 20 s, trocada por inteiro; nada é gravado a mais no banco). Gravar uma configuração derruba a fotografia ao concluir a transação. As chaves `contaazul.*` não passam pelo cache (o refresh token gira e o outro processo não pode ler valor velho).
- O banner de falhas do Dashboard lista rotinas com erro/atraso; "Dar ciência" grava `job_status.ack_sig` (assinatura da falha). Outro erro ou novo atraso muda a assinatura e o aviso volta.
- **Minha conta** (`/conta`, e botão no portal do cliente): edita o nome e troca a senha (limite de 8 tentativas/15 min; derruba as outras sessões).
