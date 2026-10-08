import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { EyeOff, Eye, FlaskConical, RefreshCw, HardDrive, ShieldCheck } from 'lucide-react'
import { get, post, put, fmtDT, fmtNum } from '../api'
import { Card, Check, Field, Loading, PageHead, Pill, SevBadge, Stat, Table, Tabs, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'

const ST = { ok: 'ok', falha: 'bad', 'sem backup': 'bad', offline: 'warn', 'sem dados': 'mut', ignorado: 'mut' }
const TYPES = { machine: 'Máquina', database: 'Banco de dados', mailbox: 'Caixa de e-mail', drive: 'OneDrive', site: 'SharePoint', team: 'Teams' }
const ago = (v) => { if (!v) return '—'; const h = (Date.now() - new Date(v).getTime()) / 36e5; return h < 1 ? 'há ' + Math.max(1, Math.round(h * 60)) + ' min' : h < 48 ? 'há ' + Math.round(h) + ' h' : 'há ' + Math.round(h / 24) + ' d' }

function Overview({ ov, clients, edit, reload }) {
  const toast = useToast(); const nav = useNavigate()
  const [q, setQ] = useState(''); const [st, setSt] = useState(''); const [ty, setTy] = useState(''); const [cl, setCl] = useState('')
  const rows = ov.assets.filter(a => (!q || (a.name + ' ' + (a.tenant || '')).toLowerCase().includes(q.toLowerCase())) && (!st || a.status === st) && (!ty || a.type === ty) && (!cl || String(a.client_id) === cl))
  const toggle = async (a) => { try { await put('/protection/assets/' + a.id, { ignored: !a.ignored }); toast(a.ignored ? 'Monitoramento reativado' : 'Item ignorado (sem alertas de backup antigo/offline)'); reload() } catch (e) { toast(e.message, true) } }
  const c = ov.counts
  return <>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat label="Backups em dia" value={fmtNum(c.ok)} tone="ok" desc={`${ov.assets.length} itens protegidos`} />
      <Stat label="Com falha" value={fmtNum(c.falha)} tone={c.falha ? 'bad' : ''} desc={`${ov.failed_24h} falha(s) nas últimas 24h`} />
      <Stat label="Sem backup recente" value={fmtNum(c['sem backup'])} tone={c['sem backup'] ? 'bad' : ''} desc={`sem sucesso há mais de ${ov.thresholds.stale_h}h`} />
      <Stat label="Agentes offline" value={fmtNum(c.offline)} tone={c.offline ? 'warn' : ''} desc={`offline há mais de ${Math.round(ov.thresholds.offline_min / 60)}h`} />
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
      { h: 'Plano', r: r => <span className="sub">{r.policy || '—'}</span> }, { h: 'Último sucesso', r: r => <span title={fmtDT(r.last_success_at)}>{ago(r.last_success_at)}</span> },
      { h: 'Última falha', r: r => r.last_failure_at ? <span title={fmtDT(r.last_failure_at)}>{ago(r.last_failure_at)}</span> : '—' },
      { h: 'Agente', r: r => r.online === null || r.online === undefined ? '—' : r.online ? <Pill tone="ok">online</Pill> : <Pill tone="warn">offline</Pill> },
      { h: '', r: r => edit && <button className="btn sm" title={r.ignored ? 'Voltar a monitorar' : 'Ignorar (não gerar alerta de backup antigo / offline)'} onClick={() => toggle(r)}>{r.ignored ? <Eye /> : <EyeOff />}</button> }]} /></Card></>
}

const EST = { online: 'ok', offline: 'mut', 'sem contato': 'warn', 'antivírus off': 'bad', assinaturas: 'warn', quarentena: 'bad', atenção: 'warn', ignorado: 'mut' }
function Endpoints({ ov, clients, edit, reload }) {
  const toast = useToast(); const nav = useNavigate()
  const [q, setQ] = useState(''); const [st, setSt] = useState(''); const [cl, setCl] = useState('')
  const rows = ov.assets.filter(a => (!q || (a.name + ' ' + (a.user || '') + ' ' + (a.site || '')).toLowerCase().includes(q.toLowerCase())) && (!st || a.status === st) && (!cl || String(a.client_id) === cl))
  const toggle = async (a) => { try { await put('/protection/assets/' + a.id, { ignored: !a.ignored }); reload() } catch (e) { toast(e.message, true) } }
  const c = ov.counts; const prob = (c['sem contato'] || 0) + (c['antivírus off'] || 0) + (c.assinaturas || 0) + (c.quarentena || 0) + (c['atenção'] || 0)
  return <>
    {ov.blocked && <div className="banner bad"><div className="grow"><b>O EMS recusou o login.</b> Corrija o usuário/senha em Configuração e salve para tentar novamente (a NAVI não insiste, para não bloquear o usuário no EMS).</div></div>}
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat label="Endpoints" value={fmtNum(ov.total)} desc={`${ov.online} online agora`} />
      <Stat label="Com problema" value={fmtNum(prob)} tone={prob ? 'bad' : 'ok'} desc="sem contato, antivírus, assinaturas, quarentena" />
      <Stat label="Sem contato" value={fmtNum(c['sem contato'] || 0)} tone={c['sem contato'] ? 'warn' : ''} desc={`há mais de ${ov.offline_days} dias`} />
      <Stat label="Antivírus desativado" value={fmtNum(c['antivírus off'] || 0)} tone={c['antivírus off'] ? 'bad' : ''} desc="estações online sem proteção" />
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
      { h: 'Último contato', r: r => <span title={fmtDT(r.last_contact)}>{ago(r.last_contact)}</span> },
      { h: '', r: r => edit && <button className="btn sm" title={r.ignored ? 'Voltar a monitorar' : 'Ignorar'} onClick={() => toggle(r)}>{r.ignored ? <Eye /> : <EyeOff />}</button> }]} /></Card></>
}

function Tenants({ ov, ems, clients, edit, reload }) {
  const toast = useToast()
  const map = async (t, v) => { try { const r = await put('/protection/tenants/' + t.id, { client_id: v ? +v : null }); toast(`Associação salva · ${r.events_relinked} evento(s) atualizados`); reload() } catch (e) { toast(e.message, true) } }
  return <Card title="Clientes do Acronis e sites do EMS → clientes da NAVI" pad={false}>
    <div className="sub" style={{ padding: '10px 20px 0' }}>Associe cada cliente (tenant) do Acronis ao cliente correspondente da NAVI. É essa associação que define para quem vão os alertas de backup, o portal e os relatórios. Sem associação, o problema aparece aqui mas ninguém é avisado.</div>
    <Table rows={[...ov.tenants.map(t => ({ ...t, src: 'Acronis' })), ...(ems?.tenants || []).map(t => ({ ...t, src: 'EMS (site)' }))]} cols={[{ h: 'Origem', r: r => <Pill tone="info">{r.src}</Pill> }, { h: 'Cliente / site na origem', r: r => <b>{r.name}</b> }, { h: 'Itens', k: 'assets' },
      { h: 'Cliente na NAVI', r: r => <select style={{ minWidth: 240 }} disabled={!edit} value={r.client_id || ''} onChange={e => map(r, e.target.value)}><option value="">— não associado —</option>{clients.map(x => <option key={x.id} value={x.id}>{x.trade_name}</option>)}</select> },
      { h: 'Estado', r: r => r.client_id ? <Pill tone="ok">associado</Pill> : <Pill tone="warn">pendente</Pill> }]} /></Card>
}

function Config() {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/protection/config'), []); const [x, setX] = useState(null); const [busy, setBusy] = useState('')
  React.useEffect(() => { if (data && !x) setX({ ...data, acronis_secret: '', ems_password: '' }) }, [data]) // eslint-disable-line
  if (!x) return <Loading />
  const set = (k, v) => setX({ ...x, [k]: v })
  const save = async () => { try { await put('/protection/config', { ...x, acronis_secret: x.acronis_secret || null, ems_password: x.ems_password || null, ems_offline_days: +x.ems_offline_days, stale_h: +x.stale_h, offline_min: +x.offline_min, ems_port: +x.ems_port }); toast('Configuração salva'); setX(null); reload() } catch (e) { toast(e.message, true) } }
  const test = async (s) => { setBusy(s); try { const r = await post('/protection/test/' + s); toast(r.detail, !r.ok) } catch (e) { toast(e.message, true) } finally { setBusy('') } }
  const syncEms = async () => { setBusy('syncems'); try { const r = await post('/protection/sync/ems'); toast(`Sincronizado · ${r.endpoints} endpoints · ${r.new} novo(s) problema(s) · ${r.resolved} resolvido(s)`) } catch (e) { toast(e.message, true) } finally { setBusy('') } }
  const sync = async () => { setBusy('sync'); try { const r = await post('/protection/sync/acronis'); toast(`Sincronizado · ${r.assets} itens · ${r.new} novo(s) problema(s) · ${r.resolved} resolvido(s)`) } catch (e) { toast(e.message, true) } finally { setBusy('') } }
  return <div style={{ display: 'grid', gap: 16 }}>
    <Card title="Acronis Cyber Protect Cloud" actions={<><button className="btn sm" disabled={!!busy} onClick={() => test('acronis')}><FlaskConical />{busy === 'acronis' ? 'Testando…' : 'Testar conexão'}</button><button className="btn sm" disabled={!!busy} onClick={sync}><RefreshCw />{busy === 'sync' ? 'Sincronizando…' : 'Sincronizar agora'}</button></>}>
      <Check label="Monitorar o Acronis" checked={x.acronis_enabled} onChange={v => set('acronis_enabled', v)} />
      <div className="row r3" style={{ marginTop: 12 }}><Field label="URL DO DATACENTER"><input value={x.acronis_url} onChange={e => set('acronis_url', e.target.value)} /></Field>
        <Field label="ID DO CLIENTE (API)"><input value={x.acronis_client_id} onChange={e => set('acronis_client_id', e.target.value)} /></Field>
        <Field label="SEGREDO" hint={x.acronis_secret_set ? 'Já configurado — deixe em branco para manter.' : 'Obrigatório.'}><input type="password" autoComplete="new-password" value={x.acronis_secret} onChange={e => set('acronis_secret', e.target.value)} placeholder={x.acronis_secret_set ? '••••••••' : ''} /></Field></div>
      <div className="row r2"><Field label="ALERTAR SE NÃO HOUVER BACKUP COM SUCESSO HÁ (HORAS)" hint="Use um valor maior que o intervalo dos seus planos (ex.: 72h para planos diários)."><input type="number" min="1" value={x.stale_h} onChange={e => set('stale_h', e.target.value)} /></Field>
        <Field label="ALERTAR AGENTE OFFLINE APÓS (MINUTOS)"><input type="number" min="5" value={x.offline_min} onChange={e => set('offline_min', e.target.value)} /></Field></div>
      <p className="hint">Recomendação de segurança: use no Acronis um usuário de API com perfil <b>somente leitura</b>. A NAVI só faz consultas (GET).</p></Card>
    <Card title="FortiClient EMS (endpoints)" actions={<><button className="btn sm" disabled={!!busy} onClick={() => test('ems')}><FlaskConical />{busy === 'ems' ? 'Testando…' : 'Testar conexão'}</button><button className="btn sm" disabled={!!busy} onClick={syncEms}><RefreshCw />{busy === 'syncems' ? 'Sincronizando…' : 'Sincronizar agora'}</button></>}>
      {x.ems_blocked && <div className="banner bad"><div className="grow">O EMS recusou o login anterior. Informe a senha correta, salve e teste.</div></div>}
      <Check label="Monitorar o EMS" checked={x.ems_enabled} onChange={v => set('ems_enabled', v)} />
      <div className="row r3" style={{ marginTop: 12 }}><Field label="ENDEREÇO (IP OU DNS)"><input value={x.ems_host} onChange={e => set('ems_host', e.target.value)} placeholder="172.16.31.205" /></Field>
        <Field label="PORTA HTTPS"><input type="number" value={x.ems_port} onChange={e => set('ems_port', e.target.value)} /></Field>
        <Field label="ALERTAR SEM CONTATO APÓS (DIAS)"><input type="number" min="1" value={x.ems_offline_days} onChange={e => set('ems_offline_days', e.target.value)} /></Field></div>
      <div className="row r2"><Field label="USUÁRIO" hint="Use um usuário somente leitura do EMS."><input value={x.ems_user || ''} onChange={e => set('ems_user', e.target.value)} /></Field>
        <Field label="SENHA" hint={x.ems_password_set ? 'Já configurada — deixe em branco para manter.' : ''}><input type="password" autoComplete="new-password" value={x.ems_password} onChange={e => set('ems_password', e.target.value)} placeholder={x.ems_password_set ? '••••••••' : ''} /></Field></div></Card>
    <div><button className="btn primary" onClick={save}>Salvar configuração</button></div></div>
}

export default function Protection() {
  const me = useAuth(); const [tab, setTab] = useState('geral')
  const ov = useLoad(() => get('/protection/overview'), [], 60000); const ems = useLoad(() => get('/protection/ems'), [], 60000); const clients = useLoad(() => get('/clients'), [])
  const reloadAll = () => { ov.reload(); ems.reload() }
  const edit = can(me, 'clients.edit'); const cfg = can(me, 'settings.view')
  const tabs = [['geral', 'Backup (Acronis)'], ['eps', 'Endpoints (EMS)'], ['tenants', 'Clientes'], ...(cfg ? [['cfg', 'Configuração']] : [])]
  return <>
    <PageHead title="Backup e Endpoints" desc="Acronis Cyber Protect (backup) e FortiClient EMS (endpoints) · consultas somente leitura"><Pill tone="info"><HardDrive size={14} />Acronis</Pill><Pill tone="info"><ShieldCheck size={14} />EMS</Pill></PageHead>
    <Tabs value={tab} onChange={setTab} tabs={tabs} />
    {tab !== 'cfg' && (!ov.data || !ems.data || !clients.data ? <Loading err={ov.err || ems.err} /> : tab === 'geral' ? <Overview ov={ov.data} clients={clients.data} edit={edit} reload={reloadAll} />
      : tab === 'eps' ? <Endpoints ov={ems.data} clients={clients.data} edit={edit} reload={reloadAll} /> : <Tenants ov={ov.data} ems={ems.data} clients={clients.data} edit={edit} reload={reloadAll} />)}
    {tab === 'cfg' && <Config />}</>
}
