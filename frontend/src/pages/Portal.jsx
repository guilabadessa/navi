import React, { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Download, LogOut, Moon, Sun, Wrench } from 'lucide-react'
import { download, get, fmtDT, fmtDur, fmtNum, fmtPct } from '../api'
import { Card, Loading, Pill, SevBadge, Stat, StatusBadge, Table, useLoad, useToast } from '../ui'
import { getTheme, toggleTheme } from '../theme'

// Portal do cliente: somente leitura, restrito ao proprio cliente (o servidor garante o isolamento)
export default function Portal({ me, onLogout }) {
  const toast = useToast(); const [days, setDays] = useState(30); const [theme, setTheme] = useState(getTheme()); const [tab, setTab] = useState('geral')
  const { data: d, err } = useLoad(() => get('/portal/overview?days=' + days), [days], 30000)
  const dark = theme === 'dark'
  const s = d?.summary
  const byDay = d ? Object.entries(d.by_day).map(([k, v]) => ({ d: k.slice(5).split('-').reverse().join('/'), v })) : []
  return <div style={{ minHeight: '100vh' }}>
    <div className="top" style={{ position: 'sticky' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}><img src={dark ? '/navi/brand/branco.png' : '/navi/brand/azul.png'} alt="Orca TI" style={{ height: 30 }} />
        <div><h1 style={{ fontSize: 19, lineHeight: 1.1 }}>{d ? d.client.name : 'Portal do cliente'}</h1><div className="sub" style={{ fontSize: 12.5 }}>Monitoramento · NAVI by Orca TI</div></div></div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <select style={{ width: 'auto' }} value={days} onChange={e => setDays(+e.target.value)}>{[7, 30, 90].map(x => <option key={x} value={x}>Últimos {x} dias</option>)}</select>
        <button className="iconbtn" title="Tema" onClick={() => setTheme(toggleTheme())}>{dark ? <Sun /> : <Moon />}</button>
        <button className="btn sm" onClick={onLogout}><LogOut />Sair</button></div></div>
    <div className="content" style={{ margin: '0 auto' }}>
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
        <div className="tabs">{[['geral', 'Visão geral'], ['inc', 'Incidentes'], ['hosts', 'Hosts'], ...(d.backup?.enabled ? [['bkp', 'Backup']] : []), ['rel', 'Relatórios']].map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
        {tab === 'geral' && <>
          <Card title={`Incidentes por dia (${days} dias)`} style={{ marginBottom: 16 }}><div style={{ height: 230 }}><ResponsiveContainer>
            <BarChart data={byDay}><CartesianGrid vertical={false} stroke="var(--line2)" /><XAxis dataKey="d" tick={{ fontSize: 11 }} interval="preserveStartEnd" /><YAxis allowDecimals={false} width={30} tick={{ fontSize: 11 }} />
              <Tooltip cursor={{ fill: 'var(--hover)' }} /><Bar dataKey="v" name="Incidentes" fill="#1e73f8" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer></div></Card>
          <Card title="Problemas em andamento" pad={false}><Table rows={d.active} empty="🎉 Nenhum problema em andamento." cols={[{ h: 'Severidade', r: r => <SevBadge n={r.severity} /> }, { h: 'Host', r: r => <b>{r.host}</b> },
            { h: 'Problema', r: r => <div className="trunc" title={r.trigger_name}>{r.trigger_name}</div> }, { h: 'Início', r: r => fmtDT(r.started_at) }]} /></Card></>}
        {tab === 'inc' && <Card pad={false}><Table rows={d.history} empty="Nenhum incidente no período." cols={[{ h: 'Status', r: r => <StatusBadge s={r.status} /> }, { h: 'Sev.', r: r => <SevBadge n={r.severity} /> }, { h: 'Host', r: r => <b>{r.host}</b> },
          { h: 'Problema', r: r => <div className="trunc" title={r.trigger_name}>{r.trigger_name}</div> }, { h: 'Início', r: r => fmtDT(r.started_at) }, { h: 'Recuperação', r: r => fmtDT(r.recovered_at) }, { h: 'Duração', r: r => fmtDur(r.duration_s), cls: 'mono' }]} /></Card>}
        {tab === 'hosts' && <Card pad={false}><Table rows={d.by_host} empty="Sem hosts." cols={[{ h: 'Host', r: r => <b>{r.host}</b> }, { h: 'Incidentes', k: 'incidents' }, { h: 'Indisponibilidade', r: r => fmtDur(r.downtime_s) }, { h: 'Disponibilidade', r: r => fmtPct(r.availability, 3) }]} /></Card>}
        {tab === 'bkp' && d.backup && <>
          {d.backup.alerts.length > 0 && <Card title="Atenção no backup" pad={false} style={{ marginBottom: 16 }}><Table rows={d.backup.alerts} cols={[{ h: 'Severidade', r: r => <SevBadge n={r.severity} /> }, { h: 'Item', r: r => <b>{r.host}</b> }, { h: 'Situação', k: 'trigger_name' }, { h: 'Desde', r: r => fmtDT(r.started_at) }]} /></Card>}
          <Card title={`Itens protegidos (${d.backup.assets.length})`} pad={false}><Table rows={d.backup.assets} empty="Nenhum item de backup." cols={[
            { h: 'Situação', r: r => <Pill tone={r.status === 'ok' ? 'ok' : r.status === 'sem dados' ? 'mut' : r.status === 'offline' ? 'warn' : 'bad'}>{r.status === 'ok' ? 'protegido' : r.status}</Pill> },
            { h: 'Item', r: r => <b>{r.name}</b> }, { h: 'Tipo', r: r => ({ machine: 'Servidor', database: 'Banco de dados', mailbox: 'E-mail', drive: 'OneDrive', site: 'SharePoint', team: 'Teams' }[r.type] || r.type) },
            { h: 'Último backup com sucesso', r: r => fmtDT(r.last_success_at) }]} /></Card></>}
        {tab === 'rel' && <Card title="Relatórios mensais" pad={false}><Table rows={d.reports} empty="Nenhum relatório disponível ainda." cols={[{ h: 'Relatório', r: r => <b>{r.name}</b> },
          { h: 'Período', r: r => `${fmtDT(r.period_start)} a ${fmtDT(r.period_end)}` }, { h: 'Gerado em', r: r => fmtDT(r.generated_at) },
          { h: '', r: r => <button className="btn sm" onClick={() => download(`/portal/reports/${r.id}/download`, `${r.name}.pdf`).catch(e => toast(e.message, true))}><Download />Baixar PDF</button> }]} /></Card>}
      </>}
      <div className="sub" style={{ textAlign: 'center', marginTop: 28, fontSize: 12.5 }}>Dados em tempo real do monitoramento · {me.email}</div>
    </div></div>
}
