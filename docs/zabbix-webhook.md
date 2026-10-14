# Webhook de eventos em tempo real (Zabbix → NAVI)

## Para que serve
Sem o webhook a NAVI **já funciona**: o worker consulta a API do Zabbix a cada 60 s (`poll_events`) e registra PROBLEM/RESOLVED.
O webhook é opcional, mas melhora: o evento chega em **segundos** (não até 60 s depois) e o alerta por WhatsApp sai mais rápido.
A consulta por API continua como rede de segurança (se o webhook falhar, o evento entra pelo polling).

## Passo a passo
1. **NAVI** → Configurações → Webhook → *Gerar token* (aparece uma única vez).
2. **Zabbix** → Alerts → Media types → *Create media type*
   - Name: `NAVI Webhook` · Type: `Webhook`
   - Parameters (nome = valor):

     | Nome | Valor |
     |---|---|
     | url | `https://sonar.orcati.com.br/navi/api/webhook/zabbix` |
     | token | *(token gerado no passo 1)* |
     | eventid | `{EVENT.ID}` |
     | status | `{EVENT.STATUS}` |
     | hostid | `{HOST.ID}` |
     | host | `{HOST.NAME}` |
     | ip | `{HOST.IP}` |
     | triggerid | `{TRIGGER.ID}` |
     | trigger | `{EVENT.NAME}` |
     | itemid | `{ITEM.ID1}` |
     | item | `{ITEM.NAME1}` |
     | severity | `{EVENT.NSEVERITY}` |
     | opdata | `{EVENT.OPDATA}` |
     | r_eventid | `{EVENT.RECOVERY.ID}` |
     | tags | `{EVENT.TAGSJSON}` |

   - Script: conteúdo de `docs/zabbix-navi-webhook.js`
   - Aba *Message templates*: adicione **Problem** e **Problem recovery** (assunto `NAVI`, mensagem `{EVENT.NAME}`).
   - Salve e use o botão **Test** (deve retornar `OK`).
3. **Usuário técnico**: Users → Users → Create: `navi-webhook`, em um grupo com permissão *Read* em todos os host groups
   (o Zabbix só notifica usuários que enxergam o host). Aba *Media*: tipo `NAVI Webhook`, *Send to* `navi`, 24x7, todas as severidades.
4. **Action**: Alerts → Actions → Trigger actions → *Create action* `NAVI - eventos` (mesmas condições da action atual).
   - Operations: *Send message* → user `navi-webhook` → media type `NAVI Webhook`.
   - Recovery operations: o mesmo.
   - **Crie uma action nova** e deixe a atual (WA-AKG) intacta: as duas coexistem.
5. Confira em NAVI → Eventos: os novos eventos aparecem com origem `webhook`.

## Atenção: evitar mensagem duplicada
Enquanto a action antiga (Zabbix → WA-AKG) estiver ativa, mantenha **desligado** o "WhatsApp" dos clientes na NAVI.
Assim o webhook só registra o incidente (dashboard, SLA, relatórios) e o WhatsApp continua saindo pelo caminho atual.
Quando for migrar: ligue o WhatsApp do cliente na NAVI e desative a operação antiga dessa action.
