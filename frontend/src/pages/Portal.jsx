import React, { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Download, LogOut, Moon, Sun, UserRound, Wrench } from 'lucide-react'
import { download, get, fmtDT, fmtDur, fmtNum, fmtPct } from '../api'
import { Card, KIND, KindPill, LiveDur, Loading, Modal, PERIODS, Pill, SevBadge, Stat, StatusBadge, Table, periodLabel, useLoad, useToast } from '../ui'
import { getTheme, toggleTheme } from '../theme'
import { useAuth, can } from '../App'
import Account from './Account'
import Contracts from './Contracts'
import { CloudPanel } from './CloudPanel'
import { BackupPanel, EndpointsPanel, ServicesCard } from './ProtectionPanels'
import FinanceTab from './FinanceTab'
import NaviGuide, { PORTAL_ASKS, PORTAL_SEV, PORTAL_TIPS } from './NaviGuide'

const SEVN = { 0: 'Não classificado', 1: 'Informação', 2: 'Atenção', 3: 'Média', 4: 'Alta', 5: 'Desastre' }
const CKEY = 'navi.portal.cid'

const TYPES = { machine: 'Servidor', database: 'Banco de dados', mailbox: 'E-mail', drive: 'OneDrive', site: 'SharePoint', team: 'Teams' }
const hostState = (h) => h.available === 2 ? ['bad', 'indisponível'] : h.open ? ['warn', 'com alerta'] : h.available === 1 ? ['ok', 'disponível'] : ['mut', 'desconhecido']

// Portal do cliente: somente leitura, restrito ao proprio cliente (o servidor garante o isolamento).
// "embedded"/clientId = pre-visualizacao pela equipe Orca (mostra exatamente o que o cliente ve).
// Situacao atual de cada servico contratado: operando normalmente ou com falha
function ServiceStatus({ d, go }) {
  const items = []
  if (d.services?.infra !== false) {
    const down = d.hosts.filter(h => h.available === 2).length; const open = d.active.filter(e => (e.kind || 'infra') === 'infra').length
    items.push({ k: 'infra', tab: 'hosts', title: 'Infraestrutura', bad: down > 0 || open > 0, warn: false, line: `${d.hosts.length - down} de ${d.hosts.length} hosts disponíveis`, extra: open ? `${open} problema(s) em andamento` : 'Nenhum problema em andamento' })
  }
  if (d.backup?.enabled) {
    const a = d.backup.assets.filter(x => x.status !== 'ignorado' && x.status !== 'sem dados'); const bad = a.filter(x => x.status !== 'ok').length
    items.push({ k: 'bkp', tab: 'bkp', title: 'Backup', bad: bad > 0, line: `${a.length - bad} de ${a.length} itens com backup em dia`, extra: bad ? `${bad} item(ns) com falha ou atraso` : 'Todos os backups executaram com sucesso' })
  }
  if (d.endpoints?.enabled) {
    const a = d.endpoints.assets.filter(x => x.status !== 'ignorado'); const bad = a.filter(x => x.status !== 'online' && x.status !== 'offline').length
    items.push({ k: 'eps', tab: 'eps', title: 'Endpoints', bad: bad > 0, line: `${a.length - bad} de ${a.length} endpoints em conformidade`, extra: bad ? `${bad} endpoint(s) com pendência` : 'Antivírus e proteção em dia' })
  }
  if (d.cloud) {
    const bad = d.cloud.off.length
    items.push({ k: 'cloud', tab: 'cloud', title: 'Cloud Orca', bad: bad > 0, line: `${d.cloud.running} de ${d.cloud.total} máquinas ligadas`, extra: bad ? `${bad} máquina(s) desligada(s) ou com erro` : 'Todas as máquinas operando' })
  }
  if (!items.length) return null
  return <div className="grid g3 svcstat" style={{ marginBottom: 16 }}>{items.map(i => <div key={i.k} className={'card svc cardlink ' + (i.bad ? 'bad' : 'ok')} style={{ padding: 16 }} role="button" tabIndex={0} onClick={() => go && go(i.tab)} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && go && go(i.tab)}>
    <div className="l">{i.title}</div>
    <div className="st"><i className="dot" style={{ background: i.bad ? '#bd1723' : '#16a34a' }} />{i.bad ? 'Com falha' : 'Operando normalmente'}</div>
    <div className="sub">{i.line}</div><div className="sub">{i.extra}</div></div>)}</div>
}

export default function Portal({ me, onLogout, reloadMe, clientId: forced, embedded, minSev }) {
  const toast = useToast(); const auth = useAuth(); const canFin = can(auth, 'portal.finance') || can(auth, 'finance.view'); const [days, setDays] = useState(0.0417); const [theme, setTheme] = useState(getTheme()); const [tab, setTab] = useState('geral')
  const [grp, setGrp] = useState(''); const [hq, setHq] = useState(''); const [acc, setAcc] = useState(!!me?.must_change_password && !forced)
  const mine = auth?.clients || []
  const [pick, setPick] = useState(() => { try { return +localStorage.getItem(CKEY) || 0 } catch { return 0 } })
  const clientId = forced || (mine.some(c => c.id === pick) ? pick : (mine[0]?.id || undefined))
  const choose = (v) => { setPick(+v); setTab('geral'); setGrp(''); try { localStorage.setItem(CKEY, v) } catch { /* ignore */ } }
  const [fsev, setFsev] = useState(''); const [fst, setFst] = useState(''); const [fq, setFq] = useState(''); const [fk, setFk] = useState('')
  const { data: d, err, reload } = useLoad(() => get(`/portal/overview?days=${days}${clientId ? '&client_id=' + clientId : ''}${minSev != null ? '&min_sev=' + minSev : ''}`), [days, clientId, minSev], 30000)
  const dark = theme === 'dark'
  const s = d?.summary
  const byDay = d ? Object.entries(d.by_day).map(([k, v]) => ({ d: k.slice(5).split('-').reverse().join('/'), v })) : []
  const hist = d ? d.history.filter(e => (!fk || (e.kind || 'infra') === fk) && (!fsev || e.severity >= +fsev) && (!fst || (fst === 'open' ? e.status === 'PROBLEM' : e.status !== 'PROBLEM')) && (!fq || (e.host + ' ' + e.trigger_name).toLowerCase().includes(fq.toLowerCase()))) : []
  const hosts = d ? d.hosts.filter(h => (!grp || h.groups.includes(grp)) && (!hq || (h.name + ' ' + (h.ip || '')).toLowerCase().includes(hq.toLowerCase()))) : []
  const dl = (r) => download(`/portal/reports/${r.id}/download`, `${r.name}.pdf`).catch(e => toast(e.message, true))
  const infra = d ? d.services?.infra !== false : true
  const tabs = d ? [['geral', 'Visão geral'], ['inc', 'Incidentes'], ...(infra ? [['hosts', `Hosts (${d.hosts.length})`]] : []),
    ...(d.backup?.enabled ? [['bkp', 'Backup']] : []), ...(d.endpoints?.enabled ? [['eps', 'Endpoints']] : []), ...(d.services?.cloud ? [['cloud', 'Cloud Orca']] : []), ['rel', 'Relatórios'], ...(canFin ? [['fin', 'Financeiro']] : [])] : []
  return <div style={{ minHeight: embedded ? 0 : '100vh' }}>
    {!embedded && <div className="top ptop" style={{ position: 'sticky' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}><img src="/cliente/brand/branco.png" alt="Orca TI" className="plogo" />
        <div className="pprod"><h1 className="pbrand">NAVI</h1><div className="psub">Portal do Cliente</div></div>
        <div className="pclient">{mine.length > 1 ? <select value={clientId || ''} onChange={e => choose(e.target.value)} title="Trocar de cliente">{mine.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select> : <b>{d ? d.client.name : ''}</b>}</div></div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <select style={{ width: 'auto' }} value={String(days)} onChange={e => setDays(+e.target.value)} aria-label="Período">{PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <button className="iconbtn" aria-label="Alternar tema claro ou escuro" title="Tema" onClick={() => setTheme(toggleTheme())}>{dark ? <Sun /> : <Moon />}</button>
        {!forced && <button className="btn sm" onClick={() => setAcc(true)}><UserRound />Minha conta</button>}
        <button className="btn sm" onClick={onLogout}><LogOut />Sair</button></div></div>}
    {acc && <Modal title="Minha conta" wide onClose={() => setAcc(false)}><Account me={me} onChanged={reloadMe} /></Modal>}
    <div className={embedded ? '' : 'content'} style={{ margin: '0 auto' }}>
      {embedded && <div className="bar"><b style={{ fontSize: 18 }}>{d?.client.name}</b><div className="grow" /><select style={{ width: 'auto' }} value={String(days)} onChange={e => setDays(+e.target.value)} aria-label="Período">{PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>}
      {!d ? <Loading err={err} /> : <>
        {d.active.length > 0
          ? <div className="banner bad" role="button" tabIndex={0} style={{ cursor: 'pointer' }} onClick={() => { setFk(''); setFst('open'); setTab('inc') }}><div className="grow"><b>{d.active.length} problema(s) em andamento.</b> Nossa equipe já está acompanhando. <u>Ver detalhes</u></div></div>
          : <div className="banner info"><div className="grow">✅ Todos os serviços monitorados estão operando normalmente.</div></div>}
        {d.maintenance.length > 0 && <div className="banner warn"><Wrench size={20} /><div className="grow"><b>Manutenção programada:</b> {d.maintenance.map(m => `${m.name} — ${fmtDT(m.start)} a ${fmtDT(m.end)}`).join(' · ')}</div></div>}
        <div className="grid g4" style={{ marginBottom: 16 }}>
          {infra && <Stat onClick={() => setTab('hosts')} label="Disponibilidade" value={fmtPct(s.availability, 3)} tone={s.availability >= 99 ? 'ok' : s.availability >= 95 ? 'warn' : 'bad'} desc={`média dos ${s.hosts_total} equipamentos no período`} />}
          <Stat onClick={() => { setFk(''); setTab('inc') }} label="Incidentes" value={fmtNum(s.incidents)} tone={s.open ? 'bad' : ''} desc={`${s.resolved} resolvido(s) · ${s.open} em aberto`} />
          {['infra', 'backup', 'endpoint', 'cloud'].filter(k => d.services?.[k] !== false && (k === 'infra' ? infra : d.services?.[k])).map(k => <Stat key={k} onClick={() => { setFk(k); setTab('inc') }} label={`Incidentes · ${KIND[k]}`} value={fmtNum(s.by_kind?.[k]?.total || 0)} tone={s.by_kind?.[k]?.open ? 'bad' : ''} desc={`${s.by_kind?.[k]?.open || 0} em aberto`} />)}
          {infra && <Stat onClick={() => setTab('inc')} label="Tempo médio de reparo" value={fmtDur(s.mttr_s)} desc="MTTR (infraestrutura)" />}
        </div>
        <div className="tabs">{tabs.map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
        {PORTAL_TIPS[tab] && <p className="tabhelp">{PORTAL_TIPS[tab][1]}</p>}
        {tab === 'geral' && <>
          <ServiceStatus d={d} go={setTab} />
          <Contracts items={d.contracts} />
          {infra && <Card title={`Incidentes por dia · ${periodLabel(days)}`} style={{ marginBottom: 16 }}><div style={{ height: 230 }}><ResponsiveContainer>
            <BarChart data={byDay}><CartesianGrid vertical={false} stroke="var(--line2)" /><XAxis dataKey="d" tick={{ fontSize: 11 }} interval="preserveStartEnd" /><YAxis allowDecimals={false} width={30} tick={{ fontSize: 11 }} />
              <Tooltip cursor={{ fill: 'var(--hover)' }} /><Bar dataKey="v" name="Incidentes" fill="#1e73f8" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer></div></Card>}
          <Card title={`Problemas em andamento (${d.active.length})`} pad={false}><Table rows={d.active} empty="🎉 Nenhum problema em andamento." onRow={() => { setFk(''); setFst('open'); setTab('inc') }} cols={[{ h: 'Categoria', r: r => <KindPill k={r.kind} /> }, { h: 'Severidade', r: r => <SevBadge n={r.severity} /> }, { h: 'Item', r: r => <b>{r.host}</b> },
            { h: 'Problema', r: r => <div className="trunc" title={r.trigger_name}>{r.trigger_name}</div> }, { h: 'Início', r: r => fmtDT(r.started_at) }, { h: 'Em andamento há', r: r => <LiveDur since={r.started_at} /> }]} /></Card></>}
        {tab === 'inc' && <>
          <div className="tabs" style={{ marginBottom: 12 }}>{[['', 'Todos', d.history.length], ...['infra', 'backup', 'endpoint', 'cloud'].filter(k => d.history.some(e => (e.kind || 'infra') === k) || d.services?.[k]).map(k => [k, KIND[k], d.history.filter(e => (e.kind || 'infra') === k).length])].map(([k, l, n]) => <button key={k || 'all'} className={fk === k ? 'on' : ''} onClick={() => setFk(k)}>{l} ({n})</button>)}</div>
          <div className="bar"><div className="grow"><input placeholder="Buscar por item ou problema…" value={fq} onChange={e => setFq(e.target.value)} /></div>
            <select value={fsev} onChange={e => setFsev(e.target.value)}><option value="">Todas as severidades</option>{[5, 4, 3, 2, 1, 0].filter(n => n >= (d.min_sev || 0)).map(n => <option key={n} value={n}>{SEVN[n]} ou superior</option>)}</select>
            <select value={fst} onChange={e => setFst(e.target.value)}><option value="">Todas as situações</option><option value="open">Em andamento</option><option value="done">Resolvidos</option></select>
            {(fsev || fst || fq || fk) && <button className="btn sm" onClick={() => { setFsev(''); setFst(''); setFq(''); setFk('') }}>Limpar filtros</button>}</div>
          <div className="sub" style={{ margin: '0 2px 10px' }}>{hist.length} de {d.history.length} incidente(s) · exibindo severidade {SEVN[d.min_sev]} ou superior</div>
          <Card pad={false}><Table rows={hist} empty="Nenhum incidente com estes filtros." cols={[{ h: 'Status', r: r => <StatusBadge s={r.status} /> }, { h: 'Categoria', r: r => <KindPill k={r.kind} /> }, { h: 'Sev.', r: r => <SevBadge n={r.severity} /> }, { h: 'Item', r: r => <b>{r.host}</b> },
            { h: 'Problema', r: r => <div className="trunc" title={r.trigger_name}>{r.trigger_name}</div> }, { h: 'Início', r: r => fmtDT(r.started_at) }, { h: 'Recuperação', r: r => fmtDT(r.recovered_at) }, { h: 'Duração', r: r => r.status === 'PROBLEM' ? <LiveDur since={r.started_at} /> : fmtDur(r.duration_s), cls: 'mono' }]} /></Card></>}
        {tab === 'hosts' && <>
          <div className="bar"><div className="grow"><input placeholder="Buscar host ou IP…" value={hq} onChange={e => setHq(e.target.value)} /></div>
            <select value={grp} onChange={e => setGrp(e.target.value)}><option value="">Todos os grupos</option>{d.groups.map(g => <option key={g.name}>{g.name}</option>)}</select></div>
          <Card pad={false}><Table rows={hosts} empty="Nenhum host." cols={[
            { h: 'Estado', r: r => { const [t, l] = hostState(r); return <Pill tone={t}>{l}</Pill> } }, { h: 'Host', r: r => <b>{r.name}</b> }, { h: 'IP', k: 'ip', cls: 'mono' },
            { h: 'Grupos', r: r => r.groups.map(g => <span className="chip" key={g}>{g}</span>) }, { h: 'Incidentes', k: 'incidents' },
            { h: 'Indisponibilidade', r: r => fmtDur(r.downtime_s) }, { h: 'Disponibilidade', r: r => r.availability == null ? '—' : fmtPct(r.availability, 3) }]} /></Card></>}
        {tab === 'bkp' && d.protection && <><ServicesCard services={d.protection.services} />{d.backup.alerts.length > 0 && <Card title="Atenção no backup" pad={false} style={{ marginBottom: 16 }}><Table rows={d.backup.alerts} cols={[{ h: 'Severidade', r: r => <SevBadge n={r.severity} /> }, { h: 'Item', r: r => <b>{r.host}</b> }, { h: 'Situação', k: 'trigger_name' }, { h: 'Desde', r: r => fmtDT(r.started_at) }]} /></Card>}<BackupPanel data={d.protection} runPath={r => `/portal/backups/${r.id}/run${clientId ? '?client_id=' + clientId : ''}`} reload={reload} /></>}
        {tab === 'eps' && d.protection && <EndpointsPanel data={d.protection} />}
        {tab === 'cloud' && <CloudPanel path={`/portal/cloud${clientId ? '?client_id=' + clientId : ''}`} powerPath={u => `/portal/cloud/${u}/power${clientId ? '?client_id=' + clientId : ''}`} />}
        {tab === 'fin' && canFin && <FinanceTab clientId={clientId} key={clientId} />}
        {tab === 'rel' && <Card title="Relatórios mensais" pad={false}><Table rows={d.reports} empty="Nenhum relatório disponível ainda." cols={[{ h: 'Relatório', r: r => <b>{r.name}</b> },
          { h: 'Período', r: r => `${fmtDT(r.period_start)} a ${fmtDT(r.period_end)}` }, { h: 'Gerado em', r: r => fmtDT(r.generated_at) },
          { h: '', r: r => <button className="btn sm" onClick={() => dl(r)}><Download />Baixar PDF</button> }]} /></Card>}
      </>}
      {!embedded && d && <NaviGuide scope="portal" tips={PORTAL_TIPS} current={tab} asks={PORTAL_ASKS} go={setTab} tour={tabs.map(t => t[0])} extra={PORTAL_SEV} userKey={me?.id} name={me?.name} />}
      {!embedded && <div className="sub" style={{ textAlign: 'center', marginTop: 28, fontSize: 12.5 }}>Dados em tempo real do monitoramento · {me?.email}</div>}
    </div></div>
}
