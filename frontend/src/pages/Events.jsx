import React, { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Download, Bookmark } from 'lucide-react'
import { get, put, download, fmtDT, fmtDur, SEV } from '../api'
import { Card, Drawer, LiveDur, Loading, PERIODS, PageHead, Pager, Pill, SevBadge, StatusBadge, Table, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'

function Diag({ id }) {
  const { data: d, err } = useLoad(() => get('/alerts/diagnose/' + id), [id])
  if (err) return null
  if (!d) return null
  return <div className="card" style={{ padding: 16, marginTop: 18, borderColor: d.will_alert ? '#bfe5cb' : '#f3d3a0' }}>
    <h3 style={{ marginBottom: 10 }}>{d.will_alert ? '✅ Este evento atende às regras de alerta' : '⚠ Este evento NÃO gera alerta de WhatsApp'}</h3>
    {d.checks.map((c, i) => <div key={i} style={{ display: 'flex', gap: 10, padding: '6px 0', borderTop: i ? '1px solid #eef1f8' : 'none', fontSize: 14 }}>
      <span style={{ color: c.ok ? 'var(--ok)' : 'var(--crit)', fontWeight: 700 }}>{c.ok ? '✔' : '✖'}</span><div><b>{c.label}</b><div className="sub">{c.detail}</div></div></div>)}</div>
}

function Detail({ id, onClose }) {
  const me = useAuth(); const toast = useToast(); const { data: e, err } = useLoad(() => get('/events/' + id), [id]); const [n, setN] = useState(null)
  return <Drawer title={`Evento ${e ? e.zbx_eventid : ''}`} onClose={onClose}>{!e ? <Loading err={err} /> : <>
    <div style={{ marginBottom: 14, display: 'flex', gap: 8 }}><StatusBadge s={e.status} /><SevBadge n={e.severity} /></div>
    <div className="kv"><b>Host</b><span>{e.host}</span><b>IP</b><span>{e.ip || '—'}</span><b>Trigger</b><span>{e.trigger_name}</span><b>Item</b><span>{e.item_name || '—'}</span>
      <b>Grupos</b><span>{(e.group_names || []).map(g => <span className="chip" key={g}>{g}</span>)}</span><b>Início</b><span>{fmtDT(e.started_at)}</span><b>Recuperação</b><span>{e.recovered_at ? fmtDT(e.recovered_at) : 'em aberto'}</span>
      <b>Duração</b><span>{e.status === 'PROBLEM' ? <LiveDur since={e.started_at} /> : fmtDur(e.duration_s)}</span><b>Valor</b><span>{e.opdata || '—'}</span><b>Origem</b><span>{e.source}</span><b>WhatsApp</b><span>{e.wa_status || '—'} {e.wa_message_id && <span className="sub mono">· {e.wa_message_id.slice(0, 14)}…</span>}</span></div>
    <Diag id={id} />
    <h3 style={{ margin: '22px 0 8px' }}>Mensagens enviadas</h3>
    {e.dispatches.length ? e.dispatches.map(d => <div key={d.id} className="card" style={{ padding: 14, marginBottom: 10 }}><div style={{ display: 'flex', gap: 8, marginBottom: 8 }}><Pill tone={d.kind === 'problem' ? 'bad' : 'ok'}>{d.kind}</Pill><Pill tone={d.status === 'sent' ? 'ok' : d.status === 'failed' ? 'bad' : 'warn'}>{d.status}</Pill><span className="sub">{fmtDT(d.sent_at || d.due_at)}</span></div>
      <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontFamily: 'inherit', fontSize: 14 }}>{d.text || '(aguardando envio)'}</pre>{d.error && <div style={{ color: 'var(--crit)', marginTop: 6 }}>{d.error}</div>}</div>) : <div className="sub">Nenhuma mensagem para este evento.</div>}
    <h3 style={{ margin: '22px 0 8px' }}>Observações</h3>
    <textarea value={n ?? e.notes ?? ''} onChange={x => setN(x.target.value)} disabled={!can(me, 'events.edit')} />
    {can(me, 'events.edit') && <button className="btn primary" style={{ marginTop: 10 }} onClick={async () => { await put(`/events/${id}/notes`, { notes: n ?? e.notes }); toast('Observação salva') }}>Salvar observação</button>}
  </>}</Drawer>
}

const SAVED = 'navi.events.saved'
const loadSaved = () => { try { return JSON.parse(localStorage.getItem(SAVED) || '[]') } catch { return [] } }

export default function Events() {
  const [sp] = useSearchParams()
  const [status, setStatus] = useState(sp.get('status') || ''); const [q, setQ] = useState(sp.get('q') || ''); const [sev, setSev] = useState(sp.get('min_severity') || ''); const [page, setPage] = useState(1)
  const [days, setDays] = useState(sp.has('days') ? sp.get('days') : '0.0417'); const [sel, setSel] = useState(null); const [cl, setCl] = useState(sp.get('client_id') || '')
  const [saved, setSaved] = useState(loadSaved()); const toast = useToast(); const [kind, setKind] = useState(sp.get('kind') || '')
  const clients = useLoad(() => get('/clients'), [])
  const since = days ? new Date(Date.now() - days * 864e5).toISOString() : ''
  const qs = `kind=${kind}&status=${status}&q=${encodeURIComponent(q)}${sev !== '' ? '&min_severity=' + sev : ''}${cl ? '&client_id=' + cl : ''}${since ? '&since=' + encodeURIComponent(since) : ''}`
  const { data, err } = useLoad(() => get(`/events?page=${page}&size=50&${qs}`), [page, kind, status, q, sev, days, cl], 15000)
  const apply = (f) => { setStatus(f.status); setQ(f.q); setSev(f.sev); setCl(f.cl); setDays(f.days); setPage(1) }
  const saveFilter = () => {
    const name = prompt('Nome do filtro salvo (ex.: Links caídos):'); if (!name) return
    const l = [...saved.filter(x => x.name !== name), { name, status, q, sev, cl, days }]
    setSaved(l); try { localStorage.setItem(SAVED, JSON.stringify(l)) } catch { /* ignore */ }; toast('Filtro salvo')
  }
  const rmFilter = (name) => { const l = saved.filter(x => x.name !== name); setSaved(l); try { localStorage.setItem(SAVED, JSON.stringify(l)) } catch { /* ignore */ } }
  const clear = () => { setKind(''); apply({ status: '', q: '', sev: '', cl: '', days: '0.0417' }) }
  const dirty = kind || status || q || sev !== '' || cl || days !== '0.0417'
  return <>
    <PageHead title="Eventos e Incidentes" desc="Ocorrências de todos os clientes (problema e recuperação ligados pelo Event ID do Zabbix). Filtre, exporte em CSV e abra o detalhe">
      <button className="btn" onClick={saveFilter}><Bookmark />Salvar filtro</button>
      <button className="btn" onClick={() => download(`/events-export?${qs}`, 'eventos-navi.csv').catch(e => toast(e.message, true))}><Download />Exportar CSV</button></PageHead>
    <div className="bar"><div className="grow"><input placeholder="Buscar host, IP, trigger ou item…" value={q} onChange={e => { setQ(e.target.value); setPage(1) }} /></div>
      <select value={kind} onChange={e => { setKind(e.target.value); setPage(1) }}><option value="">Todas as origens</option><option value="infra">Infraestrutura (Zabbix)</option><option value="backup">Backup (Acronis)</option><option value="endpoint">Endpoints (EMS)</option></select>
      <select value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}><option value="">Todos</option><option value="PROBLEM">Em aberto</option><option value="RESOLVED">Resolvidos</option></select>
      <select value={sev} onChange={e => { setSev(e.target.value); setPage(1) }}><option value="">Qualquer severidade</option>{SEV.map((s, i) => <option key={i} value={i}>≥ {s}</option>)}</select>
      <select value={cl} onChange={e => { setCl(e.target.value); setPage(1) }}><option value="">Todos os clientes</option>{(clients.data || []).map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select>
      <select value={days} onChange={e => { setDays(e.target.value); setPage(1) }} aria-label="Período">{PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}<option value="">Todo o histórico</option></select>
      {dirty && <button className="btn sm" onClick={clear}>Limpar filtros</button>}</div>
    {saved.length > 0 && <div style={{ marginBottom: 14 }}><span className="sub">Filtros salvos: </span>{saved.map(f => <span key={f.name} className="chip" style={{ cursor: 'pointer' }} onClick={() => apply(f)}>{f.name} <span title="Remover" onClick={e => { e.stopPropagation(); rmFilter(f.name) }}>✕</span></span>)}</div>}
    <Card pad={false}>{data ? <><Table rows={data.items} onRow={r => setSel(r.id)} cols={[
      { h: 'Status', r: r => <StatusBadge s={r.status} /> }, { h: 'Sev.', r: r => <SevBadge n={r.severity} /> }, { h: 'Host', r: r => <><b>{r.host}</b>{r.kind && r.kind !== 'infra' && <div><Pill tone="info">{r.kind === 'backup' ? 'backup' : 'endpoint'}</Pill></div>}</> }, { h: 'IP', k: 'ip', cls: 'mono' },
      { h: 'Trigger', r: r => <div className="trunc" title={r.trigger_name}>{r.trigger_name}</div> }, { h: 'Início', r: r => fmtDT(r.started_at) }, { h: 'Recuperação', r: r => fmtDT(r.recovered_at) },
      { h: 'Duração', r: r => r.status === 'PROBLEM' ? <LiveDur since={r.started_at} /> : fmtDur(r.duration_s), cls: 'mono' }, { h: 'WA', r: r => r.wa_status ? <Pill tone={r.wa_status === 'failed' ? 'bad' : 'ok'}>{r.wa_status}</Pill> : '—' }]} />
      <div style={{ padding: '0 16px 12px' }}><Pager page={page} size={50} total={data.total} onPage={setPage} /></div></> : <Loading err={err} />}</Card>
    {sel && <Detail id={sel} onClose={() => setSel(null)} />}</>
}
