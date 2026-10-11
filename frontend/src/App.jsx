import React, { createContext, useContext, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Activity, Globe, BarChart3, Bell, Building2, ClipboardList, FileText, LayoutDashboard, LogOut, Mail, MessageCircle, Radar,
  HardDrive, Menu, Search, UserRound, Settings as Cog, ShieldCheck, Sparkles, Sun, Moon, Timer, Tv, Users as UsersIcon } from 'lucide-react'
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
import { WhatsApp, Email } from './pages/Channels'
import NaviIA from './pages/NaviIA'
import { UsersPage, AuditPage } from './pages/Admin'
import Settings from './pages/Settings'
import Palette from './Palette'
import Portal from './pages/Portal'
import Account from './pages/Account'
import AppUpdate from './pages/AppUpdate'
import PortalSwitch from './pages/PortalSwitch'
import NaviGuide, { STAFF_ASKS, STAFF_TIPS } from './pages/NaviGuide'
import Protection from './pages/Protection'
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
  ['/protecao', 'Backup e Endpoints', HardDrive, 'monitoring.view'],
  ['/portal', 'Portal do cliente', Globe, 'clients.view'],
  ['/alertas', 'Alertas', Bell, 'alerts.view'],
  ['/relatorios', 'Relatórios', FileText, 'reports.view'],
  ['/rotinas', 'Rotinas', Timer, 'routines.view'],
  ['/whatsapp', 'WhatsApp', MessageCircle, 'whatsapp.view'],
  ['/email', 'E-mail', Mail, 'email.view'],
  ['/navi-ia', 'NAVI IA', Sparkles, 'navi.use'],
  ['/usuarios', 'Usuários', UsersIcon, 'users.manage'],
  ['/auditoria', 'Auditoria', ClipboardList, 'audit.view'],
  ['/configuracoes', 'Configurações', Cog, 'settings.view'],
]

// Integracoes: nada na barra quando tudo esta bem; so aparece a que estiver com problema (o detalhe completo fica em Configuracoes)
const INTEGRATIONS = [['zabbix', 'Zabbix'], ['evolution', 'Evolution'], ['email', 'E-mail'], ['acronis', 'Acronis'], ['acronis_us', 'Acronis EUA'], ['ems', 'EMS'], ['cloud', 'Cloud Orca'], ['contaazul', 'Conta Azul'], ['navi', 'NAVI']]
function StatusPills() {
  const [st, setSt] = useState({})
  useEffect(() => { const f = () => get('/settings/status').then(setSt).catch(() => {}); f(); const t = setInterval(f, 30000); return () => clearInterval(t) }, [])
  const bad = INTEGRATIONS.filter(([k]) => st[k] && st[k].ok === false)
  if (!bad.length) return null
  return <div className="pills">{bad.map(([k, label]) => <div key={k} className="pill bad" role="status" title={st[k].detail || 'com problema'}><i />{label}</div>)}</div>
}

function Shell({ me, onLogout, reloadMe }) {
  const loc = useLocation(); const navTo = useNavigate(); const [menu, setMenu] = useState(false); const [pal, setPal] = useState(false); const [theme, setTheme] = useState(getTheme()); const [tv, setTv] = useState(getTv())
  useEffect(() => { const h = e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPal(p => !p) } }; window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h) }, [])
  const cur = loc.pathname === '/conta' ? ['/conta', 'Minha conta'] : NAV.find(([p]) => p === '/' ? loc.pathname === '/' : loc.pathname.startsWith(p))
  useEffect(() => { if (me.must_change_password && loc.pathname !== '/conta') navTo('/conta') }, [me.must_change_password, loc.pathname])
  const allowed = new Set(NAV.filter(([, , , p]) => can(me, p)).map(([to]) => to))
  const tips = Object.fromEntries(Object.entries(STAFF_TIPS).filter(([k]) => allowed.has(k)))
  const here = Object.keys(tips).filter(k => k === '/' ? loc.pathname === '/' : loc.pathname.startsWith(k)).sort((a, b) => b.length - a.length)[0]
  return <div className="app">
    <a href="#conteudo" className="skip">Pular para o conteúdo</a>
    {menu && <div className="scrim" onClick={() => setMenu(false)} />}
    <aside className={'side' + (menu ? ' open' : '')} onClick={e => e.target.closest('a') && setMenu(false)}>
      <div className="brand"><img src="/cliente/brand/simbolo_branco.png" alt="Orca TI" /><div><div className="t">NAVI</div><div className="s">Inteligência operacional<br />Orca TI</div></div></div>
      <nav className="nav">{NAV.filter(([, , , p]) => can(me, p)).map(([to, label, Icon]) =>
        <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => isActive ? 'active' : ''}><Icon />{label}</NavLink>)}</nav>
      <div className="me"><b>{me.name}</b><span>{me.role.replace('_', ' ')}</span>
        <div style={{ marginTop: 8, display: 'flex', gap: 14 }}><NavLink to="/conta" style={{ color: '#9db6ff', display: 'inline-flex', gap: 6, alignItems: 'center' }}><UserRound size={15} />Minha conta</NavLink><a href="#" style={{ color: '#9db6ff', display: 'inline-flex', gap: 6, alignItems: 'center' }} onClick={e => { e.preventDefault(); onLogout() }}><LogOut size={15} />Sair</a></div></div>
    </aside>
    <div className="main" id="conteudo">
      <div className="top"><div className="tleft" style={{ display: 'flex', alignItems: 'center', gap: 10 }}><button className="iconbtn menu-btn" aria-label="Abrir menu" onClick={() => setMenu(true)}><Menu /></button><h1>{cur ? cur[1] : 'NAVI'}</h1></div>
        <div className="topr">
          <button className="searchbtn" onClick={() => setPal(true)}><Search size={16} />Buscar… <span className="kbd" style={{ marginLeft: 'auto' }}>Ctrl K</span></button>
          <button className="iconbtn" aria-label="Modo NOC (tela cheia)" title={tv ? 'Sair do modo NOC (tela cheia)' : 'Modo NOC (esconde o menu)'} onClick={() => { tvMode(!tv); setTv(!tv) }}><Tv /></button>
          <button className="iconbtn" aria-label="Alternar tema claro ou escuro" title="Alternar tema claro/escuro" onClick={() => setTheme(toggleTheme())}>{theme === 'dark' ? <Sun /> : <Moon />}</button>
          <StatusPills /></div></div>
      {pal && <Palette onClose={() => setPal(false)} />}
      <div className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/clientes" element={<Clients />} />
          <Route path="/clientes/:id" element={<ClientDetail />} />
          <Route path="/monitoramento" element={<Monitoring />} />
          <Route path="/eventos" element={<Events key={loc.search} />} />
          <Route path="/protecao" element={<Protection />} />
          <Route path="/portal" element={<PortalSwitch />} />
          <Route path="/alertas" element={<Alerts />} />
          <Route path="/relatorios" element={<Reports />} />
          <Route path="/rotinas" element={<Routines />} />
          <Route path="/whatsapp" element={<WhatsApp />} />
          <Route path="/email" element={<Email />} />
          <Route path="/navi-ia" element={<NaviIA />} />
          <Route path="/usuarios" element={<UsersPage />} />
          <Route path="/auditoria" element={<AuditPage />} />
          <Route path="/configuracoes" element={<Settings />} />
          <Route path="/conta" element={<Account me={me} onChanged={reloadMe} />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </div>
    </div>
    <NaviGuide scope="staff" tips={tips} current={here} asks={STAFF_ASKS} go={navTo} tour={Object.keys(tips)} userKey={me.id} name={me.name} />
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
  if (me.role === 'CLIENTE') return <Auth.Provider value={me}><AppUpdate /><Portal me={me} onLogout={logout} reloadMe={load} /></Auth.Provider>
  return <Auth.Provider value={me}><AppUpdate /><Shell me={me} onLogout={logout} reloadMe={load} /></Auth.Provider>
}
