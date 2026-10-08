import React, { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Building2, Radar, Activity, Search } from 'lucide-react'
import { get, fmtDT } from './api'
import { SevBadge } from './ui'

// Busca global (Ctrl+K): clientes, hosts e eventos
export default function Palette({ onClose }) {
  const [q, setQ] = useState(''); const [r, setR] = useState(null); const [i, setI] = useState(0); const nav = useNavigate(); const ref = useRef()
  useEffect(() => { ref.current && ref.current.focus() }, [])
  useEffect(() => {
    if (q.trim().length < 2) { setR(null); return }
    const t = setTimeout(() => get('/search?q=' + encodeURIComponent(q.trim())).then(x => { setR(x); setI(0) }).catch(() => {}), 220)
    return () => clearTimeout(t)
  }, [q])
  const items = r ? [
    ...r.clients.map(c => ({ k: 'c' + c.id, sec: 'Clientes', icon: <Building2 size={16} />, label: c.name, go: '/clientes/' + c.id })),
    ...r.hosts.map(h => ({ k: 'h' + h.hostid, sec: 'Hosts', icon: <Radar size={16} />, label: h.name, sub: h.ip, go: '/eventos?q=' + encodeURIComponent(h.name) })),
    ...r.events.map(e => ({ k: 'e' + e.id, sec: 'Eventos', icon: <Activity size={16} />, label: `${e.host} — ${e.trigger}`, sub: fmtDT(e.started_at), sev: e.severity, go: '/eventos?q=' + encodeURIComponent(e.host || '') })),
  ] : []
  const go = (it) => { onClose(); nav(it.go) }
  const key = (e) => {
    if (e.key === 'Escape') onClose()
    else if (e.key === 'ArrowDown') { e.preventDefault(); setI(Math.min(i + 1, items.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setI(Math.max(i - 1, 0)) }
    else if (e.key === 'Enter' && items[i]) go(items[i])
  }
  let last = ''
  return <div className="overlay" onMouseDown={e => e.target === e.currentTarget && onClose()}>
    <div className="palette">
      <input ref={ref} value={q} onChange={e => setQ(e.target.value)} onKeyDown={key} placeholder="Buscar cliente, host, IP ou problema…" />
      <div style={{ maxHeight: '55vh', overflow: 'auto', paddingBottom: 8 }}>
        {!r && <div className="empty" style={{ padding: 28 }}><Search size={22} style={{ opacity: .5 }} /><div>Digite ao menos 2 letras.</div></div>}
        {r && !items.length && <div className="empty" style={{ padding: 28 }}>Nada encontrado para “{q}”.</div>}
        {items.map((it, n) => { const h = it.sec !== last; last = it.sec
          return <React.Fragment key={it.k}>{h && <div className="sec">{it.sec}</div>}
            <div className={'it ' + (n === i ? 'on' : '')} onMouseEnter={() => setI(n)} onClick={() => go(it)}>{it.icon}{it.sev !== undefined && <SevBadge n={it.sev} />}
              <span className="trunc" style={{ maxWidth: 380 }}>{it.label}</span><span className="sub" style={{ marginLeft: 'auto' }}>{it.sub}</span></div></React.Fragment> })}
      </div>
      <div style={{ padding: '8px 22px', borderTop: '1px solid var(--line)', display: 'flex', gap: 14, fontSize: 12.5, color: 'var(--mut)' }}>
        <span><span className="kbd">↑↓</span> navegar</span><span><span className="kbd">Enter</span> abrir</span><span><span className="kbd">Esc</span> fechar</span></div>
    </div></div>
}
