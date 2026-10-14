import React, { useState } from 'react'
import { CheckCircle2, MessageSquareText, Paperclip, Plus, Send } from 'lucide-react'
import { get, post, upload, download } from '../api'
import { Card, Field, Loading, Modal, Pill, Table, useLoad, useToast } from '../ui'
import { maskTarget } from '../mask'

const STATUS_TONE = { aberto: 'bad', andamento: 'warn', aguardando_cliente: 'info', aguardando_orca: 'bad', resolvido: 'ok', fechado: 'mut' }
const PRIORITY_TONE = { critica: 'bad', alta: 'warn', media: 'info', baixa: 'mut' }
const PRIORITIES = [['baixa', 'Baixa'], ['media', 'Média'], ['alta', 'Alta'], ['critica', 'Crítica']]
const fmt = (v) => v ? new Date(v).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '—'

function NewTicketForm({ qs, path, onClose, onSaved }) {
  const [x, setX] = useState({ queue_id: qs[0]?.id || '', subject: '', priority: 'media', body: '', contact_phone: '', unit: '' })
  const toast = useToast()
  const save = async () => {
    if (!x.subject.trim() || !x.body.trim()) { toast('Preencha o assunto e a descrição', true); return }
    try { await post(path, { ...x, queue_id: x.queue_id || null, contact_phone: x.contact_phone || null, unit: x.unit.trim() || null }); toast('Chamado aberto! Nossa equipe já foi avisada.'); onSaved() } catch (e) { toast(e.message, true) }
  }
  return <Modal title="Abrir chamado" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" onClick={save}><Send size={15} />Abrir chamado</button></>}>
    {qs.length > 0 && <Field label="ASSUNTO SOBRE" hint="Ajuda a direcionar para o time certo."><select value={x.queue_id} onChange={e => setX({ ...x, queue_id: +e.target.value || '' })}><option value="">Não sei / outro assunto</option>{qs.map(q => <option key={q.id} value={q.id}>{q.name}</option>)}</select></Field>}
    <Field label="ASSUNTO *"><input value={x.subject} onChange={e => setX({ ...x, subject: e.target.value })} placeholder="Ex.: Impressora não imprime" /></Field>
    <Field label="UNIDADE (opcional)" hint="Se a sua empresa tem mais de uma unidade, informe a qual este chamado se refere."><input value={x.unit} onChange={e => setX({ ...x, unit: e.target.value })} placeholder="Ex.: Matriz, Filial Bauru" /></Field>
    <div className="row r2">
      <Field label="PRIORIDADE"><select value={x.priority} onChange={e => setX({ ...x, priority: e.target.value })}>{PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
      <Field label="TELEFONE PARA CONTATO (opcional)"><input value={x.contact_phone} onChange={e => setX({ ...x, contact_phone: maskTarget(e.target.value) })} placeholder="(14) 99999-9999" /></Field></div>
    <Field label="DESCRIÇÃO *"><textarea style={{ minHeight: 120 }} value={x.body} onChange={e => setX({ ...x, body: e.target.value })} placeholder="Descreva o que está acontecendo..." /></Field>
  </Modal>
}

function TicketDetail({ id, clientId, onClose, onChanged }) {
  const qsuf = clientId ? '?client_id=' + clientId : ''
  const t = useLoad(() => get(`/portal/tickets/${id}${qsuf}`), [id]); const [reply, setReply] = useState('')
  const [sending, setSending] = useState(false); const [closing, setClosing] = useState(false); const toast = useToast()
  const send = async (close) => {
    if (!reply.trim()) { toast(close ? 'Escreva um comentário antes de encerrar' : 'Escreva uma mensagem', true); return }
    try { await post(`/portal/tickets/${id}/messages${qsuf}`, { body: reply, status: close ? 'resolvido' : undefined }); setReply(''); setClosing(false); t.reload(); onChanged() } catch (e) { toast(e.message, true) }
  }
  const sendFile = async (e) => {
    const file = e.target.files[0]; e.target.value = ''; if (!file) return
    if (file.size > 15 * 1024 * 1024) { toast('Arquivo maior que 15 MB', true); return }
    setSending(true); try { await upload(`/portal/tickets/${id}/attachments${qsuf}`, file); t.reload(); onChanged() } catch (e2) { toast(e2.message, true) } finally { setSending(false) }
  }
  const getAttachment = (m) => download(`/portal/tickets/${id}/attachments/${m.attachment.id}${qsuf}`, m.attachment.filename)
  if (!t.data) return <Modal title="Chamado" onClose={onClose}><Loading err={t.err} /></Modal>
  const d = t.data; const closed = d.status === 'resolvido' || d.status === 'fechado'
  return <Modal wide title={`#${d.number} · ${d.subject}`} onClose={onClose}>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
      <Pill tone={STATUS_TONE[d.status]}>{d.status_label}</Pill><Pill tone={PRIORITY_TONE[d.priority]}>{d.priority_label}</Pill>
      <span className="sub">Aberto em {fmt(d.created_at)}{d.unit ? ` · Unidade: ${d.unit}` : ''}{d.contact_phone ? ` · Tel.: ${d.contact_phone}` : ''}</span></div>
    <div style={{ maxHeight: 320, overflow: 'auto', border: '1px solid var(--line)', borderRadius: 12, padding: 12, marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {d.messages.map(m => <div key={m.id} style={{ background: m.origin === 'portal' ? '#eef4ff' : '#f3f4f6', borderRadius: 10, padding: '8px 12px' }}>
        <div className="sub" style={{ marginBottom: 2 }}><b>{m.origin === 'portal' ? 'Você' : m.author_name || 'Orca TI'}</b> · {fmt(m.created_at)}{m.status_change && <> · <Pill tone={STATUS_TONE[m.status_change]}>→ {m.status_change_label}</Pill></>}</div>
        <div style={{ whiteSpace: 'pre-wrap' }}>{m.body}</div>
        {m.attachment && <button type="button" className="btn sm" style={{ marginTop: 6 }} onClick={() => getAttachment(m)}><Paperclip size={14} />{m.attachment.filename} ({Math.ceil(m.attachment.size_bytes / 1024)} KB)</button>}</div>)}
    </div>
    {closed ? <p className="hint">Este chamado já foi encerrado. Se o problema persistir, abra um novo chamado.</p> : <>
      <Field label={closing ? 'COMENTÁRIO DE ENCERRAMENTO (obrigatório) *' : 'RESPONDER'}>
        <textarea style={{ minHeight: 80 }} value={reply} onChange={e => setReply(e.target.value)} placeholder={closing ? 'Explique rapidamente como foi resolvido...' : 'Escreva sua mensagem...'} /></Field>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        {closing ? <>
          <button className="btn primary" onClick={() => send(true)}><CheckCircle2 size={15} />Confirmar encerramento</button>
          <button className="btn sm" onClick={() => setClosing(false)}>Cancelar</button></> : <>
          <button className="btn primary" onClick={() => send(false)}><MessageSquareText size={15} />Enviar</button>
          <button className="btn sm" onClick={() => setClosing(true)}><CheckCircle2 size={15} />Encerrar chamado</button>
          <label className="btn sm" style={{ cursor: sending ? 'wait' : 'pointer' }}><Paperclip size={15} />{sending ? 'Enviando…' : 'Anexar arquivo'}<input type="file" style={{ display: 'none' }} disabled={sending} onChange={sendFile} /></label>
          <span className="sub">Até 15 MB</span></>}</div></>}
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
      { h: '#', r: r => <b>{r.number}</b> }, { h: 'Assunto', r: r => <div className="trunc" style={{ maxWidth: 320 }}>{r.subject}</div> }, { h: 'Unidade', r: r => r.unit || <span className="sub">—</span> },
      { h: 'Prioridade', r: r => <Pill tone={PRIORITY_TONE[r.priority]}>{r.priority_label}</Pill> },
      { h: 'Situação', r: r => <Pill tone={STATUS_TONE[r.status]}>{r.status_label}</Pill> }, { h: 'Atualizado', r: r => fmt(r.updated_at) }]} /> : <Loading />}</Card>
    {openId && <TicketDetail id={openId} clientId={clientId} onClose={() => setOpenId(null)} onChanged={list.reload} />}
    {newT && <NewTicketForm qs={qs.data || []} path={path} onClose={() => setNewT(false)} onSaved={() => { setNewT(false); list.reload() }} />}
  </>
}
