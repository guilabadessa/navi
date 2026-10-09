import React, { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react'
import { SEV } from './api'
import { X } from 'lucide-react'

const ToastCtx = createContext(() => {})
export const useToast = () => useContext(ToastCtx)
export function ToastProvider({ children }) {
  const [t, setT] = useState(null)
  const show = useCallback((msg, err) => { setT({ msg, err }); setTimeout(() => setT(null), err ? 7000 : 3500) }, [])
  return <ToastCtx.Provider value={show}>{children}{t && <div className={'toast ' + (t.err ? 'err' : '')} role={t.err ? 'alert' : 'status'} aria-live={t.err ? 'assertive' : 'polite'}>{t.msg}</div>}</ToastCtx.Provider>
}

export const Card = ({ title, actions, children, pad = true, style }) => (
  <div className="card" style={style}>
    {(title || actions) && <div className="hd"><h3>{title}</h3><div style={{ display: 'flex', gap: 8 }}>{actions}</div></div>}
    {pad ? <div className="bd">{children}</div> : children}
  </div>)

// Cartao de indicador. Com `onClick`, o cartao inteiro e clicavel (teclado incluido) e leva para o detalhe.
export const Stat = ({ label, value, desc, tone, onClick }) => (
  <div className={'card stat ' + (tone || '') + (onClick ? ' cardlink' : '')} {...(onClick ? { role: 'button', tabIndex: 0, onClick, onKeyDown: e => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onClick(e)) } : {})}>
    <div className="l">{label}</div><div className="v">{value}</div>{desc && <div className="d">{desc}</div>}</div>)

// Periodos dos filtros (valor em dias; 1 hora = 1/24)
export const PERIODS = [['0.0417', 'Última hora'], ['1', 'Últimas 24h'], ['7', 'Últimos 7 dias'], ['30', 'Últimos 30 dias'], ['90', 'Últimos 90 dias']]
export const periodLabel = (d) => (PERIODS.find(([v]) => Math.abs(+v - +d) < 0.01) || [0, `Últimos ${d} dias`])[1]

export const SevBadge = ({ n }) => <span className={'badge sev' + n}>{SEV[n] ?? n}</span>
// Etiquetas dos servicos do cliente (infraestrutura / backup / estacoes)
export const ServiceChips = ({ s }) => { const x = [['infra', 'Infra'], ['backup', 'Backup'], ['endpoint', 'Endpoints']].filter(([k]) => s && s[k]); return x.length ? <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>{x.map(([k, l]) => <span key={k} className="badge b-info">{l}</span>)}</span> : <span className="badge b-mut">Sem serviços</span> }
export const Pill = ({ tone = 'mut', children }) => <span className={'badge b-' + tone}>{children}</span>
export const StatusBadge = ({ s }) => s === 'PROBLEM' ? <Pill tone="bad"><i className="dot live" style={{ background: '#bd1723' }} />EM ABERTO</Pill> : <Pill tone="ok">RESOLVIDO</Pill>

export function Field({ label, hint, children }) {
  // associa o rotulo ao campo (leitores de tela) quando o filho e um input/select/textarea
  const id = useId(); const only = React.Children.count(children) === 1 ? React.Children.toArray(children)[0] : null
  const native = only && typeof only.type === 'string' && ['input', 'select', 'textarea'].includes(only.type)
  return <div><label className="f" htmlFor={native ? id : undefined}>{label}</label>
    {native ? React.cloneElement(only, { id: only.props.id || id, 'aria-describedby': hint ? id + '-h' : undefined }) : children}
    {hint && <div className="hint" id={id + '-h'}>{hint}</div>}</div>
}
export const Check = ({ label, checked, onChange }) => <label className="check"><input type="checkbox" checked={!!checked} onChange={e => onChange(e.target.checked)} />{label}</label>

export function Modal({ title, onClose, children, footer, wide }) {
  const ref = useRef(null); const tid = useId()
  useEffect(() => {
    const prev = document.activeElement
    ref.current?.focus()
    const h = e => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => { window.removeEventListener('keydown', h); if (prev && prev.focus) prev.focus() }  // devolve o foco a quem abriu
  }, [onClose])
  return <div className="overlay" onMouseDown={e => e.target === e.currentTarget && onClose()}>
    <div className={'modal ' + (wide ? 'wide' : '')} role="dialog" aria-modal="true" aria-labelledby={tid} tabIndex={-1} ref={ref}>
      <div className="hd"><h2 id={tid} style={{ fontSize: 20 }}>{title}</h2><button className="btn sm" onClick={onClose} aria-label="Fechar"><X /></button></div>
      <div className="bd">{children}</div>{footer && <div className="ft">{footer}</div>}</div></div>
}
export function Drawer({ title, onClose, children }) {
  return <><div className="overlay" style={{ padding: 0, zIndex: 29 }} onMouseDown={onClose} />
    <div className="drawer" role="dialog" aria-modal="true" aria-label={title}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}><h2>{title}</h2><button className="btn sm" onClick={onClose} aria-label="Fechar"><X /></button></div>{children}</div></>
}
export const Tabs = ({ tabs, value, onChange }) => <div className="tabs" role="tablist">{tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={value === k} className={value === k ? 'on' : ''} onClick={() => onChange(k)}>{l}</button>)}</div>

export function Table({ cols, rows, onRow, empty = 'Nenhum registro encontrado.' }) {
  if (!rows || !rows.length) return <div className="empty">{empty}</div>
  return <div className="tbl-wrap"><table className="tbl"><thead><tr>{cols.map((c, i) => <th key={i} scope="col" style={c.w ? { width: c.w } : null}>{c.h}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={r.id ?? r.hostid ?? r.client_id ?? i} className={onRow ? 'click' : ''} onClick={() => onRow && onRow(r)} tabIndex={onRow ? 0 : undefined} onKeyDown={onRow ? (e => { if (e.key === 'Enter' && e.target === e.currentTarget) onRow(r) }) : undefined}>
      {cols.map((c, j) => <td key={j} className={c.cls}>{c.r ? c.r(r) : r[c.k]}</td>)}</tr>)}</tbody></table></div>
}
export function Pager({ page, size, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / size))
  return <div style={{ display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'flex-end', padding: '12px 4px 0' }}>
    <span className="sub">{total} registro(s)</span>
    <button className="btn sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹</button>
    <span className="mono">{page} / {pages}</span>
    <button className="btn sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>›</button></div>
}
export const PageHead = ({ title, desc, badges, children }) => <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, marginBottom: 20, flexWrap: 'wrap' }}>
  <div><h1 style={{ fontSize: 26 }}>{title}</h1>{badges && <div style={{ margin: '4px 0' }}>{badges}</div>}{desc && <p className="sub">{desc}</p>}</div><div style={{ display: 'flex', gap: 10 }}>{children}</div></div>

export function useLoad(fn, deps = [], interval) {
  const [data, setData] = useState(null); const [err, setErr] = useState(null); const [loading, setLoading] = useState(true)
  const run = useCallback(async () => { try { setData(await fn()); setErr(null) } catch (e) { setErr(e.message) } finally { setLoading(false) } }, deps) // eslint-disable-line
  useEffect(() => { setLoading(true); run(); if (interval) { const t = setInterval(run, interval); return () => clearInterval(t) } }, [run, interval])
  return { data, err, loading, reload: run, setData }
}
export const Loading = ({ err }) => err ? <div className="empty" style={{ color: 'var(--crit)' }}>{err}</div> : <div className="empty">Carregando…</div>

// multi-select simples com busca (host groups/hosts)
export function MultiPick({ options, value, onChange, placeholder = 'Buscar…' }) {
  const [q, setQ] = useState('')
  const sel = new Set(value || [])
  const list = options.filter(o => !q || o.label.toLowerCase().includes(q.toLowerCase())).slice(0, 80)
  const toggle = (v) => { const s = new Set(sel); s.has(v) ? s.delete(v) : s.add(v); onChange([...s]) }
  const byv = Object.fromEntries(options.map(o => [o.value, o.label]))
  return <div>
    <div style={{ marginBottom: 8 }}>{[...sel].map(v => <span className="chip" key={v} style={{ cursor: 'pointer' }} onClick={() => toggle(v)}>{byv[v] || v} ✕</span>)}</div>
    <input placeholder={placeholder} value={q} onChange={e => setQ(e.target.value)} />
    <div style={{ maxHeight: 190, overflow: 'auto', border: '1px solid var(--line)', borderRadius: 10, marginTop: 6 }}>
      {list.map(o => <label key={o.value} className="check" style={{ padding: '7px 12px', borderBottom: '1px solid #f0f2f9' }}><input type="checkbox" checked={sel.has(o.value)} onChange={() => toggle(o.value)} />{o.label}{o.sub && <span className="sub" style={{ marginLeft: 'auto' }}>{o.sub}</span>}</label>)}
      {!list.length && <div className="empty" style={{ padding: 14 }}>Sem resultados</div>}</div></div>
}


// Categorias de incidente (origem do evento)
export const KIND = { infra: 'Infraestrutura', backup: 'Backup', endpoint: 'Endpoints' }
export const KindPill = ({ k }) => <span className={'badge b-' + ({ infra: 'info', backup: 'ok', endpoint: 'mut' }[k || 'infra'])}>{KIND[k || 'infra'] || k}</span>

// Tempo decorrido em tempo real (incidente em aberto): "2h 14min 05s", atualizado a cada segundo
const _fmt = (s) => { s = Math.max(0, Math.floor(s)); const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), x = s % 60
  return (d ? d + 'd ' : '') + (d || h ? h + 'h ' : '') + (m || d || h ? String(m).padStart(m || d || h ? 2 : 1, '0') + 'min ' : '') + String(x).padStart(2, '0') + 's' }
export function LiveDur({ since }) {
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(n => n + 1), 1000); return () => clearInterval(t) }, [])
  return <b className="mono" style={{ color: 'var(--crit, #bd1723)' }} title="Em andamento — contando em tempo real">{_fmt((Date.now() - new Date(since).getTime()) / 1000)}</b>
}
