# Gateway WhatsApp (WA-AKG) — Sub-projeto A

Data: 2026-10-14 · Status: aguardando revisão

## Contexto e visão geral

O objetivo maior é atendimento por WhatsApp no NAVI: menu tipo URA (comercial / financeiro / suporte), identificação do cliente por CNPJ, fila e monitor de atendimento, chat do analista dentro do NAVI, aviso a números/grupos quando alguém entra na fila, abertura automática de chamado e, por fim, um construtor visual de fluxos (gatilhos, ações, conectores).

Isso foi dividido em 4 sub-projetos, entregues em ordem, cada um com spec, plano e implementação próprios:

| # | Sub-projeto | Entrega |
|---|---|---|
| **A** | **Gateway WhatsApp (este documento)** | WA-AKG no ar, recepção de mensagens, envio, migração dos alertas da Evolution |
| B | Atendimento: fila e chat | Conversas, fila, monitor, atribuição, chat em tempo real, avisos de fila |
| C | Motor de fluxo | Executa menu, CNPJ, transferência para fila, abertura de chamado |
| D | Construtor visual | Canvas de blocos para montar/editar fluxos |

Este documento cobre **somente o A**.

## Decisões já tomadas

- O WA-AKG (https://github.com/mrifqidaffaaditya/WA-AKG, MIT, Next.js + Baileys + Prisma) **substitui** a Evolution API: alertas, resumo diário, avisos de chamado e atendimento passam todos por ele.
- Usa um **número novo e dedicado** (atendimento + alertas). Baileys é conexão não oficial: há risco de banimento; o número principal e os celulares da equipe ficam fora disso.
- Roda **nesta mesma máquina**, em Docker. A RAM será aumentada depois; até lá o container tem limite de memória.
- O chat do atendimento será dentro do NAVI (sub-projeto B). O A só armazena as mensagens recebidas.

## Abordagem escolhida: adaptador compatível com chave de troca

O NAVI usa a Evolution só por `factory.evolution(db)` (10 pontos), com interface pequena: `send_text(number, text, quoted_id, quoted_text)`, `send_document(number, pdf_bytes, filename, caption)`, `message_id(resp)`, `status()`, mais `normalize_target`. Criamos `WaAkgService` com a **mesma interface** e a `factory` escolhe o provedor pela configuração `whatsapp.provider` (`evolution` | `wa_akg`). Nenhum chamador muda; o rollback é trocar a configuração. O código da Evolution só é removido numa limpeza posterior, depois que o WA-AKG estiver estável.

Descartadas: reescrever todos os chamadores sobre uma nova abstração (risco alto, ganho baixo) e ler o banco do WA-AKG direto (acopla ao schema interno de terceiros).

## Componentes

### 1. Container `wa-akg`
- Serviço novo no `docker-compose.yml`, na mesma rede do `api`.
- Imagem construída a partir do repositório na **tag `v1.6.3`** (nunca `main`), via `build.context` apontando para o Git. O build do Next.js é pesado: como a RAM só sobe depois, o build roda aqui com um swapfile temporário de 3 GB, fora do horário de pico.
- `mem_limit` inicial ~600 MB; porta publicada apenas em `127.0.0.1`; `restart: unless-stopped`; logs com rotação como os demais.
- Banco: o WA-AKG v1.6.3 usa Prisma com provider `mysql` (não roda em Postgres). O Postgres do NAVI é remoto e não é usado. Sobe um container `wa-akg-db` (MariaDB 10.11 com buffer pool de 64 MB, `mem_limit` 256 MB), exclusivo do gateway e sem porta publicada. *(Correção feita durante o planejamento.)*
- Volume persistente para as sessões do Baileys (perder o volume exige novo pareamento por QR).
- Variáveis (`DATABASE_URL`, `AUTH_SECRET`, `BASE_URL`, senha do Swagger etc.) em `secrets/`/`.env`, fora do git. `/docs` (Swagger) desabilitado ou com senha trocada (padrão do projeto é `admin/admin123`).
- Painel do WA-AKG acessível só por túnel/Apache restrito; não exposto à internet.

### 2. `WaAkgService` (`backend/app/services/wa_akg_service.py`)
- Envio: `POST /api/messages/{sessão}/{jid}/send` com `X-API-Key`; texto, documento e resposta citada (`quoted`), com fallback sem citação como hoje.
- Converte o destino para JID (`<numero>@s.whatsapp.net`, grupos `@g.us`) reaproveitando `normalize_target`, incluindo a variação do 9º dígito brasileiro.
- `message_id(resp)` e `status()` (estado da sessão, QR quando pendente).
- Erros viram `EvolutionError`-equivalente comum (`WhatsAppError`), para os chamadores não mudarem tratamento.

### 3. Recepção de mensagens
- `POST /api/wa/webhook`: valida a assinatura (secret do webhook configurado no WA-AKG); rejeita se inválida.
- Deduplica pelo id externo da mensagem (reentrega do WA-AKG não duplica).
- Grava em `wa_messages` e chama um **gancho** (`on_inbound(message)`) que no A não faz nada além de registrar; B e C se plugam ali.
- Ignora eventos que não sejam mensagem (presença, status) e mensagens do próprio número (`fromMe`) além de armazená-las como saída.

### 4. Dados
Tabela `wa_messages`: `id`, `external_id` (único), `session`, `jid`, `direction` (`in`/`out`), `type`, `text`, `media_ref`, `raw` (JSON opcional, limitado), `created_at`. Índices em `jid, created_at` e em `external_id`. Migração Alembic `0028`.

### 5. Configurações
Em Configurações > WhatsApp: provedor ativo, URL e chave do WA-AKG (segredo criptografado como as demais), nome da sessão, secret do webhook, estado da sessão, QR code para parear e botão de teste de envio. Alterações auditadas.

### 6. Monitoramento
Estado da sessão WhatsApp na verificação de saúde já existente (`health_checks`, chave `evolution` mantida para não quebrar a tela), para os avisos não pararem em silêncio — hoje uma falha só vira log.

## Plano de migração
1. Subir o WA-AKG e parear o número novo (QR).
2. Teste de envio com a Evolution ainda como provedor ativo.
3. Trocar `whatsapp.provider` para `wa_akg`; validar um alerta real e um aviso de chamado.
4. Manter a configuração da Evolution por 1 semana como rollback; depois removê-la numa limpeza separada.

Os números/grupos de destino existentes (NOC, filas de chamado) continuam valendo; grupos precisam do novo número adicionado a eles.

## Segurança
- Webhook só aceita chamadas assinadas; endpoint sem sessão de usuário, protegido apenas pelo secret.
- Chave de API e secret do webhook guardados como as demais credenciais; nunca retornados pela API de configurações.
- Painel e Swagger do WA-AKG não expostos publicamente.
- Mensagens recebidas são dado não confiável: o A só armazena; nada é interpretado como comando.

## Testes
- Unitários do `WaAkgService` com HTTP simulado: envio de texto/documento, conversão de JID, 9º dígito, citação com fallback, erros HTTP/conexão.
- Webhook: assinatura inválida (401), duplicada (idempotente), mensagem válida, evento ignorado.
- `factory`: seleção do provedor por configuração e padrão `evolution` enquanto não migrado.
- Validação manual final: pareamento, envio real e recebimento real.

## Fora do escopo do A
Menu/URA, fila, chat, atribuição, avisos de fila, abertura de chamado e construtor visual (B, C, D). Disparo em massa/broadcast do WA-AKG não será usado.

## Riscos
- **Banimento do número** (conexão não oficial): número dedicado, sem envio em massa, volume baixo no início.
- **Memória** (hoje ~1,6 GB livres): limite no container, build só após o aumento de RAM.
- **Sessão expira/cai**: monitor de status e novo QR documentado.
- **Atualizações do WA-AKG** quebrando a API: versão fixada e upgrade só deliberado.
