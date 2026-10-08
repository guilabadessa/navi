import React, { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'

// NAVI, a assistente da Orca TI: mascote animado que orienta o cliente pelo portal (tour, dicas por tela e atalhos).
const TIPS = {
  geral: ['Visão geral', 'Aqui você vê a disponibilidade do período, os incidentes por dia e os problemas que estão em andamento agora.'],
  inc: ['Incidentes', 'O histórico de ocorrências do seu ambiente. Use os filtros de severidade, situação, host e busca para achar o que precisa.'],
  hosts: ['Hosts', 'Seus servidores e equipamentos monitorados, com estado atual e disponibilidade. Filtre por grupo ou procure pelo nome/IP.'],
  grp: ['Grupos', 'Seus ambientes agrupados. Clique em um grupo para ver só os hosts dele.'],
  bkp: ['Backup', 'A situação dos backups: quando foi o último com sucesso de cada servidor e se há algum alerta aberto.'],
  eps: ['Estações', 'As estações protegidas (antivírus/FortiClient) e quando cada uma falou conosco pela última vez.'],
  rel: ['Relatórios', 'Os relatórios mensais em PDF. É só clicar para baixar.'],
  fin: ['Financeiro', 'Boletos e notas fiscais do mês. Troque o mês no seletor; o que estiver vencido de meses anteriores aparece em destaque.'],
}
const ASKS = [['Onde vejo meus boletos?', 'fin'], ['Como baixo um relatório?', 'rel'], ['Meu backup está em dia?', 'bkp'], ['Quais incidentes aconteceram?', 'inc']]
const SEV = 'As severidades vão de Informação até Desastre. Aqui você vê as definidas para o seu acesso (por padrão, de Alta para cima). Se precisar acompanhar mais detalhes, peça à equipe da Orca.'

export default function NaviGuide({ tabs, tab, setTab, userKey, name }) {
  const key = 'navi.guide.' + (userKey || 'x')
  const [open, setOpen] = useState(false); const [mode, setMode] = useState('home'); const [step, setStep] = useState(0); const [seen, setSeen] = useState(true)
  const t0 = useRef(null)
  const avail = tabs.map(([k]) => k).filter(k => TIPS[k])
  useEffect(() => {
    let done = false
    try { done = localStorage.getItem(key) === '1' } catch { /* sem armazenamento */ }
    setSeen(done)
    if (!done) { t0.current = setTimeout(() => { setOpen(true); setMode('hello') }, 1400) }
    return () => clearTimeout(t0.current)
  }, [key])
  const finish = () => { setOpen(false); setSeen(true); try { localStorage.setItem(key, '1') } catch { /* ignore */ } }
  const go = (k) => { setTab(k); setOpen(false) }
  const startTour = () => { setMode('tour'); setStep(0); if (avail[0]) setTab(avail[0]) }
  const goStep = (i) => { setStep(i); setTab(avail[i]) }
  const cur = TIPS[tab]
  const first = (name || '').split(' ')[0]
  return <div className="guide" aria-live="polite">
    {open && <div className="guide-bubble" role="dialog" aria-label="Assistente NAVI">
      <button className="guide-x" title="Fechar" onClick={finish}><X size={15} /></button>
      {mode === 'hello' && <>
        <b>Oi{first ? `, ${first}` : ''}! Eu sou o NAVI 👋</b>
        <p>Sou o assistente da Orca TI. Posso te mostrar onde fica cada coisa neste portal?</p>
        <div className="guide-actions"><button className="btn primary sm" onClick={startTour}>Fazer um tour rápido</button><button className="btn sm" onClick={() => setMode('home')}>Tenho uma dúvida</button><button className="btn sm ghost" onClick={finish}>Agora não</button></div></>}
      {mode === 'home' && <>
        <b>Como posso ajudar?</b>
        {cur && <p className="guide-tip"><span>Você está em <b>{cur[0]}</b>.</span> {cur[1]}</p>}
        <div className="guide-asks">{ASKS.filter(([, k]) => avail.includes(k)).map(([q, k]) => <button key={q} onClick={() => go(k)}>{q}</button>)}
          <button onClick={() => setMode('sev')}>O que são as severidades?</button><button onClick={startTour}>Quero um tour completo</button></div></>}
      {mode === 'sev' && <><b>Severidades</b><p>{SEV}</p><div className="guide-actions"><button className="btn sm" onClick={() => setMode('home')}><ChevronLeft size={14} />Voltar</button></div></>}
      {mode === 'tour' && avail[step] && <>
        <b>{TIPS[avail[step]][0]} <span className="sub">({step + 1}/{avail.length})</span></b><p>{TIPS[avail[step]][1]}</p>
        <div className="guide-actions"><button className="btn sm" disabled={step === 0} onClick={() => goStep(step - 1)}><ChevronLeft size={14} />Anterior</button>
          {step < avail.length - 1 ? <button className="btn primary sm" onClick={() => goStep(step + 1)}>Próximo<ChevronRight size={14} /></button> : <button className="btn primary sm" onClick={() => { finish() }}>Concluir</button>}</div></>}
    </div>}
    <button className={'guide-fab' + (open ? ' on' : '') + (!seen ? ' attn' : '')} aria-label="Falar com o NAVI" title="NAVI — assistente da Orca TI"
      onClick={() => { if (open) { setOpen(false) } else { setOpen(true); setMode('home') } }}>
      <span className="guide-ring" /><img src="/cliente/brand/navi-sm.png" alt="" width="64" height="64" /><i className="guide-dot" /></button>
  </div>
}
