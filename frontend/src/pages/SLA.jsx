import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { get, fmtDur, fmtPct } from '../api'
import { Card, Loading, PageHead, Pill, Stat, Table, useLoad } from '../ui'

export default function SLA() {
  const [days, setDays] = useState(30); const nav = useNavigate(); const { data, err } = useLoad(() => get('/sla?days=' + days), [days], 60000)
  const items = data?.items || []; const below = items.filter(i => i.met === false).length
  return <>
    <PageHead title="SLA" desc="SLA realizado versus contratado por cliente">
      <select style={{ width: 'auto' }} value={days} onChange={e => setDays(+e.target.value)}>{[7, 30, 90, 180, 365].map(d => <option key={d} value={d}>Últimos {d} dias</option>)}</select></PageHead>
    {!data ? <Loading err={err} /> : <>
      <div className="grid g3" style={{ marginBottom: 16 }}><Stat label="Clientes ativos" value={items.length} /><Stat label="Abaixo do SLA" value={below} tone={below ? 'bad' : 'ok'} /><Stat label="Dentro do SLA" value={items.length - below} tone="ok" /></div>
      <Card pad={false}><Table rows={items} onRow={r => nav('/clientes/' + r.client_id)} cols={[
        { h: 'Cliente', r: r => <b>{r.client}</b> }, { h: 'Hosts', k: 'hosts' }, { h: 'SLA contratado', r: r => fmtPct(r.sla_target) },
        { h: 'SLA realizado', r: r => <div style={{ minWidth: 150 }}><b>{fmtPct(r.availability, 3)}</b><div className="progress" style={{ marginTop: 4 }}><i style={{ width: Math.max(0, Math.min(100, r.availability)) + '%', background: r.met === false ? 'var(--crit)' : undefined }} /></div></div> },
        { h: 'Incidentes', k: 'incidents' }, { h: 'Indisponível', r: r => fmtDur(r.downtime_s) }, { h: 'MTTR', r: r => fmtDur(r.mttr_s) }, { h: 'MTBF', r: r => fmtDur(r.mtbf_s) },
        { h: 'Resultado', r: r => r.met === false ? <Pill tone="bad">NÃO ATINGIDO</Pill> : <Pill tone="ok">ATINGIDO</Pill> }]} /></Card></>}</>
}
