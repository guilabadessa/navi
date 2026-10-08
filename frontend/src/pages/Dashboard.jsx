import React from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { get, fmtDT, fmtDur, fmtNum, fmtPct } from '../api'
import { Card, Loading, PageHead, SevBadge, Stat, StatusBadge, Table, useLoad } from '../ui'
import { useNavigate } from 'react-router-dom'

const SEVC = { 'Não classificado': '#97aab3', Informação: '#7499ff', Atenção: '#e0a800', Média: '#f08a24', Alta: '#e45959', Desastre: '#bd1723' }
const since = (v) => fmtDur((Date.now() - new Date(v).getTime()) / 1000)

export default function Dashboard() {
  const { data: d, err } = useLoad(() => get('/dashboard'), [], 20000)
  const nav = useNavigate()
  if (!d) return <Loading err={err} />
  const days = Object.entries(d.by_day).map(([k, v]) => ({ d: k.slice(5).split('-').reverse().join('/'), v }))
  return <>
    <PageHead title="NAVI NOC" desc={`Visão em tempo real · atualizado ${new Date(d.generated_at).toLocaleTimeString('pt-BR')}`} />
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat label="Problemas ativos" value={fmtNum(d.problems_active)} tone={d.problems_active ? 'bad' : 'ok'} desc={`${d.clients_affected} cliente(s) afetado(s)`} />
      <Stat label="Hosts monitorados" value={fmtNum(d.hosts_total)} desc={`${d.hosts_down} indisponível(is)`} tone={d.hosts_down ? 'warn' : ''} />
      <Stat label="Disponibilidade (30d)" value={fmtPct(d.availability_30d, 3)} tone="ok" desc={`MTTR ${fmtDur(d.mttr_s)}`} />
      <Stat label="Links indisponíveis" value={fmtNum(d.links_down)} tone={d.links_down ? 'bad' : ''} desc="alertas de link/WAN em aberto" />
    </div>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat label="Problemas hoje" value={fmtNum(d.problems_today)} />
      <Stat label="Últimos 7 dias" value={fmtNum(d.problems_7d)} />
      <Stat label="Últimos 30 dias" value={fmtNum(d.problems_30d)} />
      <Stat label="SLA médio (30d)" value={fmtPct(d.sla_30d, 3)} />
    </div>
    <div className="grid g-2-1" style={{ marginBottom: 16 }}>
      <Card title="Incidentes por dia (30 dias)"><div style={{ height: 250 }}><ResponsiveContainer>
        <BarChart data={days}><CartesianGrid vertical={false} stroke="#eef1f8" /><XAxis dataKey="d" tick={{ fontSize: 11 }} interval="preserveStartEnd" /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={34} />
          <Tooltip cursor={{ fill: '#eef3ff' }} /><Bar dataKey="v" name="Incidentes" fill="#1e73f8" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer></div></Card>
      <Card title="Por severidade"><div style={{ height: 250 }}><ResponsiveContainer>
        <PieChart><Pie data={d.by_severity} dataKey="incidents" nameKey="key" innerRadius={55} outerRadius={90} paddingAngle={2}>
          {d.by_severity.map((s, i) => <Cell key={i} fill={SEVC[s.key] || '#1e73f8'} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer></div></Card>
    </div>
    <Card title="Problemas ativos agora" pad={false} style={{ marginBottom: 16 }}>
      <Table rows={d.live} onRow={() => nav('/eventos?status=PROBLEM')} empty="🎉 Nenhum problema ativo no momento." cols={[
        { h: 'Severidade', r: r => <SevBadge n={r.severity} /> }, { h: 'Host', r: r => <b>{r.host}</b> }, { h: 'IP', k: 'ip' },
        { h: 'Problema', r: r => <div className="trunc" title={r.trigger_name}>{r.trigger_name}</div> },
        { h: 'Início', r: r => fmtDT(r.started_at) }, { h: 'Há', r: r => since(r.started_at), cls: 'mono' }, { h: 'WhatsApp', r: r => r.wa_status || '—' }]} /></Card>
    <div className="grid g2">
      <Card title="Top hosts com problemas (30d)" pad={false}><Table rows={d.top_hosts} cols={[{ h: 'Host', k: 'host' }, { h: 'Incidentes', k: 'incidents' }, { h: 'Indisponível', r: r => fmtDur(r.downtime_s) }]} /></Card>
      <Card title="Top clientes com problemas (30d)" pad={false}><Table rows={d.top_clients} cols={[{ h: 'Cliente', k: 'client' }, { h: 'Incidentes', k: 'incidents' }, { h: 'Indisponível', r: r => fmtDur(r.downtime_s) }]} /></Card>
    </div></>
}
