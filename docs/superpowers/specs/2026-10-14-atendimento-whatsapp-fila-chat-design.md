# Atendimento por WhatsApp: menu, filas por setor e chat no NAVI (sub-projeto B)

Data: 2026-10-14. Depende do sub-projeto A (gateway WA-AKG, em producao). O C (fluxo editavel, CNPJ, abrir chamado) e o D (construtor visual) vem depois.

## Objetivo
O cliente escreve para o numero do WhatsApp da Orca, recebe um menu (1 comercial, 2 financeiro, 3 suporte, ou aguardar), cai na fila do setor e um analista o atende por um chat dentro do NAVI. Todos os analistas veem e tratam todas as filas; o setor define apenas quem e avisado.

## Fora de escopo (C e D)
Consulta de CNPJ, abertura de chamado pelo fluxo, fluxo editavel com gatilhos/acoes, construtor visual, botoes interativos (ver "Botoes").

## Fluxo da conversa
Estados: `menu` -> `aguardando` -> `atendendo` -> `encerrada`.
- Mensagem de um numero individual (nao grupo) sem conversa aberta cria a conversa em `menu` e envia a saudacao configurada com as opcoes.
- Resposta `1`/`2`/`3` (so o digito, com espacos) coloca em `aguardando` na fila do setor e confirma ao cliente. Opcao invalida: repete o menu uma vez; a segunda invalida vai para a fila `geral`.
- Sem resposta em N minutos (padrao 2, `menu_timeout_min`) vai para `geral`. Job do worker a cada 30 s.
- Analista assume (`assigned_to`, `atendendo`), transfere (outro analista e/ou outro setor) e encerra (com mensagem de encerramento opcional). Mensagem nova apos encerrar abre conversa nova.
- Mensagem do dono digitada pelo celular (`fromMe`) entra no historico como saida.
- Mensagens de grupo (`@g.us`) e de `status@broadcast` nao geram conversa.
- Respostas automaticas so saem para quem escreveu primeiro (reduz risco de banimento).

## Dados (migration 0029)
- `wa_conversations`: id, jid, push_name, client_id (FK clients, null), queue (comercial|financeiro|suporte|geral), state, assigned_to (FK users, null), menu_sent_at, menu_tries, queued_at, assumed_at, closed_at, closed_by, last_message_at, unread (int). Indice em jid + state; a regra "uma conversa aberta por jid" e garantida no servico.
- `wa_messages`: + `conversation_id` (FK, null, indexado), + `sent_by` (FK users, null), + `failed` (bool).
- Configuracao em `settings` (chave `atendimento.config`, JSON): `greeting`, `menu_timeout_min`, `wait_alert_min` (padrao 5), `closing_message`, e por setor `alert_to: [jid|numero]` e `alert_enabled`.

## Aviso de fila
Ao entrar em `aguardando`, envia aos destinos do setor: "Fila {Setor}: {nome} ({cliente}) aguardando - {n} na fila". Nao avisa na entrada em `menu`. Falha de envio e logada e nao quebra o fluxo.

## Cliente do NAVI
Vinculo automatico comparando os digitos do numero (com/sem 55 e 9o digito) com `Client.whatsapp`; se houver um unico cliente, vincula. Senao o analista vincula pela tela.

## API (`/cliente/api/atendimento`)
- `GET /queues` contadores e maior espera por fila; `GET /conversations?queue=&mine=&state=`; `GET /conversations/{id}/messages?since=`.
- `POST /conversations/{id}/assume|transfer|close|link-client`; `POST /conversations/{id}/send` (texto) e `/send-media` (multipart).
- `GET/PUT /config`. Permissoes: `atendimento.view`, `atendimento.act`; config exige `settings.edit`. Toda acao relevante vai para `audit.log`.

## Motor (`services/atendimento_service.py`)
`on_inbound` (gancho em `wa_inbound`) decide por estado: sem conversa abre menu; em `menu` interpreta opcao; em `aguardando`/`atendendo` grava e incrementa `unread`. `tick(db)` trata timeout do menu. Envio do analista grava a mensagem na hora (id retornado pelo gateway); o eco do webhook e descartado pelo `external_id` unico.

## Tela "Atendimento"
Item no menu com contador de espera. Topo: um cartao por fila (aguardando, maior espera, vermelho acima de `wait_alert_min`). Esquerda: lista filtravel (fila / minhas). Centro: chat com texto, imagem e documento nos dois sentidos, atualizado por consulta a cada 3 s. Direita: cliente (nome, CNPJ, chamados abertos) e acoes assumir/transferir/encerrar/vincular. Aba de configuracao em Configuracoes.

## Falhas
Gateway fora: mensagem do analista fica `failed` com botao de reenviar. Webhook invalido continua 401. Corrida de duas pessoas assumindo: assumir e atomico (UPDATE condicional por estado), a segunda recebe 409.

## Botoes
Entrega inicial so com texto numerado. Depois, teste real de enquete/lista do WA-AKG no numero do usuario; se o voto/clique voltar pelo webhook, vira opcao de configuracao. O WA-AKG nao tem botao de resposta rapida (Baileys).

## Testes
Motor (opcao valida/invalida/timeout/reabertura/grupo ignorado), API (assumir concorrente, transferir, encerrar, enviar, falha), aviso por setor, vinculo de cliente, permissoes e rotas em `test_security`; build do frontend; teste real pelo celular.
