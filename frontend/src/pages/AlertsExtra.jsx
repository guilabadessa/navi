import React, { useState } from 'react'
import { Pencil, Plus, Trash2, RefreshCw } from 'lucide-react'
import { get, post, put, del, SEV } from '../api'
import { Card, Check, Field, Loading, Modal, Pill, Table, useLoad, useToast } from '../ui'

function SevForm({ r, onClose, onSaved }) {
  const [x, setX] = useState({ name: '', host_pattern: '', trigger_pattern: '', from_max: 0, severity: 4, enabled: true, ...r }); const toast = useToast()
  const save = async () => {
    const b = { ...x, host_pattern: x.host_pattern || null, trigger_pattern: x.trigger_pattern || null, from_max: +x.from_max, severity: +x.severity }
    try { x.id ? await put('/severity-rules/' + x.id, b) : await post('/severity-rules', b); toast('Regra salva'); onSaved() } catch (e) { toast(e.message, true) }
  }
  return <Modal title={x.id ? 'Editar reclassificação' : 'Nova reclassificação'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" onClick={save}>Salvar</button></>}>
    <div className="row"><Field label="NOME"><input value={x.name} onChange={e => setX({ ...x, name: e.target.value })} placeholder="SD-WAN health = Alta" /></Field></div>
    <div className="row r2"><Field label="HOST CONTÉM (opcional)"><input value={x.host_pattern || ''} onChange={e => setX({ ...x, host_pattern: e.target.value })} /></Field>
      <Field label="TRIGGER CONTÉM" hint="Texto ou padrão com *. Informe host e/ou trigger."><input value={x.trigger_pattern || ''} onChange={e => setX({ ...x, trigger_pattern: e.target.value })} placeholder="health" /></Field></div>
    <div className="row r2"><Field label="SE A SEVERIDADE ORIGINAL FOR ATÉ" hint="Só eleva eventos que já estão neste nível ou abaixo."><select value={x.from_max} onChange={e => setX({ ...x, from_max: e.target.value })}>{SEV.map((s, i) => <option key={i} value={i}>{s}</option>)}</select></Field>
      <Field label="TRATAR COMO" hint="Nunca rebaixa a severidade do Zabbix."><select value={x.severity} onChange={e => setX({ ...x, severity: e.target.value })}>{SEV.map((s, i) => <option key={i} value={i}>{s}</option>)}</select></Field></div>
    <Check label="Regra ativa" checked={x.enabled} onChange={v => setX({ ...x, enabled: v })} /></Modal>
}

export function SeverityTab({ edit }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/severity-rules'), []); const [ed, setEd] = useState(null)
  const reapply = async () => { try { const r = await post('/severity-rules/reapply'); toast(`${r.changed} evento(s) reclassificado(s)`) } catch (e) { toast(e.message, true) } }
  return <>
    <div className="banner info"><div className="grow">Ajuste a severidade <b>na NAVI</b> (o Zabbix não é alterado). Ex.: triggers de SD-WAN chegam como “Não classificado” e podem ser tratadas como <b>Alta</b>, passando a alertar, entrar no SLA e nos relatórios.</div>
      {edit && <><button className="btn sm" onClick={reapply} title="Aplica as regras aos eventos já gravados"><RefreshCw />Reaplicar nos eventos existentes</button><button className="btn primary sm" onClick={() => setEd({})}><Plus />Nova</button></>}</div>
    <Card pad={false}>{data ? <Table rows={data} empty="Nenhuma reclassificação cadastrada." cols={[
      { h: 'Regra', r: r => <b>{r.name}</b> }, { h: 'Host', r: r => r.host_pattern || '*' }, { h: 'Trigger', r: r => r.trigger_pattern || '*' },
      { h: 'De', r: r => '≤ ' + SEV[r.from_max] }, { h: 'Para', r: r => <b>{SEV[r.severity]}</b> }, { h: 'Estado', r: r => <Pill tone={r.enabled ? 'ok' : 'mut'}>{r.enabled ? 'ativa' : 'desligada'}</Pill> },
      { h: '', r: r => edit && <div style={{ display: 'flex', gap: 6 }}><button className="btn sm" onClick={() => setEd(r)}><Pencil /></button>
        <button className="btn sm danger" onClick={async () => { if (confirm('Excluir regra?')) { await del('/severity-rules/' + r.id); reload() } }}><Trash2 /></button></div> }]} /> : <Loading />}</Card>
    {ed && <SevForm r={ed} onClose={() => setEd(null)} onSaved={() => { setEd(null); reload() }} />}</>
}

export function MigrationTab({ edit }) {
  const toast = useToast(); const sh = useLoad(() => get('/alerts/shadow'), []); const clients = useLoad(() => get('/clients'), [])
  const set = async (v) => { try { await put('/alerts/shadow', { shadow: v }); toast(v ? 'Modo sombra ativado: nada será enviado' : 'Modo sombra desativado: alertas voltam a ser enviados'); sh.reload() } catch (e) { toast(e.message, true) } }
  return <>
    <Card title="Modo sombra" style={{ marginBottom: 16 }}>
      <p style={{ marginTop: 0 }}>Enquanto o Zabbix ainda envia os alertas antigos para o WhatsApp, ative o <b>modo sombra</b>: a NAVI avalia as regras e registra o que <i>enviaria</i> (visível em Eventos → detalhes, status “ignorado”), mas <b>não envia nada</b>. Compare com o que chegou do Zabbix e, quando estiver igual, desative o modo sombra.</p>
      {sh.data ? <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}><Pill tone={sh.data.shadow ? 'warn' : 'ok'}>{sh.data.shadow ? 'Modo sombra ATIVO — nenhum alerta é enviado' : 'Envio normal'}</Pill>
        {edit && <button className={'btn ' + (sh.data.shadow ? 'primary' : '')} onClick={() => set(!sh.data.shadow)}>{sh.data.shadow ? 'Desativar e voltar a enviar' : 'Ativar modo sombra'}</button>}</div> : <Loading />}
    </Card>
    <Card title="Checklist de migração por cliente" pad={false}>
      <div className="sub" style={{ padding: '10px 20px 0' }}>Para evitar mensagem duplicada, só ative o WhatsApp de um cliente na NAVI depois de <b>desativar a operação dele na action antiga do Zabbix</b> (ou use o modo sombra para validar antes).</div>
      {clients.data ? <Table rows={clients.data} empty="Nenhum cliente cadastrado." cols={[
        { h: 'Cliente', r: r => <b>{r.trade_name}</b> }, { h: 'Host groups', r: r => r.group_count ? <Pill tone="ok">{r.group_count}</Pill> : <Pill tone="bad">nenhum</Pill> },
        { h: 'Destino WhatsApp', r: r => r.whatsapp_group_jid || r.whatsapp ? <Pill tone="ok">definido</Pill> : <Pill tone="bad">sem destino</Pill> },
        { h: 'WhatsApp NAVI', r: r => r.wa_enabled ? <Pill tone="ok">ativo</Pill> : <Pill>desligado</Pill> }, { h: 'E-mail NAVI', r: r => r.mail_enabled ? <Pill tone="ok">ativo</Pill> : <Pill>desligado</Pill> },
        { h: 'Próximo passo', r: r => !r.group_count ? 'Associar host groups' : !(r.whatsapp_group_jid || r.whatsapp) ? 'Definir grupo/celular' : !r.wa_enabled ? 'Validar em modo sombra → ativar' : 'Confirmar que a action antiga do Zabbix foi desligada' }]} /> : <Loading />}
    </Card></>
}
