import React, { useRef, useState, useEffect } from 'react'
import { Send, Sparkles } from 'lucide-react'
import { post, fmtDur } from '../api'
import { Card, PageHead, Table } from '../ui'

const SUG = ['Top 10 hosts com mais problemas nos últimos 30 dias', 'Quais clientes tiveram mais indisponibilidade este mês?', 'Quais os problemas mais recorrentes?', 'Top hosts da última semana']

function Data({ d }) {
  const rows = d.hosts || d.clients || d.triggers; if (!rows) return null
  const cols = d.hosts ? [['host', 'Host'], ['incidents', 'Incidentes'], ['downtime_s', 'Indisponível']] : d.clients ? [['client', 'Cliente'], ['incidents', 'Incidentes'], ['downtime_s', 'Indisponível']] : [['trigger', 'Problema'], ['incidents', 'Ocorrências']]
  return <div style={{ marginTop: 10 }}><Table rows={rows.map((r, i) => ({ ...r, id: i }))} cols={cols.map(([k, h]) => ({ h, r: r => k === 'downtime_s' ? fmtDur(r[k]) : r[k] }))} /></div>
}

export default function NaviIA() {
  const [msgs, setMsgs] = useState([{ who: 'n', text: 'Olá! Eu sou a NAVI. Pergunte sobre hosts, clientes e incidentes do seu ambiente.' }]); const [q, setQ] = useState(''); const [busy, setBusy] = useState(false); const end = useRef()
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])
  const ask = async (text) => { if (!text.trim()) return; setMsgs(m => [...m, { who: 'u', text }]); setQ(''); setBusy(true)
    try { const r = await post('/navi/ask', { question: text }); setMsgs(m => [...m, { who: 'n', text: r.answer, data: r.data, mode: r.mode }]) } catch (e) { setMsgs(m => [...m, { who: 'n', text: 'Erro: ' + e.message }]) } finally { setBusy(false) } }
  return <>
    <PageHead title="NAVI IA" desc="Assistente do NOC — consultas ao ambiente com acesso apenas a dados autorizados" />
    <Card><div className="chat">{msgs.map((m, i) => <div key={i} className={'msg ' + m.who} style={m.data ? { maxWidth: '95%' } : null}>{m.who === 'n' && <Sparkles size={15} style={{ marginRight: 6, color: 'var(--blue)', verticalAlign: -2 }} />}{m.text}{m.data && <Data d={m.data} />}</div>)}{busy && <div className="msg n">Analisando…</div>}<div ref={end} /></div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '12px 0' }}>{SUG.map(s => <span key={s} className="chip" style={{ cursor: 'pointer' }} onClick={() => ask(s)}>{s}</span>)}</div>
      <form onSubmit={e => { e.preventDefault(); ask(q) }} style={{ display: 'flex', gap: 10 }}><input placeholder="Pergunte à NAVI…" value={q} onChange={e => setQ(e.target.value)} /><button className="btn primary" disabled={busy}><Send />Enviar</button></form>
      <p className="hint" style={{ marginTop: 10 }}>Modo atual: consultas determinísticas. A análise generativa (resumos, causas, relatórios sob demanda) será habilitada ao conectar um provedor de LLM — a NAVI nunca envia credenciais ao modelo.</p></Card></>
}
