import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { EyeOff, Eye, FlaskConical, RefreshCw, HardDrive, ShieldCheck } from 'lucide-react'
import { get, post, put, fmtDT, fmtNum } from '../api'
import { Card, Check, Field, Loading, PageHead, Pill, SevBadge, Stat, Table, Tabs, useLoad, useToast } from '../ui'
import { Play } from 'lucide-react'
import { EventBalloons } from './ProtectionPanels'
import { useAuth, can } from '../App'

const ST = { ok: 'ok', falha: 'bad', 'sem backup': 'bad', offline: 'warn', 'sem dados': 'mut', ignorado: 'mut' }
const TYPES = { machine: 'Máquina', database: 'Banco de dados', mailbox: 'Caixa de e-mail', drive: 'OneDrive', site: 'SharePoint', team: 'Teams' }
const ago = (v) => { if (!v) return '—'; const h = (Date.now() - new Date(v).getTime()) / 36e5; return h < 1 ? 'há ' + Math.max(1, Math.round(h * 60)) + ' min' : h < 48 ? 'há ' + Math.round(h) + ' h' : 'há ' + Math.round(h / 24) + ' d' }

export function Overview({ ov, clients, edit, reload }) {
  const toast = useToast(); const nav = useNavigate()
  const [q, setQ] = useState(''); const [st, setSt] = useState(''); const [ty, setTy] = useState(''); const [cl, setCl] = useState('')
  const rows = ov.assets.filter(a => (!q || (a.name + ' ' + (a.tenant || '')).toLowerCase().includes(q.toLowerCase())) && (!st || a.status === st) && (!ty || a.type === ty) && (!cl || String(a.client_id) === cl))
  const toggle = async (a) => { try { await put('/protection/assets/' + a.id, { ignored: !a.ignored }); toast(a.ignored ? 'Monitoramento reativado' : 'Item ignorado (sem alertas de backup antigo/offline)'); reload() } catch (e) { toast(e.message, true) } }
  const run = async (r) => { if (!confirm(`Executar agora o plano de backup de “${r.name}”?`)) return; try { const x = await post(`/protection/assets/${r.id}/run-backup`); toast(x.detail); reload() } catch (e) { toast(e.message, true) } }
  const c = ov.counts
  return <>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat onClick={() => setSt("ok")} label="Backups em dia" value={fmtNum(c.ok)} tone="ok" desc={`${ov.assets.length} itens protegidos`} />
      <Stat onClick={() => setSt("falha")} label="Com falha" value={fmtNum(c.falha)} tone={c.falha ? 'bad' : ''} desc={`${ov.failed_24h} falha(s) nas últimas 24h`} />
      <Stat onClick={() => setSt("sem backup")} label="Sem backup recente" value={fmtNum(c['sem backup'])} tone={c['sem backup'] ? 'bad' : ''} desc={`sem sucesso há mais de ${ov.thresholds.stale_h}h`} />
      <Stat onClick={() => setSt("offline")} label="Agentes offline" value={fmtNum(c.offline)} tone={c.offline ? 'warn' : ''} desc={`offline há mais de ${Math.round(ov.thresholds.offline_min / 60)}h`} />
    </div>
    {ov.alerts.length > 0 && <Card title={`Problemas de backup em aberto (${ov.alerts.length})`} pad={false} style={{ marginBottom: 16 }}>
      <Table rows={ov.alerts} onRow={r => nav(`/eventos?kind=backup&q=${encodeURIComponent(r.host || '')}&days=`)} cols={[{ h: 'Sev.', r: r => <SevBadge n={r.severity} /> }, { h: 'Cliente', r: r => r.client_name || <Pill tone="warn">sem cliente</Pill> },
        { h: 'Item', r: r => <b>{r.host}</b> }, { h: 'Problema', r: r => r.trigger_name }, { h: 'Plano', r: r => <span className="sub">{r.item_name || '—'}</span> }, { h: 'Desde', r: r => fmtDT(r.started_at) }]} /></Card>}
    <div className="bar"><div className="grow"><input placeholder="Buscar máquina, banco ou cliente…" value={q} onChange={e => setQ(e.target.value)} /></div>
      <select value={cl} onChange={e => setCl(e.target.value)}><option value="">Todos os clientes</option>{clients.map(x => <option key={x.id} value={x.id}>{x.trade_name}</option>)}</select>
      <select value={st} onChange={e => setSt(e.target.value)}><option value="">Todos os status</option>{Object.keys(ST).map(k => <option key={k}>{k}</option>)}</select>
      <select value={ty} onChange={e => setTy(e.target.value)}><option value="">Todos os tipos</option>{Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
    <Card pad={false}><Table rows={rows} empty="Nada encontrado." cols={[
      { h: 'Status', r: r => <Pill tone={ST[r.status]}>{r.status}</Pill> }, { h: 'Item', r: r => <b>{r.name}</b> }, { h: 'Tipo', r: r => TYPES[r.type] || r.type },
      { h: 'Cliente (Acronis)', r: r => <>{r.tenant}{r.client ? <div className="sub">→ {r.client}</div> : <div className="sub" style={{ color: 'var(--orange)' }}>não associado</div>}</> },
      { h: 'Proteção', r: r => <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>{(r.techs || []).map(t => <span key={t} className="badge b-info">{t}</span>)}</span> }, { h: 'Plano', r: r => <span className="sub">{r.policy || '—'}</span> }, { h: 'Último sucesso', r: r => <span title={fmtDT(r.last_success_at)}>{ago(r.last_success_at)}</span> },
      { h: 'Última falha', r: r => r.last_failure_at ? <span title={fmtDT(r.last_failure_at)}>{ago(r.last_failure_at)}</span> : '—' },
      { h: 'Agente', r: r => r.online === null || r.online === undefined ? '—' : r.online ? <Pill tone="ok">online</Pill> : <Pill tone="warn">offline</Pill> },
      { h: '', r: r => <div style={{ display: 'flex', gap: 6 }}>{r.can_run && <button className="btn sm" title="Executar o plano de backup agora" onClick={() => run(r)}><Play />Executar</button>}{edit && <button className="btn sm" title={r.ignored ? 'Voltar a monitorar' : 'Ignorar (não gerar alerta de backup antigo / offline)'} onClick={() => toggle(r)}>{r.ignored ? <Eye /> : <EyeOff />}</button>}</div> }]} /></Card></>
}

const EST = { online: 'ok', offline: 'mut', 'sem contato': 'warn', 'antivírus off': 'bad', assinaturas: 'warn', quarentena: 'bad', atenção: 'warn', ignorado: 'mut' }
export function Endpoints({ ov, clients, edit, reload }) {
  const toast = useToast(); const nav = useNavigate()
  const [q, setQ] = useState(''); const [st, setSt] = useState(''); const [cl, setCl] = useState('')
  const rows = ov.assets.filter(a => (!q || (a.name + ' ' + (a.user || '') + ' ' + (a.site || '')).toLowerCase().includes(q.toLowerCase())) && (!st || a.status === st) && (!cl || String(a.client_id) === cl))
  const toggle = async (a) => { try { await put('/protection/assets/' + a.id, { ignored: !a.ignored }); reload() } catch (e) { toast(e.message, true) } }
  const c = ov.counts; const prob = (c['sem contato'] || 0) + (c['antivírus off'] || 0) + (c.assinaturas || 0) + (c.quarentena || 0) + (c['atenção'] || 0)
  return <>
    {ov.blocked && <div className="banner bad"><div className="grow"><b>O EMS recusou o login.</b> Corrija o usuário/senha em Configuração e salve para tentar novamente (a NAVI não insiste, para não bloquear o usuário no EMS).</div></div>}
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat onClick={() => setSt("")} label="Endpoints" value={fmtNum(ov.total)} desc={`${ov.online} online agora`} />
      <Stat onClick={() => setSt(["sem contato", "antivírus off", "assinaturas", "quarentena", "atenção"].find(k => c[k]) || "")} label="Com problema" value={fmtNum(prob)} tone={prob ? 'bad' : 'ok'} desc="sem contato, antivírus, assinaturas, quarentena" />
      <Stat onClick={() => setSt("sem contato")} label="Sem contato" value={fmtNum(c['sem contato'] || 0)} tone={c['sem contato'] ? 'warn' : ''} desc={`há mais de ${ov.offline_days} dias`} />
      <Stat onClick={() => setSt("antivírus off")} label="Antivírus desativado" value={fmtNum(c['antivírus off'] || 0)} tone={c['antivírus off'] ? 'bad' : ''} desc="estações online sem proteção" />
    </div>
    {ov.alerts.length > 0 && <Card title={`Problemas de endpoints em aberto (${ov.alerts.length})`} pad={false} style={{ marginBottom: 16 }}>
      <Table rows={ov.alerts} onRow={r => nav(`/eventos?kind=endpoint&q=${encodeURIComponent(r.host || '')}&days=`)} cols={[{ h: 'Sev.', r: r => <SevBadge n={r.severity} /> }, { h: 'Cliente', r: r => r.client_name || <Pill tone="warn">sem cliente</Pill> },
        { h: 'Estação', r: r => <b>{r.host}</b> }, { h: 'Problema', r: r => r.trigger_name }, { h: 'Detalhe', r: r => <span className="sub">{r.opdata || ''}</span> }, { h: 'Desde', r: r => fmtDT(r.started_at) }]} /></Card>}
    <div className="bar"><div className="grow"><input placeholder="Buscar estação, usuário ou site…" value={q} onChange={e => setQ(e.target.value)} /></div>
      <select value={cl} onChange={e => setCl(e.target.value)}><option value="">Todos os clientes</option>{clients.map(x => <option key={x.id} value={x.id}>{x.trade_name}</option>)}</select>
      <select value={st} onChange={e => setSt(e.target.value)}><option value="">Todos os status</option>{Object.keys(EST).map(k => <option key={k}>{k}</option>)}</select></div>
    <Card pad={false}><Table rows={rows} empty="Nenhum endpoint (a integração está ativa e já sincronizou?)." cols={[
      { h: 'Status', r: r => <Pill tone={EST[r.status]}>{r.status}</Pill> }, { h: 'Estação', r: r => <b>{r.name}</b> }, { h: 'Usuário', k: 'user' },
      { h: 'Site (EMS)', r: r => <>{r.site}{r.client ? <div className="sub">→ {r.client}</div> : <div className="sub" style={{ color: 'var(--orange)' }}>não associado</div>}</> },
      { h: 'Sistema', r: r => <span className="sub">{(r.os || '').replace('Microsoft ', '').replace(' Edition, 64-bit', '').slice(0, 38)}</span> },
      { h: 'FortiClient', r: r => <span className="sub">{r.fct_version || '—'}</span> }, { h: 'Antivírus', r: r => r.av_enabled === false ? <Pill tone="bad">desativado</Pill> : r.sig_ok === false ? <Pill tone="warn">assin. antigas</Pill> : <Pill tone="ok">ok</Pill> },
      { h: 'Eventos', r: r => <EventBalloons events={r.events} vulnSev={r.vuln_sev} /> },
      { h: 'Último contato', r: r => <span title={fmtDT(r.last_contact)}>{ago(r.last_contact)}</span> },
      { h: '', r: r => edit && <button className="btn sm" title={r.ignored ? 'Voltar a monitorar' : 'Ignorar'} onClick={() => toggle(r)}>{r.ignored ? <Eye /> : <EyeOff />}</button> }]} /></Card></>
}

function Tenants({ ov, ems }) {
  const nav = useNavigate()
  return <Card title="Associações: Acronis e EMS → clientes da NAVI" pad={false}>
    <div className="sub" style={{ padding: '10px 20px 0' }}>A associação agora é feita no <b>cadastro do cliente</b>, nas abas <b>Acronis</b> e <b>FortiClient EMS</b> (igual aos hosts do Zabbix). Esta lista só mostra o estado atual — itens pendentes não geram alerta, portal nem relatório.</div>
    <Table rows={[...ov.tenants.map(t => ({ ...t, src: 'Acronis' })), ...(ems?.tenants || []).map(t => ({ ...t, src: 'EMS (site)' }))]} onRow={r => r.client_id && nav('/clientes/' + r.client_id)} cols={[{ h: 'Origem', r: r => <Pill tone="info">{r.src}</Pill> }, { h: 'Cliente / site na origem', r: r => <b>{r.name}</b> }, { h: 'Itens', k: 'assets' },
      { h: 'Tecnologias contratadas', r: r => <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>{(r.services || []).slice(0, 6).map(t => <span key={t} className="badge b-mut">{t}</span>)}</span> },
      { h: 'Cliente na NAVI', r: r => r.client_id ? <b>{r.client_name}</b> : <span className="sub">— não associado —</span> },
      { h: 'Estado', r: r => r.client_id ? <Pill tone="ok">associado</Pill> : <Pill tone="warn">pendente · associe no cadastro do cliente</Pill> }]} /></Card>
}

export default function Protection() {
  const me = useAuth(); const nav = useNavigate(); const [tab, setTab] = useState('geral')
  const ov = useLoad(() => get('/protection/overview'), [], 60000); const ems = useLoad(() => get('/protection/ems'), [], 60000); const clients = useLoad(() => get('/clients'), [])
  const reloadAll = () => { ov.reload(); ems.reload() }
  const edit = can(me, 'clients.edit'); const cfg = can(me, 'settings.view')
  const tabs = [['geral', 'Backup (Acronis)'], ['eps', 'Endpoints (EMS)'], ['tenants', 'Associações']]
  return <>
    <PageHead title="Backup e Endpoints" desc="Acronis Cyber Protect (backup e proteção) e FortiClient EMS (endpoints)"><Pill tone="info"><HardDrive size={14} />Acronis</Pill><Pill tone="info"><ShieldCheck size={14} />EMS</Pill></PageHead>
    <Tabs value={tab} onChange={setTab} tabs={tabs} />
    {cfg && <div className="hint" style={{ marginBottom: 10 }}>As credenciais do Acronis e do EMS ficam em <a href="#" onClick={e => { e.preventDefault(); nav('/configuracoes') }}>Configurações</a>.</div>}
    {(!ov.data || !ems.data || !clients.data ? <Loading err={ov.err || ems.err} /> : tab === 'geral' ? <Overview ov={ov.data} clients={clients.data} edit={edit} reload={reloadAll} />
      : tab === 'eps' ? <Endpoints ov={ems.data} clients={clients.data} edit={edit} reload={reloadAll} /> : <Tenants ov={ov.data} ems={ems.data} />)}
</>
}
