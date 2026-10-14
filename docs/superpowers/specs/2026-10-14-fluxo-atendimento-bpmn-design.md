# Fluxo de atendimento editavel (BPMN) com CNPJ e abertura de chamado (sub-projetos C + D)

Data: 2026-10-14. Depende do B (filas e chat, em producao). O C (motor) e o D (editor visual) foram unidos porque o usuario pediu o fluxo padrao como diagrama BPMN totalmente editavel.

## Objetivo
O menu fixo do B vira um fluxo guardado no banco, desenhado e editado como diagrama (sequence flow): inicio, mensagens, menus (gateways), perguntas, consulta de CNPJ no NAVI, condicoes, abertura de chamado, aviso, entrada em fila e fim. O fluxo padrao reproduz o pedido do usuario e pode ser alterado, testado em simulador e restaurado.

## Fluxo padrao
- Inicio -> Menu (saudacao; 1 Comercial, 2 Financeiro, 3 Suporte; sem resposta em 2 min -> fila Geral; opcao invalida: repete uma vez e depois fila Geral).
- 1 -> fila Comercial.
- 2 -> pergunta CNPJ -> consulta: achou -> "Ola {cliente}" -> fila Financeiro; nao achou/invalido: tenta de novo uma vez; falhando de novo -> mensagem -> fila Comercial.
- 3 -> pergunta CNPJ -> consulta: achou -> menu "1 falar com analista / 2 abrir chamado": 1 -> fila Suporte; 2 -> pergunta a descricao -> cria chamado -> responde com o codigo -> fim. CNPJ nao achado: mesmo caminho do financeiro (tenta de novo, depois Comercial).

## Modelo do fluxo (JSON)
`{"nodes":[{"id","type","x","y","data":{...}}], "edges":[{"id","source","target","handle"}]}`.
Tipos e saidas (`handle`):
- `start`: next. `message` (text): next. `notify` (to[], text): next.
- `menu` (text, options[{key,label,aliases}], timeout_min, max_invalid): `opt:<key>` por opcao, `invalid`, `timeout`. Espera resposta.
- `ask` (text, var, validate cnpj|text|any, min_len, max_attempts, timeout_min): ok, invalid (apos max_attempts), timeout. Espera resposta.
- `lookup_client` (var, max_tries): found, retry, not_found. Vincula a conversa ao cliente achado.
- `condition` (var, op empty|not_empty|equals, value): true, false.
- `create_ticket` (subject, body, priority, queue_id): next, error. Cria o chamado do cliente vinculado (ou, sem vinculo, falha para `error`).
- `enqueue` (queue comercial|financeiro|suporte|geral): terminal; coloca na fila (aviso do B).
- `end` (text): terminal; encerra a conversa sem analista.
Variaveis nos textos: `{nome} {telefone} {cliente} {cnpj} {chamado}` e qualquer `var` de pergunta. Desconhecida vira vazio.

## Regras de execucao
- Nos automaticos executam em sequencia ate parar em `menu`/`ask` (aguarda), `enqueue` ou `end`. Limite de 40 passos por execucao.
- Resposta valida em `menu`/`ask` segue a saida correspondente. `menu` invalido: repete ate `max_invalid` (padrao 1) e entao segue `invalid` (se ausente, fila Geral). `ask` invalido: repete a pergunta ate `max_attempts` (padrao 2) e entao segue `invalid` (se ausente, fila Geral).
- Timeout (por no, padrao `menu_timeout_min` do B): segue `timeout` (se ausente, fila Geral). Job de 30 s existente.
- No removido/ausente em conversa em andamento, fluxo invalido ou erro: fila Geral (nunca deixa o cliente sem resposta).
- Estado por conversa: `flow_node` e `flow_vars` (JSON; guarda tentativas e contadores).
- Motor puro (`flow_engine`) com `Host` injetado (say, find_client, create_ticket, notify) para testes e simulador.

## Validacao ao salvar
Um unico `start`; ids unicos; tipos e `handle`s validos; destino existente; saidas obrigatorias ligadas (start/message/notify.next; menu opt:*; ask.ok; lookup.found e not_found; condition true/false; create_ticket.next); `enqueue.queue` valido; `menu` com ao menos uma opcao e chaves unicas; ciclo apenas de nos automaticos e erro (laco infinito). Erros voltam em lista (422) com o id do no.

## CNPJ
Valida digitos verificadores; a busca compara os digitos com `clients.cnpj` (so digitos, no banco). Valor invalido conta como tentativa do `ask`; valido e inexistente conta no `lookup_client`.

## Chamado criado pelo fluxo
`ticket_service.create_from_whatsapp`: cliente vinculado, origem `whatsapp`, status `aguardando_orca`, contato = telefone da conversa, autor = nome do contato, descricao como primeira mensagem, notificacao normal de chamado novo.

## API (`/cliente/api/atendimento`)
`GET /flow` (view), `PUT /flow` (settings.edit; valida), `POST /flow/validate`, `POST /flow/reset`, `POST /flow/simulate {definition, inputs[]}` (so leitura: consulta cliente de verdade, chamado e avisos simulados, nada e enviado).

## Editor visual
Pagina `Fluxo` (React Flow): paleta para adicionar nos, arrastar e ligar saidas (handles rotulados), formas BPMN (evento de inicio/fim circulares, gateways em losango, tarefas retangulares), inspetor lateral para editar o no, validacao com erros por no, simulador em formato de chat, salvar, restaurar padrao. Somente quem tem `settings.edit` edita; quem tem `atendimento.view` visualiza.

## Fora de escopo
Versionamento/rascunho do fluxo (um fluxo ativo; restaurar padrao disponivel), multiplos fluxos por horario, botoes interativos do WhatsApp.

## Testes
Motor (cada tipo, tentativas, timeout, no ausente, limite de passos), validador (cada erro), fluxo padrao ponta a ponta no simulador (comercial; financeiro achado e nao achado; suporte com chamado e com analista), integracao no `atendimento_service`, API, build do frontend e teste real pelo celular.
