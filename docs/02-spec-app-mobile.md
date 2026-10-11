# Spec: App mobile NAVI (Android) com push de alertas

## Objetivo
Levar o portal NAVI para o celular: o **cliente** acompanha a situacao do proprio ambiente; a **equipe NOC** recebe alertas de todos os clientes e abre qualquer cliente.

## Perfis
| Perfil | Ve | Push |
|---|---|---|
| CLIENTE (`users.client_id` / `user_clients`) | portal somente leitura do(s) proprio(s) cliente(s), respeitando `portal_min_sev` e `portal.finance` | incidentes Media+ do proprio cliente (>= `portal_min_sev`) |
| Equipe NOC | todos os clientes, alertas, eventos, protecao, Cloud; troca de cliente via PortalSwitch | incidentes Media+ de todos; escalonamento do NOC |

Regra herdada: so incidentes (`INCIDENT_MIN_SEV=3`) geram push; Atencao/Informacao nao.

## Fases
1. **PWA (teste imediato):** o portal atual (`/cliente/`) vira instalavel: `manifest.webmanifest`, icones (mascote/logo Orca), service worker minimo, `display: standalone`. Instala no Android via Chrome > "Instalar app". Sem build nativo.
2. **Push Web (VAPID):** tabela `push_subscriptions(user_id, endpoint, keys, created_at, last_seen)`; endpoints `POST/DELETE /api/push/subscribe`; envio pelo worker no mesmo motor de despacho de alertas (novo canal `push`, dedupe e escalonamento iguais aos de WhatsApp/e-mail). Chaves VAPID em Configuracoes (criptografadas).
3. **APK (opcional):** empacotar o PWA com Capacitor/TWA para distribuir como APK/Play Store e usar FCM. So se a fase 2 nao bastar (ex.: push confiavel com app fechado).

## Requisitos
- Login igual ao portal (convite por e-mail, sem senha temporaria); sessao persistente no aparelho.
- Toque no push abre o incidente correspondente (deep link `/cliente/...`).
- Preferencias por usuario: ligar/desligar push, severidade minima (nunca abaixo de Media).
- Sem 2FA nem backup externo (decisoes anteriores); push nao carrega dados sensiveis alem de cliente, severidade e titulo.
- Somente leitura: nada de acoes destrutivas pelo app.

## Fora de escopo
Ack de alertas pela NAVI (exige token Zabbix de escrita), app iOS, modo offline alem do shell.

## Criterios de aceite
- Instala na tela inicial do Android e abre em tela cheia.
- Usuario CLIENTE nunca ve nem recebe dados de outro cliente.
- Incidente Media+ aberto gera push em ate 1 min; Atencao/Informacao nao geram.
- Tocar na notificacao abre o incidente.

## Testes
`tools/ui-smoke` (jsdom) para telas; teste de backend para filtro de destinatarios do push por cliente/severidade. **Cuidado:** o worker envia mensagens reais; parar o worker antes de testes que criem despachos.
