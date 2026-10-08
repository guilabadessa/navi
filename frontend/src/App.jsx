import React, { createContext, useContext, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Activity, BarChart3, Bell, Building2, ClipboardList, FileText, LayoutDashboard, LogOut, Mail, MessageCircle, Radar,
  Search, Settings as Cog, ShieldCheck, Sparkles, Sun, Moon, Timer, Tv, Users as UsersIcon } from 'lucide-react'
import { get, post, setCsrf } from './api'
import { useToast } from './ui'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import { Clients, ClientDetail } from './pages/Clients'
import Monitoring from './pages/Monitoring'
import Events from './pages/Events'
import Alerts from './pages/Alerts'
import Reports from './pages/Reports'
import Routines from './pages/Routines'
import SLA from './pages/SLA'
import { WhatsApp, Email } from './pages/Channels'
import NaviIA from './pages/NaviIA'
import { UsersPage, AuditPage } from './pages/Admin'
import Settings from './pages/Settings'
import Palette from './Palette'
import Portal from './pages/Portal'
import AcceptInvite from './pages/AcceptInvite'
import { getTheme, toggleTheme, getTv, tvMode } from './theme'

const Auth = createContext(null)
export const useAuth = () => useContext(Auth)
export const can = (me, p) => me && (me.perms.includes('*') || me.perms.includes(p))

const NAV = [
  ['/', 'Dashboard', LayoutDashboard, 'dashboard.view'],
  ['/clientes', 'Clientes', Building2, 'clients.view'],
  ['/monitoramento', 'Monitoramento', Radar, 'monitoring.view'],
  ['/eventos', 'Eventos', Activity, 'events.view'],
  ['/alertas', 'Alertas', Bell, 'alerts.view'],
  ['/relatorios', 'Relatórios', FileText, 'reports.view'],
  ['/rotinas', 'Rotinas', Timer, 'routines.view'],
  ['/sla', 'SLA', BarChart3, 'sla.view'],
  ['/whatsapp', 'WhatsApp', MessageCircle, 'whatsapp.view'],
  ['/email', 'E-mail', Mail, 'email.view'],
  ['/navi-ia', 'NAVI IA', Sparkles, 'navi.use'],
  ['/usuarios', 'Usuários', UsersIcon, 'users.manage'],
  ['/auditoria', 'Auditoria', ClipboardList, 'audit.view'],
  ['/configuracoes', 'Configurações', Cog, 'settings.view'],
]

function StatusPills() {
  const [st, setSt] = useState({})
  useEffect(() => { const f = () => get('/settings/status').then(setSt).catch(() => {}); f(); const t = setInterval(f, 30000); return () => clearInterval(t) }, [])
  const P = ({ k, label }) => <div className={'pill ' + (st[k] ? (st[k].ok ? 'ok' : 'bad') : '')} title={st[k]?.detail || 'sem verificação ainda'}><i />{label}</div>
  return <div className="pills"><P k="zabbix" label="Zabbix" /><P k="evolution" label="Evolution" /><P k="email" label="E-mail" /><P k="navi" label="NAVI" /></div>
}

function Shell({ me, onLogout }) {
  const loc = useLocation(); const [pal, setPal] = useState(false); const [theme, setTheme] = useState(getTheme()); const [tv, setTv] = useState(getTv())
  useEffect(() => { const h = e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPal(p => !p) } }; window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h) }, [])
  const cur = NAV.find(([p]) => p === '/' ? loc.pathname === '/' : loc.pathname.startsWith(p))
  return <div className="app">
    <aside className="side">
      <div className="brand"><img src="/navi/brand/simbolo_branco.png" alt="" /><div><div className="t">NAVI</div><div className="s">Navegação, Orientação<br />e Assistência</div></div></div>
      <nav className="nav">{NAV.filter(([, , , p]) => can(me, p)).map(([to, label, Icon]) =>
        <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => isActive ? 'active' : ''}><Icon />{label}</NavLink>)}</nav>
      <div className="me"><b>{me.name}</b><span>{me.role.replace('_', ' ')}</span>
        <div style={{ marginTop: 8 }}><a href="#" style={{ color: '#9db6ff', display: 'inline-flex', gap: 6, alignItems: 'center' }} onClick={e => { e.preventDefault(); onLogout() }}><LogOut size={15} />Sair</a></div></div>
    </aside>
    <div className="main">
      <div className="top"><h1>{cur ? cur[1] : 'NAVI'}</h1>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <button className="searchbtn" onClick={() => setPal(true)}><Search size={16} />Buscar… <span className="kbd" style={{ marginLeft: 'auto' }}>Ctrl K</span></button>
          <StatusPills />
          <button className="iconbtn" title={tv ? 'Sair do modo NOC (tela cheia)' : 'Modo NOC (esconde o menu)'} onClick={() => { tvMode(!tv); setTv(!tv) }}><Tv /></button>
          <button className="iconbtn" title="Alternar tema claro/escuro" onClick={() => setTheme(toggleTheme())}>{theme === 'dark' ? <Sun /> : <Moon />}</button></div></div>
      {pal && <Palette onClose={() => setPal(false)} />}
      <div className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/clientes" element={<Clients />} />
          <Route path="/clientes/:id" element={<ClientDetail />} />
          <Route path="/monitoramento" element={<Monitoring />} />
          <Route path="/eventos" element={<Events key={loc.search} />} />
          <Route path="/alertas" element={<Alerts />} />
          <Route path="/relatorios" element={<Reports />} />
          <Route path="/rotinas" element={<Routines />} />
          <Route path="/sla" element={<SLA />} />
          <Route path="/whatsapp" element={<WhatsApp />} />
          <Route path="/email" element={<Email />} />
          <Route path="/navi-ia" element={<NaviIA />} />
          <Route path="/usuarios" element={<UsersPage />} />
          <Route path="/auditoria" element={<AuditPage />} />
          <Route path="/configuracoes" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </div>
    </div>
  </div>
}

export default function App() {
  const [me, setMe] = useState(undefined)
  const nav = useNavigate(); const toast = useToast()
  const load = () => get('/auth/me').then(m => { setCsrf(m.csrf); setMe(m) }).catch(() => setMe(null))
  useEffect(() => { load(); const h = () => setMe(null); window.addEventListener('navi:unauth', h); return () => window.removeEventListener('navi:unauth', h) }, [])
  const logout = async () => { await post('/auth/logout').catch(() => {}); setMe(null); nav('/') }
  const loc = useLocation()
  const onLogin = m => { setCsrf(m.csrf); setMe(m) }
  if (loc.pathname.startsWith('/convite/')) return <Routes><Route path="/convite/:token" element={<AcceptInvite onLogin={onLogin} />} /></Routes>
  if (me === undefined) return null
  if (!me) return <Login onLogin={onLogin} />
  if (me.role === 'CLIENTE') return <Auth.Provider value={me}><Portal me={me} onLogout={logout} /></Auth.Provider>
  return <Auth.Provider value={me}><Shell me={me} onLogout={logout} /></Auth.Provider>
}
