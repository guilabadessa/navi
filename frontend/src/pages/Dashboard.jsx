import React, { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AlertTriangle, EyeOff, Wrench, Building2 } from 'lucide-react'
import { get, post, fmtDT, fmtDur, fmtNum, fmtPct } from '../api'
import { Card, Loading, PageHead, Pill, SevBadge, Stat, Table, useLoad, useToast } from '../ui'
import { useNavigate } from 'react-router-dom'
import { useAuth, can } from '../App'

const SEVC = { 'Não classificado': '#97aab3', Informação: '#7499ff', Atenção: '#e0a800', Média: '#f08a24', Alta: '#e45959', Desastre: '#bd1723' }
const since = (v) => fmtDur((Date.now() - new Date(v).getTime()) / 1000)
const ls = (k, d) => { try { return localStorage.getItem('navi.dash.' + k) ?? d } catch { return d } }
const lset = (k, v) => { try { localStorage.setItem('navi.dash.' + k, v) } catch { /* ignore */ } }

export default function Dashboard() {
  const me = useAuth(); const toast = useToast(); const nav = useNavigate()
  const [cl, setCl] = useState(ls('cl', '')); const [days, setDays] = useState(ls('days', '30'))
  const clients = useLoad(() => get('/clients'), [])
  const { data: d, err, reload } = useLoad(() => get(`/dashboard?days=${days}${cl ? '&client_id=' + cl : ''}`), [cl, days], 20000)
  if (!d) return <Loading err={err} />
  const evs = (extra = '') => nav(`/eventos?days=${days}${cl ? '&client_id=' + cl : ''}${extra}`)
  const byDay = Object.entries(d.by_day).map(([k, v]) => ({ d: k.slice(5).split('-').reverse().join('/'), v }))
  const sevTotal = d.by_severity.reduce((a, s) => a + s.incidents, 0) || 1
  const maint = async (cid, name) => {
    if (!confirm(`Colocar ${name} em manutenção por 2 horas? Nenhum alerta será enviado para este cliente nesse período.`)) return
    try { await post(`/clients/${cid}/maintenance`, { hours: 2 }); toast('Cliente em manutenção por 2h'); reload() } catch (e) { toast(e.message, true) }
  }
  const failed = d.alerts_24h?.failed || 0
  return <>
    <PageHead title="NAVI NOC" desc={`Visão em tempo real · atualizado ${new Date(d.generated_at).toLocaleTimeString('pt-BR')}`}>
      <select style={{ width: 'auto' }} value={cl} onChange={e => { setCl(e.target.value); lset('cl', e.target.value) }}>
        <option value="">Todos os clientes</option>{(clients.data || []).map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select>
      <select style={{ width: 'auto' }} value={days} onChange={e => { setDays(e.target.value); lset('days', e.target.value) }}>
        {[1, 7, 30, 90].map(x => <option key={x} value={x}>{x === 1 ? 'Últimas 24h' : `Últimos ${x} dias`}</option>)}</select>
    </PageHead>

    {d.stale_jobs.length > 0 && <div className="banner bad"><AlertTriangle size={20} /><div className="grow"><b>Processamento da NAVI com atraso:</b> {d.stale_jobs.join(', ')}. Os alertas podem não estar sendo enviados — verifique o worker.</div></div>}
    {d.shadow && <div className="banner info"><EyeOff size={20} /><div className="grow"><b>Modo sombra ativo:</b> os alertas são registrados, mas <u>não são enviados</u>. Desative em Alertas → Migração.</div><button className="btn sm" onClick={() => nav('/alertas')}>Abrir</button></div>}
    {!cl && d.coverage?.hosts_uncovered > 0 && <div className="banner warn"><Building2 size={20} /><div className="grow"><b>{d.coverage.hosts_uncovered} de {d.coverage.hosts_total} hosts sem cliente associado</b> — não geram alerta, SLA nem relatório.</div><button className="btn sm" onClick={() => nav('/clientes?cobertura=1')}>Associar agora</button></div>}
    {failed > 0 && <div className="banner warn"><AlertTriangle size={20} /><div className="grow"><b>{failed} envio(s) de alerta falharam nas últimas 24h.</b> Confira os detalhes nos eventos.</div></div>}

    <div className="grid g4" style={{ marginBottom: 16 }}>
      <div className="cardlink" onClick={() => evs('&status=PROBLEM')}><Stat label="Problemas ativos" value={fmtNum(d.problems_active)} tone={d.problems_active ? 'bad' : 'ok'} desc={`${d.clients_affected} cliente(s) afetado(s)`} /></div>
      <div className="cardlink" onClick={() => nav('/monitoramento')}><Stat label="Hosts monitorados" value={fmtNum(d.hosts_total)} desc={`${d.hosts_down} indisponível(is)`} tone={d.hosts_down ? 'warn' : ''} /></div>
      <div className="cardlink" onClick={() => nav('/sla')}><Stat label={`Disponibilidade (${days}d)`} value={fmtPct(d.availability_30d, 3)} tone="ok" desc={`MTTR ${fmtDur(d.mttr_s)}`} /></div>
      <div className="cardlink" onClick={() => evs('&status=PROBLEM&q=link')}><Stat label="Links indisponíveis" value={fmtNum(d.links_down)} tone={d.links_down ? 'bad' : ''} desc="alertas de link/WAN em aberto" /></div>
    </div>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <div className="cardlink" onClick={() => nav('/eventos?days=1')}><Stat label="Problemas hoje" value={fmtNum(d.problems_today)} /></div>
      <div className="cardlink" onClick={() => evs()}><Stat label={`Últimos ${days} dias`} value={fmtNum(d.problems_30d)} /></div>
      <div className="cardlink" onClick={() => nav('/protecao')}><Stat label="Backup e endpoints" value={fmtNum((d.backup_active || 0) + (d.endpoint_active || 0))} tone={(d.backup_active || 0) + (d.endpoint_active || 0) ? 'bad' : 'ok'} desc={`Acronis ${d.backup_active || 0} · EMS ${d.endpoint_active || 0}`} /></div>
      <Stat label="Alertas enviados (24h)" value={fmtNum(d.alerts_24h?.sent || 0)} tone={failed ? 'warn' : ''} desc={`${failed} falha(s) · ${d.alerts_24h?.skipped || 0} ignorado(s)`} />
    </div>

    <div className="grid g-2-1" style={{ marginBottom: 16 }}>
      <Card title={`Incidentes por dia (${days === '1' ? '24h' : days + ' dias'})`}><div style={{ height: 250 }}><ResponsiveContainer>
        {days === '1'
          ? <BarChart data={d.by_hour}><CartesianGrid vertical={false} stroke="var(--line2)" /><XAxis dataKey="h" tick={{ fontSize: 11 }} interval={1} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={34} /><Tooltip cursor={{ fill: 'var(--hover)' }} /><Bar dataKey="v" name="Incidentes" fill="#1e73f8" radius={[5, 5, 0, 0]} /></BarChart>
          : <BarChart data={byDay}><CartesianGrid vertical={false} stroke="var(--line2)" /><XAxis dataKey="d" tick={{ fontSize: 11 }} interval="preserveStartEnd" /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={34} />
            <Tooltip cursor={{ fill: 'var(--hover)' }} /><Bar dataKey="v" name="Incidentes" fill="#1e73f8" radius={[5, 5, 0, 0]} /></BarChart>}</ResponsiveContainer></div></Card>
      <Card title="Por severidade">
        <div style={{ height: 190 }}><ResponsiveContainer>
          <PieChart><Pie data={d.by_severity} dataKey="incidents" nameKey="key" innerRadius={48} outerRadius={80} paddingAngle={2}
            onClick={(s) => evs('&min_severity=' + Math.max(0, Object.keys(SEVC).indexOf(s.key)))}>
            {d.by_severity.map((s, i) => <Cell key={i} fill={SEVC[s.key] || '#1e73f8'} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer></div>
        <div className="sevbar" style={{ margin: '4px 0 8px' }}>{d.by_severity.map(s => <i key={s.key} title={`${s.key}: ${s.incidents}`} style={{ width: (s.incidents / sevTotal * 100) + '%', background: SEVC[s.key] }} />)}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', fontSize: 12.5 }}>{d.by_severity.map(s => <span key={s.key}><i className="dot" style={{ background: SEVC[s.key], marginRight: 5 }} />{s.key} <b>{s.incidents}</b></span>)}</div>
      </Card>
    </div>

    <Card title={`Problemas ativos agora (${d.problems_active})`} pad={false} style={{ marginBottom: 16 }}
      actions={<button className="btn sm" onClick={() => evs('&status=PROBLEM')}>Ver todos</button>}>
      <Table rows={d.live} onRow={r => nav(`/eventos?status=PROBLEM&q=${encodeURIComponent(r.host || '')}`)} empty="🎉 Nenhum problema ativo no momento." cols={[
        { h: 'Severidade', r: r => <SevBadge n={r.severity} /> },
        { h: 'Cliente', r: r => r.client_name ? <b>{r.client_name}</b> : <Pill tone="warn">sem cliente</Pill> },
        { h: 'Host', r: r => <b>{r.host}</b> }, { h: 'IP', k: 'ip' },
        { h: 'Problema', r: r => <div className="trunc" title={r.trigger_name}>{r.trigger_name}</div> },
        { h: 'Início', r: r => fmtDT(r.started_at) }, { h: 'Há', r: r => since(r.started_at), cls: 'mono' }, { h: 'Alerta', r: r => r.wa_status || '—' },
        { h: '', r: r => r.client_id && can(me, 'clients.edit') && <button className="btn sm" title="Colocar o cliente em manutenção por 2h" onClick={e => { e.stopPropagation(); maint(r.client_id, r.client_name) }}><Wrench /></button> }]} /></Card>

    <div className="grid g2">
      <Card title={`Top hosts com problemas (${days}d)`} pad={false}><Table rows={d.top_hosts} onRow={r => nav(`/eventos?q=${encodeURIComponent(r.host)}&days=${days}`)} cols={[{ h: 'Host', k: 'host' }, { h: 'Incidentes', k: 'incidents' }, { h: 'Indisponível', r: r => fmtDur(r.downtime_s) }]} /></Card>
      <Card title={`Top clientes com problemas (${days}d)`} pad={false}><Table rows={d.top_clients} onRow={r => nav(`/clientes/${r.client_id}`)} cols={[{ h: 'Cliente', k: 'client' }, { h: 'Incidentes', k: 'incidents' }, { h: 'Indisponível', r: r => fmtDur(r.downtime_s) }]} /></Card>
    </div>
    <div style={{ marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {Object.entries(d.health || {}).map(([k, v]) => <Pill key={k} tone={v.ok ? 'ok' : 'bad'}>{k}: {v.detail}</Pill>)}</div></>
}
