# NAVI — Fase 1: Auditoria (08/10/2026)

Somente leitura, exceto: instalação de `git` e `sshpass`, e `start`/`enable` do
`zabbix-server` (executados pelo usuário). Backup das configs em
`/opt/noc/backups/*-pre-navi/`.

## 1. Arquitetura encontrada

| Item | Servidor APP (`orca-zabbix-app`) | Servidor BD (`orca-zabbix-bd`) |
|---|---|---|
| IP privado | 172.16.31.218 (+ IP público 186.237.58.182 / DNS sonar.orcati.com.br) | 172.16.31.208 |
| SO | Debian 12 | Debian 12 (uptime 211 dias) |
| CPU / RAM | 2 vCPU / 3,8 GB | 4 vCPU / 3,8 GB (**RAM quase toda em uso**) |
| Disco | 50 GB (34 GB livres) | 345 GB (241 GB livres) |
| Serviços | Zabbix Server 7.0.12, Apache 2.4 + PHP 8.2 (frontend), Zabbix Agent2, Grafana (:3000), snmpd, Acronis | PostgreSQL 16.8 |
| Portas | 22, 80, 443, 3000, 10050, 10051 | 22, 5432 |
| Docker / Node / Nginx | não instalados | — |
| Firewall | iptables ACCEPT total, sem ufw | — |

Observações:
- O prompt cita Ubuntu e IP privado .104; o real é **Debian 12 e .218**.
- Zabbix instalado por pacotes oficiais (`zabbix-server-pgsql`, `zabbix-frontend-php`,
  `zabbix-apache-conf`), apontando para o banco em 172.16.31.208 (`zabbixorca`).
- HTTPS: Apache com vhost `000-default-le-ssl` (Let's Encrypt), frontend em `/zabbix`.
- Zabbix: schema 7.0.0, 60 hosts, 34 host groups, ~17,8 mil itens, ~18,5 mil eventos;
  banco `zabbixorca` com 83 GB.
- Bancos no PostgreSQL: `zabbixorca`, `navi` (vazio, dono `navi`, **sem nenhuma tabela**), `postgres`.
- `pg_hba.conf`: `navi` só via `hostssl` a partir de 172.16.31.218; `postgres` só acessa
  `zabbixorca` pela rede 172.16.31.0/24 (administração do banco `navi` é feita via SSH local).

## 2. Riscos

1. **Zabbix Server estava parado** após o upgrade (desabilitado). Corrigido: ativo e habilitado.
   Lacuna de coleta de ~10:39 até a retomada.
2. **E-mail do Zabbix falhando** (`failed to send email: Login denied`); log com 1,4 GB sem rotação efetiva.
3. **Itens do host "Zabbix server" não suportados** (`vfs.dev.*[vda]`; o disco agora é `sda`).
4. **RAM**: 3,8 GB no APP e BD no limite. Rodar Postgres + backend + frontend + Chromium (PDF)
   no APP exige cuidado; recomendável aumentar RAM ou limitar containers.
5. **Sem firewall** no APP; portas 3000 e 10051 expostas em todas as interfaces.
6. **Segredos**: senhas foram trocadas por chat; recomenda-se rotacioná-las após o setup
   (`postgres`, `zabbixorca`, root SSH). Preferir chave SSH em vez de senha root.
7. Banco do Zabbix de 83 GB: relatórios devem usar a API e agregações, evitando varreduras em `history*`.

## 3. Arquitetura proposta

- **Backend**: Python FastAPI + SQLAlchemy/Alembic (migrations), Argon2 para senhas.
- **Worker/scheduler**: APScheduler ou RQ (Redis) para sync, alertas, relatórios.
- **Frontend**: Next.js/React (SPA servida atrás do Apache existente).
- **PDF**: Playwright/Chromium em container separado.
- **Banco NAVI**: PostgreSQL existente (`navi` em 172.16.31.208, SSL, usuário `navi`).
- **Execução**: Docker Compose isolado em `/opt/noc`; proxy reverso pelo **Apache já existente**
  (novo vhost/`Location /navi`, sem alterar o `/zabbix`).
- **Integrações**: `ZabbixService` (API), `EvolutionService`, `EmailService`, `PdfService`,
  `ReportService`, `NotificationService`, `NaviService` (abstração de IA).
- **Alertas em tempo real**: webhook do Zabbix para a NAVI (Media Type novo, em paralelo ao atual).

## 4. Plano de implantação

| Fase | Entrega | Reversão |
|---|---|---|
| 2 Base | Docker, compose, migrations, login, admin, esqueleto API/UI | `docker compose down`; banco `navi` é isolado |
| 3 Zabbix | Conexão API, sync de hosts/groups/triggers/items, clientes↔host groups | desligar worker; dados locais |
| 4 Alertas | Webhook PROBLEM/RESOLVED, Evolution, quoted reply | manter Media Type atual ativo |
| 5 Relatórios | KPIs, PDF com identidade Orca, histórico | — |
| 6 Agendamento | Rotinas diária/semanal/mensal, WhatsApp e e-mail | desabilitar rotinas |
| 7 NAVI IA | Camada de consulta/análise | feature flag |

## 5. Arquivos a criar (Fase 2)

`docker-compose.yml`, `.env.example`, `README.md`, `backend/` (app, models, alembic),
`frontend/`, `worker/`, `reports/templates/`, configuração do vhost Apache (com backup prévio).

## 6. Portas previstas (apenas em 127.0.0.1)

- Backend API: 127.0.0.1:8100
- Frontend: 127.0.0.1:3100
- Redis (se usado): interno ao compose, sem publicar
- Exposição externa somente via Apache 443 (`/navi`)

## 7. Pendências para confirmação antes da Fase 2

1. Autorizar instalação do Docker + Compose no APP.
2. Confirmar RAM: aumentar APP (recomendado ≥ 8 GB) ou aceitar limite apertado.
3. Subdomínio/caminho desejado (`/navi` em sonar.orcati.com.br ou `navi.orcati.com.br`).
4. Fornecer: token da API do Zabbix, API key/instância da Evolution, SMTP.
5. Corrigir o SMTP atual do Zabbix (senha recusada) — fora do escopo, mas afeta alertas.
