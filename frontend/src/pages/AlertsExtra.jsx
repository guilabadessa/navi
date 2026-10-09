import React, { useState } from 'react'
import { FlaskConical, Pencil, Plus, Trash2, RefreshCw } from 'lucide-react'
import { get, post, put, del, SEV } from '../api'
import { Card, Check, Field, Loading, Modal, Pill, Table, useLoad, useToast } from '../ui'
import { maskTarget } from '../mask'

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

const DAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
const toLocalInput = (v) => { if (!v) return ''; const d = new Date(v); const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}` }

function WindowForm({ w, clients, onClose, onSaved }) {
  const [x, setX] = useState({ name: '', client_id: '', kind: 'once', start_at: '', end_at: '', weekdays: [6], start_time: '02:00', duration_min: 120, enabled: true, ...w, start_at: toLocalInput(w.start_at), end_at: toLocalInput(w.end_at) }); const toast = useToast()
  const save = async () => {
    const b = { name: x.name, client_id: x.client_id ? +x.client_id : null, kind: x.kind, enabled: x.enabled,
      start_at: x.kind === 'once' && x.start_at ? new Date(x.start_at).toISOString() : null, end_at: x.kind === 'once' && x.end_at ? new Date(x.end_at).toISOString() : null,
      weekdays: x.kind === 'weekly' ? x.weekdays : null, start_time: x.kind === 'weekly' ? x.start_time : null, duration_min: x.kind === 'weekly' ? +x.duration_min : null }
    try { x.id ? await put('/maintenance/' + x.id, b) : await post('/maintenance', b); toast('Janela salva'); onSaved() } catch (e) { toast(e.message, true) }
  }
  const tg = (i) => setX({ ...x, weekdays: x.weekdays.includes(i) ? x.weekdays.filter(d => d !== i) : [...x.weekdays, i].sort() })
  return <Modal title={x.id ? 'Editar janela de manutenção' : 'Nova janela de manutenção'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" onClick={save}>Salvar</button></>}>
    <div className="row r2"><Field label="NOME"><input value={x.name} onChange={e => setX({ ...x, name: e.target.value })} placeholder="Manutenção semanal do firewall" /></Field>
      <Field label="CLIENTE"><select value={x.client_id || ''} onChange={e => setX({ ...x, client_id: e.target.value })}><option value="">Todos os clientes</option>{clients.map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select></Field></div>
    <div className="row"><Field label="TIPO"><select value={x.kind} onChange={e => setX({ ...x, kind: e.target.value })}><option value="once">Pontual (data e hora)</option><option value="weekly">Recorrente (toda semana)</option></select></Field></div>
    {x.kind === 'once' ? <div className="row r2"><Field label="INÍCIO"><input type="datetime-local" value={x.start_at} onChange={e => setX({ ...x, start_at: e.target.value })} /></Field>
      <Field label="FIM"><input type="datetime-local" value={x.end_at} onChange={e => setX({ ...x, end_at: e.target.value })} /></Field></div>
      : <><div className="row"><div><label className="f">DIAS DA SEMANA</label><div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{DAYS.map((n, i) => <button key={n} type="button" className={'btn sm ' + (x.weekdays.includes(i) ? 'primary' : '')} onClick={() => tg(i)}>{n}</button>)}</div></div></div>
        <div className="row r2"><Field label="HORÁRIO DE INÍCIO"><input type="time" value={x.start_time} onChange={e => setX({ ...x, start_time: e.target.value })} /></Field>
          <Field label="DURAÇÃO (MINUTOS)"><input type="number" min="1" max="1440" value={x.duration_min} onChange={e => setX({ ...x, duration_min: e.target.value })} /></Field></div></>}
    <p className="hint">Durante a janela os alertas do cliente são suprimidos e o período é <b>descontado do SLA</b> e dos relatórios.</p>
    <Check label="Janela ativa" checked={x.enabled} onChange={v => setX({ ...x, enabled: v })} /></Modal>
}

export function MaintenanceTab({ edit }) {
  const { data, reload } = useLoad(() => get('/maintenance'), [], 60000); const clients = useLoad(() => get('/clients'), []); const [ed, setEd] = useState(null)
  const fmt = (v) => v ? new Date(v).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '—'
  return <>
    <div className="banner info"><div className="grow">Agende manutenções combinadas com o cliente (pontuais ou toda semana). Os alertas ficam em silêncio e o tempo é descontado do SLA. Para um aviso imediato, use o botão de manutenção de 2h no dashboard.</div>
      {edit && <button className="btn primary sm" onClick={() => setEd({})}><Plus />Nova janela</button>}</div>
    <Card pad={false}>{data ? <Table rows={data} empty="Nenhuma janela cadastrada." cols={[
      { h: 'Janela', r: r => <b>{r.name}</b> }, { h: 'Cliente', r: r => r.client_name || 'Todos' },
      { h: 'Quando', r: r => r.kind === 'weekly' ? `${(r.weekdays || []).map(i => DAYS[i]).join(', ')} às ${r.start_time} (${r.duration_min} min)` : `${fmt(r.start_at)} → ${fmt(r.end_at)}` },
      { h: 'Próxima', r: r => r.active ? <Pill tone="warn">em andamento</Pill> : r.next?.length ? fmt(r.next[0]) : <span className="sub">—</span> },
      { h: 'Estado', r: r => <Pill tone={r.enabled ? 'ok' : 'mut'}>{r.enabled ? 'ativa' : 'desligada'}</Pill> },
      { h: '', r: r => edit && <div style={{ display: 'flex', gap: 6 }}><button className="btn sm" onClick={() => setEd(r)}><Pencil /></button>
        <button className="btn sm danger" onClick={async () => { if (confirm('Excluir janela?')) { await del('/maintenance/' + r.id); reload() } }}><Trash2 /></button></div> }]} /> : <Loading />}</Card>
    {ed && clients.data && <WindowForm w={ed} clients={clients.data} onClose={() => setEd(null)} onSaved={() => { setEd(null); reload() }} />}</>
}

export function NocTab({ edit }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/noc-settings'), []); const [x, setX] = useState(null); const [tb, setTb] = useState(false)
  React.useEffect(() => { if (data && !x) setX(data) }, [data]) // eslint-disable-line
  if (!x) return <Loading />
  const set = (k, v) => setX({ ...x, [k]: v })
  const save = async () => { try { await put('/noc-settings', x); toast('Configurações do NOC salvas'); reload() } catch (e) { toast(e.message, true) } }
  const test = async (what) => { if (tb) return; setTb(true); try { const r = await post('/noc-settings/test', { what }); toast(r.result) } catch (e) { toast(e.message, true) } finally { setTb(false) } }
  return <div style={{ display: 'grid', gap: 16 }}>
    <Card title="Canal interno do NOC" actions={edit && <button className="btn sm" disabled={tb} onClick={() => test('message')}><FlaskConical />Enviar teste</button>}>
      <p className="sub" style={{ marginTop: 0 }}>Destinos da equipe Orca TI (não são enviados a clientes): escalonamentos e resumo diário.</p>
      <div className="row r2"><Field label="GRUPO DE WHATSAPP DO NOC" hint="JID do grupo (…@g.us) ou número com DDD."><input value={x.noc_wa || ''} onChange={e => set('noc_wa', maskTarget(e.target.value))} placeholder="120363…@g.us" disabled={!edit} /></Field>
        <Field label="E-MAILS DO NOC" hint="Separe por vírgula ou ponto e vírgula."><input value={x.noc_emails || ''} onChange={e => set('noc_emails', e.target.value)} placeholder="noc@orcati.com.br" disabled={!edit} /></Field></div></Card>
    <Card title="Escalonamento de alertas">
      <p className="sub" style={{ marginTop: 0 }}>Se um problema continuar <b>sem recuperação</b> depois do prazo, o NOC é avisado novamente (uma única vez por evento). Não escalona clientes em manutenção nem eventos reconhecidos no Zabbix.</p>
      <Check label="Ativar escalonamento" checked={x.escalation_enabled} onChange={v => set('escalation_enabled', v)} />
      <div className="row r2" style={{ marginTop: 12 }}><Field label="ESCALONAR APÓS (MINUTOS)"><input type="number" min="1" value={x.escalation_minutes} onChange={e => set('escalation_minutes', +e.target.value)} disabled={!edit} /></Field>
        <Field label="SOMENTE SEVERIDADE"><select value={x.escalation_min_severity} onChange={e => set('escalation_min_severity', +e.target.value)} disabled={!edit}>{SEV.map((s, i) => <option key={i} value={i}>{s} ou maior</option>)}</select></Field></div></Card>
    <Card title="Agrupamento de alertas (tempestade)">
      <p className="sub" style={{ marginTop: 0 }}>Quando vários hosts do mesmo cliente caem juntos (ex.: queda de energia), a NAVI envia <b>uma mensagem única</b> com a lista, em vez de uma por host. O mesmo vale para as recuperações.</p>
      <Check label="Agrupar alertas simultâneos" checked={x.storm_enabled} onChange={v => set('storm_enabled', v)} />
      <div className="row r2" style={{ marginTop: 12 }}><Field label="AGRUPAR A PARTIR DE (ALERTAS)"><input type="number" min="2" value={x.storm_threshold} onChange={e => set('storm_threshold', +e.target.value)} disabled={!edit} /></Field>
        <Field label="ESPERA PARA JUNTAR (SEGUNDOS)" hint="Atraso curto antes de enviar, para reunir os alertas. Quedas que se resolvem nesse tempo nem chegam a ser enviadas."><input type="number" min="0" max="120" value={x.storm_hold_s} onChange={e => set('storm_hold_s', +e.target.value)} disabled={!edit} /></Field></div></Card>
    <Card title="Resumo diário do NOC" actions={edit && <button className="btn sm" disabled={tb} onClick={() => test('digest')}><FlaskConical />Enviar agora</button>}>
      <p className="sub" style={{ marginTop: 0 }}>Todos os dias, no horário escolhido: problemas em aberto por cliente, movimento das últimas 24h, falhas de envio e saúde das integrações.</p>
      <Check label="Enviar resumo diário" checked={x.digest_enabled} onChange={v => set('digest_enabled', v)} />
      <div className="row r2" style={{ marginTop: 12 }}><Field label="HORÁRIO"><input type="time" value={x.digest_time} onChange={e => set('digest_time', e.target.value)} disabled={!edit} /></Field>
        <div><label className="f">ÚLTIMO ENVIO</label><div className="sub" style={{ paddingTop: 8 }}>{x.digest_status || 'ainda não enviado'}</div></div></div></Card>
    {edit && <div><button className="btn primary" onClick={save}>Salvar configurações</button></div>}</div>
}
