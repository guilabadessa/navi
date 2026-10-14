import React, { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { get, download } from '../api'
import { Card, Drawer, Loading, PageHead, Pager, Pill, Stat, useLoad, useToast } from '../ui'
import AtNav from './AtNav'
import { Bubble } from './Atendimento'

const dur = (s) => s == null ? '—' : s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)} min` : `${Math.floor(s / 3600)}h${String(Math.round(s % 3600 / 60)).padStart(2, '0')}`
const dt = (v) => v ? new Date(v).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '—'
const REASONS = [['analista', 'Encerrado pelo analista'], ['inatividade', 'Inatividade'], ['fluxo', 'Resolvido pelo fluxo']]
const today = () => new Date().toLocaleDateString('sv-SE')
const daysAgo = (n) => new Date(Date.now() - n * 864e5).toLocaleDateString('sv-SE')

function Transcript({ conv, onClose }) {
  const { data } = useLoad(() => get(`/atendimento/conversations/${conv.id}/messages?since=0`), [conv.id])
  return <Drawer title={`${conv.name || conv.number} · +${conv.number}`} onClose={onClose}>
    <div className="sub" style={{ marginBottom: 10 }}>{conv.client ? conv.client.name + ' · ' : ''}{conv.queue_name} · {conv.assigned_name || 'sem analista'} · {conv.closed_reason_label}<br />
      Espera {dur(conv.wait_s)} · 1ª resposta {dur(conv.first_response_s)} · duração {dur(conv.duration_s)}</div>
    {!data ? <Loading /> : <div className="at-body" style={{ maxHeight: 'none' }}>{data.messages.map(m => <Bubble key={m.id} m={m} />)}</div>}
  </Drawer>
}

export default function AtendimentoHistorico() {
  const toast = useToast()
  const [f, setF] = useState({ q: '', queue: '', agent_id: '', reason: '', date_from: daysAgo(30), date_to: today() }); const [page, setPage] = useState(1); const [open, setOpen] = useState(null)
  const qs = (extra = {}) => new URLSearchParams(Object.entries({ ...f, ...extra }).filter(([, v]) => v !== '' && v != null)).toString()
  const queues = useLoad(() => get('/atendimento/queue-defs'), []); const agents = useLoad(() => get('/atendimento/agents'), [])
  const list = useLoad(() => get('/atendimento/history?' + qs({ page })), [JSON.stringify(f), page])
  const st = useLoad(() => get('/atendimento/stats?' + qs()), [JSON.stringify(f)])
  useEffect(() => { setPage(1) }, [JSON.stringify(f)])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const exp = async () => { try { await download('/atendimento/history/export?' + qs(), 'atendimentos.csv') } catch (e) { toast(e.message, true) } }
  const s = st.data
  return <>
    <PageHead title="Histórico de atendimentos" desc="Conversas encerradas, com tempos de espera e de atendimento" />
    <AtNav />
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat label="Atendimentos" value={s ? s.total : '…'} desc="no período" />
      <Stat label="Espera média" value={s ? dur(s.avg_wait_s) : '…'} desc="na fila até assumir" />
      <Stat label="1ª resposta média" value={s ? dur(s.avg_first_response_s) : '…'} desc="da entrada na fila" />
      <Stat label="Duração média" value={s ? dur(s.avg_duration_s) : '…'} desc="do atendimento" />
    </div>
    {s && s.total > 0 && <div className="row r2" style={{ marginBottom: 16 }}>
      <Card title="Por fila" pad={false}>{s.by_queue.map(x => <div key={x.key} className="cfg-row"><i className="cfg-dot" style={{ background: x.color }} /><div className="grow"><b>{x.label}</b></div><span className="sub">{x.count} · espera {dur(x.avg_wait_s)} · duração {dur(x.avg_duration_s)}</span></div>)}</Card>
      <Card title="Por analista" pad={false}>{s.by_agent.map(x => <div key={String(x.key)} className="cfg-row"><div className="grow"><b>{x.label}</b></div><span className="sub">{x.count} · 1ª resposta {dur(x.avg_first_response_s)} · duração {dur(x.avg_duration_s)}</span></div>)}</Card></div>}
    <Card pad={false}>
      <div className="at-hfilters">
        <input placeholder="Buscar por nome, número ou cliente…" value={f.q} onChange={set('q')} />
        <select value={f.queue} onChange={set('queue')}><option value="">Todas as filas</option>{(queues.data || []).map(q => <option key={q.slug} value={q.slug}>{q.name}</option>)}</select>
        <select value={f.agent_id} onChange={set('agent_id')}><option value="">Todos os analistas</option>{(agents.data || []).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select>
        <select value={f.reason} onChange={set('reason')}><option value="">Todos os motivos</option>{REASONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <label className="sub">De <input type="date" value={f.date_from} onChange={set('date_from')} /></label>
        <label className="sub">até <input type="date" value={f.date_to} onChange={set('date_to')} /></label>
        <button className="btn" onClick={exp}><Download size={15} />CSV</button>
      </div>
      {!list.data ? <Loading err={list.err} /> : <div style={{ overflowX: 'auto' }}><table className="tbl"><thead><tr><th>Encerrado em</th><th>Contato</th><th>Cliente</th><th>Fila</th><th>Analista</th><th>Motivo</th><th>Espera</th><th>Duração</th><th>Msgs</th></tr></thead>
        <tbody>{list.data.items.map(c => <tr key={c.id} onClick={() => setOpen(c)} style={{ cursor: 'pointer' }}>
          <td>{dt(c.closed_at)}</td><td><b>{c.name || c.number}</b><div className="sub">+{c.number}</div></td><td>{c.client ? c.client.name : '—'}</td>
          <td><span className="badge" style={{ background: c.queue_color + '26', color: c.queue_color }}>{c.queue_name}</span></td><td>{c.assigned_name || '—'}</td>
          <td><Pill tone={c.closed_reason === 'inatividade' ? 'warn' : 'mut'}>{c.closed_reason_label}</Pill></td><td>{dur(c.wait_s)}</td><td>{dur(c.duration_s)}</td><td>{c.messages}</td></tr>)}
          {!list.data.items.length && <tr><td colSpan={9} className="empty">Nenhum atendimento no período.</td></tr>}</tbody></table></div>}
      {list.data && list.data.total > list.data.size && <Pager page={page} size={list.data.size} total={list.data.total} onPage={setPage} />}
    </Card>
    {open && <Transcript conv={open} onClose={() => setOpen(null)} />}
  </>
}
