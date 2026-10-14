# Operação do atendimento por WhatsApp

- **Número:** pareado no WA-AKG (sessão `orca`). Conexão em Configurações > WhatsApp (WA-AKG). A Evolution foi removida do NAVI.
- **Fluxo:** Atendimento > "Fluxo de atendimento". Salvar vale para as próximas mensagens; conversas em andamento seguem o passo em que estão (se o passo foi removido, vão para a fila Geral). "Restaurar padrão" volta ao fluxo original.
- **Filas e avisos:** Configurações > Atendimento (destinos por fila, tempo de espera em alerta, inatividade, respostas prontas).
- **Encerramento automático:** sem mensagem de ninguém por 24 h (configurável; 0 desliga) a conversa em fila ou em atendimento é encerrada com aviso ao cliente. Menus de retorno e perguntas aceitam "0" para voltar.
- **Bot nativo do WA-AKG:** mantido inerte (lista de números vazia). Se o painel do WA-AKG for recriado, repetir: modo "específico" sem números, e desligar ping/uptime/figurinhas.
- **Botões de balão:** não disponíveis. O Baileys não envia botões de resposta rápida de forma confiável e o WA-AKG não repassa o voto de enquete pelo webhook (testado na leitura do código v1.6.3). O menu é por texto numerado.
- **Diagnóstico:** `docker compose logs api | grep -i atendimento`; mensagens ficam em `wa_messages`, conversas em `wa_conversations`, fluxo salvo em `wa_flows`.

## Atendimento v2 (filas editáveis, histórico, caixa de entrada)
- **Telas** (menu Atendimento): Conversas (abas Fila/Meus/Todos/Encerradas, busca, etiquetas, notas internas, linha do tempo), Histórico (filtros, indicadores, CSV), Fluxo (editor BPMN) e Configurações (Filas, Etiquetas, Horário, Respostas prontas, Geral).
- **Filas:** criadas/editadas em Configurações > Filas. O slug nunca muda ao renomear. A fila Geral é do sistema (fallback). Excluir só é possível sem conversas abertas e sem uso no fluxo.
- **Fluxo:** passos novos Horário de atendimento, Definir variável e Aplicar etiqueta; versões (últimas 20) em "Versões"; exportar/importar JSON; desfazer/refazer, duplicar, organizar.
- **Evolution:** removida (código, configuração e telas). Não existe provedor alternativo ao WA-AKG.
