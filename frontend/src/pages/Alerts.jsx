import React, { useEffect, useState } from 'react'
import { FlaskConical, Plus, Pencil, Trash2 } from 'lucide-react'
import { get, post, put, del, fmtDT, SEV } from '../api'
import { SeverityTab, MigrationTab } from './AlertsExtra'
import { Card, Check, Field, Loading, Modal, PageHead, Pill, Table, Tabs, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'
import { maskTarget } from '../mask'

const DELAYS = [[0, 'Imediato'], [60, '1 minuto'], [120, '2 minutos'], [300, '5 minutos'], [600, '10 minutos'], [900, '15 minutos']]
const MACROS = ['{CLIENTE}', '{HOST}', '{HOST.IP}', '{TRIGGER.NAME}', '{ITEM.NAME}', '{SEVERIDADE}', '{OPDATA}', '{EVENT.DATE}', '{EVENT.TIME}', '{PROBLEM.TIME}', '{RECOVERY.TIME}', '{DURATION}', '{TAGS}']

function RuleForm({ r, clients, tpls, onClose, onSaved }) {
  const [x, setX] = useState({ name: '', client_id: null, host_pattern: '', trigger_pattern: '', severities: [], min_severity: 3, on_problem: true, on_recovery: true, delay_s: 0, dest_jid: '', problem_template_id: null, recovery_template_id: null, quote_recovery: true, notify_whatsapp: true, notify_email: false, email_to: '', enabled: true, ...r })
  const toast = useToast(); const set = k => e => setX({ ...x, [k]: e.target ? e.target.value : e })
  const num = k => e => setX({ ...x, [k]: e.target.value === '' ? null : Number(e.target.value) })
  const sevs = x.severities || []
  const toggleSev = i => setX({ ...x, severities: sevs.includes(i) ? sevs.filter(s => s !== i) : [...sevs, i] })
  const [tw, setTw] = useState(''); const [te, setTe] = useState(''); const [tres, setTres] = useState(null); const [testing, setTesting] = useState(false)
  const payload = () => ({ ...x, severities: sevs.length ? sevs : null, dest_jid: x.dest_jid || null, host_pattern: x.host_pattern || null, trigger_pattern: x.trigger_pattern || null, email_to: x.email_to || null })
  const save = async () => { try { const b = payload(); x.id ? await put('/alerts/rules/' + x.id, b) : await post('/alerts/rules', b); toast('Regra salva'); onSaved() } catch (e) { toast(e.message, true) } }
  const test = async () => { setTesting(true); setTres(null); try { setTres(await post('/alerts/test-rule', { ...payload(), to_whatsapp: tw || null, to_email: te || null })) } catch (e) { toast(e.message, true) } finally { setTesting(false) } }
  const cl = clients.find(c => c.id === x.client_id)
  return <Modal wide title={x.id ? 'Editar regra de alerta' : 'Nova regra de alerta'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" onClick={save}>Salvar</button></>}>
    <div className="row r2"><Field label="NOME *"><input value={x.name} onChange={set('name')} placeholder="Link caiu — todos os clientes" /></Field>
      <Field label="CLIENTE" hint={x.client_id ? '' : 'Todos os clientes: a regra vale para qualquer cliente e cada um recebe no seu próprio grupo/celular/e-mail.'}><select value={x.client_id || ''} onChange={num('client_id')}><option value="">Todos os clientes</option>{clients.map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select></Field></div>
    <div className="row r2"><Field label="HOST (contém / curinga *)" hint="Vazio = todos os hosts."><input value={x.host_pattern || ''} onChange={set('host_pattern')} placeholder="ex.: FortiGate" /></Field>
      <Field label="TRIGGER (contém / curinga *)" hint="Ex.: “link” pega ‘ICMP Ping: Link Indisponível’ e ‘Interface…: Link down’. Vazio = qualquer trigger."><input value={x.trigger_pattern || ''} onChange={set('trigger_pattern')} placeholder="ex.: link" /></Field></div>
    <div className="row r3"><Field label="SEVERIDADE MÍNIMA" hint="“Média” = Média, Alta e Desastre."><select value={x.min_severity} onChange={num('min_severity')}>{SEV.map((s, i) => <option key={i} value={i}>{s} ou maior</option>)}</select></Field>
      <Field label="ENVIAR SE O PROBLEMA PERSISTIR POR"><select value={DELAYS.some(d => d[0] === x.delay_s) ? x.delay_s : 'c'} onChange={e => e.target.value !== 'c' && setX({ ...x, delay_s: +e.target.value })}>{DELAYS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}<option value="c">Personalizado…</option></select></Field>
      <Field label="ATRASO PERSONALIZADO (segundos)"><input type="number" min="0" value={x.delay_s} onChange={num('delay_s')} /></Field></div>
    <details style={{ marginBottom: 14 }}><summary style={{ cursor: 'pointer', fontWeight: 600, color: 'var(--blue)' }}>Filtrar por severidades específicas (opcional)</summary>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 10 }}>{SEV.map((s, i) => <Check key={i} label={s} checked={sevs.includes(i)} onChange={() => toggleSev(i)} />)}</div>
      <p className="hint">Se marcar severidades aqui, elas substituem a “severidade mínima”.</p></details>
    <h3 style={{ fontSize: 15, margin: '6px 0 10px' }}>Canais e destinos</h3>
    <div className="grid g2" style={{ marginBottom: 14 }}>
      <div className="card" style={{ padding: 14 }}><Check label="WhatsApp" checked={x.notify_whatsapp} onChange={v => setX({ ...x, notify_whatsapp: v })} />
        <input style={{ marginTop: 8 }} disabled={!x.notify_whatsapp} value={x.dest_jid || ''} onChange={e => setX({ ...x, dest_jid: maskTarget(e.target.value) })} placeholder="Vazio = grupo/celular do cliente do evento" />
        <div className="hint">Para fixar um destino: celular com DDD (o 55 é adicionado) ou JID do grupo (…@g.us).</div></div>
      <div className="card" style={{ padding: 14 }}><Check label="E-mail" checked={x.notify_email} onChange={v => setX({ ...x, notify_email: v })} />
        <input style={{ marginTop: 8 }} disabled={!x.notify_email} value={x.email_to || ''} onChange={set('email_to')} placeholder="Vazio = e-mails de alerta do cliente do evento" />
        <div className="hint">Vários endereços separados por vírgula.</div></div></div>
    <div className="row" style={{ display: 'flex', gap: 22, flexWrap: 'wrap' }}><Check label="Avisar PROBLEM" checked={x.on_problem} onChange={v => setX({ ...x, on_problem: v })} /><Check label="Avisar RESOLVED (recuperação)" checked={x.on_recovery} onChange={v => setX({ ...x, on_recovery: v })} /><Check label="Recuperação como resposta (WhatsApp)" checked={x.quote_recovery} onChange={v => setX({ ...x, quote_recovery: v })} /></div>
    <div className="row r2"><Field label="TEMPLATE DE ALERTA (WhatsApp)"><select value={x.problem_template_id || ''} onChange={num('problem_template_id')}><option value="">Padrão</option>{tpls.filter(t => t.kind === 'problem').map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
      <Field label="TEMPLATE DE RECUPERAÇÃO (WhatsApp)"><select value={x.recovery_template_id || ''} onChange={num('recovery_template_id')}><option value="">Padrão</option>{tpls.filter(t => t.kind === 'recovery').map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field></div>
    <Check label="Regra habilitada" checked={x.enabled} onChange={v => setX({ ...x, enabled: v })} />
    <div className="card" style={{ padding: 16, marginTop: 18, background: '#f8faff' }}><h3 style={{ fontSize: 15, marginBottom: 4 }}>🧪 Testar esta regra</h3>
      <p className="hint" style={{ marginBottom: 10 }}>Envia um alerta de exemplo (identificado como teste) pelos canais marcados, usando um evento real parecido, sem criar incidente. Preencha os campos abaixo para enviar a um destino específico.</p>
      <div className="row r2" style={{ marginBottom: 10 }}><Field label="WHATSAPP DE TESTE (opcional)"><input value={tw} onChange={e => setTw(maskTarget(e.target.value))} placeholder="(14) 99999-9999 ou grupo@g.us" disabled={!x.notify_whatsapp} /></Field>
        <Field label="E-MAIL DE TESTE (opcional)"><input value={te} onChange={e => setTe(e.target.value)} placeholder="voce@orcati.com.br" disabled={!x.notify_email} /></Field></div>
      <button className="btn primary" disabled={testing || (!x.notify_whatsapp && !x.notify_email)} onClick={test}>{testing ? 'Enviando…' : 'Enviar teste'}</button>
      {tres && <div style={{ marginTop: 12, display: 'grid', gap: 6 }}>
        {['whatsapp', 'email', 'aviso'].filter(k => tres[k]).map(k => <div key={k}><Pill tone={tres[k].ok ? 'ok' : 'bad'}>{k === 'whatsapp' ? 'WhatsApp' : k === 'email' ? 'E-mail' : 'Aviso'}</Pill> <span className="sub">{tres[k].detail}</span></div>)}
        <div className="hint">Evento usado: {tres.evento_usado.host} — {tres.evento_usado.trigger} ({tres.evento_usado.severidade})</div></div>}</div>
  </Modal>
}

function TemplateForm({ t, onClose, onSaved }) {
  const [x, setX] = useState({ name: '', kind: 'problem', body: '', is_default: false, ...t }); const [prev, setPrev] = useState(''); const toast = useToast()
  const preview = async () => { try { setPrev((await post('/alerts/templates/preview', x)).text) } catch (e) { toast(e.message, true) } }
  const save = async () => { try { x.id ? await put('/alerts/templates/' + x.id, x) : await post('/alerts/templates', x); toast('Template salvo'); onSaved() } catch (e) { toast(e.message, true) } }
  return <Modal wide title={x.id ? 'Editar template' : 'Novo template'} onClose={onClose} footer={<><button className="btn" onClick={preview}>Pré-visualizar</button><button className="btn primary" onClick={save}>Salvar</button></>}>
    <div className="row r3"><Field label="NOME"><input value={x.name} onChange={e => setX({ ...x, name: e.target.value })} /></Field>
      <Field label="TIPO"><select value={x.kind} onChange={e => setX({ ...x, kind: e.target.value })}><option value="problem">Alerta (PROBLEM)</option><option value="recovery">Recuperação (RESOLVED)</option></select></Field>
      <div style={{ paddingTop: 22 }}><Check label="Padrão do tipo" checked={x.is_default} onChange={v => setX({ ...x, is_default: v })} /></div></div>
    <div className="grid g2"><Field label="MENSAGEM"><textarea style={{ minHeight: 330, fontFamily: 'ui-monospace,monospace', fontSize: 13.5 }} value={x.body} onChange={e => setX({ ...x, body: e.target.value })} /></Field>
      <div><label className="f">PRÉ-VISUALIZAÇÃO (WhatsApp)</label><div style={{ background: '#e7f6dc', borderRadius: 14, padding: 16, minHeight: 330, whiteSpace: 'pre-wrap', fontSize: 14.5 }}>{prev || 'Clique em “Pré-visualizar”.'}</div></div></div>
    <div style={{ marginTop: 12 }}><span className="sub">Macros: </span>{MACROS.map(m => <span key={m} className="chip" style={{ cursor: 'pointer' }} onClick={() => setX({ ...x, body: x.body + m })}>{m}</span>)}</div></Modal>
}

export default function Alerts() {
  const me = useAuth(); const toast = useToast(); const [tab, setTab] = useState('rules'); const [ed, setEd] = useState(null); const [ted, setTed] = useState(null)
  const rules = useLoad(() => get('/alerts/rules'), []); const tpls = useLoad(() => get('/alerts/templates'), []); const clients = useLoad(() => get('/clients'), [])
  const edit = can(me, 'alerts.edit')
  return <>
    <PageHead title="Alertas" desc="Regras personalizadas, templates de mensagem e política de envio">
      {edit && tab === 'rules' && <button className="btn primary" onClick={() => setEd({})}><Plus />Nova regra</button>}
      {edit && tab === 'tpl' && <button className="btn primary" onClick={() => setTed({})}><Plus />Novo template</button>}</PageHead>
    <Tabs value={tab} onChange={setTab} tabs={[['rules', 'Regras'], ['sev', 'Severidades'], ['tpl', 'Templates de mensagem'], ['mig', 'Migração / modo sombra']]} />
    {tab === 'rules' && <Card pad={false}>{rules.data ? <Table rows={rules.data} empty="Nenhuma regra personalizada. Os clientes usam a configuração padrão de WhatsApp definida no cadastro." cols={[
      { h: 'Regra', r: r => <b>{r.name}</b> }, { h: 'Cliente', r: r => r.client_name || 'Todos' }, { h: 'Host', r: r => r.host_pattern || '*' }, { h: 'Trigger', r: r => r.trigger_pattern || '*' },
      { h: 'Severidade', r: r => r.severities ? r.severities.map(s => SEV[s]).join(', ') : '≥ ' + SEV[r.min_severity] }, { h: 'Atraso', r: r => r.delay_s ? r.delay_s + 's' : 'imediato' },
      { h: 'Canais', r: r => <>{r.notify_whatsapp && <Pill tone="ok">WhatsApp</Pill>} {r.notify_email && <Pill tone="info">E-mail</Pill>}</> }, { h: 'Envia', r: r => [r.on_problem && 'PROBLEM', r.on_recovery && 'RESOLVED'].filter(Boolean).join(' + ') }, { h: 'Estado', r: r => <Pill tone={r.enabled ? 'ok' : 'mut'}>{r.enabled ? 'ativa' : 'desligada'}</Pill> },
      { h: 'Últimas 24h', r: r => { const s = r.stats_24h || {}; const t = Object.values(s).reduce((a, b) => a + b, 0); return t ? <span title={JSON.stringify(s)}><b>{s.sent || 0}</b> env.{s.failed ? <> · <span style={{ color: 'var(--crit)' }}>{s.failed} falha(s)</span></> : null}</span> : <span className="sub">sem disparos</span> } },
      { h: '', r: r => edit && <div style={{ display: 'flex', gap: 6 }}><button className="btn sm" title="Enviar teste desta regra" onClick={async () => { try { const { id, created_at, client_name, stats_24h, ...b } = r; const o = await post('/alerts/test-rule', b); toast(['whatsapp', 'email', 'aviso'].filter(k => o[k]).map(k => `${k}: ${o[k].detail}`).join(' · '), !['whatsapp', 'email'].some(k => o[k]?.ok)) } catch (e) { toast(e.message, true) } }}><FlaskConical /></button><button className="btn sm" onClick={() => setEd(r)}><Pencil /></button><button className="btn sm danger" onClick={async () => { if (confirm('Excluir regra?')) { await del('/alerts/rules/' + r.id); rules.reload() } }}><Trash2 /></button></div> }]} /> : <Loading />}</Card>}
    {tab === 'sev' && <SeverityTab edit={edit} />}
    {tab === 'mig' && <MigrationTab edit={edit} />}
    {tab === 'tpl' && <Card pad={false}>{tpls.data ? <Table rows={tpls.data} cols={[{ h: 'Template', r: r => <b>{r.name}</b> }, { h: 'Tipo', r: r => <Pill tone={r.kind === 'problem' ? 'bad' : 'ok'}>{r.kind === 'problem' ? 'alerta' : 'recuperação'}</Pill> }, { h: 'Padrão', r: r => r.is_default ? <Pill tone="info">padrão</Pill> : '' },
      { h: 'Prévia', r: r => <div className="trunc" style={{ maxWidth: 420 }}>{r.body.replace(/\n+/g, ' ')}</div> },
      { h: '', r: r => edit && <div style={{ display: 'flex', gap: 6 }}><button className="btn sm" onClick={() => setTed(r)}><Pencil /></button>{!r.is_default && <button className="btn sm danger" onClick={async () => { if (confirm('Excluir template?')) { await del('/alerts/templates/' + r.id); tpls.reload() } }}><Trash2 /></button>}</div> }]} /> : <Loading />}</Card>}
    {ed && clients.data && tpls.data && <RuleForm r={ed} clients={clients.data} tpls={tpls.data} onClose={() => setEd(null)} onSaved={() => { setEd(null); rules.reload() }} />}
    {ted && <TemplateForm t={ted} onClose={() => setTed(null)} onSaved={() => { setTed(null); tpls.reload() }} />}</>
}
