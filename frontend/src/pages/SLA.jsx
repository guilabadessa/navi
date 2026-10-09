import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { get, fmtDur, fmtPct } from '../api'
import { Card, Loading, PageHead, Pill, ServiceChips, Stat, Table, useLoad } from '../ui'

export default function SLA() {
  const [days, setDays] = useState(30); const nav = useNavigate(); const { data, err } = useLoad(() => get('/sla?days=' + days), [days], 60000)
  const items = data?.items || []; const below = items.filter(i => i.met === false).length; const withInfra = items.filter(i => i.services?.infra).length
  return <>
    <PageHead title="SLA" desc="Disponibilidade realizada versus contratada por cliente, descontadas as janelas de manutenção">
      <select style={{ width: 'auto' }} value={days} onChange={e => setDays(+e.target.value)}>{[7, 30, 90].map(d => <option key={d} value={d}>Últimos {d} dias</option>)}</select></PageHead>
    {!data ? <Loading err={err} /> : <>
      <div className="grid g3" style={{ marginBottom: 16 }}><Stat label="Clientes ativos" value={items.length} desc={`${withInfra} com infraestrutura monitorada`} /><Stat label="Abaixo do SLA" value={below} tone={below ? 'bad' : 'ok'} /><Stat label="Dentro do SLA" value={withInfra - below} tone="ok" /></div>
      <Card pad={false}><Table rows={items} onRow={r => nav('/clientes/' + r.client_id)} cols={[
        { h: 'Cliente', r: r => <><b>{r.client}</b><div style={{ marginTop: 3 }}><ServiceChips s={r.services} /></div></> }, { h: 'Hosts', r: r => r.services?.infra ? r.hosts : '—' }, { h: 'SLA contratado', r: r => r.services?.infra ? fmtPct(r.sla_target) : '—' },
        { h: 'SLA realizado', r: r => r.availability == null ? <span className="sub">Sem infraestrutura monitorada</span> : <div style={{ minWidth: 150 }}><b>{fmtPct(r.availability, 3)}</b><div className="progress" style={{ marginTop: 4 }}><i style={{ width: Math.max(0, Math.min(100, r.availability)) + '%', background: r.met === false ? 'var(--crit)' : undefined }} /></div></div> },
        { h: 'Incidentes', r: r => r.services?.infra ? r.incidents : '—' }, { h: 'Indisponível', r: r => r.services?.infra ? fmtDur(r.downtime_s) : '—' }, { h: 'MTTR', r: r => r.services?.infra ? fmtDur(r.mttr_s) : '—' }, { h: 'MTBF', r: r => r.services?.infra ? fmtDur(r.mtbf_s) : '—' },
        { h: 'Backup', r: r => r.backup_items ? <Pill tone={r.backup_bad ? 'bad' : 'ok'}>{r.backup_items - r.backup_bad}/{r.backup_items} em dia</Pill> : '—' },
        { h: 'Estações', r: r => r.endpoint_items ? <Pill tone={r.endpoint_bad ? 'bad' : 'ok'}>{r.endpoint_items - r.endpoint_bad}/{r.endpoint_items} ok</Pill> : '—' },
        { h: 'Resultado', r: r => !r.services?.infra ? <Pill>N/A</Pill> : r.met === false ? <Pill tone="bad">NÃO ATINGIDO</Pill> : <Pill tone="ok">ATINGIDO</Pill> }]} /></Card></>}</>
}
