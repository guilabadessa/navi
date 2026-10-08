# NAVI — Navegação, Orientação e Assistência
Plataforma de NOC da **Orca TI**: monitoramento (Zabbix), incidentes, SLA/KPIs, alertas por WhatsApp (Evolution API),
relatórios executivos/técnicos em PDF e rotinas agendadas. Acesso: `https://navi.orcati.com.br/cliente/`.

## Arquitetura
```
Navegador ──HTTPS──> Apache (já existente, /zabbix intocado) ──/cliente──> 127.0.0.1:8100  [container api]
                                                                         │  FastAPI + SPA React (Vite)
Zabbix Server/API  <───── ZabbixService ─────────────────────────────────┤
Evolution API      <───── EvolutionService ──────────────[container worker: APScheduler]
SMTP (Office 365)  <───── EmailService                    sync · eventos · alertas · relatórios · backup · health
PostgreSQL 16 (172.16.31.208, db `navi`, SSL)  <── SQLAlchemy/Alembic
```
- `backend/app`: `routers/` (API), `services/` (zabbix, evolution, email, sync, event, notification, kpi, report, delivery, navi), `jobs.py` (worker), `models.py`, `security.py`.
- `frontend/src`: React (Dashboard, Clientes, Monitoramento, Eventos, Alertas, Relatórios, Rotinas, SLA, WhatsApp, E-mail, NAVI IA, Usuários, Auditoria, Configurações).
- O banco do Zabbix **não** é usado como banco da NAVI e nada é gravado nele.
- **API-first / retenção mínima**: a NAVI espelha só grupos e hosts (e remove o que sumiu do Zabbix). Itens, triggers e os eventos
  dos relatórios são consultados **ao vivo** na API. Eventos resolvidos ficam 90 dias (alertas/dashboard), PDFs: **2 por cliente**,
  logs: 5 dias.
- Relatório em duas etapas: **gerar → baixar/visualizar → confirmar envio** (WhatsApp/e-mail só enviam após confirmação).

## E-mails
Modelo único (identidade Orca TI, `backend/app/templates/email/`) para relatório, avisos e acesso de novos usuários. Nos e-mails de cliente aparece
somente o **nome fantasia**. A assinatura (texto ou imagem) é configurável em Configurações → E-mail (SMTP) e vale para todos os envios.
Alertas por WhatsApp usam apenas o que está marcado no cadastro do cliente (o webhook do Zabbix é opcional e não é necessário: `docs/zabbix-webhook.md`).

## Comandos
```bash
cd /opt/noc
docker compose up -d --build        # sobe/atualiza api + worker (migrations rodam sozinhas)
docker compose logs -f api worker   # logs (rotacionam: 10MB x 3)
docker compose down                 # para (dados ficam no banco NAVI e em ./storage)
```
## Reverter
- NAVI inteira: `docker compose down && a2disconf navi && systemctl reload apache2` (Zabbix não é afetado).
- Backups: `/opt/noc/backups/` (configs Zabbix/Apache pré-NAVI; dumps diários do banco NAVI em `backups/navi-db`, 7 últimos).

## Segurança
Senhas Argon2id · sessão em cookie HttpOnly/Secure/SameSite · CSRF por header · rate limit (login e API) · CSP e headers de segurança ·
segredos só em `.env`/banco cifrado (Fernet) · nenhuma chave no frontend · auditoria de ações. Veja `.env.example`.

## Estado por fase
| Fase | Estado |
|---|---|
| 1 Auditoria | ✅ `docs/01-auditoria-fase1.md` |
| 2 Base (Docker, banco, migrations, login, admin, UI) | ✅ |
| 3 Zabbix (API, sync, clientes↔grupos, hosts, eventos) | ✅ código pronto · **falta o token da API** |
| 4 Alertas (webhook, PROBLEM/RESOLVED, Evolution, quoted reply) | ✅ código pronto · **falta instância/API key da Evolution** |
| 5 Relatórios (KPIs, PDF Orca, histórico, filtros) | ✅ validado ponta a ponta |
| 6 Agendamento (diário/semanal/mensal, WA, e-mail) | ✅ código pronto · e-mail depende do SMTP |
| 7 NAVI IA | ✅ consultas determinísticas · LLM plugável (`NaviService`) |
