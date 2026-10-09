import React, { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AlertTriangle, EyeOff, Wrench, Building2 } from 'lucide-react'
import { get, post, fmtDT, fmtDur, fmtNum, fmtPct } from '../api'
import { Card, Loading, Modal, PageHead, Pill, SevBadge, Stat, Table, useLoad, useToast } from '../ui'
import { useNavigate } from 'react-router-dom'
import { useAuth, can } from '../App'

const SEVC = { 'Não classificado': '#97aab3', Informação: '#7499ff', Atenção: '#e0a800', Média: '#f08a24', Alta: '#e45959', Desastre: '#bd1723' }
const since = (v) => fmtDur((Date.now() - new Date(v).getTime()) / 1000)
const ls = (k, d) => { try { return localStorage.getItem('navi.dash.' + k) ?? d } catch { return d } }
const lset = (k, v) => { try { localStorage.setItem('navi.dash.' + k, v) } catch { /* ignore */ } }

// Banner de falhas de rotina: clicar mostra o detalhe; "Dar ciencia" some com o aviso ate surgir uma falha nova
function JobAlerts({ jobs, reload, canAck }) {
  const toast = useToast(); const [open, setOpen] = useState(false); const [busy, setBusy] = useState('')
  const ack = async (j) => {
    setBusy(j.name)
    try { await post(`/dashboard/jobs/${j.name}/ack`); toast('Ciência registrada'); await reload() } catch (e) { toast(e.message, true) } finally { setBusy('') }
  }
  const when = (v) => v ? fmtDT(v) : 'nunca executou'
  return <>
    <div className="banner bad" role="button" tabIndex={0} style={{ cursor: 'pointer' }} onClick={() => setOpen(true)} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && setOpen(true)}>
      <AlertTriangle size={20} /><div className="grow"><b>{jobs.length === 1 ? '1 rotina da NAVI com falha' : `${jobs.length} rotinas da NAVI com falha`}:</b> {jobs.map(j => j.label + (j.kind === 'erro' ? ' (erro)' : ' (atraso)')).join(', ')}. Os alertas podem não estar sendo enviados — clique para ver os detalhes.</div>
      <button className="btn sm" onClick={e => { e.stopPropagation(); setOpen(true) }}>Ver detalhes</button></div>
    {open && <Modal title="Falhas nas rotinas da NAVI" onClose={() => setOpen(false)} wide
      footer={<button className="btn" onClick={() => setOpen(false)}>Fechar</button>}>
      {jobs.length === 0 && <div className="empty">Nenhuma falha pendente. 🎉</div>}
      {jobs.map(j => <div key={j.name} style={{ borderBottom: '1px solid var(--line)', padding: '12px 0' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <b>{j.label}</b><Pill tone={j.kind === 'erro' ? 'bad' : 'warn'}>{j.kind === 'erro' ? 'Erro na execução' : 'Atrasada'}</Pill>
          <div className="grow" />
          {canAck && <button className="btn sm" disabled={busy === j.name} onClick={() => ack(j)}>{busy === j.name ? 'Registrando…' : 'Dar ciência'}</button>}</div>
        <div style={{ fontSize: 13, marginTop: 4, color: 'var(--mut)' }}>Última execução: {when(j.last_run)}{j.kind === 'atraso' && j.interval_s ? ` · deveria rodar a cada ${fmtDur(j.interval_s)}` : ''}</div>
        {j.error && <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, background: 'var(--line)', padding: 10, borderRadius: 8, marginTop: 8, maxHeight: 160, overflow: 'auto' }}>{j.error}</pre>}
        {j.kind === 'atraso' && <div style={{ fontSize: 13, marginTop: 6 }}>Possível causa: o worker está parado. Verifique com <code>docker compose ps</code> e reinicie o serviço <code>worker</code>.</div>}
      </div>)}
      <p style={{ fontSize: 12, marginTop: 12, color: 'var(--mut)' }}>“Dar ciência” remove o aviso desta falha. Se a rotina falhar com outro erro, ou voltar a atrasar, o aviso reaparece.</p>
    </Modal>}
  </>
}

// Envios de alerta que falharam (24h): detalhe por envio e ciencia
function FailedSends({ items, reload, canAck }) {
  const toast = useToast(); const [open, setOpen] = useState(false); const [busy, setBusy] = useState(false)
  const ack = async () => {
    setBusy(true)
    try { await post('/dashboard/dispatches/ack'); toast('Ciência registrada'); setOpen(false); await reload() } catch (e) { toast(e.message, true) } finally { setBusy(false) }
  }
  return <>
    <div className="banner warn" role="button" tabIndex={0} style={{ cursor: 'pointer' }} onClick={() => setOpen(true)} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && setOpen(true)}>
      <AlertTriangle size={20} /><div className="grow"><b>{items.length} envio(s) de alerta falharam nas últimas 24h.</b> Clique para ver o motivo de cada um.</div>
      <button className="btn sm" onClick={e => { e.stopPropagation(); setOpen(true) }}>Ver detalhes</button></div>
    {open && <Modal title="Envios de alerta com falha" wide onClose={() => setOpen(false)}
      footer={<><button className="btn" onClick={() => setOpen(false)}>Fechar</button>{canAck && <button className="btn primary" disabled={busy} onClick={ack}>{busy ? 'Registrando…' : 'Dar ciência em todos'}</button>}</>}>
      {items.map(i => <div key={i.id} style={{ borderBottom: '1px solid var(--line)', padding: '10px 0' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}><b>{i.client || 'Sem cliente'}</b><Pill tone="mut">{i.channel === 'email' ? 'E-mail' : 'WhatsApp'}</Pill><span style={{ color: 'var(--mut)', fontSize: 13 }}>{fmtDT(i.at)} · {i.attempts} tentativa(s)</span></div>
        <div style={{ fontSize: 13, marginTop: 4 }}>{i.host ? `${i.host} — ` : ''}{i.trigger || 'alerta'}</div>
        <div style={{ fontSize: 13, color: 'var(--mut)' }}>Destino: {i.dest}</div>
        {i.error && <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, background: 'var(--line)', padding: 8, borderRadius: 8, marginTop: 6, maxHeight: 120, overflow: 'auto' }}>{i.error}</pre>}
      </div>)}
      <p style={{ fontSize: 12, marginTop: 12, color: 'var(--mut)' }}>“Dar ciência” remove o aviso destes envios. Novas falhas voltam a aparecer.</p>
    </Modal>}
  </>
}

export default function Dashboard() {
  const me = useAuth(); const toast = useToast(); const nav = useNavigate()
  const [cl, setCl] = useState(ls('cl', '')); const [days, setDays] = useState(ls('days', '30'))
  const clients = useLoad(() => get('/clients'), [])
  const { data: d, err, reload } = useLoad(() => get(`/dashboard?days=${days}${cl ? '&client_id=' + cl : ''}`), [cl, days], 20000)
  const health = useLoad(() => get('/dashboard/clients-health'), [], 30000)
  if (!d) return <Loading err={err} />
  const evs = (extra = '') => nav(`/eventos?days=${days}${cl ? '&client_id=' + cl : ''}${extra}`)
  const byDay = Object.entries(d.by_day).map(([k, v]) => ({ d: k.slice(5).split('-').reverse().join('/'), v }))
  const sevTotal = d.by_severity.reduce((a, s) => a + s.incidents, 0) || 1
  const maint = async (cid, name) => {
    if (!confirm(`Colocar ${name} em manutenção por 2 horas? Nenhum alerta será enviado para este cliente nesse período.`)) return
    try { await post(`/clients/${cid}/maintenance`, { hours: 2 }); toast('Cliente em manutenção por 2h'); reload() } catch (e) { toast(e.message, true) }
  }
  const noInfra = !!(d.services && !d.services.infra)
  const failed = d.alerts_24h?.failed || 0  // total bruto (card); o banner usa so os sem ciencia
  return <>
    <PageHead title="Painel do NOC" desc={`Situação de todos os clientes em tempo real · atualizado às ${new Date(d.generated_at).toLocaleTimeString('pt-BR')}`}>
      <select style={{ width: 'auto' }} value={cl} onChange={e => { setCl(e.target.value); lset('cl', e.target.value) }}>
        <option value="">Todos os clientes</option>{(clients.data || []).map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select>
      <select style={{ width: 'auto' }} value={days} onChange={e => { setDays(e.target.value); lset('days', e.target.value) }}>
        {[1, 7, 30, 90].map(x => <option key={x} value={x}>{x === 1 ? 'Últimas 24h' : `Últimos ${x} dias`}</option>)}</select>
    </PageHead>

    {d.stale_jobs.length > 0 && <JobAlerts jobs={d.stale_jobs} reload={reload} canAck={can(me, 'routines.edit')} />}
    {d.shadow && <div className="banner info"><EyeOff size={20} /><div className="grow"><b>Modo sombra ativo:</b> os alertas são registrados, mas <u>não são enviados</u>. Desative em Alertas → Migração.</div><button className="btn sm" onClick={() => nav('/alertas')}>Abrir</button></div>}
    {!cl && d.coverage?.hosts_uncovered > 0 && <div className="banner warn"><Building2 size={20} /><div className="grow"><b>{d.coverage.hosts_uncovered} de {d.coverage.hosts_total} hosts sem cliente associado</b> — não geram alerta nem relatório.</div><button className="btn sm" onClick={() => nav('/clientes?cobertura=1')}>Associar agora</button></div>}
    {d.failed_dispatches.length > 0 && <FailedSends items={d.failed_dispatches} reload={reload} canAck={can(me, 'alerts.edit')} />}

    <div className="grid g4" style={{ marginBottom: 16 }}>
      <div className="cardlink" onClick={() => evs('&status=PROBLEM')}><Stat label="Problemas ativos" value={fmtNum(d.problems_active)} tone={d.problems_active ? 'bad' : 'ok'} desc={`${d.clients_affected} cliente(s) afetado(s)`} /></div>
      {noInfra ? <>
        <div className="cardlink" onClick={() => nav('/protecao')}><Stat label="Backups com alerta" value={fmtNum(d.backup_active || 0)} tone={d.backup_active ? 'bad' : 'ok'} desc={d.services.backup ? 'Acronis' : 'cliente sem backup'} /></div>
        <div className="cardlink" onClick={() => nav('/protecao')}><Stat label="Estações com alerta" value={fmtNum(d.endpoint_active || 0)} tone={d.endpoint_active ? 'bad' : 'ok'} desc={d.services.endpoint ? 'FortiClient EMS' : 'cliente sem estações'} /></div>
        <Stat label="Serviços do cliente" value={[d.services.backup && 'Backup', d.services.endpoint && 'Estações'].filter(Boolean).join(' + ') || 'Nenhum'} desc="Sem hosts de infraestrutura associados" />
      </> : <>
      <div className="cardlink" onClick={() => nav('/monitoramento')}><Stat label="Hosts monitorados" value={fmtNum(d.hosts_total)} desc={`${d.hosts_down} indisponível(is)`} tone={d.hosts_down ? 'warn' : ''} /></div>
      <div className="cardlink" onClick={() => nav('/monitoramento')}><Stat label={`Disponibilidade (${days}d)`} value={fmtPct(d.availability_30d, 3)} tone="ok" desc={`MTTR ${fmtDur(d.mttr_s)}`} /></div>
      <div className="cardlink" onClick={() => evs('&status=PROBLEM&q=link')}><Stat label="Links indisponíveis" value={fmtNum(d.links_down)} tone={d.links_down ? 'bad' : ''} desc="alertas de link/WAN em aberto" /></div>
      </>}
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

    {!cl && health.data && health.data.items.length > 0 && <Card title="Saúde por cliente" pad={false} style={{ marginBottom: 16 }}>
      <Table rows={health.data.items} onRow={r => nav('/clientes/' + r.client_id)} cols={[{ h: 'Cliente', r: r => <b>{r.client}</b> },
        { h: 'Infraestrutura', r: r => r.infra ? <Pill tone={r.infra_worst >= 4 ? 'bad' : 'warn'}>{r.infra} problema(s)</Pill> : <Pill tone="ok">{r.hosts_down ? r.hosts_down + ' host(s) fora' : 'ok'}</Pill> },
        { h: 'Backup', r: r => !r.has_backup ? <span className="sub">—</span> : r.backup || r.backup_bad ? <Pill tone={r.backup_worst >= 4 || r.backup_bad ? 'bad' : 'warn'}>{r.backup || r.backup_bad} problema(s)</Pill> : <Pill tone="ok">{r.backup_items} ok</Pill> },
        { h: 'Estações', r: r => !r.has_ems ? <span className="sub">—</span> : r.endpoint || r.endpoint_bad ? <Pill tone={r.endpoint_worst >= 4 ? 'bad' : 'warn'}>{r.endpoint || r.endpoint_bad} atenção</Pill> : <Pill tone="ok">{r.endpoint_items} ok</Pill> },
        { h: 'Hosts', k: 'hosts' }]} /></Card>}
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
