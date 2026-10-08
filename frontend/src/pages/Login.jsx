import React, { useState } from 'react'
import { post } from '../api'

export default function Login({ onLogin }) {
  const [email, setEmail] = useState(''); const [password, setPassword] = useState('')
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { onLogin(await post('/auth/login', { email, password })) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  return <div className="login">
    <div className="art">
      <img src="/navi/brand/branco.png" alt="Orca TI" style={{ height: 44, alignSelf: 'flex-start' }} />
      <div><h1>NAVI</h1><p>Navegação, Orientação e Assistência</p>
        <p style={{ fontSize: 15, opacity: .8 }}>Centro de inteligência do NOC Orca TI — monitoramento, incidentes, SLA, relatórios e comunicação operacional em um só lugar.</p></div>
      <div style={{ fontSize: 13, color: '#8fa8ee' }}>© Orca TI · Operação de TI e Infraestrutura</div>
    </div>
    <div className="form"><form onSubmit={submit}>
      <img src="/navi/brand/azul.png" alt="" style={{ height: 34, marginBottom: 26 }} />
      <h2 style={{ fontSize: 28 }}>Acessar a plataforma</h2><p className="sub" style={{ marginBottom: 24 }}>Entre com suas credenciais Orca TI.</p>
      <div className="row"><div><label className="f">E-MAIL</label><input type="email" autoFocus required value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" /></div></div>
      <div className="row"><div><label className="f">SENHA</label><input type="password" required value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" /></div></div>
      {err && <div style={{ color: 'var(--crit)', marginBottom: 12, fontWeight: 600 }}>{err}</div>}
      <button className="btn primary" style={{ width: '100%', justifyContent: 'center', padding: 13 }} disabled={busy}>{busy ? 'Entrando…' : 'Entrar'}</button>
    </form></div></div>
}
