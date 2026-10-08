import React, { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Download, LogOut, Moon, Sun, Wrench } from 'lucide-react'
import { download, get, fmtDT, fmtDur, fmtNum, fmtPct } from '../api'
import { Card, Loading, Pill, SevBadge, Stat, StatusBadge, Table, useLoad, useToast } from '../ui'
import { getTheme, toggleTheme } from '../theme'
import { useAuth, can } from '../App'
import FinanceTab from './FinanceTab'
import NaviGuide from './NaviGuide'

const SEVN = { 0: 'Não classificado', 1: 'Informação', 2: 'Atenção', 3: 'Média', 4: 'Alta', 5: 'Desastre' }
const CKEY = 'navi.portal.cid'

const TYPES = { machine: 'Servidor', database: 'Banco de dados', mailbox: 'E-mail', drive: 'OneDrive', site: 'SharePoint', team: 'Teams' }
const hostState = (h) => h.available === 2 ? ['bad', 'indisponível'] : h.open ? ['warn', 'com alerta'] : h.available === 1 ? ['ok', 'disponível'] : ['mut', 'desconhecido']

// Portal do cliente: somente leitura, restrito ao proprio cliente (o servidor garante o isolamento).
// "embedded"/clientId = pre-visualizacao pela equipe Orca (mostra exatamente o que o cliente ve).
export default function Portal({ me, onLogout, clientId: forced, embedded, minSev }) {
  const toast = useToast(); const auth = useAuth(); const canFin = can(auth, 'portal.finance') || can(auth, 'finance.view'); const [days, setDays] = useState(30); const [theme, setTheme] = useState(getTheme()); const [tab, setTab] = useState('geral')
  const [grp, setGrp] = useState(''); const [hq, setHq] = useState('')
  const mine = auth?.clients || []
  const [pick, setPick] = useState(() => { try { return +localStorage.getItem(CKEY) || 0 } catch { return 0 } })
  const clientId = forced || (mine.some(c => c.id === pick) ? pick : (mine[0]?.id || undefined))
  const choose = (v) => { setPick(+v); setTab('geral'); setGrp(''); try { localStorage.setItem(CKEY, v) } catch { /* ignore */ } }
  const [fsev, setFsev] = useState(''); const [fst, setFst] = useState(''); const [fq, setFq] = useState('')
  const { data: d, err } = useLoad(() => get(`/portal/overview?days=${days}${clientId ? '&client_id=' + clientId : ''}${minSev != null ? '&min_sev=' + minSev : ''}`), [days, clientId, minSev], 30000)
  const dark = theme === 'dark'
  const s = d?.summary
  const byDay = d ? Object.entries(d.by_day).map(([k, v]) => ({ d: k.slice(5).split('-').reverse().join('/'), v })) : []
  const hist = d ? d.history.filter(e => (!fsev || e.severity >= +fsev) && (!fst || (fst === 'open' ? e.status === 'PROBLEM' : e.status !== 'PROBLEM')) && (!fq || (e.host + ' ' + e.trigger_name).toLowerCase().includes(fq.toLowerCase()))) : []
  const hosts = d ? d.hosts.filter(h => (!grp || h.groups.includes(grp)) && (!hq || (h.name + ' ' + (h.ip || '')).toLowerCase().includes(hq.toLowerCase()))) : []
  const dl = (r) => download(`/portal/reports/${r.id}/download`, `${r.name}.pdf`).catch(e => toast(e.message, true))
  const tabs = d ? [['geral', 'Visão geral'], ['inc', 'Incidentes'], ['hosts', `Hosts (${d.hosts.length})`], ['grp', `Grupos (${d.groups.length})`],
    ...(d.backup?.enabled ? [['bkp', 'Backup']] : []), ...(d.endpoints?.enabled ? [['eps', 'Estações']] : []), ['rel', 'Relatórios'], ...(canFin ? [['fin', 'Financeiro']] : [])] : []
  return <div style={{ minHeight: embedded ? 0 : '100vh' }}>
    {!embedded && <div className="top ptop" style={{ position: 'sticky' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}><img src="/cliente/brand/navi-sm.png" alt="NAVI" className="pmascot" />
        <div><h1 className="pbrand">NAVI</h1><div className="psub">Portal do Cliente</div></div>
        <div className="pclient">{mine.length > 1 ? <select value={clientId || ''} onChange={e => choose(e.target.value)} title="Trocar de cliente">{mine.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select> : <b>{d ? d.client.name : ''}</b>}</div></div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <select style={{ width: 'auto' }} value={days} onChange={e => setDays(+e.target.value)}>{[7, 30, 90].map(x => <option key={x} value={x}>Últimos {x} dias</option>)}</select>
        <button className="iconbtn" title="Tema" onClick={() => setTheme(toggleTheme())}>{dark ? <Sun /> : <Moon />}</button>
        <button className="btn sm" onClick={onLogout}><LogOut />Sair</button></div></div>}
    <div className={embedded ? '' : 'content'} style={{ margin: '0 auto' }}>
      {embedded && <div className="bar"><b style={{ fontSize: 18 }}>{d?.client.name}</b><div className="grow" /><select style={{ width: 'auto' }} value={days} onChange={e => setDays(+e.target.value)}>{[7, 30, 90].map(x => <option key={x} value={x}>Últimos {x} dias</option>)}</select></div>}
      {!d ? <Loading err={err} /> : <>
        {d.active.length > 0
          ? <div className="banner bad"><div className="grow"><b>{d.active.length} problema(s) em andamento.</b> Nossa equipe já está acompanhando.</div></div>
          : <div className="banner info"><div className="grow">✅ Todos os serviços monitorados estão operando normalmente.</div></div>}
        {d.maintenance.length > 0 && <div className="banner warn"><Wrench size={20} /><div className="grow"><b>Manutenção programada:</b> {d.maintenance.map(m => `${m.name} — ${fmtDT(m.start)} a ${fmtDT(m.end)}`).join(' · ')}</div></div>}
        <div className="grid g4" style={{ marginBottom: 16 }}>
          <Stat label="Disponibilidade" value={fmtPct(s.availability, 3)} tone={s.sla_met === false ? 'bad' : 'ok'} desc={`SLA contratado ${fmtPct(d.client.sla_target)} · ${s.sla_met === false ? 'não atingido' : 'atingido'}`} />
          <Stat label="Incidentes" value={fmtNum(s.incidents)} tone={s.open ? 'bad' : ''} desc={`${s.resolved} resolvido(s) · ${s.open} em aberto`} />
          <Stat label="Indisponibilidade total" value={fmtDur(s.downtime_s)} desc={`${s.hosts_affected} de ${s.hosts_total} host(s) afetado(s)`} />
          <Stat label="Tempo médio de reparo" value={fmtDur(s.mttr_s)} desc="MTTR" />
        </div>
        <div className="tabs">{tabs.map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
        {tab === 'geral' && <>
          <Card title={`Incidentes por dia (${days} dias)`} style={{ marginBottom: 16 }}><div style={{ height: 230 }}><ResponsiveContainer>
            <BarChart data={byDay}><CartesianGrid vertical={false} stroke="var(--line2)" /><XAxis dataKey="d" tick={{ fontSize: 11 }} interval="preserveStartEnd" /><YAxis allowDecimals={false} width={30} tick={{ fontSize: 11 }} />
              <Tooltip cursor={{ fill: 'var(--hover)' }} /><Bar dataKey="v" name="Incidentes" fill="#1e73f8" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer></div></Card>
          <Card title="Problemas em andamento" pad={false}><Table rows={d.active} empty="🎉 Nenhum problema em andamento." cols={[{ h: 'Severidade', r: r => <SevBadge n={r.severity} /> }, { h: 'Host', r: r => <b>{r.host}</b> },
            { h: 'Problema', r: r => <div className="trunc" title={r.trigger_name}>{r.trigger_name}</div> }, { h: 'Início', r: r => fmtDT(r.started_at) }]} /></Card></>}
        {tab === 'inc' && <>
          <div className="bar"><div className="grow"><input placeholder="Buscar por host ou problema…" value={fq} onChange={e => setFq(e.target.value)} /></div>
            <select value={fsev} onChange={e => setFsev(e.target.value)}><option value="">Todas as severidades</option>{[5, 4, 3, 2, 1, 0].filter(n => n >= (d.min_sev || 0)).map(n => <option key={n} value={n}>{SEVN[n]} ou superior</option>)}</select>
            <select value={fst} onChange={e => setFst(e.target.value)}><option value="">Todas as situações</option><option value="open">Em andamento</option><option value="done">Resolvidos</option></select>
            {(fsev || fst || fq) && <button className="btn sm" onClick={() => { setFsev(''); setFst(''); setFq('') }}>Limpar filtros</button>}</div>
          <div className="sub" style={{ margin: '0 2px 10px' }}>{hist.length} de {d.history.length} incidente(s) · exibindo severidade {SEVN[d.min_sev]} ou superior</div>
          <Card pad={false}><Table rows={hist} empty="Nenhum incidente com estes filtros." cols={[{ h: 'Status', r: r => <StatusBadge s={r.status} /> }, { h: 'Sev.', r: r => <SevBadge n={r.severity} /> }, { h: 'Host', r: r => <b>{r.host}</b> },
            { h: 'Problema', r: r => <div className="trunc" title={r.trigger_name}>{r.trigger_name}</div> }, { h: 'Início', r: r => fmtDT(r.started_at) }, { h: 'Recuperação', r: r => fmtDT(r.recovered_at) }, { h: 'Duração', r: r => fmtDur(r.duration_s), cls: 'mono' }]} /></Card></>}
        {tab === 'hosts' && <>
          <div className="bar"><div className="grow"><input placeholder="Buscar host ou IP…" value={hq} onChange={e => setHq(e.target.value)} /></div>
            <select value={grp} onChange={e => setGrp(e.target.value)}><option value="">Todos os grupos</option>{d.groups.map(g => <option key={g.name}>{g.name}</option>)}</select></div>
          <Card pad={false}><Table rows={hosts} empty="Nenhum host." cols={[
            { h: 'Estado', r: r => { const [t, l] = hostState(r); return <Pill tone={t}>{l}</Pill> } }, { h: 'Host', r: r => <b>{r.name}</b> }, { h: 'IP', k: 'ip', cls: 'mono' },
            { h: 'Grupos', r: r => r.groups.map(g => <span className="chip" key={g}>{g}</span>) }, { h: 'Incidentes', k: 'incidents' },
            { h: 'Indisponibilidade', r: r => fmtDur(r.downtime_s) }, { h: 'Disponibilidade', r: r => r.availability == null ? '—' : fmtPct(r.availability, 3) }]} /></Card></>}
        {tab === 'grp' && <div className="grid g3">{d.groups.length ? d.groups.map(g => <div className="card cardlink" key={g.name} style={{ padding: 18 }} onClick={() => { setGrp(g.name); setTab('hosts') }}>
          <h3>{g.name}</h3><div className="sub" style={{ margin: '6px 0 10px' }}>{g.hosts} host(s)</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{g.down > 0 ? <Pill tone="bad">{g.down} indisponível(is)</Pill> : <Pill tone="ok">tudo disponível</Pill>}{g.open > 0 && <Pill tone="warn">{g.open} alerta(s)</Pill>}<Pill tone="mut">{g.incidents} incidente(s) em {days}d</Pill></div></div>)
          : <div className="empty">Nenhum grupo vinculado a este cliente.</div>}</div>}
        {tab === 'bkp' && d.backup && <>
          {d.backup.alerts.length > 0 && <Card title="Atenção no backup" pad={false} style={{ marginBottom: 16 }}><Table rows={d.backup.alerts} cols={[{ h: 'Severidade', r: r => <SevBadge n={r.severity} /> }, { h: 'Item', r: r => <b>{r.host}</b> }, { h: 'Situação', k: 'trigger_name' }, { h: 'Desde', r: r => fmtDT(r.started_at) }]} /></Card>}
          <Card title={`Itens protegidos (${d.backup.assets.length})`} pad={false}><Table rows={d.backup.assets} empty="Nenhum item de backup." cols={[
            { h: 'Situação', r: r => <Pill tone={r.status === 'ok' ? 'ok' : r.status === 'sem dados' ? 'mut' : r.status === 'offline' ? 'warn' : 'bad'}>{r.status === 'ok' ? 'protegido' : r.status}</Pill> },
            { h: 'Item', r: r => <b>{r.name}</b> }, { h: 'Tipo', r: r => TYPES[r.type] || r.type }, { h: 'Último backup com sucesso', r: r => fmtDT(r.last_success_at) }]} /></Card></>}
        {tab === 'eps' && d.endpoints && <Card title={`Estações protegidas (${d.endpoints.assets.length})`} pad={false}><Table rows={d.endpoints.assets} empty="Nenhuma estação." cols={[
          { h: 'Situação', r: r => <Pill tone={r.status === 'online' ? 'ok' : r.status === 'offline' ? 'mut' : 'warn'}>{r.status}</Pill> }, { h: 'Estação', r: r => <b>{r.name}</b> }, { h: 'Usuário', k: 'user' },
          { h: 'Sistema', r: r => <span className="sub">{r.os}</span> }, { h: 'Último contato', r: r => fmtDT(r.last_contact) }]} /></Card>}
        {tab === 'fin' && canFin && <FinanceTab clientId={clientId} key={clientId} />}
        {tab === 'rel' && <Card title="Relatórios mensais" pad={false}><Table rows={d.reports} empty="Nenhum relatório disponível ainda." cols={[{ h: 'Relatório', r: r => <b>{r.name}</b> },
          { h: 'Período', r: r => `${fmtDT(r.period_start)} a ${fmtDT(r.period_end)}` }, { h: 'Gerado em', r: r => fmtDT(r.generated_at) },
          { h: '', r: r => <button className="btn sm" onClick={() => dl(r)}><Download />Baixar PDF</button> }]} /></Card>}
      </>}
      {!embedded && d && <NaviGuide tabs={tabs} tab={tab} setTab={setTab} userKey={me?.id} name={me?.name} />}
      {!embedded && <div className="sub" style={{ textAlign: 'center', marginTop: 28, fontSize: 12.5 }}>Dados em tempo real do monitoramento · {me?.email}</div>}
    </div></div>
}
