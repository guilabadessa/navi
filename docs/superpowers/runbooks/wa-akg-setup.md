# WA-AKG — subida, pareamento e troca de provedor

Banco: PostgreSQL do `172.16.31.208`, banco e usuário `wa_akg` (só acessíveis de `172.16.31.218`, via SSL). Senha em `/opt/noc/.env` (`WA_AKG_DB_PASSWORD`).
O Prisma do WA-AKG foi trocado de MySQL para PostgreSQL em `wa-akg/Dockerfile` (reaplicar a cada atualização de tag).

## 1. Subir
`cd /opt/noc && docker compose build wa-akg && docker compose up -d wa-akg` (build pesado: swapfile de 3 GB; fora do horário de pico).
Conferir: `docker compose ps` e `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3100/`.

## 2. Painel do WA-AKG (só por túnel)
`ssh -L 3100:127.0.0.1:3100 <este-servidor>` e abrir `http://127.0.0.1:3100`.
Login: `WA_AKG_ADMIN_EMAIL` / `WA_AKG_ADMIN_PASSWORD` do `.env`.

## 3. API key, sessão e webhook
1. Configurações > API Keys: gerar `wag_...`.
2. Criar a sessão `orca` e parear o **número novo**: WhatsApp > Aparelhos conectados > Conectar aparelho, lendo o QR (do painel ou do botão "Mostrar QR code" no NAVI).
3. Webhook da sessão `orca`: URL `http://api:8100/cliente/api/wa/webhook`, um **secret** forte, eventos `message.received` e `message.sent`.

## 4. NAVI
Configurações > WhatsApp (WA-AKG): URL `http://wa-akg:3000`, sessão `orca`, API key, mesmo secret do webhook. Testar conexão. Manter o provedor em **Evolution** até validar.

## 5. Trocar
Provedor ativo = WA-AKG > Salvar > testar um alerta/aviso real. Adicionar o número novo aos grupos de aviso do NOC e das filas.
Rollback: provedor de volta para Evolution (imediato). Manter a Evolution configurada por 1 semana.

## 6. Depois do aumento de RAM
`swapoff /swapfile && rm /swapfile`.
