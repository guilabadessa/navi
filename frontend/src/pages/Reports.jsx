import React, { useState } from 'react'
import { Download, FilePlus2, Mail, MessageCircle, Pencil, Play, Plus, Send } from 'lucide-react'
import { get, post, put, del, download, fmtDT, fmtDur, fmtPct, SEV } from '../api'
import { Card, Check, Field, Loading, Modal, MultiPick, PageHead, Pager, Pill, Table, Tabs, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'

const iso = (d) => d ? new Date(d).toISOString() : null
const loc = (v) => v ? new Date(new Date(v).getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : ''

function ReportForm({ r, clients, onClose, onSaved }) {
  const [x, setX] = useState({ name: '', client_id: null, cnpj: '', period_start: null, period_end: null, host_ids: [], group_ids: [], triggers: [], items: [], severities: [], include_resolved: true, include_open: true, include_charts: true, include_kpis: true, letterhead: 'orca', notes: '', wa_dest: '', email_dest: '', ...r })
  const toast = useToast(); const [tab, setTab] = useState('g')
  const hosts = useLoad(() => get(`/zabbix/hosts?size=200${x.client_id ? '&client_id=' + x.client_id : ''}`), [x.client_id]); const groups = useLoad(() => get('/zabbix/groups'), [])
  const set = k => e => setX({ ...x, [k]: e.target ? e.target.value : e })
  const csv = k => ({ value: (x[k] || []).join(', '), onChange: e => setX({ ...x, [k]: e.target.value.split(',').map(s => s.trim()).filter(Boolean) }) })
  const save = async () => { try { const b = { ...x, client_id: x.client_id || null, wa_dest: x.wa_dest || null, email_dest: x.email_dest || null, period_start: iso(x.period_start), period_end: iso(x.period_end) }
    const res = x.id ? await put('/reports/' + x.id, b) : await post('/reports', b); toast('Relatório salvo'); onSaved(res) } catch (e) { toast(e.message, true) } }
  const onClient = e => { const id = e.target.value ? Number(e.target.value) : null; const c = clients.find(c => c.id === id); setX({ ...x, client_id: id, cnpj: c ? c.cnpj || '' : x.cnpj, host_ids: [] }) }
  return <Modal wide title={x.id ? 'Editar relatório' : 'Novo relatório'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" onClick={save}>Salvar</button></>}>
    <Tabs value={tab} onChange={setTab} tabs={[['g', 'Geral'], ['f', 'Hosts e filtros'], ['o', 'Conteúdo'], ['d', 'Destinatários']]} />
    {tab === 'g' && <><div className="row r2"><Field label="NOME DO RELATÓRIO *"><input value={x.name} onChange={set('name')} placeholder="SLA Mensal — Hotel X" /></Field>
      <Field label="CLIENTE"><select value={x.client_id || ''} onChange={onClient}><option value="">— selecione —</option>{clients.map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select></Field></div>
      <div className="row r3"><Field label="CNPJ"><input value={x.cnpj || ''} onChange={set('cnpj')} /></Field><Field label="PERÍODO INICIAL" hint="Opcional se usar rotina"><input type="datetime-local" value={loc(x.period_start)} onChange={e => setX({ ...x, period_start: e.target.value })} /></Field>
        <Field label="PERÍODO FINAL"><input type="datetime-local" value={loc(x.period_end)} onChange={e => setX({ ...x, period_end: e.target.value })} /></Field></div>
      <Field label="OBSERVAÇÕES (aparecem no PDF)"><textarea value={x.notes || ''} onChange={set('notes')} /></Field></>}
    {tab === 'f' && <><p className="sub" style={{ marginBottom: 10 }}>Sem seleção, o relatório usa todos os hosts dos Host Groups do cliente.</p>
      <div className="grid g2"><Field label="HOSTS ESPECÍFICOS">{hosts.data ? <MultiPick value={x.host_ids} onChange={v => setX({ ...x, host_ids: v })} options={hosts.data.items.map(h => ({ value: h.hostid, label: h.name, sub: h.ip }))} /> : <Loading />}</Field>
        <Field label="HOST GROUPS">{groups.data ? <MultiPick value={x.group_ids} onChange={v => setX({ ...x, group_ids: v })} options={groups.data.map(g => ({ value: g.groupid, label: g.name, sub: g.host_count + ' hosts' }))} /> : <Loading />}</Field></div>
      <div className="row r2" style={{ marginTop: 14 }}><Field label="TRIGGERS (contém, separe por vírgula)"><input {...csv('triggers')} /></Field><Field label="ITENS (contém, separe por vírgula)"><input {...csv('items')} /></Field></div>
      <Field label="SEVERIDADES"><div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>{SEV.map((s, i) => <Check key={i} label={s} checked={x.severities.includes(i)} onChange={v => setX({ ...x, severities: v ? [...x.severities, i] : x.severities.filter(a => a !== i) })} />)}</div></Field></>}
    {tab === 'o' && <div style={{ display: 'grid', gap: 12 }}><Check label="Incluir eventos resolvidos" checked={x.include_resolved} onChange={v => setX({ ...x, include_resolved: v })} /><Check label="Incluir eventos em aberto" checked={x.include_open} onChange={v => setX({ ...x, include_open: v })} />
      <Check label="Incluir gráficos" checked={x.include_charts} onChange={v => setX({ ...x, include_charts: v })} /><Check label="Incluir KPIs e visão executiva" checked={x.include_kpis} onChange={v => setX({ ...x, include_kpis: v })} />
      <Field label="PAPEL TIMBRADO"><select value={x.letterhead} onChange={set('letterhead')}><option value="orca">Orca TI (padrão)</option></select></Field></div>}
    {tab === 'd' && <><Field label="DESTINATÁRIO WHATSAPP" hint='JID do grupo/contato, ou "client" para usar o grupo do cliente'><input value={x.wa_dest || ''} onChange={set('wa_dest')} placeholder="client" /></Field>
      <div style={{ height: 12 }} /><Field label="DESTINATÁRIOS DE E-MAIL" hint='Separe por vírgula, ou "client" para usar os e-mails de relatório do cliente'><textarea value={x.email_dest || ''} onChange={set('email_dest')} /></Field></>}
  </Modal>
}

function GenerateModal({ r, onClose, onDone }) {
  const toast = useToast(); const [m, setM] = useState(r.period_start ? 'custom' : 'prev_month'); const [a, setA] = useState(r.period_start); const [b, setB] = useState(r.period_end)
  const [wa, setWa] = useState(false); const [em, setEm] = useState(false); const [busy, setBusy] = useState(false); const [pv, setPv] = useState(null)
  const body = () => m === 'custom' ? { period_start: iso(a), period_end: iso(b), send_wa: wa, send_email: em } : { period_mode: m, send_wa: wa, send_email: em }
  const go = async () => { setBusy(true); try { const run = await post(`/reports/${r.id}/generate`, body()); toast(`PDF gerado${run.wa_status ? ' · WhatsApp: ' + run.wa_status : ''}${run.email_status ? ' · E-mail: ' + run.email_status : ''}`); onDone(run) } catch (e) { toast(e.message, true) } finally { setBusy(false) } }
  const prev = async () => { try { setPv(await post(`/reports/${r.id}/preview`, body())) } catch (e) { toast(e.message, true) } }
  return <Modal title={`Gerar: ${r.name}`} onClose={onClose} footer={<><button className="btn" onClick={prev}>Prévia dos KPIs</button><button className="btn primary" disabled={busy} onClick={go}><Play />{busy ? 'Gerando…' : 'Gerar PDF'}</button></>}>
    <div className="row r3"><Field label="PERÍODO"><select value={m} onChange={e => setM(e.target.value)}><option value="prev_day">Dia anterior</option><option value="prev_week">Semana anterior</option><option value="prev_month">Mês anterior</option><option value="custom">Personalizado</option></select></Field>
      {m === 'custom' && <><Field label="INÍCIO"><input type="datetime-local" value={loc(a)} onChange={e => setA(e.target.value)} /></Field><Field label="FIM"><input type="datetime-local" value={loc(b)} onChange={e => setB(e.target.value)} /></Field></>}</div>
    <div style={{ display: 'flex', gap: 24 }}><Check label="Enviar por WhatsApp" checked={wa} onChange={setWa} /><Check label="Enviar por e-mail" checked={em} onChange={setEm} /></div>
    {pv && <div className="grid g4" style={{ marginTop: 16 }}>{[['Disponibilidade', fmtPct(pv.kpis.summary.availability, 3)], ['Incidentes', pv.kpis.summary.incidents], ['Indisponibilidade', fmtDur(pv.kpis.summary.downtime_s)], ['Hosts', pv.hosts]].map(([l, v]) => <div key={l} className="card stat"><div className="l">{l}</div><div className="v" style={{ fontSize: 22 }}>{v}</div></div>)}</div>}</Modal>
}

export default function Reports() {
  const me = useAuth(); const toast = useToast(); const [tab, setTab] = useState('def'); const [ed, setEd] = useState(null); const [gen, setGen] = useState(null); const [page, setPage] = useState(1)
  const reps = useLoad(() => get('/reports'), []); const clients = useLoad(() => get('/clients'), []); const runs = useLoad(() => get(`/reports/runs?page=${page}&size=25`), [page])
  const edit = can(me, 'reports.edit'), send = can(me, 'reports.send')
  const resend = async (run, kind) => { const to = kind === 'wa' ? prompt('JID do destino WhatsApp (ou "client"):', 'client') : prompt('E-mail(s) destino (ou "client"):', 'client'); if (!to) return
    try { const r = await post(`/reports/runs/${run.id}/send`, kind === 'wa' ? { wa_dest: to } : { email_to: to }); toast(kind === 'wa' ? 'WhatsApp: ' + r.wa_status : 'E-mail: ' + r.email_status); runs.reload() } catch (e) { toast(e.message, true) } }
  return <>
    <PageHead title="Relatórios" desc="Relatórios executivos e técnicos de disponibilidade e SLA em PDF">
      {edit && <button className="btn primary" onClick={() => setEd({})}><Plus />Novo relatório</button>}</PageHead>
    <Tabs value={tab} onChange={setTab} tabs={[['def', 'Definições'], ['hist', 'Histórico de PDFs']]} />
    {tab === 'def' && <Card pad={false}>{reps.data ? <Table rows={reps.data} empty="Nenhum relatório criado ainda." cols={[
      { h: 'Relatório', r: r => <b>{r.name}</b> }, { h: 'Cliente', r: r => r.client_name || '—' }, { h: 'Filtros', r: r => `${r.host_ids?.length || 0} hosts · ${r.group_ids?.length || 0} grupos` },
      { h: 'Gerações', k: 'runs' }, { h: 'Última', r: r => fmtDT(r.last_run) },
      { h: '', r: r => <div style={{ display: 'flex', gap: 6 }}>{edit && <button className="btn sm primary" onClick={() => setGen(r)}><FilePlus2 />Gerar</button>}{edit && <button className="btn sm" onClick={() => setEd(r)}><Pencil /></button>}</div> }]} /> : <Loading />}</Card>}
    {tab === 'hist' && <Card pad={false}>{runs.data ? <><Table rows={runs.data.items} empty="Nenhum PDF gerado." cols={[
      { h: 'Gerado em', r: r => fmtDT(r.generated_at) }, { h: 'Relatório', r: r => <b>{r.name}</b> }, { h: 'Cliente', r: r => r.client_name || '—' }, { h: 'Período', r: r => `${fmtDT(r.period_start).slice(0, 10)} → ${fmtDT(r.period_end).slice(0, 10)}` },
      { h: 'Disp.', r: r => r.kpis ? fmtPct(r.kpis.availability, 3) : '—' }, { h: 'Por', r: r => r.generated_by },
      { h: 'Status', r: r => <Pill tone={r.status === 'ok' ? 'ok' : 'bad'}>{r.status}</Pill> }, { h: 'WhatsApp', r: r => <span className="sub">{r.wa_status || '—'}</span> }, { h: 'E-mail', r: r => <span className="sub">{r.email_status ? r.email_status.slice(0, 28) : '—'}</span> },
      { h: '', r: r => r.status === 'ok' && <div style={{ display: 'flex', gap: 6 }}><button className="btn sm" title="Baixar" onClick={() => download(`/reports/runs/${r.id}/download`, `relatorio_${r.id}.pdf`)}><Download /></button>
        {send && <><button className="btn sm" title="Reenviar WhatsApp" onClick={() => resend(r, 'wa')}><MessageCircle /></button><button className="btn sm" title="Reenviar e-mail" onClick={() => resend(r, 'em')}><Mail /></button></>}</div> }]} />
      <div style={{ padding: '0 16px 12px' }}><Pager page={page} size={25} total={runs.data.total} onPage={setPage} /></div></> : <Loading />}</Card>}
    {ed && clients.data && <ReportForm r={ed} clients={clients.data} onClose={() => setEd(null)} onSaved={() => { setEd(null); reps.reload() }} />}
    {gen && <GenerateModal r={gen} onClose={() => setGen(null)} onDone={() => { setGen(null); reps.reload(); runs.reload(); setTab('hist') }} />}</>
}
