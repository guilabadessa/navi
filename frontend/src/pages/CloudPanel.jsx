import React, { useEffect, useRef, useState } from 'react'
import { Activity, BellOff, BellRing, Play, Power, RotateCw, ShieldAlert } from 'lucide-react'
import { get, post, put, del } from '../api'
import { Card, Field, Loading, Modal, Pill, Stat, Table, useLoad, useToast } from '../ui'

const ST = { RUNNING: ['ok', 'ligada'], STOPPED: ['mut', 'desligada'], SHUTOFF: ['mut', 'desligada'], STARTING: ['warn', 'ligando'], STOPPING: ['warn', 'desligando'], ERROR: ['bad', 'com erro'], DESTROYED: ['mut', 'removida'] }
const QL = { Instance: 'Máquinas', IP: 'IPs públicos', Volume: 'Discos', Snapshot: 'Snapshots', CPU: 'vCPUs', Memory: 'Memória', PrimaryStorage: 'Armazenamento', SecondaryStorage: 'Armazenamento secundário', Network: 'Redes', Template: 'Templates', VPC: 'VPCs' }
const ram = (mb) => mb >= 1024 ? `${(mb / 1024).toFixed(mb % 1024 ? 1 : 0).replace('.', ',')} GB` : `${mb} MB`
const qfmt = (q, v) => q.unit === 'mb' ? ram(v) : q.unit === 'gb' ? `${v} GB` : String(v)
const ago = (v) => { if (!v) return ''; const m = Math.round((Date.now() - new Date(v).getTime()) / 60000); return m < 1 ? 'agora' : m < 60 ? `há ${m} min` : m < 2880 ? `há ${Math.round(m / 60)} h` : `há ${Math.round(m / 1440)} d` }
const confirmText = (name, action, label) => `${label} a máquina “${name}”?\n\n` + (action === 'start' ? 'A máquina será ligada agora.' : action === 'reboot' ? 'A máquina será desligada e ligada de novo. Os usuários conectados serão desconectados e os serviços ficam indisponíveis por alguns minutos.' : action === 'force-stop' ? 'DESLIGAMENTO FORÇADO: equivale a puxar o cabo de energia e pode causar perda de dados ou corromper o sistema.' : 'A máquina será desligada. Os usuários conectados serão desconectados e os serviços ficam indisponíveis até ligar de novo.')

// Saude da maquina (CPU, memoria, disco, ping). "Monitorar ao vivo" consulta a cada 5 s por ate 5 minutos.
const tone = (p) => p == null ? '' : p >= 90 ? 'var(--crit)' : p >= 80 ? 'var(--orange)' : undefined
function Meter({ label, pct, desc, hist }) {
  const p = pct == null ? null : Math.max(0, Math.min(100, pct))
  return <div style={{ marginBottom: 14 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}><b>{label}</b><span>{p == null ? 'sem dados' : `${pct.toFixed(1).replace('.', ',')}%`}</span></div>
    <div className="progress"><i style={{ width: (p || 0) + '%', background: tone(p) }} /></div>
    {desc && <div className="sub">{desc}</div>}
    {hist && hist.length > 1 && <svg viewBox="0 0 100 20" preserveAspectRatio="none" style={{ width: '100%', height: 28, marginTop: 4 }} aria-hidden="true">
      <polyline fill="none" stroke="var(--acc, #1e73f8)" strokeWidth="1.4" vectorEffect="non-scaling-stroke" points={hist.map((v, i) => `${(i / (hist.length - 1)) * 100},${20 - (Math.max(0, Math.min(100, v)) / 100) * 20}`).join(' ')} /></svg>}
  </div>
}
export function VmHealth({ vm, path, onClose }) {
  const [h, setH] = useState(null); const [err, setErr] = useState(null); const [live, setLive] = useState(false)
  const [hist, setHist] = useState({ cpu: [], mem: [] }); const started = useRef(0)
  const load = async () => { try { const d = await get(path); setH(d); setErr(null); setHist(x => ({ cpu: d.cpu != null ? [...x.cpu, d.cpu].slice(-60) : x.cpu, mem: d.mem != null ? [...x.mem, d.mem].slice(-60) : x.mem })) } catch (e) { setErr(e.message); setLive(false) } }
  useEffect(() => { load() }, [path]) // eslint-disable-line
  useEffect(() => {
    if (!live) return
    started.current = Date.now()
    const t = setInterval(() => { if (Date.now() - started.current > 300000) { setLive(false); return } load() }, 5000)
    return () => clearInterval(t)
  }, [live]) // eslint-disable-line
  const mon = h && h.source === 'zabbix'
  return <Modal title={`Saúde · ${vm.name}`} onClose={onClose} footer={<>
    {mon && <button className={'btn ' + (live ? 'danger' : 'primary')} onClick={() => setLive(!live)}><Activity size={15} />{live ? 'Parar monitoramento' : 'Monitorar ao vivo'}</button>}
    <button className="btn" onClick={onClose}>Fechar</button></>}>
    {!h ? <Loading err={err} /> : <>
      {err && <div className="banner bad"><div className="grow">{err}</div></div>}
      <div className="sub" style={{ marginBottom: 12 }}>{vm.ip ? <span className="mono">{vm.ip}</span> : null}{h.sampled_at ? ` · medido ${new Date(h.sampled_at).toLocaleTimeString('pt-BR')}` : ''}{live ? ' · ao vivo (atualiza a cada 5 s, por até 5 min)' : ''}</div>
      {h.hint && <div className="banner"><div className="grow">{h.hint}</div></div>}
      {mon && h.cpu != null && <Meter label="Processador (CPU)" pct={h.cpu} desc={`${vm.cpu} vCPU`} hist={hist.cpu} />}
      {mon && h.mem != null && <Meter label="Memória" pct={h.mem} desc={ram(vm.ram_mb)} hist={hist.mem} />}
      {mon && (h.disks || []).map(d => <Meter key={d.mount} label={`Disco ${d.mount}`} pct={d.used_pct} />)}
      {!mon && <div className="sub">Estado informado pela nuvem: <b>{(ST[h.state] || [0, h.state])[1]}</b> · {vm.cpu} vCPU · {ram(vm.ram_mb)} · {vm.disk_gb || '—'} GB provisionados.</div>}
    </>}
  </Modal>
}

// Botoes de acao de uma maquina (ligar / reiniciar / desligar [/ forcar]), todos com confirmacao
function VmActions({ vm, busy, onAct, staff }) {
  const run = vm.state === 'RUNNING'; const off = ['STOPPED', 'SHUTOFF'].includes(vm.state); const b = busy === vm.uuid || (vm.reboot && ['parando', 'ligando'].includes(vm.reboot.phase))
  return <div className="vm-actions">
    {off && <button className="btn sm primary" disabled={b} onClick={() => onAct(vm, 'start', 'Ligar')}><Play />Ligar</button>}
    {run && <button className="btn sm" disabled={b} onClick={() => onAct(vm, 'reboot', 'Reiniciar')}><RotateCw />Reiniciar</button>}
    {run && <button className="btn sm danger" disabled={b} onClick={() => onAct(vm, 'stop', 'Desligar')}><Power />Desligar</button>}
    {run && staff && <button className="btn sm danger" disabled={b} title="Desligamento forçado (equivale a puxar o cabo de energia)" aria-label="Desligar à força" onClick={() => onAct(vm, 'force-stop', 'Desligar à força')}><ShieldAlert /></button>}
    {!run && !off && <span className="sub">aguarde…</span>}</div>
}
const StateCell = ({ r }) => r.reboot && ['parando', 'ligando'].includes(r.reboot.phase) ? <Pill tone="warn">reiniciando ({r.reboot.phase})…</Pill> : r.reboot?.phase === 'erro' ? <Pill tone="bad">erro ao reiniciar</Pill> : <Pill tone={(ST[r.state] || ['mut'])[0]}>{(ST[r.state] || [0, r.state])[1]}</Pill>

// Maquinas da Cloud Orca de um cliente: estado, recursos, consumo do plano e ligar / desligar / reiniciar.
// `path`: GET da visao geral; `powerPath(uuid)`: POST das acoes.
export function CloudPanel({ path, powerPath, healthPath }) {
  const toast = useToast(); const [busy, setBusy] = useState(''); const [q, setQ] = useState(''); const [st, setSt] = useState(''); const [hv, setHv] = useState(null)
  const { data: d, err, reload } = useLoad(() => get(path), [path], 15000)
  if (!d) return <Loading err={err} />
  const act = async (v, action, label) => {
    if (!confirm(confirmText(v.name, action, label))) return
    setBusy(v.uuid)
    try { const r = await post(powerPath(v.uuid), { action }); toast(r.detail); setTimeout(() => reload(), 3000) } catch (e) { toast(e.message, true) } finally { setBusy('') }
  }
  const all = d.instances; const onl = all.filter(v => v.state === 'RUNNING')
  const rows = all.filter(v => (!q || (v.name + ' ' + (v.ip || '') + ' ' + (v.os || '')).toLowerCase().includes(q.toLowerCase())) && (!st || (st === 'on' ? v.state === 'RUNNING' : v.state !== 'RUNNING'))).sort((a, b) => (a.state === 'RUNNING') - (b.state === 'RUNNING') || a.name.localeCompare(b.name))
  return <>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat onClick={() => setSt('')} label="Máquinas" value={all.length} desc={`${onl.length} ligada(s) · ${all.length - onl.length} desligada(s)`} />
      <Stat onClick={() => setSt('on')} label="vCPUs ligadas" value={onl.reduce((a, v) => a + v.cpu, 0)} desc="das máquinas ligadas" />
      <Stat onClick={() => setSt('on')} label="Memória ligada" value={ram(onl.reduce((a, v) => a + v.ram_mb, 0))} desc="das máquinas ligadas" />
      <Stat onClick={() => setSt('')} label="Disco provisionado" value={`${all.reduce((a, v) => a + (v.disk_gb || 0), 0)} GB`} desc="soma dos discos" /></div>
    {d.quotas.length > 0 && <Card title="Consumo do plano (limites contratados)" style={{ marginBottom: 16 }}>
      <div className="grid g4">{d.quotas.map(x => { const p = x.max ? Math.min(100, Math.round(100 * x.used / x.max)) : 0
        return <div key={x.type}><div className="l" style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--mut)', fontWeight: 600 }}>{QL[x.type] || x.type}</div>
          <div style={{ fontWeight: 700, margin: '3px 0' }}>{qfmt(x, x.used)} de {qfmt(x, x.max)}</div><div className="progress"><i style={{ width: p + '%', background: p >= 100 ? 'var(--crit)' : p >= 85 ? 'var(--orange)' : undefined }} /></div></div> })}</div></Card>}
    <div className="bar"><div className="grow"><input placeholder="Buscar máquina, IP ou sistema…" value={q} onChange={e => setQ(e.target.value)} /></div>
      <select value={st} onChange={e => setSt(e.target.value)}><option value="">Todas as máquinas</option><option value="on">Ligadas</option><option value="off">Desligadas / com problema</option></select>
      <button className="btn sm" onClick={() => reload()} title="Atualizar agora"><RotateCw />Atualizar</button></div>
    <Card pad={false}><Table rows={rows} empty="Nenhuma máquina encontrada." cols={[
      { h: 'Estado', r: r => <StateCell r={r} /> },
      { h: 'Máquina', r: r => <><b>{r.name}</b><div className="sub">{r.os}</div></> }, { h: 'Recursos', r: r => `${r.cpu} vCPU · ${ram(r.ram_mb)} · ${r.disk_gb || '—'} GB`, cls: 'nw' },
      { h: 'Rede', r: r => <><span className="mono">{r.ip || '—'}</span><div className="sub">{r.network}</div></> }, { h: 'Zona', k: 'zone' },
      { h: 'Ações', cls: 'nw', r: r => <div className="vm-actions">{healthPath && r.state === 'RUNNING' && <button className="btn sm" title="Ver CPU, memória e disco" onClick={() => setHv(r)}><Activity size={15} />Saúde</button>}{d.can_run ? <VmActions vm={r} busy={busy} onAct={act} staff={d.staff} /> : <span className="sub">somente consulta</span>}</div> }]} /></Card>
    {hv && <VmHealth vm={hv} path={healthPath(hv.uuid)} onClose={() => setHv(null)} />}
    <p className="hint" style={{ marginTop: 8 }}>Atualizado automaticamente a cada 15 segundos. Máquinas desligadas pela NAVI não geram alerta; as desligadas por outros meios geram um incidente na categoria Cloud Orca.</p></>
}

// Frota inteira (Monitoramento): todas as maquinas de todos os clientes, com filtros e acoes
export function CloudFleet() {
  const toast = useToast(); const [busy, setBusy] = useState(''); const [q, setQ] = useState(''); const [st, setSt] = useState(''); const [cl, setCl] = useState(''); const [hv, setHv] = useState(null)
  const { data: d, err, reload } = useLoad(() => get('/cloud/vms'), [], 30000)
  if (!d) return <Loading err={err} />
  const act = async (v, action, label) => {
    if (!confirm(`Cliente: ${v.client}\n\n` + confirmText(v.name, action, label))) return
    setBusy(v.uuid)
    try { const r = await post(`/cloud/clients/${v.client_id}/instances/${v.uuid}/power`, { action }); toast(r.detail); setTimeout(() => reload(), 3000) } catch (e) { toast(e.message, true) } finally { setBusy('') }
  }
  const ign = async (v) => { try { await put(`/cloud/vms/${v.uuid}/ignore`, { ignored: !v.ignored }); toast(v.ignored ? 'Alertas reativados para a máquina' : 'Máquina ignorada: não gera mais alerta quando desligada'); reload() } catch (e) { toast(e.message, true) } }
  const clients = [...new Map(d.vms.map(v => [v.client_id, v.client])).entries()]
  const rows = d.vms.filter(v => (!cl || String(v.client_id) === cl) && (!st || (st === 'on' ? v.state === 'RUNNING' : v.state !== 'RUNNING')) && (!q || (v.name + ' ' + (v.client || '') + ' ' + (v.ip || '')).toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => (a.state === 'RUNNING') - (b.state === 'RUNNING') || (a.client || '').localeCompare(b.client || '') || a.name.localeCompare(b.name))
  const on = d.vms.filter(v => v.state === 'RUNNING').length; const bad = d.accounts.filter(a => a.last_error).length
  return <>
    {bad > 0 && <div className="banner bad"><div className="grow"><b>{bad} conta(s) da Cloud Orca sem acesso:</b> {d.accounts.filter(a => a.last_error).map(a => `${a.client} (${a.last_error.slice(0, 80)})`).join(' · ')}</div></div>}
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat onClick={() => { setSt(''); setCl('') }} label="Máquinas" value={d.vms.length} desc={`${clients.length} cliente(s) com Cloud Orca`} />
      <Stat onClick={() => setSt('on')} label="Ligadas" value={on} tone="ok" />
      <Stat onClick={() => setSt('off')} label="Desligadas / com problema" value={d.vms.length - on} tone={d.vms.length - on ? 'warn' : ''} />
      <Stat label="Contas vinculadas" value={d.accounts.length} desc={bad ? `${bad} com erro de acesso` : 'todas respondendo'} tone={bad ? 'bad' : ''} /></div>
    <div className="bar"><div className="grow"><input placeholder="Buscar máquina, cliente ou IP…" value={q} onChange={e => setQ(e.target.value)} /></div>
      <select value={cl} onChange={e => setCl(e.target.value)}><option value="">Todos os clientes</option>{clients.map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select>
      <select value={st} onChange={e => setSt(e.target.value)}><option value="">Todas</option><option value="on">Ligadas</option><option value="off">Desligadas / com problema</option></select></div>
    <Card pad={false}><Table rows={rows} empty="Nenhuma máquina encontrada. Vincule a conta Cloud Orca no cadastro do cliente." cols={[
      { h: 'Estado', r: r => <><Pill tone={(ST[r.state] || ['mut'])[0]}>{(ST[r.state] || [0, r.state])[1]}</Pill>{r.state !== 'RUNNING' && r.since && <div className="sub">{ago(r.since)}{r.expected_off ? ' · desligada pela NAVI' : r.ignored ? ' · ignorada' : r.linked_ignored ? ' · silenciada (ignorada em outra integração)' : ''}</div>}</> },
      { h: 'Cliente', r: r => <b>{r.client}</b> }, { h: 'Máquina', r: r => <>{r.name}<div className="sub">{r.os}</div></> }, { h: 'Recursos', r: r => `${r.cpu} vCPU · ${ram(r.ram_mb)} · ${r.disk_gb || '—'} GB`, cls: 'nw' },
      { h: 'IP', r: r => <span className="mono">{r.ip || '—'}</span>, cls: 'nw' }, { h: 'Zona', k: 'zone' },
      { h: 'Ações', cls: 'nw', r: r => <div className="vm-actions">{r.state === 'RUNNING' && <button className="btn sm" title="Ver CPU, memória e disco" onClick={() => setHv(r)}><Activity size={15} />Saúde</button>}{d.can_run && <VmActions vm={r} busy={busy} onAct={act} staff />}
        <button className="btn sm" title={r.ignored ? 'Voltar a alertar quando desligada' : 'Não alertar quando esta máquina estiver desligada'} aria-label={r.ignored ? 'Voltar a alertar' : 'Ignorar alertas desta máquina'} onClick={() => ign(r)}>{r.ignored ? <BellRing size={15} /> : <BellOff size={15} />}</button></div> }]} /></Card>
    {hv && <VmHealth vm={hv} path={`/cloud/clients/${hv.client_id}/instances/${hv.uuid}/health`} onClose={() => setHv(null)} />}</>
}

// Configuracao da chave de API da conta do cliente (cadastro do cliente)
export function CloudConfig({ clientId }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get(`/cloud/clients/${clientId}`), [clientId])
  const [k, setK] = useState(''); const [s, setS] = useState(''); const [busy, setBusy] = useState(false)
  if (!data) return <Loading />
  const save = async (enabled = data.enabled) => { setBusy(true); try { await put(`/cloud/clients/${clientId}`, { api_key: k || null, secret_key: s || null, enabled }); toast('Cloud Orca salva'); setK(''); setS(''); reload() } catch (e) { toast(e.message, true) } finally { setBusy(false) } }
  const unlink = async () => { if (!confirm('Desvincular a Cloud Orca deste cliente? As chaves guardadas serão apagadas.')) return; await del(`/cloud/clients/${clientId}`); toast('Desvinculada'); reload() }
  return <>
    <p className="sub" style={{ marginBottom: 12 }}>Vincula a <b>conta deste cliente na Cloud Orca</b>. Cada cliente tem a sua chave de API, gerada no portal da nuvem pelo usuário dele (ou por um usuário da conta dele): a própria nuvem garante que a chave só enxerga e controla as máquinas daquele cliente. Com isso o cliente passa a ver e controlar as máquinas no portal (ligar, desligar, reiniciar).</p>
    {data.linked && <div className="card" style={{ padding: '10px 14px', marginBottom: 14 }}>
      <div><b>{data.enabled ? '✔ Vinculada' : 'Vinculada (desativada)'}</b>{data.owner ? ` · conta ${data.owner}` : ''}</div>
      <div className="sub">{data.last_error ? <span style={{ color: 'var(--crit)' }}>Último erro: {data.last_error}</span> : data.last_ok ? 'Última consulta com sucesso: ' + new Date(data.last_ok).toLocaleString('pt-BR') : ''}</div></div>}
    <div className="row r2"><Field label="CHAVE DE API" hint={data.linked ? 'Já cadastrada — preencha só para trocar.' : 'Gerada no portal da nuvem.'}><input autoComplete="off" value={k} onChange={e => setK(e.target.value)} placeholder={data.linked ? '••••••••••••' : ''} /></Field>
      <Field label="CHAVE SECRETA" hint="O valor nunca é exibido depois de salvo."><input type="password" autoComplete="new-password" value={s} onChange={e => setS(e.target.value)} placeholder={data.linked ? '••••••••••••' : ''} /></Field></div>
    <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
      <button className="btn primary" disabled={busy || (!data.linked && !(k && s)) || (!!k !== !!s)} onClick={() => save()}>{busy ? 'Validando…' : data.linked && !k ? 'Salvar' : 'Validar e salvar'}</button>
      {data.linked && <button className="btn" onClick={() => save(!data.enabled)}>{data.enabled ? 'Desativar' : 'Ativar'}</button>}
      {data.linked && <button className="btn danger" onClick={unlink}>Desvincular</button>}</div>
    <p className="hint" style={{ marginTop: 10 }}>Se a nuvem recusar a chave, confira se a conta tem API habilitada e se o IP do servidor da NAVI está liberado na lista de IPs permitidos.</p></>
}
