import React, { useState } from 'react'
import { Download, Eye, FilePlus2, Mail, MessageCircle, Pencil, Play, Plus, Send, Trash2 } from 'lucide-react'
import { api, get, post, put, del, download, fmtDT, fmtDur, fmtPct, SEV } from '../api'
import { Card, Check, Field, Loading, Modal, MultiPick, PageHead, Pager, Pill, Table, Tabs, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'
import { ResolvedLine } from './Dest'
import { maskCNPJ, maskTarget, cnpjHint } from '../mask'

const MODS = [['infra', 'Infraestrutura (disponibilidade por equipamento)'], ['backup', 'Backup (Acronis)'], ['endpoint', 'Estações e antivírus (FortiClient EMS)']]
const iso = (d) => d ? new Date(d).toISOString() : null
const loc = (v) => v ? new Date(new Date(v).getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : ''

function ReportForm({ r, clients, onClose, onSaved }) {
  const [x, setX] = useState({ name: '', client_id: null, cnpj: '', period_start: null, period_end: null, host_ids: [], group_ids: [], triggers: [], items: [], severities: [], include_resolved: true, include_open: true, include_charts: true, include_kpis: true, modules: null, letterhead: 'orca', notes: '', wa_dest: '', email_dest: '', ...r })
  const toast = useToast(); const [tab, setTab] = useState('g')
  const hosts = useLoad(() => get(`/zabbix/hosts?size=200${x.client_id ? '&client_id=' + x.client_id : ''}`), [x.client_id]); const groups = useLoad(() => get('/zabbix/groups'), [])
  const set = k => e => setX({ ...x, [k]: e.target ? e.target.value : e })
  const csv = k => ({ value: (x[k] || []).join(', '), onChange: e => setX({ ...x, [k]: e.target.value.split(',').map(s => s.trim()).filter(Boolean) }) })
  const save = async () => { try { const b = { ...x, client_id: x.client_id || null, wa_dest: x.wa_dest || null, email_dest: x.email_dest || null, period_start: iso(x.period_start), period_end: iso(x.period_end) }
    const res = x.id ? await put('/reports/' + x.id, b) : await post('/reports', b); toast('Relatório salvo'); onSaved(res) } catch (e) { toast(e.message, true) } }
  const onClient = e => { const id = e.target.value ? Number(e.target.value) : null; const c = clients.find(c => c.id === id); setX({ ...x, client_id: id, cnpj: c ? c.cnpj || '' : x.cnpj, host_ids: [] }) }
  return <Modal wide title={x.id ? 'Editar relatório' : 'Novo relatório'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" onClick={save}>Salvar</button></>}>
    <Tabs value={tab} onChange={setTab} tabs={[['g', 'Geral'], ['f', 'Hosts e filtros'], ['o', 'Conteúdo'], ['d', 'Destinatários']]} />
    {tab === 'g' && <><div className="row r2"><Field label="NOME DO RELATÓRIO *"><input value={x.name} onChange={set('name')} placeholder="Relatório Mensal — Hotel X" /></Field>
      <Field label="CLIENTE"><select value={x.client_id || ''} onChange={onClient}><option value="">— selecione —</option>{clients.map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select></Field></div>
      {x.client_id && (() => { const svc = (clients.find(c => c.id === x.client_id) || {}).services || {}; const have = MODS.filter(([k]) => svc[k]); const sel = x.modules || have.map(([k]) => k)
        return <Field label="O QUE INCLUIR NO RELATÓRIO" hint={have.length ? 'Só aparecem os serviços que este cliente possui. Sem alterar, o relatório inclui todos.' : 'Este cliente ainda não tem hosts, backup (Acronis) nem estações (EMS) associados.'}>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>{have.map(([k, l]) => <Check key={k} label={l} checked={sel.includes(k)} onChange={v => { const n = v ? [...sel, k] : sel.filter(a => a !== k); setX({ ...x, modules: n.length === have.length ? null : n }) }} />)}</div></Field> })()}
      <div className="row r3"><Field label="CNPJ" hint={cnpjHint(x.cnpj)}><input inputMode="numeric" value={x.cnpj || ''} onChange={e => setX({ ...x, cnpj: maskCNPJ(e.target.value) })} placeholder="00.000.000/0000-00" /></Field><Field label="PERÍODO INICIAL" hint="Opcional se usar rotina"><input type="datetime-local" value={loc(x.period_start)} onChange={e => setX({ ...x, period_start: e.target.value })} /></Field>
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
      <div style={{ height: 12 }} /><Field label="DESTINATÁRIOS DE E-MAIL" hint='Separe por vírgula, ou "client" para usar os e-mails de relatório do cliente'><textarea value={x.email_dest || ''} onChange={set('email_dest')} /></Field>
      <div style={{ marginTop: 10 }}>{x.client_id ? <ResolvedLine client={clients.find(c => c.id === x.client_id)} wa={x.wa_dest} email={x.email_dest} /> : <p className="hint">Selecione o cliente na aba Geral para ver os destinos reais.</p>}</div></>}
  </Modal>
}

function GenerateModal({ r, onClose, onDone }) {
  const toast = useToast(); const [m, setM] = useState(r.period_start ? 'custom' : 'prev_month'); const [a, setA] = useState(r.period_start); const [b, setB] = useState(r.period_end)
  const [busy, setBusy] = useState(false); const [pv, setPv] = useState(null); const [run, setRun] = useState(null); const [dest, setDest] = useState(null)
  const [wa, setWa] = useState(true); const [em, setEm] = useState(true); const [waTo, setWaTo] = useState(''); const [emTo, setEmTo] = useState(''); const [res, setRes] = useState(null); const [sending, setSending] = useState(false)
  const body = () => m === 'custom' ? { period_start: iso(a), period_end: iso(b) } : { period_mode: m }
  const prev = async () => { try { setPv(await post(`/reports/${r.id}/preview`, body())) } catch (e) { toast(e.message, true) } }
  const go = async () => { setBusy(true); try { const x = await post(`/reports/${r.id}/generate`, body()); setRun(x)
      const d = await get(`/reports/runs/${x.id}/destinations`); setDest(d); setWaTo(d.wa); setEmTo(d.email); setWa(!!d.wa); setEm(!!d.email) } catch (e) { toast(e.message, true) } finally { setBusy(false) } }
  const view = async () => { const rr = await api(`/reports/runs/${run.id}/download`, { raw: true }); window.open(URL.createObjectURL(await rr.blob()), '_blank') }
  const send = async () => { setSending(true); try { const out = await post(`/reports/runs/${run.id}/send`, { wa_dest: wa ? waTo : null, email_to: em ? emTo : null }); setRes(out)
      toast('Envio concluído — veja o resultado abaixo') } catch (e) { toast(e.message, true) } finally { setSending(false) } }
  const close = () => { onDone(run); }
  if (!run) return <Modal title={`Gerar: ${r.name}`} onClose={onClose} footer={<><button className="btn" onClick={prev}>Prévia dos KPIs</button><button className="btn primary" disabled={busy} onClick={go}><Play />{busy ? 'Gerando PDF…' : 'Gerar PDF'}</button></>}>
    <div className="row r3"><Field label="PERÍODO"><select value={m} onChange={e => setM(e.target.value)}><option value="prev_day">Dia anterior</option><option value="prev_week">Semana anterior</option><option value="prev_month">Mês anterior</option><option value="custom">Personalizado</option></select></Field>
      {m === 'custom' && <><Field label="INÍCIO"><input type="datetime-local" value={loc(a)} onChange={e => setA(e.target.value)} /></Field><Field label="FIM"><input type="datetime-local" value={loc(b)} onChange={e => setB(e.target.value)} /></Field></>}</div>
    <p className="hint">O PDF é gerado primeiro, sem enviar nada. Depois você poderá baixar, conferir e só então confirmar o envio.</p>
    {pv && !pv.kpis && <p className="hint" style={{ marginTop: 16 }}>Este relatório não inclui infraestrutura: a prévia de KPIs não se aplica. Serviços incluídos: {pv.modules.join(', ')}.</p>}
    {pv && pv.kpis && <div className="grid g4" style={{ marginTop: 16 }}>{[['Disponibilidade', fmtPct(pv.kpis.summary.availability, 3)], ['Incidentes', pv.kpis.summary.incidents], ['Indisponibilidade', fmtDur(pv.kpis.summary.downtime_s)], ['Hosts', pv.hosts]].map(([l, v]) => <div key={l} className="card stat"><div className="l">{l}</div><div className="v" style={{ fontSize: 22 }}>{v}</div></div>)}</div>}</Modal>
  return <Modal title="PDF gerado" onClose={close} footer={<button className="btn" onClick={close}>Concluir</button>}>
    <div className="card" style={{ padding: 16, display: 'flex', gap: 14, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
      <div><b>{run.name}</b><div className="sub">{fmtDT(run.period_start).slice(0, 10)} → {fmtDT(run.period_end).slice(0, 10)} · {(run.size / 1024).toFixed(0)} KB{run.kpis ? ` · disponibilidade ${fmtPct(run.kpis.availability, 3)}` : ''}</div></div>
      <div style={{ display: 'flex', gap: 8 }}><button className="btn" onClick={view}><Eye />Visualizar</button><button className="btn primary" onClick={() => download(`/reports/runs/${run.id}/download`, `${(run.name || 'relatorio').replace(/\s+/g, '_')}.pdf`)}><Download />Baixar PDF</button></div></div>
    <h3 style={{ margin: '22px 0 10px' }}>Enviar o relatório</h3>
    <p className="hint" style={{ marginBottom: 12 }}>Nada foi enviado ainda. Confira o PDF e confirme os destinos para enviar.</p>
    <div className="row r2"><div><Check label="WhatsApp" checked={wa} onChange={setWa} /><input style={{ marginTop: 6 }} disabled={!wa} value={waTo} onChange={e => setWaTo(maskTarget(e.target.value))} placeholder="Grupo (1203…@g.us) ou celular com DDD" />
        <div className="hint">{dest?.wa_kind === 'grupo' ? '✔ Usando o grupo WhatsApp do cliente.' : dest?.wa_kind === 'celular' ? '✔ Cliente sem grupo — usando o celular cadastrado.' : ''} Para celular informe DDD + número (o 55 é adicionado automaticamente); para grupo use o JID terminado em @g.us.</div>
        {dest?.wa_missing && <div className="hint" style={{ color: 'var(--orange)' }}>⚠ O cliente não tem grupo nem celular WhatsApp cadastrado — informe o destino aqui ou cadastre em Clientes.</div>}</div>
      <div><Check label="E-mail" checked={em} onChange={setEm} /><input style={{ marginTop: 6 }} disabled={!em} value={emTo} onChange={e => setEmTo(e.target.value)} placeholder="email1@dominio.com, email2@dominio.com" />
        {dest?.email_missing && <div className="hint" style={{ color: 'var(--orange)' }}>⚠ O cliente não tem e-mail de relatório cadastrado — informe aqui.</div>}</div></div>
    <button className="btn primary" disabled={sending || (!(wa && waTo) && !(em && emTo))} onClick={send}><Send />{sending ? 'Enviando…' : 'Confirmar envio'}</button>
    {res && <div className="card" style={{ padding: 14, marginTop: 14 }}><div><b>WhatsApp:</b> {res.wa_status || 'não solicitado'}</div><div><b>E-mail:</b> {res.email_status || 'não solicitado'}</div></div>}
  </Modal>
}

export default function Reports() {
  const me = useAuth(); const toast = useToast(); const [tab, setTab] = useState('def'); const [ed, setEd] = useState(null); const [gen, setGen] = useState(null); const [page, setPage] = useState(1)
  const reps = useLoad(() => get('/reports'), []); const clients = useLoad(() => get('/clients'), []); const runs = useLoad(() => get(`/reports/runs?page=${page}&size=25`), [page])
  const edit = can(me, 'reports.edit'), send = can(me, 'reports.send')
  const resend = async (run, kind) => { const to = kind === 'wa' ? prompt('JID do destino WhatsApp (ou "client"):', 'client') : prompt('E-mail(s) destino (ou "client"):', 'client'); if (!to) return
    try { const r = await post(`/reports/runs/${run.id}/send`, kind === 'wa' ? { wa_dest: to } : { email_to: to }); toast(kind === 'wa' ? 'WhatsApp: ' + r.wa_status : 'E-mail: ' + r.email_status); runs.reload() } catch (e) { toast(e.message, true) } }
  const removeDef = async (r) => {
    if (!confirm(`Excluir o relatório "${r.name}"?\n\nSerão removidos também as rotinas agendadas dele e os PDFs já gerados (${r.runs || 0}). Esta ação não pode ser desfeita.`)) return
    try { await del('/reports/' + r.id); toast('Relatório excluído'); reps.reload(); runs.reload() } catch (e) { toast(e.message, true) }
  }
  const removeRun = async (run) => {
    if (!confirm('Excluir este PDF do histórico? O arquivo será apagado.')) return
    try { await del('/reports/runs/' + run.id); toast('PDF excluído'); runs.reload() } catch (e) { toast(e.message, true) }
  }
  return <>
    <PageHead title="Relatórios" desc="Relatórios executivos e técnicos de disponibilidade, backup e endpoints em PDF · dados consultados ao vivo no Zabbix · guardamos os 2 PDFs mais recentes por cliente">
      {edit && <button className="btn primary" onClick={() => setEd({})}><Plus />Novo relatório</button>}</PageHead>
    <Tabs value={tab} onChange={setTab} tabs={[['def', 'Definições'], ['hist', 'Histórico de PDFs']]} />
    {tab === 'def' && <Card pad={false}>{reps.data ? <Table rows={reps.data} empty="Nenhum relatório criado ainda." cols={[
      { h: 'Relatório', r: r => <b>{r.name}</b> }, { h: 'Cliente', r: r => r.client_name || '—' }, { h: 'Filtros', r: r => `${r.host_ids?.length || 0} hosts · ${r.group_ids?.length || 0} grupos` },
      { h: 'Gerações', k: 'runs' }, { h: 'Última', r: r => fmtDT(r.last_run) },
      { h: '', r: r => <div style={{ display: 'flex', gap: 6 }}>{edit && <button className="btn sm primary" onClick={() => setGen(r)}><FilePlus2 />Gerar</button>}{edit && <button className="btn sm" onClick={() => setEd(r)}><Pencil /></button>}{edit && <button className="btn sm danger" title="Excluir relatório" onClick={() => removeDef(r)}><Trash2 /></button>}</div> }]} /> : <Loading />}</Card>}
    {tab === 'hist' && <Card pad={false}>{runs.data ? <><Table rows={runs.data.items} empty="Nenhum PDF gerado." cols={[
      { h: 'Gerado em', r: r => fmtDT(r.generated_at) }, { h: 'Relatório', r: r => <b>{r.name}</b> }, { h: 'Cliente', r: r => r.client_name || '—' }, { h: 'Período', r: r => `${fmtDT(r.period_start).slice(0, 10)} → ${fmtDT(r.period_end).slice(0, 10)}` },
      { h: 'Disp.', r: r => r.kpis ? fmtPct(r.kpis.availability, 3) : '—' }, { h: 'Por', r: r => r.generated_by },
      { h: 'Status', r: r => <Pill tone={r.status === 'ok' ? 'ok' : 'bad'}>{r.status}</Pill> }, { h: 'WhatsApp', r: r => <span className="sub">{r.wa_status || '—'}</span> }, { h: 'E-mail', r: r => <span className="sub">{r.email_status ? r.email_status.slice(0, 28) : '—'}</span> },
      { h: '', r: r => <div style={{ display: 'flex', gap: 6 }}>{r.status === 'ok' && <button className="btn sm" title="Baixar" onClick={() => download(`/reports/runs/${r.id}/download`, `relatorio_${r.id}.pdf`)}><Download /></button>}
        {r.status === 'ok' && send && <><button className="btn sm" title="Reenviar WhatsApp" onClick={() => resend(r, 'wa')}><MessageCircle /></button><button className="btn sm" title="Reenviar e-mail" onClick={() => resend(r, 'em')}><Mail /></button></>}{edit && <button className="btn sm danger" title="Excluir PDF" onClick={() => removeRun(r)}><Trash2 /></button>}</div> }]} />
      <div style={{ padding: '0 16px 12px' }}><Pager page={page} size={25} total={runs.data.total} onPage={setPage} /></div></> : <Loading />}</Card>}
    {ed && clients.data && <ReportForm r={ed} clients={clients.data} onClose={() => setEd(null)} onSaved={() => { setEd(null); reps.reload() }} />}
    {gen && <GenerateModal r={gen} onClose={() => setGen(null)} onDone={() => { setGen(null); reps.reload(); runs.reload(); setTab('hist') }} />}</>
}
