import React, { useState } from 'react'
import { Play, Power, RotateCw, ShieldAlert } from 'lucide-react'
import { get, post, put, del } from '../api'
import { Card, Field, Loading, Pill, Stat, Table, useLoad, useToast } from '../ui'

const ST = { RUNNING: ['ok', 'ligada'], STOPPED: ['mut', 'desligada'], SHUTOFF: ['mut', 'desligada'], STARTING: ['warn', 'ligando'], STOPPING: ['warn', 'desligando'], ERROR: ['bad', 'com erro'], DESTROYED: ['mut', 'removida'] }
const QL = { Instance: 'Máquinas', IP: 'IPs públicos', Volume: 'Discos', Snapshot: 'Snapshots', CPU: 'vCPUs', Memory: 'Memória', 'Primary Storage': 'Armazenamento', Network: 'Redes' }
const ram = (mb) => mb >= 1024 ? `${(mb / 1024).toFixed(mb % 1024 ? 1 : 0).replace('.', ',')} GB` : `${mb} MB`

// Maquinas da Nuvem Orca de um cliente: estado, recursos, consumo da cota e ligar / desligar / reiniciar.
// `path`: GET da visao geral; `powerPath(uuid)`: POST das acoes; `staff`: libera desligamento forcado.
export function CloudPanel({ path, powerPath, staff }) {
  const toast = useToast(); const [busy, setBusy] = useState('')
  const { data: d, err, reload } = useLoad(() => get(path), [path], 15000)
  if (!d) return <Loading err={err} />
  const act = async (v, action, label) => {
    if (!confirm(`${label} a máquina “${v.name}”?${action === 'stop' || action === 'reboot' || action === 'force-stop' ? '\n\nOs usuários conectados serão desconectados e serviços da máquina ficarão indisponíveis.' : ''}`)) return
    setBusy(v.uuid)
    try { const r = await post(powerPath(v.uuid), { action }); toast(r.detail); setTimeout(() => reload(), 3000) } catch (e) { toast(e.message, true) } finally { setBusy('') }
  }
  const on = d.instances.filter(v => v.state === 'RUNNING').length
  return <>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat label="Máquinas" value={d.instances.length} desc={`${on} ligada(s) · ${d.instances.length - on} desligada(s)`} />
      <Stat label="vCPUs em uso" value={d.instances.filter(v => v.state === 'RUNNING').reduce((a, v) => a + v.cpu, 0)} desc="das máquinas ligadas" />
      <Stat label="Memória em uso" value={ram(d.instances.filter(v => v.state === 'RUNNING').reduce((a, v) => a + v.ram_mb, 0))} desc="das máquinas ligadas" />
      <Stat label="Disco provisionado" value={`${d.instances.reduce((a, v) => a + (v.disk_gb || 0), 0)} GB`} desc="soma dos discos" /></div>
    {d.quotas.length > 0 && <Card title="Consumo do plano (limites contratados)" style={{ marginBottom: 16 }}>
      <div className="grid g4">{d.quotas.map(q => { const p = q.max ? Math.min(100, Math.round(100 * q.used / q.max)) : 0
        return <div key={q.type}><div className="l" style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--mut)', fontWeight: 600 }}>{QL[q.type] || q.type}</div>
          <div style={{ fontWeight: 700, margin: '3px 0' }}>{q.type === 'Memory' ? `${ram(q.used)} de ${ram(q.max)}` : `${q.used} de ${q.max}`}</div><div className="progress"><i style={{ width: p + '%', background: p >= 100 ? 'var(--crit)' : p >= 85 ? 'var(--orange)' : undefined }} /></div></div> })}</div></Card>}
    <Card pad={false}><Table rows={d.instances} empty="Nenhuma máquina encontrada na conta." cols={[
      { h: 'Estado', r: r => r.reboot && ['parando', 'ligando'].includes(r.reboot.phase) ? <Pill tone="warn">reiniciando ({r.reboot.phase})…</Pill> : r.reboot?.phase === 'erro' ? <Pill tone="bad" >erro ao reiniciar</Pill> : <Pill tone={(ST[r.state] || ['mut'])[0]}>{(ST[r.state] || [0, r.state])[1]}</Pill> },
      { h: 'Máquina', r: r => <><b>{r.name}</b><div className="sub">{r.os}</div></> }, { h: 'Recursos', r: r => `${r.cpu} vCPU · ${ram(r.ram_mb)} · ${r.disk_gb || '—'} GB` },
      { h: 'Rede', r: r => <><span className="mono">{r.ip || '—'}</span><div className="sub">{r.network}</div></> }, { h: 'Zona', k: 'zone' },
      { h: 'Ações', r: r => { const run = r.state === 'RUNNING'; const off = ['STOPPED', 'SHUTOFF'].includes(r.state); const b = busy === r.uuid || (r.reboot && ['parando', 'ligando'].includes(r.reboot.phase))
        return d.can_run ? <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {off && <button className="btn sm" disabled={b} onClick={() => act(r, 'start', 'Ligar')}><Play />Ligar</button>}
          {run && <button className="btn sm" disabled={b} onClick={() => act(r, 'reboot', 'Reiniciar')}><RotateCw />Reiniciar</button>}
          {run && <button className="btn sm danger" disabled={b} onClick={() => act(r, 'stop', 'Desligar')}><Power />Desligar</button>}
          {run && staff && <button className="btn sm danger" disabled={b} title="Desligamento forçado (equivale a puxar o cabo)" onClick={() => act(r, 'force-stop', 'Desligar à força')}><ShieldAlert />Forçar</button>}</div> : <span className="sub">somente consulta</span> } }]} /></Card></>
}

// Configuracao da chave de API da conta do cliente (cadastro do cliente)
export function CloudConfig({ clientId }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get(`/cloud/clients/${clientId}`), [clientId])
  const [k, setK] = useState(''); const [s, setS] = useState(''); const [busy, setBusy] = useState(false)
  if (!data) return <Loading />
  const save = async (enabled = data.enabled) => { setBusy(true); try { await put(`/cloud/clients/${clientId}`, { api_key: k || null, secret_key: s || null, enabled }); toast('Nuvem Orca salva'); setK(''); setS(''); reload() } catch (e) { toast(e.message, true) } finally { setBusy(false) } }
  const unlink = async () => { if (!confirm('Desvincular a Nuvem Orca deste cliente? As chaves guardadas serão apagadas.')) return; await del(`/cloud/clients/${clientId}`); toast('Desvinculada'); reload() }
  return <>
    <p className="sub" style={{ marginBottom: 12 }}>Vincula a <b>conta deste cliente na Nuvem Orca</b>. Cada cliente tem a sua chave de API, gerada no portal da nuvem pelo usuário dele (ou por um usuário da conta dele): a própria nuvem garante que a chave só enxerga e controla as máquinas daquele cliente. Com isso o cliente passa a ver e controlar as máquinas no portal (ligar, desligar, reiniciar).</p>
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
