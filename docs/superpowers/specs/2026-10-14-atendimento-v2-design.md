# Atendimento v2: filas editaveis, configuracao no front, historico e caixa de entrada estilo Kommo

Data: 2026-10-14. Evolui o B/C/D em producao. Pedido do usuario: "editar filas, adicionar novas, toda a configuracao no front, historico de atendimentos, padrao Kommo de edicao e melhorias nos fluxos".

## Etapa 1 - Filas editaveis e pagina de configuracao
- Tabela `wa_queues` (slug unico, nome, cor, ordem, ativa, avisos [liga/desliga + destinos], espera em alerta por fila, `system`). A fila `geral` e do sistema (fallback; nao exclui nem desativa). Migration semeia as 4 filas atuais copiando os avisos ja configurados.
- CRUD pelo front (criar, renomear, cor, ordem, ativar/desativar, avisos, excluir). Exclusao bloqueada se ha conversas abertas na fila ou se o fluxo salvo a usa (mensagem diz onde). Fila desativada some das escolhas e o motor cai na `geral`.
- Monitor, transferencia, filtros, fluxo (passo "Entrar na fila"), validador e avisos passam a usar as filas do banco.
- Pagina `Atendimento > Configuracoes` (menu lateral estilo Kommo): Filas, Respostas prontas (lista com criar/editar/excluir), Etiquetas, Horario de atendimento, Geral (inatividade, tempo padrao, mensagens). A aba antiga em Configuracoes aponta para ela.

## Etapa 2 - Historico e indicadores
- Campos novos na conversa: `closed_reason` (analista|inatividade|fluxo), `first_response_at`.
- `GET /history` (busca por nome/numero/cliente, fila, analista, motivo, periodo, paginacao), `GET /history/export` (CSV), `GET /stats` (total, espera media, 1a resposta media, duracao media, por fila, por analista, por motivo).
- Pagina `Atendimento > Historico`: cartoes de indicadores, filtros, tabela e gaveta com a conversa completa (somente leitura).

## Etapa 3 - Caixa de entrada estilo Kommo
- Abas Fila / Meus / Todos / Encerrados com contadores, chips por fila (cor), busca, filtro por etiqueta.
- Etiquetas (catalogo `wa_tags`) na conversa; nome do contato editavel (`contact_name`).
- Nota interna no chat (nunca enviada ao cliente) e linha do tempo de eventos (assumiu, transferiu, entrou na fila, encerrou, inatividade) gravadas como mensagens `note` e `sys`.

## Etapa 4 - Fluxos
- Novos passos: `hours` (saidas open/closed; usa o horario de atendimento), `set_var` (variavel = texto com variaveis), `tag` (aplica etiqueta na conversa).
- Historico de versoes do fluxo (`wa_flow_versions`, ultimas 20) com restaurar; exportar/importar JSON.
- Editor: desfazer/refazer, duplicar passo, mini-mapa, organizar automaticamente, encaixe em grade, atalhos, escolha de fila/etiqueta por lista.

## Compatibilidade
Conversas e fluxo salvo continuam validos (slugs das 4 filas preservados). Sem perda de dados na migracao; `downgrade` remove as tabelas novas.

## Testes
Servico (filas dinamicas, aviso, fallback, inatividade, motivos, tempos), API (CRUD de filas com bloqueios, historico/CSV/estatisticas, notas, etiquetas, versoes), motor (hours/set_var/tag), validador (fila inexistente), build do frontend e teste real.
