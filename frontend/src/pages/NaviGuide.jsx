import React, { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'

// NAVI, a assistente da Orca TI: o mascote fica no rodape da tela como "a cara" do assistente (nao e a marca do sistema).
// Orienta por tour, dicas da tela atual e atalhos. Serve ao portal do cliente (por aba) e ao painel da equipe (por pagina).
export default function NaviGuide({ tips, current, asks = [], go, tour = [], userKey, name, scope = 'portal', extra }) {
  const key = `navi.guide.${scope}.${userKey || 'x'}`
  const [open, setOpen] = useState(false); const [mode, setMode] = useState('home'); const [step, setStep] = useState(0); const [seen, setSeen] = useState(true)
  const t0 = useRef(null)
  const steps = tour.filter(k => tips[k])
  useEffect(() => {
    let done = false
    try { done = localStorage.getItem(key) === '1' } catch { /* sem armazenamento */ }
    setSeen(done)
    if (!done) { t0.current = setTimeout(() => { setOpen(true); setMode('hello') }, 1600) }
    return () => clearTimeout(t0.current)
  }, [key])
  const finish = () => { setOpen(false); setSeen(true); try { localStorage.setItem(key, '1') } catch { /* ignore */ } }
  const jump = (k) => { go(k); setOpen(false) }
  const startTour = () => { setMode('tour'); setStep(0); if (steps[0]) go(steps[0]) }
  const goStep = (i) => { setStep(i); go(steps[i]) }
  const cur = tips[current]
  const first = (name || '').split(' ')[0]
  return <div className="guide" aria-live="polite">
    {open && <div className="guide-bubble" role="dialog" aria-label="Assistente NAVI">
      <button className="guide-x" title="Fechar" onClick={finish} aria-label="Fechar"><X size={15} /></button>
      {mode === 'hello' && <>
        <b>Oi{first ? `, ${first}` : ''}! Eu sou o NAVI 👋</b>
        <p>Sou o assistente da Orca TI. {scope === 'portal' ? 'Posso te mostrar onde fica cada coisa neste portal?' : 'Posso te guiar pelas telas da plataforma e explicar o que cada uma faz.'}</p>
        <div className="guide-actions"><button className="btn primary sm" onClick={startTour}>Fazer um tour rápido</button><button className="btn sm" onClick={() => setMode('home')}>Tenho uma dúvida</button><button className="btn sm ghost" onClick={finish}>Agora não</button></div></>}
      {mode === 'home' && <>
        <b>Como posso ajudar?</b>
        {cur && <p className="guide-tip"><span>Você está em <b>{cur[0]}</b>.</span> {cur[1]}</p>}
        <div className="guide-asks">{asks.filter(([, k]) => tips[k]).map(([q, k]) => <button key={q} onClick={() => jump(k)}>{q}</button>)}
          {extra && <button onClick={() => setMode('extra')}>{extra.label}</button>}<button onClick={startTour}>Quero um tour completo</button></div></>}
      {mode === 'extra' && extra && <><b>{extra.label}</b><p>{extra.text}</p><div className="guide-actions"><button className="btn sm" onClick={() => setMode('home')}><ChevronLeft size={14} />Voltar</button></div></>}
      {mode === 'tour' && steps[step] && <>
        <b>{tips[steps[step]][0]} <span className="sub">({step + 1}/{steps.length})</span></b><p>{tips[steps[step]][1]}</p>
        <div className="guide-actions"><button className="btn sm" disabled={step === 0} onClick={() => goStep(step - 1)}><ChevronLeft size={14} />Anterior</button>
          {step < steps.length - 1 ? <button className="btn primary sm" onClick={() => goStep(step + 1)}>Próximo<ChevronRight size={14} /></button> : <button className="btn primary sm" onClick={finish}>Concluir</button>}</div></>}
    </div>}
    <button className={'guide-fab' + (open ? ' on' : '') + (!seen ? ' attn' : '')} aria-label="Falar com o NAVI" title="NAVI — assistente da Orca TI"
      onClick={() => { if (open) { setOpen(false) } else { setOpen(true); setMode('home') } }}>
      <span className="guide-ring" /><img src="/cliente/brand/navi-sm.png" alt="" width="64" height="64" /><i className="guide-dot" /></button>
  </div>
}

// ---- Conteudo do portal do cliente (por aba) ----
export const PORTAL_TIPS = {
  geral: ['Visão geral', 'Disponibilidade do período, incidentes por dia e os problemas em andamento agora. O período (7, 30 ou 90 dias) é escolhido no topo.'],
  inc: ['Incidentes', 'O histórico de ocorrências do seu ambiente. Filtre por severidade, situação, host ou texto para achar o que precisa.'],
  hosts: ['Hosts', 'Seus servidores e equipamentos monitorados, com estado atual e disponibilidade. Filtre por grupo ou procure pelo nome/IP.'],
  grp: ['Grupos', 'Seus ambientes agrupados. Clique em um grupo para ver só os hosts dele.'],
  bkp: ['Backup', 'Quando foi o último backup com sucesso de cada servidor e se há algum alerta aberto.'],
  cloud: ['Cloud Orca', 'Suas máquinas na Cloud Orca: estado, recursos e consumo do plano. Você pode ligar, desligar ou reiniciar cada máquina (a ação pede confirmação e fica registrada).'],
  eps: ['Endpoints', 'Os equipamentos protegidos (antivírus, EDR, DLP, RMM) e quando cada um falou conosco pela última vez. Use os filtros por tecnologia e situação.'],
  rel: ['Relatórios', 'Os relatórios mensais em PDF. É só clicar para baixar.'],
  fin: ['Financeiro', 'Boletos e notas fiscais do mês. Troque o mês no seletor; o que estiver vencido de meses anteriores aparece em destaque.'],
}
export const PORTAL_ASKS = [['Onde vejo meus boletos?', 'fin'], ['Como baixo um relatório?', 'rel'], ['Meu backup está em dia?', 'bkp'], ['Quais incidentes aconteceram?', 'inc']]
export const PORTAL_SEV = { label: 'O que são as severidades?', text: 'As severidades vão de Informação até Desastre. Você vê as definidas para o seu acesso (por padrão, de Alta para cima). Se precisar acompanhar mais detalhes, peça à equipe da Orca.' }

// ---- Conteudo do painel da equipe (por rota) ----
export const STAFF_TIPS = {
  '/': ['Dashboard', 'Visão geral do NOC em tempo real: incidentes abertos, saúde por cliente, backup e endpoints. Use os filtros e os cartões para abrir os detalhes.'],
  '/clientes': ['Clientes', 'Cadastro dos clientes, vínculo com Host Groups do Zabbix, Acronis, EMS e Conta Azul. Aqui você também convida os usuários do portal de cada cliente.'],
  '/monitoramento': ['Monitoramento', 'Hosts e Host Groups sincronizados do Zabbix. Veja quais ainda não estão associados a um cliente.'],
  '/eventos': ['Eventos', 'Todos os incidentes (PROBLEM e RESOLVED), com filtros por cliente, severidade, origem e período. Dá para exportar em CSV.'],
  '/protecao': ['Backup e Endpoints', 'Itens protegidos pelo Acronis e endpoints (FortiClient EMS e proteção Acronis). Associe cada tenant a um cliente para os alertas chegarem à pessoa certa.'],
  '/portal': ['Portal do cliente', 'Veja o portal exatamente como o cliente vê, trocando de cliente e de severidade exibida.'],
  '/alertas': ['Alertas', 'Regras por cliente, host e severidade; templates de mensagem; escalonamento; manutenção e modo sombra. Use "Testar" antes de ativar.'],
  '/relatorios': ['Relatórios', 'Relatórios executivos e técnicos em PDF, com envio por e-mail. Guardamos os 2 mais recentes por cliente.'],
  '/rotinas': ['Rotinas', 'Relatórios agendados e as tarefas internas do worker, com o último resultado de cada uma.'],
  '/whatsapp': ['WhatsApp', 'Estado da Evolution API e o log das mensagens enviadas.'],
  '/email': ['E-mail', 'Estado do SMTP e o log dos e-mails enviados.'],
  '/navi-ia': ['NAVI IA', 'Pergunte em linguagem natural sobre o ambiente: a NAVI consulta apenas dados que você tem permissão para ver.'],
  '/usuarios': ['Usuários', 'Convide pessoas por e-mail e escolha o perfil. A pessoa cria a própria senha; nenhuma senha é definida aqui.'],
  '/auditoria': ['Auditoria', 'Registro de quem fez o quê, quando, de onde e com qual resultado.'],
  '/configuracoes': ['Configurações', 'Integrações (Zabbix, WhatsApp, e-mail, Acronis, EMS, Conta Azul), papel timbrado e webhook. Segredos ficam criptografados.'],
}
export const STAFF_ASKS = [['Como convido um cliente para o portal?', '/clientes'], ['Onde configuro as integrações?', '/configuracoes'], ['Onde vejo os incidentes?', '/eventos'], ['Como crio uma regra de alerta?', '/alertas'], ['Quero ver o portal como o cliente', '/portal']]
