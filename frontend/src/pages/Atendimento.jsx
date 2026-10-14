import React, { useEffect, useRef, useState } from 'react'
import { Link2, Paperclip, Pencil, Send, StickyNote, Tag, UserCheck, X, ArrowRightLeft } from 'lucide-react'
import { get, post, put, uploadForm } from '../api'
import { Card, Field, Modal, PageHead, Pill, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'
import { Link } from 'react-router-dom'
import AtNav from './AtNav'

const STATE = { menu: ['mut', 'No menu'], aguardando: ['warn', 'Aguardando'], atendendo: ['ok', 'Em atendimento'], encerrada: ['mut', 'Encerrada'] }
const dur = (s) => s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}min` : `${Math.floor(s / 3600)}h${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}`
const hora = (v) => v ? new Date(v).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : ''

function Monitor({ q, sel, onSel }) {
  return <div className="at-queues">{q.queues.map(x => {
    const late = x.waiting > 0 && x.oldest_seconds >= (x.alert_min || 5) * 60
    return <button key={x.queue} className={'at-q' + (sel === x.queue ? ' on' : '') + (late ? ' late' : '')} style={{ borderTop: `3px solid ${x.color}` }} onClick={() => onSel(sel === x.queue ? '' : x.queue)}>
      <span>{x.label}</span><b>{x.waiting}</b><small>{x.waiting ? `maior espera ${dur(x.oldest_seconds)}` : 'sem espera'} · {x.active} em atendimento</small></button>
  })}</div>
}

const QPill = ({ name, color }) => <span className="badge" style={{ background: (color || '#6b7a99') + '26', color: color || '#6b7a99', border: `1px solid ${(color || '#6b7a99')}55` }}>{name}</span>

function Transfer({ conv, onClose, onDone }) {
  const toast = useToast(); const agents = useLoad(() => get('/atendimento/agents'), []); const qs = useLoad(() => get('/atendimento/queue-defs'), [])
  const [u, setU] = useState(''); const [qq, setQq] = useState('')
  const go = async () => { try { await post(`/atendimento/conversations/${conv.id}/transfer`, { user_id: u ? +u : null, queue: qq || null }); toast('Conversa transferida'); onDone() } catch (e) { toast(e.message, true) } }
  return <Modal title="Transferir conversa" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" disabled={!u && !qq} onClick={go}>Transferir</button></>}>
    <Field label="PARA O ANALISTA" hint="Deixe em branco para devolver à fila do setor escolhido."><select value={u} onChange={e => setU(e.target.value)}><option value="">— fila do setor —</option>{(agents.data || []).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
    <Field label="SETOR"><select value={qq} onChange={e => setQq(e.target.value)}><option value="">— manter —</option>{(qs.data || []).filter(x => x.active).map(x => <option key={x.slug} value={x.slug}>{x.name}</option>)}</select></Field>
  </Modal>
}

function LinkClient({ conv, onClose, onDone }) {
  const toast = useToast(); const [q, setQ] = useState(''); const { data } = useLoad(() => get('/clients' + (q ? '?q=' + encodeURIComponent(q) : '')), [q])
  const rows = (Array.isArray(data) ? data : data?.items || []).slice(0, 8)
  const pick = async (id) => { try { await post(`/atendimento/conversations/${conv.id}/link-client`, { client_id: id }); onDone() } catch (e) { toast(e.message, true) } }
  return <Modal title="Vincular a um cliente" onClose={onClose}>
    <Field label="BUSCAR POR NOME OU CNPJ"><input autoFocus value={q} onChange={e => setQ(e.target.value)} /></Field>
    {rows.map(c => <button key={c.id} className="btn" style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: 6 }} onClick={() => pick(c.id)}>{c.trade_name}{c.cnpj ? ` · ${c.cnpj}` : ''}</button>)}
    {conv.client && <button className="btn" onClick={() => pick(null)}>Remover vínculo</button>}
  </Modal>
}

export function Bubble({ m }) {
  if (m.direction === 'sys') return <div className="at-sys">{m.text} · {hora(m.created_at)}</div>
  const out = m.direction === 'out', note = m.direction === 'note'
  return <div className={'at-msg ' + (note ? 'note' : out ? 'out' : 'in') + (m.failed ? ' failed' : '')}>
    {note && <b className="at-notelabel"><StickyNote size={12} /> Nota interna</b>}
    {m.has_media && (m.type === 'IMAGE' ? <img alt="Imagem recebida" src={`/cliente/api/atendimento/messages/${m.id}/media`} style={{ maxWidth: 240, borderRadius: 8, display: 'block', marginBottom: 4 }} />
      : <a href={`/cliente/api/atendimento/messages/${m.id}/media`} target="_blank" rel="noreferrer">📎 Abrir {m.type === 'DOCUMENT' ? 'documento' : 'anexo'}</a>)}
    {m.text && <div style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>}
    <small>{(out || note) && m.sent_by ? m.sent_by + ' · ' : ''}{hora(m.created_at)}{m.failed ? ' · não enviada' : ''}</small>
  </div>
}

const TagChip = ({ t, color, onRemove }) => <span className="at-tag" style={{ background: (color || '#6b7a99') + '26', color: color || '#6b7a99', border: `1px solid ${(color || '#6b7a99')}55` }}>{t}{onRemove && <button aria-label={'Remover ' + t} onClick={onRemove}>×</button>}</span>

function Chat({ conv, me, tags, onChange }) {
  const toast = useToast(); const act = can(me, 'atendimento.act')
  const [msgs, setMsgs] = useState([]); const [text, setText] = useState(''); const [modal, setModal] = useState(null); const [busy, setBusy] = useState(false); const [mode, setMode] = useState('reply')
  const [editName, setEditName] = useState(null)
  const cfg = useLoad(() => get('/atendimento/config'), [])
  const last = useRef(0); const box = useRef(null); const file = useRef(null)
  useEffect(() => { setMsgs([]); last.current = 0; setMode('reply'); setText(''); setEditName(null) }, [conv.id])
  useEffect(() => {
    let off = false
    const run = async () => {
      try {
        const r = await get(`/atendimento/conversations/${conv.id}/messages?since=${last.current}`)
        if (off || !r.messages.length) return
        last.current = r.messages[r.messages.length - 1].id
        setMsgs(x => [...x, ...r.messages]); setTimeout(() => box.current && (box.current.scrollTop = box.current.scrollHeight), 30)
      } catch { /* proxima rodada tenta de novo */ }
    }
    run(); const t = setInterval(run, 3000); return () => { off = true; clearInterval(t) }
  }, [conv.id])
  const mine = conv.assigned_to === me.id; const closed = conv.state === 'encerrada'
  const send = async () => {
    const t = text.trim(); if (!t || busy) return
    setBusy(true)
    try { await post(`/atendimento/conversations/${conv.id}/${mode === 'note' ? 'note' : 'send'}`, { text: t }); setText('') } catch (e) { toast(e.message, true) } finally { setBusy(false) }
  }
  const sendFile = async (f) => {
    if (!f) return; const fd = new FormData(); fd.append('file', f)
    try { await uploadForm('/atendimento/conversations/' + conv.id + '/send-media', fd) } catch (e) { toast(e.message, true) }
  }
  const call = async (path, body, msg) => { try { await post(`/atendimento/conversations/${conv.id}/${path}`, body); if (msg) toast(msg); onChange() } catch (e) { toast(e.message, true); onChange() } }
  const edit = async (body) => { try { await put(`/atendimento/conversations/${conv.id}`, body); onChange() } catch (e) { toast(e.message, true) } }
  const [tone, label] = STATE[conv.state] || ['mut', conv.state]
  const colorOf = (n) => (tags.find(t => t.name === n) || {}).color
  const free = tags.filter(t => !(conv.tags || []).includes(t.name))
  const canReply = act && !closed && conv.state === 'atendendo'
  return <div className="at-chat">
    <div className="at-head"><div>
      {editName === null ? <><b>{conv.name || conv.number}</b>{act && <button className="btn sm" aria-label="Editar nome do contato" style={{ marginLeft: 6 }} onClick={() => setEditName(conv.name || '')}><Pencil size={12} /></button>}</>
        : <span style={{ display: 'inline-flex', gap: 6 }}><input autoFocus value={editName} onChange={e => setEditName(e.target.value)} maxLength={255} onKeyDown={e => { if (e.key === 'Enter') { edit({ contact_name: editName }); setEditName(null) } if (e.key === 'Escape') setEditName(null) }} />
          <button className="btn sm primary" onClick={() => { edit({ contact_name: editName }); setEditName(null) }}>OK</button></span>}
      {' '}<span className="sub">+{conv.number}</span>{conv.client && <> · <Pill tone="info">{conv.client.name}</Pill></>}</div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}><Pill tone={tone}>{label}</Pill><QPill name={conv.queue_name} color={conv.queue_color} />{conv.assigned_name && <Pill tone="info">{conv.assigned_name}</Pill>}
        {act && !closed && <>
          {conv.state === 'aguardando' && <button className="btn primary" onClick={() => call('assume', {}, 'Você assumiu a conversa')}><UserCheck size={16} />Assumir</button>}
          <button className="btn" onClick={() => setModal('transfer')}><ArrowRightLeft size={16} />Transferir</button>
          <button className="btn" onClick={() => setModal('link')}><Link2 size={16} />Cliente</button>
          <button className="btn" onClick={() => { if (confirm('Encerrar este atendimento e avisar o cliente?')) call('close', { send_closing: true }, 'Atendimento encerrado') }}><X size={16} />Encerrar</button></>}</div></div>
    <div className="at-tk"><Tag size={13} />{(conv.tags || []).map(t => <TagChip key={t} t={t} color={colorOf(t)} onRemove={act ? () => edit({ tags: conv.tags.filter(x => x !== t) }) : null} />)}
      {act && free.length > 0 && <select aria-label="Adicionar etiqueta" value="" onChange={e => e.target.value && edit({ tags: [...(conv.tags || []), e.target.value] })} style={{ width: 150 }}><option value="">+ etiqueta</option>{free.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}</select>}
      {!(conv.tags || []).length && !free.length && <span className="sub">Sem etiquetas (crie em Configurações)</span>}</div>
    {conv.client && conv.client.tickets?.length > 0 && <div className="at-tk"><b>Chamados abertos:</b> {conv.client.tickets.map(t => <Link key={t.id} to="/chamados" title={t.subject}>#{t.number} {t.subject.slice(0, 40)}</Link>)}</div>}
    <div className="at-body" ref={box}>{msgs.map(m => <Bubble key={m.id} m={m} />)}{!msgs.length && <div className="empty">Sem mensagens.</div>}</div>
    {act && <div className="at-modes"><button className={mode === 'reply' ? 'on' : ''} onClick={() => setMode('reply')}>Responder</button><button className={mode === 'note' ? 'on' : ''} onClick={() => setMode('note')}><StickyNote size={13} /> Nota interna</button></div>}
    {act && mode === 'note' && <div className="at-send note"><textarea value={text} onChange={e => setText(e.target.value)} placeholder="Anotação visível só para a equipe (não vai para o cliente)…" rows={2} />
      <button className="btn primary" disabled={busy || !text.trim()} onClick={send}>Salvar nota</button></div>}
    {act && mode === 'reply' && (canReply ? <div className="at-send">
      <input type="file" ref={file} hidden onChange={e => { sendFile(e.target.files[0]); e.target.value = '' }} />
      <button className="btn" aria-label="Anexar arquivo" onClick={() => file.current.click()}><Paperclip size={16} /></button>
      {cfg.data?.quick_replies?.length > 0 && <select aria-label="Respostas prontas" value="" onChange={e => { const r = cfg.data.quick_replies[+e.target.value]; if (r) setText(t => (t ? t + '\n' : '') + r.text) }} style={{ width: 130 }}>
        <option value="">Respostas…</option>{cfg.data.quick_replies.map((r, i) => <option key={i} value={i}>{r.title}</option>)}</select>}
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder={mine ? 'Digite a resposta…' : 'Esta conversa é de outro analista; você pode responder mesmo assim.'} rows={2}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
      <button className="btn primary" disabled={busy || !text.trim()} onClick={send}><Send size={16} />Enviar</button></div>
      : <div className="at-send sub">{closed ? 'Conversa encerrada.' : conv.state === 'aguardando' ? 'Assuma a conversa para responder.' : 'Cliente ainda no menu.'}</div>)}
    {modal === 'transfer' && <Transfer conv={conv} onClose={() => setModal(null)} onDone={() => { setModal(null); onChange() }} />}
    {modal === 'link' && <LinkClient conv={conv} onClose={() => setModal(null)} onDone={() => { setModal(null); onChange() }} />}
  </div>
}

const TABS = [['fila', 'Fila'], ['meus', 'Meus'], ['todos', 'Todos abertos'], ['enc', 'Encerradas']]

export default function Atendimento() {
  const me = useAuth(); const [tab, setTab] = useState('fila'); const [queue, setQueue] = useState(''); const [search, setSearch] = useState(''); const [tag, setTag] = useState(''); const [selId, setSelId] = useState(null)
  const q = useLoad(() => get('/atendimento/queues'), [], 3000)
  const open = useLoad(() => get('/atendimento/conversations'), [], 3000)
  const closedList = useLoad(() => tab === 'enc' ? get('/atendimento/conversations?state=encerrada') : Promise.resolve([]), [tab], 8000)
  const tags = useLoad(() => get('/atendimento/tags'), [])
  const all = open.data || []
  const count = { fila: all.filter(c => ['aguardando', 'menu'].includes(c.state)).length, meus: all.filter(c => c.state === 'atendendo' && c.assigned_to === me.id).length, todos: all.length }
  const base = tab === 'enc' ? (closedList.data || []) : tab === 'fila' ? all.filter(c => ['aguardando', 'menu'].includes(c.state)) : tab === 'meus' ? all.filter(c => c.state === 'atendendo' && c.assigned_to === me.id) : all
  const term = search.trim().toLowerCase()
  const rows = base.filter(c => (!queue || c.queue === queue) && (!tag || (c.tags || []).includes(tag)) &&
    (!term || [c.name, c.number, c.client?.name, c.last_text].some(v => (v || '').toLowerCase().includes(term))))
  const sel = [...all, ...(closedList.data || [])].find(c => c.id === selId)
  const waiting = (q.data?.queues || []).reduce((n, x) => n + x.waiting, 0)
  const colorOf = (n) => ((tags.data || []).find(t => t.name === n) || {}).color
  useEffect(() => { document.title = (waiting ? `(${waiting}) ` : '') + 'NAVI'; return () => { document.title = 'NAVI' } }, [waiting])
  const reload = () => { open.reload(); q.reload(); closedList.reload() }
  return <>
    <PageHead title="Atendimento" desc="Clientes de WhatsApp aguardando e em atendimento" />
    <AtNav />
    {q.data && <Monitor q={q.data} sel={queue} onSel={setQueue} />}
    <div className="at-grid">
      <Card pad={false} title={undefined}>
        <div className="at-tabs">{TABS.map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}{count[k] != null && <span>{count[k]}</span>}</button>)}</div>
        <div className="at-filters"><input placeholder="Buscar nome, número ou cliente…" value={search} onChange={e => setSearch(e.target.value)} aria-label="Buscar conversas" />
          {(tags.data || []).length > 0 && <select aria-label="Filtrar por etiqueta" value={tag} onChange={e => setTag(e.target.value)} style={{ width: 130 }}><option value="">Etiquetas</option>{tags.data.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}</select>}</div>
        <div className="at-list">{rows.map(c => {
          const [tone, label] = STATE[c.state] || ['mut', c.state]
          return <button key={c.id} className={'at-item' + (c.id === selId ? ' on' : '')} onClick={() => setSelId(c.id)}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><b>{c.name || c.number}</b>{c.unread > 0 && <span className="at-unread">{c.unread}</span>}</div>
            <div className="sub">{c.client ? c.client.name : '+' + c.number}</div>
            <div className="sub" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.last_text}</div>
            <div style={{ display: 'flex', gap: 6, marginTop: 4, flexWrap: 'wrap' }}><Pill tone={tone}>{label}</Pill><QPill name={c.queue_name} color={c.queue_color} />{(c.tags || []).map(t => <TagChip key={t} t={t} color={colorOf(t)} />)}{c.state !== 'atendendo' && c.wait_seconds > 0 && <span className="sub">{dur(c.wait_seconds)}</span>}</div></button>
        })}{!rows.length && <div className="empty">Nenhuma conversa.</div>}</div>
      </Card>
      {sel ? <Chat conv={sel} me={me} tags={tags.data || []} onChange={reload} /> : <div className="at-chat"><div className="empty">Selecione uma conversa.</div></div>}
    </div>
  </>
}
