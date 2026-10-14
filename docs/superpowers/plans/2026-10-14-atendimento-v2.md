# Atendimento v2 Implementation Plan
> Execucao nativa autorizada ("faz as melhorias..."). Spec: `docs/superpowers/specs/2026-10-14-atendimento-v2-design.md`. Mesmos comandos de teste/build/commit dos planos anteriores; migrations 0031 (filas, etiquetas, versoes, campos) e seguintes.

## Review Focus
- Excluir/desativar fila em uso; renomear fila nao quebra conversas nem fluxo (slug estavel).
- Fluxo salvo referenciando fila apagada/desativada: cai na Geral em execucao e e recusado ao salvar.
- Historico com milhares de linhas: paginado; CSV limitado; periodo invertido tratado.
- Nota interna e eventos nunca saem pelo WhatsApp nem contam como nao lidos.

## Tasks
1. Filas no banco (modelo, migration 0031, servico dinamico, CRUD API, testes) + pagina Configuracoes (filas, respostas prontas, etiquetas, horario, geral) + navegacao do modulo.
2. Historico e indicadores (campos, API, CSV, pagina).
3. Caixa de entrada: abas, busca, etiquetas, nome do contato, notas e eventos.
4. Fluxo: passos hours/set_var/tag, versoes, editor (undo/redo, duplicar, minimapa, auto-layout, importar/exportar).
5. Implantacao, verificacao e push a cada etapa.
