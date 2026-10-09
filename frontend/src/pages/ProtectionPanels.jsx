import React, { useState } from 'react'
import { Play } from 'lucide-react'
import { post, fmtDT } from '../api'
import { Card, Pill, Stat, Table, useToast } from '../ui'

const ago = (v) => { if (!v) return '—'; const h = (Date.now() - new Date(v).getTime()) / 36e5; return h < 1 ? 'há ' + Math.max(1, Math.round(h * 60)) + ' min' : h < 48 ? 'há ' + Math.round(h) + ' h' : 'há ' + Math.round(h / 24) + ' d' }
const BST = { ok: ['ok', 'protegido'], falha: ['bad', 'com falha'], 'sem backup': ['bad', 'sem backup recente'], offline: ['warn', 'agente offline'], 'sem dados': ['mut', 'sem dados'] }
const EST = { online: 'ok', offline: 'mut', 'sem contato': 'bad', 'antivírus off': 'bad', quarentena: 'bad', assinaturas: 'warn', atenção: 'warn' }

// Servicos contratados no Acronis, agrupados por tecnologia (Backup, Seguranca/EDR, Gerenciamento/RMM, DLP...)
export function ServicesCard({ services, detail = false }) {
  if (!services || !services.length) return null
  const groups = {}; services.forEach(s => { (groups[s.group] = groups[s.group] || []).push(s) })
  return <Card title="Tecnologias habilitadas (Acronis)" style={{ marginBottom: 16 }}>
    <div className="grid g3">{Object.entries(groups).map(([g, items]) => <div key={g}><div className="l" style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--mut)', fontWeight: 600, marginBottom: 6 }}>{g}</div>
      {items.map(s => <div key={s.label} style={{ fontSize: 13.5, padding: '3px 0' }}><b>{s.label}</b>{detail && s.unit !== 'bytes' && <div className="sub">{`${s.used}${s.quota != null ? ' de ' + s.quota : ''} em uso`}</div>}</div>)}</div>)}</div></Card>
}

// Backup: filtros por situacao e tipo; botao "Executar backup agora" (quando habilitado e permitido)
export function BackupPanel({ data, reload, runPath }) {
  const toast = useToast(); const [st, setSt] = useState(''); const [ty, setTy] = useState(''); const [q, setQ] = useState(''); const [busy, setBusy] = useState(0)
  const items = data.backups || []
  const types = [...new Set(items.map(i => i.type_label))]
  const rows = items.filter(i => (!st || i.status === st) && (!ty || i.type_label === ty) && (!q || i.name.toLowerCase().includes(q.toLowerCase())))
  const c = k => items.filter(i => i.status === k).length
  const run = async (r) => {
    if (!confirm(`Executar agora o plano de backup de “${r.name}”?\n\nO Acronis iniciará o backup imediatamente.`)) return
    setBusy(r.id)
    try { const x = await post(runPath ? runPath(r) : `/protection/assets/${r.id}/run-backup`); toast(x.detail); reload && reload() } catch (e) { toast(e.message, true) } finally { setBusy(0) }
  }
  return <>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat onClick={() => setSt('')} label="Itens" value={items.length} /><Stat onClick={() => setSt('ok')} label="Protegidos" value={c('ok')} tone="ok" />
      <Stat onClick={() => setSt(c('falha') ? 'falha' : 'sem backup')} label="Com falha / atraso" value={c('falha') + c('sem backup')} tone={c('falha') + c('sem backup') ? 'bad' : ''} /><Stat onClick={() => setSt('offline')} label="Agente offline" value={c('offline')} tone={c('offline') ? 'warn' : ''} /></div>
    <div className="bar"><div className="grow"><input placeholder="Buscar item…" value={q} onChange={e => setQ(e.target.value)} /></div>
      <select value={st} onChange={e => setSt(e.target.value)}><option value="">Todas as situações</option>{Object.entries(BST).map(([k, v]) => <option key={k} value={k}>{v[1]}</option>)}</select>
      <select value={ty} onChange={e => setTy(e.target.value)}><option value="">Todos os tipos</option>{types.map(t => <option key={t}>{t}</option>)}</select></div>
    <Card pad={false}><Table rows={rows} empty="Nenhum item encontrado." cols={[
      { h: 'Situação', r: r => <Pill tone={(BST[r.status] || ['mut'])[0]}>{(BST[r.status] || [0, r.status])[1]}</Pill> }, { h: 'Item', r: r => <b>{r.name}</b> }, { h: 'Tipo', k: 'type_label' },
      { h: 'Plano', r: r => <span className="sub">{r.policy || '—'}</span> }, { h: 'Último sucesso', r: r => <span title={fmtDT(r.last_success_at)}>{ago(r.last_success_at)}</span> },
      { h: 'Última falha', r: r => r.last_failure_at ? <span title={fmtDT(r.last_failure_at)}>{ago(r.last_failure_at)}</span> : '—' },
      { h: '', r: r => r.can_run && <button className="btn sm" disabled={busy === r.id} title="Executar o plano de backup agora" onClick={() => run(r)}><Play />{busy === r.id ? 'Solicitando…' : 'Executar agora'}</button> }]} /></Card></>
}

// Endpoints: EMS e/ou protecao do Acronis; filtros por origem, tecnologia e situacao
export function EndpointsPanel({ data }) {
  const [src, setSrc] = useState(''); const [tech, setTech] = useState(''); const [st, setSt] = useState(''); const [q, setQ] = useState('')
  const items = data.endpoints || []
  const sources = [...new Set(items.map(i => i.source))]; const techs = [...new Set(items.flatMap(i => i.techs))]
  const rows = items.filter(i => (!src || i.source === src) && (!tech || i.techs.includes(tech)) && (!st || i.status === st) && (!q || (i.name + ' ' + (i.user || '')).toLowerCase().includes(q.toLowerCase())))
  const bad = items.filter(i => !i.ok).length
  return <>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat onClick={() => setSt('')} label="Endpoints" value={items.length} /><Stat onClick={() => setSt('online')} label="Online agora" value={items.filter(i => i.status === 'online').length} tone="ok" />
      <Stat onClick={() => setSt(items.find(i => !i.ok)?.status || '')} label="Com pendência" value={bad} tone={bad ? 'bad' : 'ok'} desc="sem contato, antivírus desligado, assinaturas" /><Stat onClick={() => setSrc('')} label="Origens" value={sources.length} desc={sources.join(' · ') || '—'} /></div>
    <div className="bar"><div className="grow"><input placeholder="Buscar endpoint ou usuário…" value={q} onChange={e => setQ(e.target.value)} /></div>
      {sources.length > 1 && <select value={src} onChange={e => setSrc(e.target.value)}><option value="">Todas as origens</option>{sources.map(s => <option key={s}>{s}</option>)}</select>}
      {techs.length > 1 && <select value={tech} onChange={e => setTech(e.target.value)}><option value="">Todas as tecnologias</option>{techs.map(s => <option key={s}>{s}</option>)}</select>}
      <select value={st} onChange={e => setSt(e.target.value)}><option value="">Todas as situações</option>{Object.keys(EST).map(k => <option key={k}>{k}</option>)}</select></div>
    <Card pad={false}><Table rows={rows} empty="Nenhum endpoint encontrado." cols={[
      { h: 'Situação', r: r => <Pill tone={EST[r.status] || 'mut'}>{r.status}</Pill> }, { h: 'Endpoint', r: r => <b>{r.name}</b> }, { h: 'Usuário / host', r: r => r.user || '—' },
      { h: 'Origem', r: r => <Pill tone="info">{r.source}</Pill> }, { h: 'Proteção', r: r => <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>{r.techs.map(t => <span key={t} className="badge b-info">{t}</span>)}</span> },
      { h: 'Último contato', r: r => r.last ? <span title={fmtDT(r.last)}>{ago(r.last)}</span> : '—' }]} /></Card></>
}
