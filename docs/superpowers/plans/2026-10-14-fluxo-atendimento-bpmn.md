# Fluxo de atendimento BPMN Implementation Plan

> **For agentic workers:** execucao nativa (superpowers:executing-plans), autorizada pelo usuario ("implante o fluxo padrao BPMN... deixe tudo editavel").

**Goal:** Substituir o menu fixo do B por um fluxo editavel (diagrama BPMN) com CNPJ, chamado e simulador.
**Architecture:** `flow_engine` puro (Host injetado) + `flow_service` (fluxo padrao, validador, persistencia em `wa_flows`) + integracao no `atendimento_service` + API + pagina React Flow.
**Tech Stack:** FastAPI, SQLAlchemy, Alembic 0030, React + @xyflow/react.
**Spec:** `docs/superpowers/specs/2026-10-14-fluxo-atendimento-bpmn-design.md`

## Global Constraints
- Mesmos comandos de teste/build/commit do plano do B. Migration 0030 (`wa_flows`; `wa_conversations.flow_node`, `.flow_vars`).
- Tipos de no e saidas exatamente como na spec. Fila fallback: `geral`.

## Review Focus
- Cliente responde fora do esperado em `ask`/`menu` repetidamente: nunca laco infinito nem silencio (cai na fila Geral).
- Fluxo editado enquanto ha conversa em andamento em no que sumiu: cai na fila Geral.
- CNPJ digitado com pontuacao/espacos, com letras, com todos os digitos iguais.
- Fluxo salvo com laco so de nos automaticos: recusado.
- Simulador nunca cria chamado real nem envia mensagem.

## Tasks
1. Motor puro `services/flow_engine.py` + testes (todos os tipos, tentativas, timeout, limite de passos).
2. `services/flow_service.py`: `DEFAULT_FLOW`, `validate_flow`, `load_flow(db)`, `save_flow`, `cnpj_valid`, `find_client_by_cnpj`; migration 0030, modelos `WaFlow` e colunas da conversa; testes do validador e do fluxo padrao ponta a ponta (simulador).
3. `ticket_service.create_from_whatsapp` + `RealHost`/`SimHost` e integracao no `atendimento_service` (`handle_inbound`, `tick`) removendo o menu fixo; atualizar testes do B.
4. API `/flow`, `/flow/validate`, `/flow/reset`, `/flow/simulate`.
5. Frontend: dependencia `@xyflow/react`, pagina `AtendimentoFluxo.jsx` (canvas, paleta, inspetor, validacao, simulador), rota/menu; Configuracoes do B sem saudacao.
6. Implantacao, teste real pelo celular, push.
