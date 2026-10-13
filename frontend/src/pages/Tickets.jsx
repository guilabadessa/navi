import React, { useState } from 'react'
import { ListPlus, MessageSquareText, Paperclip, Pencil, Plus, Send, Trash2, X } from 'lucide-react'
import { get, post, put, del, upload, download } from '../api'
import { Card, Field, Loading, Modal, PageHead, Pill, Table, Tabs, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'
import { maskTarget } from '../mask'

const STATUS_TONE = { aberto: 'bad', andamento: 'warn', aguardando_cliente: 'info', aguardando_orca: 'bad', resolvido: 'ok', fechado: 'mut' }
const PRIORITY_TONE = { critica: 'bad', alta: 'warn', media: 'info', baixa: 'mut' }
const STATUSES = [['aberto', 'Aberto'], ['andamento', 'Em andamento'], ['aguardando_orca', 'Aguardando Orca TI'], ['aguardando_cliente', 'Aguardando cliente'], ['resolvido', 'Resolvido'], ['fechado', 'Fechado']]
const PRIORITIES = [['baixa', 'Baixa'], ['media', 'Média'], ['alta', 'Alta'], ['critica', 'Crítica']]
const fmt = (v) => v ? new Date(v).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '—'

function QueueForm({ q, onClose, onSaved }) {
  const [x, setX] = useState({ name: '', notify_emails: '', notify_wa_jid: '', active: true, sort: 0, ...q })
  const toast = useToast(); const set = k => e => setX({ ...x, [k]: e.target ? e.target.value : e })
  const save = async () => { try { x.id ? await put('/tickets/queues/' + x.id, x) : await post('/tickets/queues', x); toast('Fila salva'); onSaved() } catch (e) { toast(e.message, true) } }
  return <Modal title={x.id ? 'Editar fila' : 'Nova fila'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" onClick={save}>Salvar</button></>}>
    <Field label="NOME DA FILA *" hint="Ex.: SOC (Fortinet/EMS), Cloud, Backup (Acronis)."><input value={x.name} onChange={set('name')} placeholder="SOC" /></Field>
    <Field label="E-MAILS AVISADOS (vírgula)" hint="Toda essa fila recebe aviso quando um chamado é aberto ou atualizado."><textarea style={{ minHeight: 70 }} value={x.notify_emails || ''} onChange={set('notify_emails')} placeholder="soc@orcati.com.br, nome@orcati.com.br" /></Field>
    <Field label="GRUPO/NÚMERO DO WHATSAPP (opcional)"><input value={x.notify_wa_jid || ''} onChange={e => setX({ ...x, notify_wa_jid: maskTarget(e.target.value) })} placeholder="120363...@g.us ou (14) 99999-9999" /></Field>
    <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}><input type="checkbox" checked={x.active} onChange={e => setX({ ...x, active: e.target.checked })} /> Fila ativa</label>
  </Modal>
}

function QueuesTab() {
  const me = useAuth(); const admin = can(me, 'settings.edit')
  const queues = useLoad(() => get('/tickets/queues'), []); const [ed, setEd] = useState(null)
  return <>
    <Card pad={false} title={admin ? undefined : 'Filas de chamado'}>
    {admin && <div style={{ padding: 14, display: 'flex', justifyContent: 'flex-end' }}><button className="btn primary" onClick={() => setEd({})}><Plus />Nova fila</button></div>}
    {queues.data ? <Table rows={queues.data} empty="Nenhuma fila cadastrada ainda." cols={[
      { h: 'Fila', r: r => <b>{r.name}</b> },
      { h: 'E-mails avisados', r: r => <div className="sub trunc" style={{ maxWidth: 320 }} title={r.notify_emails || ''}>{r.notify_emails || '—'}</div> },
      { h: 'WhatsApp', r: r => r.notify_wa_jid || '—' },
      { h: 'Estado', r: r => <Pill tone={r.active ? 'ok' : 'mut'}>{r.active ? 'ativa' : 'desligada'}</Pill> },
      { h: '', r: r => admin && <div style={{ display: 'flex', gap: 6 }}><button className="btn sm" onClick={() => setEd(r)}><Pencil /></button>
        <button className="btn sm danger" onClick={async () => { if (confirm('Excluir esta fila? Os chamados ficam sem fila.')) { await del('/tickets/queues/' + r.id); queues.reload() } }}><Trash2 /></button></div> }]} /> : <Loading />}
    {!admin && <p className="hint" style={{ padding: 14 }}>Somente um administrador pode criar ou editar filas.</p>}
    </Card>
    {ed && <QueueForm q={ed} onClose={() => setEd(null)} onSaved={() => { setEd(null); queues.reload() }} />}
  </>
}

function NewTicketForm({ clients, queues, onClose, onSaved }) {
  const [x, setX] = useState({ client_id: clients[0]?.id || '', queue_id: queues[0]?.id || '', subject: '', priority: 'media', body: '' })
  const [watchers, setWatchers] = useState([]); const [wk, setWk] = useState('email'); const [wt, setWt] = useState(''); const [wl, setWl] = useState('')
  const toast = useToast()
  const addWatcher = () => { if (!wt.trim()) return; setWatchers([...watchers, { kind: wk, target: wk === 'whatsapp' ? maskTarget(wt) : wt.trim(), label: wl.trim() || null }]); setWt(''); setWl('') }
  const save = async () => {
    if (!x.client_id || !x.subject.trim() || !x.body.trim()) { toast('Preencha cliente, assunto e descrição', true); return }
    try { await post('/tickets', { ...x, queue_id: x.queue_id || null, watchers }); toast('Chamado aberto'); onSaved() } catch (e) { toast(e.message, true) }
  }
  return <Modal wide title="Novo chamado" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" onClick={save}><Send size={15} />Abrir chamado</button></>}>
    <div className="row r2">
      <Field label="CLIENTE *"><select value={x.client_id} onChange={e => setX({ ...x, client_id: +e.target.value })}>{clients.map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select></Field>
      <Field label="FILA" hint="Define quem recebe o aviso por tecnologia."><select value={x.queue_id} onChange={e => setX({ ...x, queue_id: +e.target.value || '' })}><option value="">Sem fila</option>{queues.map(q => <option key={q.id} value={q.id}>{q.name}</option>)}</select></Field></div>
    <div className="row r2">
      <Field label="ASSUNTO *"><input value={x.subject} onChange={e => setX({ ...x, subject: e.target.value })} placeholder="Ex.: Lentidão no acesso remoto" /></Field>
      <Field label="PRIORIDADE"><select value={x.priority} onChange={e => setX({ ...x, priority: e.target.value })}>{PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field></div>
    <Field label="DESCRIÇÃO *"><textarea style={{ minHeight: 120 }} value={x.body} onChange={e => setX({ ...x, body: e.target.value })} placeholder="O que o cliente reportou, horário, impacto..." /></Field>
    <Field label="RECEBER CÓPIA (CC) — e-mail, grupo ou celular, pode adicionar vários">
      <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <select value={wk} onChange={e => setWk(e.target.value)} style={{ width: 130 }}><option value="email">E-mail</option><option value="whatsapp">WhatsApp</option></select>
        <input value={wt} onChange={e => setWt(e.target.value)} placeholder={wk === 'email' ? 'pessoa@cliente.com.br' : '(14) 99999-9999 ou grupo@g.us'} style={{ flex: 1, minWidth: 180 }} />
        <input value={wl} onChange={e => setWl(e.target.value)} placeholder="nome (opcional)" style={{ width: 160 }} />
        <button type="button" className="btn sm" onClick={addWatcher}><ListPlus size={15} />Adicionar</button></div>
      {watchers.length > 0 && <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{watchers.map((w, i) => <span key={i} className="chip">{w.label ? `${w.label} · ` : ''}{w.target} ({w.kind === 'email' ? 'e-mail' : 'WhatsApp'})
        <X size={12} style={{ cursor: 'pointer', marginLeft: 4 }} onClick={() => setWatchers(watchers.filter((_, j) => j !== i))} /></span>)}</div>}
    </Field>
  </Modal>
}

function TicketDetail({ id, queues, canEdit, onClose, onChanged }) {
  const t = useLoad(() => get('/tickets/' + id), [id]); const toast = useToast()
  const [reply, setReply] = useState(''); const [internal, setInternal] = useState(false); const [sending, setSending] = useState(false)
  const [wk, setWk] = useState('email'); const [wt, setWt] = useState(''); const [wl, setWl] = useState('')
  const send = async () => { if (!reply.trim()) return; try { await post(`/tickets/${id}/messages`, { body: reply, internal }); setReply(''); t.reload(); onChanged() } catch (e) { toast(e.message, true) } }
  const sendFile = async (e) => {
    const file = e.target.files[0]; e.target.value = ''; if (!file) return
    if (file.size > 15 * 1024 * 1024) { toast('Arquivo maior que 15 MB', true); return }
    setSending(true); try { await upload(`/tickets/${id}/attachments`, file); t.reload(); onChanged() } catch (e2) { toast(e2.message, true) } finally { setSending(false) }
  }
  const getAttachment = (m) => download(`/tickets/${id}/attachments/${m.attachment.id}`, m.attachment.filename)
  const setStatus = async (status) => { try { await put('/tickets/' + id, { status, priority: t.data.priority, queue_id: t.data.queue_id }); t.reload(); onChanged() } catch (e) { toast(e.message, true) } }
  const setField = async (field, value) => { try { await put('/tickets/' + id, { status: t.data.status, priority: t.data.priority, queue_id: t.data.queue_id, [field]: value }); t.reload(); onChanged() } catch (e) { toast(e.message, true) } }
  const addWatcher = async () => { if (!wt.trim()) return; try { await post(`/tickets/${id}/watchers`, { kind: wk, target: wk === 'whatsapp' ? maskTarget(wt) : wt.trim(), label: wl.trim() || null }); setWt(''); setWl(''); t.reload() } catch (e) { toast(e.message, true) } }
  if (!t.data) return <Modal title="Chamado" onClose={onClose}><Loading err={t.err} /></Modal>
  const d = t.data
  return <Modal wide title={`#${d.number} · ${d.subject}`} onClose={onClose}>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
      <Pill tone={STATUS_TONE[d.status]}>{d.status_label}</Pill><Pill tone={PRIORITY_TONE[d.priority]}>{d.priority_label}</Pill>
      <span className="sub">Cliente: <b>{d.client}</b> · Fila: {d.queue || 'sem fila'} · Aberto {fmt(d.created_at)} por {d.created_by_name}{d.origin === 'portal' ? ' (portal)' : ''}</span></div>
    {canEdit && <div className="row r3" style={{ marginBottom: 14 }}>
      <Field label="SITUAÇÃO"><select value={d.status} onChange={e => setStatus(e.target.value)}>{STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
      <Field label="PRIORIDADE"><select value={d.priority} onChange={e => setField('priority', e.target.value)}>{PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
      <Field label="FILA"><select value={d.queue_id || ''} onChange={e => setField('queue_id', +e.target.value || null)}><option value="">Sem fila</option>{queues.map(q => <option key={q.id} value={q.id}>{q.name}</option>)}</select></Field></div>}
    <div style={{ maxHeight: 320, overflow: 'auto', border: '1px solid var(--line)', borderRadius: 12, padding: 12, marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {d.messages.length === 0 && <span className="sub">Sem mensagens.</span>}
      {d.messages.map(m => <div key={m.id} style={{ background: m.internal ? '#fff7e0' : m.origin === 'portal' ? '#eef4ff' : '#f3f4f6', borderRadius: 10, padding: '8px 12px' }}>
        <div className="sub" style={{ marginBottom: 2 }}><b>{m.author_name || 'NAVI'}</b>{m.internal ? ' · nota interna' : m.origin === 'portal' ? ' · cliente' : ''} · {fmt(m.created_at)}</div>
        <div style={{ whiteSpace: 'pre-wrap' }}>{m.body}</div>
        {m.attachment && <button type="button" className="btn sm" style={{ marginTop: 6 }} onClick={() => getAttachment(m)}><Paperclip size={14} />{m.attachment.filename} ({Math.ceil(m.attachment.size_bytes / 1024)} KB)</button>}</div>)}
    </div>
    {canEdit && <>
      <Field label="RESPONDER"><textarea style={{ minHeight: 80 }} value={reply} onChange={e => setReply(e.target.value)} placeholder="Mensagem para o cliente (ou nota interna)..." /></Field>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}><input type="checkbox" checked={internal} onChange={e => setInternal(e.target.checked)} /> Nota interna (não avisa o cliente/fila)</label>
        <button className="btn primary" onClick={send}><MessageSquareText size={15} />Enviar</button>
        <label className="btn sm" style={{ cursor: sending ? 'wait' : 'pointer' }}><Paperclip size={15} />{sending ? 'Enviando…' : 'Anexar arquivo'}<input type="file" style={{ display: 'none' }} disabled={sending} onChange={sendFile} /></label>
        <span className="sub">Até 15 MB · imagens, PDF, TXT, CSV, ZIP, 7z, backups (.bak)</span></div>
      <Field label="OBSERVADORES (CC) DESTE CHAMADO">
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>{d.watchers.map(w => <span key={w.id} className="chip">{w.label ? `${w.label} · ` : ''}{w.target}
          <X size={12} style={{ cursor: 'pointer', marginLeft: 4 }} onClick={async () => { await del(`/tickets/${id}/watchers/${w.id}`); t.reload() }} /></span>)}</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <select value={wk} onChange={e => setWk(e.target.value)} style={{ width: 130 }}><option value="email">E-mail</option><option value="whatsapp">WhatsApp</option></select>
          <input value={wt} onChange={e => setWt(e.target.value)} placeholder={wk === 'email' ? 'pessoa@cliente.com.br' : '(14) 99999-9999 ou grupo@g.us'} style={{ flex: 1, minWidth: 180 }} />
          <input value={wl} onChange={e => setWl(e.target.value)} placeholder="nome (opcional)" style={{ width: 160 }} />
          <button type="button" className="btn sm" onClick={addWatcher}><ListPlus size={15} />Adicionar</button></div>
      </Field></>}
  </Modal>
}

function TicketsTab() {
  const me = useAuth(); const edit = can(me, 'tickets.edit')
  const [status, setStatus] = useState(''); const [openId, setOpenId] = useState(null); const [newT, setNewT] = useState(false)
  const list = useLoad(() => get('/tickets' + (status ? `?status=${status}` : '')), [status], 15000)
  const clients = useLoad(() => get('/clients'), []); const queues = useLoad(() => get('/tickets/queues'), [])
  return <>
    <div style={{ display: 'flex', gap: 10, justifyContent: 'space-between', margin: '12px 0' }}>
      <select value={status} onChange={e => setStatus(e.target.value)} style={{ width: 220 }}><option value="">Todas as situações</option>{STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
      {edit && <button className="btn primary" onClick={() => setNewT(true)}><Plus />Novo chamado</button>}</div>
    <Card pad={false}>{list.data ? <Table rows={list.data} onRow={r => setOpenId(r.id)} empty="Nenhum chamado encontrado." cols={[
      { h: '#', r: r => <b>{r.number}</b> }, { h: 'Cliente', r: r => r.client }, { h: 'Assunto', r: r => <div className="trunc" style={{ maxWidth: 280 }}>{r.subject}</div> },
      { h: 'Fila', r: r => r.queue || '—' }, { h: 'Prioridade', r: r => <Pill tone={PRIORITY_TONE[r.priority]}>{r.priority_label}</Pill> },
      { h: 'Situação', r: r => <Pill tone={STATUS_TONE[r.status]}>{r.status_label}</Pill> }, { h: 'Atualizado', r: r => fmt(r.updated_at) }]} /> : <Loading />}</Card>
    {openId && <TicketDetail id={openId} queues={queues.data || []} canEdit={edit} onClose={() => setOpenId(null)} onChanged={list.reload} />}
    {newT && clients.data && <NewTicketForm clients={clients.data} queues={queues.data || []} onClose={() => setNewT(false)} onSaved={() => { setNewT(false); list.reload() }} />}
  </>
}

export default function Tickets() {
  const me = useAuth(); const [tab, setTab] = useState('list'); const admin = can(me, 'settings.edit')
  return <>
    <PageHead title="Chamados" desc="Abertura e acompanhamento de chamados por cliente, com fila por tecnologia e cópia (CC) por e-mail ou WhatsApp" />
    {admin ? <><Tabs value={tab} onChange={setTab} tabs={[['list', 'Chamados'], ['queues', 'Filas']]} />
      {tab === 'list' && <TicketsTab />}{tab === 'queues' && <QueuesTab />}</> : <TicketsTab />}
  </>
}
