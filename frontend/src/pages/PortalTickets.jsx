import React, { useState } from 'react'
import { MessageSquareText, Plus, Send } from 'lucide-react'
import { get, post } from '../api'
import { Card, Field, Loading, Modal, Pill, Table, useLoad, useToast } from '../ui'

const STATUS_TONE = { aberto: 'bad', andamento: 'warn', aguardando_cliente: 'info', resolvido: 'ok', fechado: 'mut' }
const PRIORITY_TONE = { critica: 'bad', alta: 'warn', media: 'info', baixa: 'mut' }
const PRIORITIES = [['baixa', 'Baixa'], ['media', 'Média'], ['alta', 'Alta'], ['critica', 'Crítica']]
const fmt = (v) => v ? new Date(v).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '—'

function NewTicketForm({ qs, path, onClose, onSaved }) {
  const [x, setX] = useState({ queue_id: qs[0]?.id || '', subject: '', priority: 'media', body: '' })
  const toast = useToast()
  const save = async () => {
    if (!x.subject.trim() || !x.body.trim()) { toast('Preencha o assunto e a descrição', true); return }
    try { await post(path, { ...x, queue_id: x.queue_id || null }); toast('Chamado aberto! Nossa equipe já foi avisada.'); onSaved() } catch (e) { toast(e.message, true) }
  }
  return <Modal title="Abrir chamado" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" onClick={save}><Send size={15} />Abrir chamado</button></>}>
    {qs.length > 0 && <Field label="ASSUNTO SOBRE" hint="Ajuda a direcionar para o time certo."><select value={x.queue_id} onChange={e => setX({ ...x, queue_id: +e.target.value || '' })}><option value="">Não sei / outro assunto</option>{qs.map(q => <option key={q.id} value={q.id}>{q.name}</option>)}</select></Field>}
    <Field label="ASSUNTO *"><input value={x.subject} onChange={e => setX({ ...x, subject: e.target.value })} placeholder="Ex.: Impressora não imprime" /></Field>
    <Field label="PRIORIDADE"><select value={x.priority} onChange={e => setX({ ...x, priority: e.target.value })}>{PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
    <Field label="DESCRIÇÃO *"><textarea style={{ minHeight: 120 }} value={x.body} onChange={e => setX({ ...x, body: e.target.value })} placeholder="Descreva o que está acontecendo..." /></Field>
  </Modal>
}

function TicketDetail({ id, clientId, onClose, onChanged }) {
  const qs = clientId ? '?client_id=' + clientId : ''
  const t = useLoad(() => get(`/portal/tickets/${id}${qs}`), [id]); const [reply, setReply] = useState(''); const toast = useToast()
  const send = async () => { if (!reply.trim()) return; try { await post(`/portal/tickets/${id}/messages${qs}`, { body: reply }); setReply(''); t.reload(); onChanged() } catch (e) { toast(e.message, true) } }
  if (!t.data) return <Modal title="Chamado" onClose={onClose}><Loading err={t.err} /></Modal>
  const d = t.data; const closed = d.status === 'resolvido' || d.status === 'fechado'
  return <Modal wide title={`#${d.number} · ${d.subject}`} onClose={onClose}>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
      <Pill tone={STATUS_TONE[d.status]}>{d.status_label}</Pill><Pill tone={PRIORITY_TONE[d.priority]}>{d.priority_label}</Pill>
      <span className="sub">Aberto em {fmt(d.created_at)}</span></div>
    <div style={{ maxHeight: 320, overflow: 'auto', border: '1px solid var(--line)', borderRadius: 12, padding: 12, marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {d.messages.map(m => <div key={m.id} style={{ background: m.origin === 'portal' ? '#eef4ff' : '#f3f4f6', borderRadius: 10, padding: '8px 12px' }}>
        <div className="sub" style={{ marginBottom: 2 }}><b>{m.origin === 'portal' ? 'Você' : m.author_name || 'Orca TI'}</b> · {fmt(m.created_at)}</div>
        <div style={{ whiteSpace: 'pre-wrap' }}>{m.body}</div></div>)}
    </div>
    {closed ? <p className="hint">Este chamado já foi encerrado. Se o problema persistir, abra um novo chamado.</p> : <>
      <Field label="RESPONDER"><textarea style={{ minHeight: 80 }} value={reply} onChange={e => setReply(e.target.value)} placeholder="Escreva sua mensagem..." /></Field>
      <button className="btn primary" onClick={send}><MessageSquareText size={15} />Enviar</button></>}
  </Modal>
}

export function PortalTicketsTab({ clientId }) {
  const path = '/portal/tickets' + (clientId ? '?client_id=' + clientId : '')
  const list = useLoad(() => get(path), [clientId], 15000)
  const qs = useLoad(() => get('/portal/tickets/queues'), [])
  const [openId, setOpenId] = useState(null); const [newT, setNewT] = useState(false)
  return <>
    <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
      <button className="btn primary" onClick={() => setNewT(true)}><Plus />Abrir chamado</button></div>
    <Card pad={false}>{list.data ? <Table rows={list.data} onRow={r => setOpenId(r.id)} empty="Nenhum chamado aberto ainda." cols={[
      { h: '#', r: r => <b>{r.number}</b> }, { h: 'Assunto', r: r => <div className="trunc" style={{ maxWidth: 320 }}>{r.subject}</div> },
      { h: 'Prioridade', r: r => <Pill tone={PRIORITY_TONE[r.priority]}>{r.priority_label}</Pill> },
      { h: 'Situação', r: r => <Pill tone={STATUS_TONE[r.status]}>{r.status_label}</Pill> }, { h: 'Atualizado', r: r => fmt(r.updated_at) }]} /> : <Loading />}</Card>
    {openId && <TicketDetail id={openId} clientId={clientId} onClose={() => setOpenId(null)} onChanged={list.reload} />}
    {newT && <NewTicketForm qs={qs.data || []} path={path} onClose={() => setNewT(false)} onSaved={() => { setNewT(false); list.reload() }} />}
  </>
}
