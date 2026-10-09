import React, { useState } from 'react'
import { get, fmtDT, fmtDur } from '../api'
import { useSearchParams } from 'react-router-dom'
import { useAuth, can } from '../App'
import { CloudFleet } from './CloudPanel'
import { Endpoints as EmsEndpoints, Overview as BackupOverview } from './Protection'
import { Card, Drawer, Loading, PageHead, Pager, Pill, SevBadge, StatusBadge, Table, Tabs, useLoad } from '../ui'

const AV = { 0: ['mut', 'desconhecido'], 1: ['ok', 'disponível'], 2: ['bad', 'indisponível'] }

function HostDetail({ id, onClose }) {
  const { data: h, err } = useLoad(() => get('/zabbix/hosts/' + id), [id]); const [tab, setTab] = useState('ev')
  return <Drawer title={h ? h.name : 'Host'} onClose={onClose}>{!h ? <Loading err={err} /> : <>
    <div className="kv" style={{ marginBottom: 16 }}><b>Host</b><span>{h.host}</span><b>IP / DNS</b><span>{h.ip || '—'} {h.dns && '· ' + h.dns}</span><b>Grupos</b><span>{h.groups.map(g => <span className="chip" key={g}>{g}</span>)}</span>
      <b>Templates</b><span>{(h.templates || []).slice(0, 8).map(g => <span className="chip" key={g}>{g}</span>)}</span><b>Disponibilidade</b><span><Pill tone={AV[h.available][0]}>{AV[h.available][1]}</Pill></span><b>Status</b><span>{h.status === 0 ? 'monitorado' : 'desabilitado'}</span></div>
    <Tabs value={tab} onChange={setTab} tabs={[['ev', `Eventos (${h.events.length})`], ['tr', `Triggers (${h.triggers.length})`], ['it', `Itens (${h.item_count})`]]} />
    {tab === 'ev' && <Table rows={h.events} cols={[{ h: 'Sev.', r: r => <SevBadge n={r.severity} /> }, { h: 'Problema', r: r => <div className="trunc" style={{ maxWidth: 200 }}>{r.trigger_name}</div> }, { h: 'Início', r: r => fmtDT(r.started_at) }, { h: 'Duração', r: r => fmtDur(r.duration_s) }]} />}
    {tab === 'tr' && <Table rows={h.triggers} cols={[{ h: 'Sev.', r: r => <SevBadge n={r.priority} /> }, { h: 'Trigger', k: 'description' }, { h: 'Estado', r: r => r.value ? <Pill tone="bad">PROBLEMA</Pill> : <Pill tone="ok">OK</Pill> }]} empty={h.live_error || 'Nenhuma trigger.'} />}
    {tab === 'it' && <Table rows={h.items} cols={[{ h: 'Item', r: r => <div className="trunc" style={{ maxWidth: 260 }} title={r.key_}>{r.name}</div> }, { h: 'Último valor', r: r => <span className="mono">{r.lastvalue} {r.units}</span> }]} empty={h.live_error || 'Nenhum item.'} />}
  </>}</Drawer>
}

// Backup (Acronis) e endpoints (EMS) dentro do Monitoramento: carrega so quando a aba e aberta
function ProtTab({ kind }) {
  const me = useAuth(); const ov = useLoad(() => get(kind === 'bkp' ? '/protection/overview' : '/protection/ems'), [kind], 60000); const clients = useLoad(() => get('/clients'), [])
  if (!ov.data || !clients.data) return <Loading err={ov.err} />
  const edit = can(me, 'clients.edit')
  return kind === 'bkp' ? <BackupOverview ov={ov.data} clients={clients.data} edit={edit} reload={ov.reload} /> : <EmsEndpoints ov={ov.data} clients={clients.data} edit={edit} reload={ov.reload} />
}

export default function Monitoring() {
  const [sp] = useSearchParams(); const [tab, setTab] = useState(sp.get('aba') || 'hosts'); const [q, setQ] = useState(''); const [groupid, setGroup] = useState(''); const [av, setAv] = useState(''); const [page, setPage] = useState(1); const [sel, setSel] = useState(null)
  const { data: groups } = useLoad(() => get('/zabbix/groups'), [])
  const { data, err } = useLoad(() => get(`/zabbix/hosts?page=${page}&size=50&q=${encodeURIComponent(q)}&groupid=${groupid}${av !== '' ? '&available=' + av : ''}`), [page, q, groupid, av], 30000)
  return <>
    <PageHead title="Monitoramento" desc="Tudo o que a NAVI monitora: hosts e grupos (Zabbix), backup (Acronis), endpoints (FortiClient EMS) e máquinas da Cloud Orca, com o cliente associado a cada item" />
    <Tabs value={tab} onChange={setTab} tabs={[['hosts', 'Hosts (Zabbix)'], ['groups', 'Host Groups (Zabbix)'], ['bkp', 'Backup (Acronis)'], ['eps', 'Endpoints (EMS)'], ['cloud', 'Cloud Orca']]} />
    {(tab === 'bkp' || tab === 'eps') && <ProtTab kind={tab} />}
    {tab === 'cloud' && <CloudFleet />}
    {tab === 'hosts' && <>
      <div className="bar"><div className="grow"><input placeholder="Buscar host, IP ou DNS…" value={q} onChange={e => { setQ(e.target.value); setPage(1) }} /></div>
        <select value={groupid} onChange={e => { setGroup(e.target.value); setPage(1) }}><option value="">Todos os grupos</option>{(groups || []).map(g => <option key={g.groupid} value={g.groupid}>{g.name}</option>)}</select>
        <select value={av} onChange={e => { setAv(e.target.value); setPage(1) }}><option value="">Toda disponibilidade</option><option value="1">Disponível</option><option value="2">Indisponível</option><option value="0">Desconhecido</option></select></div>
      <Card pad={false}>{data ? <><Table rows={data.items} onRow={r => setSel(r.hostid)} cols={[
        { h: '', w: 30, r: r => <i className="dot" style={{ background: r.available === 2 ? '#bd1723' : r.available === 1 ? '#16a34a' : '#b8c0d8' }} /> },
        { h: 'Host', r: r => <b>{r.name}</b> }, { h: 'IP', k: 'ip', cls: 'mono' }, { h: 'Grupos', r: r => <div className="trunc">{r.groups.join(', ')}</div> },
        { h: 'Itens', k: 'item_count' }, { h: 'Triggers', k: 'trigger_count' }, { h: 'Eventos abertos', r: r => r.open_events ? <Pill tone="bad">{r.open_events}</Pill> : '—' },
        { h: 'Status', r: r => r.status === 0 ? <Pill tone="ok">monitorado</Pill> : <Pill>desabilitado</Pill> }]} /><div style={{ padding: '0 16px 12px' }}><Pager page={page} size={50} total={data.total} onPage={setPage} /></div></> : <Loading err={err} />}</Card></>}
    {tab === 'groups' && <Card pad={false}>{groups ? <Table rows={groups} cols={[{ h: 'Host Group', r: r => <b>{r.name}</b> }, { h: 'Hosts', k: 'host_count' }, { h: 'Cliente NAVI', r: r => r.clients.length ? r.clients.map(c => <span className="chip" key={c}>{c}</span>) : <span className="sub">não associado</span> }]} /> : <Loading />}</Card>}
    {sel && <HostDetail id={sel} onClose={() => setSel(null)} />}</>
}
