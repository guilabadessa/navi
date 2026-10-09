import React, { useRef, useState, useEffect } from 'react'
import { Send, Sparkles } from 'lucide-react'
import { post, fmtDT, fmtDur } from '../api'
import { Card, PageHead, Table } from '../ui'

const SUG = ['Top 10 hosts com mais problemas nos últimos 30 dias', 'Quais clientes tiveram mais indisponibilidade este mês?', 'Backups com falha agora', 'Endpoints sem contato ou com antivírus desligado', 'Máquinas da Cloud Orca desligadas', 'Quais serviços cada cliente possui?', 'Quais os problemas mais recorrentes?']

const SERV = { infra: 'Infra', backup: 'Backup', endpoint: 'Endpoints' }
function Data({ d }) {
  const rows = d.hosts || d.clients || d.triggers || d.alerts || d.services || d.vms; if (!rows) return null
  const cols = d.hosts ? [['host', 'Item / host'], ['incidents', 'Ocorrências'], ['downtime_s', 'Tempo']] : d.clients ? [['client', 'Cliente'], ['incidents', 'Incidentes'], ['downtime_s', 'Indisponível']]
    : d.alerts ? [['client', 'Cliente'], ['item', 'Item'], ['trigger', 'Problema'], ['since', 'Desde']] : d.vms ? [['client', 'Cliente'], ['vm', 'Máquina'], ['estado', 'Estado'], ['recursos', 'Recursos']] : d.services ? [['client', 'Cliente'], ['infra', SERV.infra], ['backup', SERV.backup], ['endpoint', SERV.endpoint], ['cloud', 'Cloud']] : [['trigger', 'Problema'], ['incidents', 'Ocorrências']]
  return <div style={{ marginTop: 10 }}><Table rows={rows.map((r, i) => ({ ...r, id: i }))} cols={cols.map(([k, h]) => ({ h, r: r => k === 'downtime_s' ? fmtDur(r[k]) : k === 'since' ? fmtDT(r[k]) : r[k] }))} /></div>
}

export default function NaviIA() {
  const [msgs, setMsgs] = useState([{ who: 'n', text: 'Olá! Eu sou a NAVI. Pergunte sobre hosts, clientes, backups, endpoints, máquinas da Cloud Orca e incidentes do seu ambiente.' }]); const [q, setQ] = useState(''); const [busy, setBusy] = useState(false); const end = useRef()
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])
  const ask = async (text) => { if (!text.trim()) return; setMsgs(m => [...m, { who: 'u', text }]); setQ(''); setBusy(true)
    try { const r = await post('/navi/ask', { question: text }); setMsgs(m => [...m, { who: 'n', text: r.answer, data: r.data, mode: r.mode }]) } catch (e) { setMsgs(m => [...m, { who: 'n', text: 'Erro: ' + e.message }]) } finally { setBusy(false) } }
  return <>
    <PageHead title="NAVI IA" desc="Pergunte em linguagem natural sobre o ambiente. A NAVI consulta apenas os dados que você tem permissão para ver" />
    <Card><div className="chat">{msgs.map((m, i) => <div key={i} className={'msg ' + m.who} style={m.data ? { maxWidth: '95%' } : null}>{m.who === 'n' && <Sparkles size={15} style={{ marginRight: 6, color: 'var(--blue)', verticalAlign: -2 }} />}{m.text}{m.data && <Data d={m.data} />}</div>)}{busy && <div className="msg n">Analisando…</div>}<div ref={end} /></div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '12px 0' }}>{SUG.map(s => <span key={s} className="chip" style={{ cursor: 'pointer' }} onClick={() => ask(s)}>{s}</span>)}</div>
      <form onSubmit={e => { e.preventDefault(); ask(q) }} style={{ display: 'flex', gap: 10 }}><input placeholder="Pergunte algo sobre o ambiente…" value={q} onChange={e => setQ(e.target.value)} /><button className="btn primary" disabled={busy}><Send />Enviar</button></form>
      <p className="hint" style={{ marginTop: 10 }}>Modo atual: consultas determinísticas. A análise generativa (resumos, causas, relatórios sob demanda) será habilitada ao conectar um provedor de LLM — a NAVI nunca envia credenciais ao modelo.</p></Card></>
}
