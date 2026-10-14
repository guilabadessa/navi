import React, { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Link2, Paperclip, Workflow, Send, UserCheck, X, ArrowRightLeft } from 'lucide-react'
import { get, post, uploadForm } from '../api'
import { Card, Field, Modal, PageHead, Pill, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'

const QLABEL = { comercial: 'Comercial', financeiro: 'Financeiro', suporte: 'Suporte', geral: 'Geral' }
const STATE = { menu: ['mut', 'No menu'], aguardando: ['warn', 'Aguardando'], atendendo: ['ok', 'Em atendimento'], encerrada: ['mut', 'Encerrada'] }
const dur = (s) => s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}min` : `${Math.floor(s / 3600)}h${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}`
const hora = (v) => v ? new Date(v).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : ''

function Monitor({ q, sel, onSel }) {
  const lim = (q.wait_alert_min || 5) * 60
  return <div className="at-queues">{q.queues.map(x => {
    const late = x.waiting > 0 && x.oldest_seconds >= lim
    return <button key={x.queue} className={'at-q' + (sel === x.queue ? ' on' : '') + (late ? ' late' : '')} onClick={() => onSel(sel === x.queue ? '' : x.queue)}>
      <span>{x.label}</span><b>{x.waiting}</b><small>{x.waiting ? `maior espera ${dur(x.oldest_seconds)}` : 'sem espera'} · {x.active} em atendimento</small></button>
  })}</div>
}

function Transfer({ conv, onClose, onDone }) {
  const toast = useToast(); const agents = useLoad(() => get('/atendimento/agents'), [])
  const [u, setU] = useState(''); const [qq, setQq] = useState('')
  const go = async () => { try { await post(`/atendimento/conversations/${conv.id}/transfer`, { user_id: u ? +u : null, queue: qq || null }); toast('Conversa transferida'); onDone() } catch (e) { toast(e.message, true) } }
  return <Modal title="Transferir conversa" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" disabled={!u && !qq} onClick={go}>Transferir</button></>}>
    <Field label="PARA O ANALISTA" hint="Deixe em branco para devolver à fila do setor escolhido."><select value={u} onChange={e => setU(e.target.value)}><option value="">— fila do setor —</option>{(agents.data || []).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
    <Field label="SETOR"><select value={qq} onChange={e => setQq(e.target.value)}><option value="">— manter —</option>{Object.entries(QLABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
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

function Bubble({ m }) {
  const out = m.direction === 'out'
  return <div className={'at-msg ' + (out ? 'out' : 'in') + (m.failed ? ' failed' : '')}>
    {m.has_media && (m.type === 'IMAGE' ? <img alt="Imagem recebida" src={`/cliente/api/atendimento/messages/${m.id}/media`} style={{ maxWidth: 240, borderRadius: 8, display: 'block', marginBottom: 4 }} />
      : <a href={`/cliente/api/atendimento/messages/${m.id}/media`} target="_blank" rel="noreferrer">📎 Abrir {m.type === 'DOCUMENT' ? 'documento' : 'anexo'}</a>)}
    {m.text && <div style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>}
    <small>{out && m.sent_by ? m.sent_by + ' · ' : ''}{hora(m.created_at)}{m.failed ? ' · não enviada' : ''}</small>
  </div>
}

function Chat({ conv, me, onChange }) {
  const toast = useToast(); const act = can(me, 'atendimento.act')
  const [msgs, setMsgs] = useState([]); const [text, setText] = useState(''); const [modal, setModal] = useState(null); const [busy, setBusy] = useState(false)
  const cfg = useLoad(() => get('/atendimento/config'), [])
  const last = useRef(0); const box = useRef(null); const file = useRef(null)
  useEffect(() => { setMsgs([]); last.current = 0 }, [conv.id])
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
    try { await post(`/atendimento/conversations/${conv.id}/send`, { text: t }); setText('') } catch (e) { toast(e.message, true) } finally { setBusy(false) }
  }
  const sendFile = async (f) => {
    if (!f) return; const fd = new FormData(); fd.append('file', f)
    try { await uploadForm('/atendimento/conversations/' + conv.id + '/send-media', fd) } catch (e) { toast(e.message, true) }
  }
  const call = async (path, body, msg) => { try { await post(`/atendimento/conversations/${conv.id}/${path}`, body); if (msg) toast(msg); onChange() } catch (e) { toast(e.message, true); onChange() } }
  const [tone, label] = STATE[conv.state] || ['mut', conv.state]
  return <div className="at-chat">
    <div className="at-head"><div><b>{conv.name || conv.number}</b> <span className="sub">+{conv.number}</span>{conv.client && <> · <Pill tone="info">{conv.client.name}</Pill></>}</div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}><Pill tone={tone}>{label}</Pill><Pill tone="mut">{QLABEL[conv.queue]}</Pill>{conv.assigned_name && <Pill tone="info">{conv.assigned_name}</Pill>}
        {act && !closed && <>
          {conv.state === 'aguardando' && <button className="btn primary" onClick={() => call('assume', {}, 'Você assumiu a conversa')}><UserCheck size={16} />Assumir</button>}
          <button className="btn" onClick={() => setModal('transfer')}><ArrowRightLeft size={16} />Transferir</button>
          <button className="btn" onClick={() => setModal('link')}><Link2 size={16} />Cliente</button>
          <button className="btn" onClick={() => { if (confirm('Encerrar este atendimento e avisar o cliente?')) call('close', { send_closing: true }, 'Atendimento encerrado') }}><X size={16} />Encerrar</button></>}</div></div>
    {conv.client && conv.client.tickets?.length > 0 && <div className="at-tk"><b>Chamados abertos:</b> {conv.client.tickets.map(t => <Link key={t.id} to="/chamados" title={t.subject}>#{t.number} {t.subject.slice(0, 40)}</Link>)}</div>}
    <div className="at-body" ref={box}>{msgs.map(m => <Bubble key={m.id} m={m} />)}{!msgs.length && <div className="empty">Sem mensagens.</div>}</div>
    {act && !closed && (conv.state === 'atendendo' ? <div className="at-send">
      <input type="file" ref={file} hidden onChange={e => { sendFile(e.target.files[0]); e.target.value = '' }} />
      <button className="btn" aria-label="Anexar arquivo" onClick={() => file.current.click()}><Paperclip size={16} /></button>
      {cfg.data?.quick_replies?.length > 0 && <select aria-label="Respostas prontas" value="" onChange={e => { const r = cfg.data.quick_replies[+e.target.value]; if (r) setText(t => (t ? t + '\n' : '') + r.text) }} style={{ width: 130 }}>
        <option value="">Respostas…</option>{cfg.data.quick_replies.map((r, i) => <option key={i} value={i}>{r.title}</option>)}</select>}
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder={mine ? 'Digite a resposta…' : 'Esta conversa é de outro analista; você pode responder mesmo assim.'} rows={2}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
      <button className="btn primary" disabled={busy || !text.trim()} onClick={send}><Send size={16} />Enviar</button></div>
      : <div className="at-send sub">{conv.state === 'aguardando' ? 'Assuma a conversa para responder.' : 'Cliente ainda no menu.'}</div>)}
    {modal === 'transfer' && <Transfer conv={conv} onClose={() => setModal(null)} onDone={() => { setModal(null); onChange() }} />}
    {modal === 'link' && <LinkClient conv={conv} onClose={() => setModal(null)} onDone={() => { setModal(null); onChange() }} />}
  </div>
}

export default function Atendimento() {
  const me = useAuth(); const [queue, setQueue] = useState(''); const [mine, setMine] = useState(false); const [closed, setClosed] = useState(false); const [selId, setSelId] = useState(null)
  const q = useLoad(() => get('/atendimento/queues'), [], 3000)
  const list = useLoad(() => get(`/atendimento/conversations?queue=${queue}&mine=${mine}${closed ? '&state=encerrada' : ''}`), [queue, mine, closed], 3000)
  const rows = list.data || []; const sel = rows.find(c => c.id === selId)
  const waiting = (q.data?.queues || []).reduce((n, x) => n + x.waiting, 0)
  useEffect(() => { document.title = (waiting ? `(${waiting}) ` : '') + 'NAVI' ; return () => { document.title = 'NAVI' } }, [waiting])
  return <>
    <PageHead title="Atendimento" desc="Clientes de WhatsApp aguardando e em atendimento"><Link className="btn" to="/atendimento/fluxo"><Workflow size={15} />Fluxo de atendimento</Link></PageHead>
    {q.data && <Monitor q={q.data} sel={queue} onSel={setQueue} />}
    <div className="at-grid">
      <Card pad={false} title={undefined}>
        <div className="at-filters"><label className="check"><input type="checkbox" checked={mine} onChange={e => setMine(e.target.checked)} />Minhas</label>
          <label className="check"><input type="checkbox" checked={closed} onChange={e => setClosed(e.target.checked)} />Encerradas</label></div>
        <div className="at-list">{rows.map(c => {
          const [tone, label] = STATE[c.state] || ['mut', c.state]
          return <button key={c.id} className={'at-item' + (c.id === selId ? ' on' : '')} onClick={() => setSelId(c.id)}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><b>{c.name || c.number}</b>{c.unread > 0 && <span className="at-unread">{c.unread}</span>}</div>
            <div className="sub">{c.client ? c.client.name : '+' + c.number}</div>
            <div className="sub" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.last_text}</div>
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}><Pill tone={tone}>{label}</Pill><Pill tone="mut">{QLABEL[c.queue]}</Pill>{c.state !== 'atendendo' && c.wait_seconds > 0 && <span className="sub">{dur(c.wait_seconds)}</span>}</div></button>
        })}{!rows.length && <div className="empty">Nenhuma conversa.</div>}</div>
      </Card>
      {sel ? <Chat conv={sel} me={me} onChange={() => { list.reload(); q.reload() }} /> : <div className="at-chat"><div className="empty">Selecione uma conversa.</div></div>}
    </div>
  </>
}
