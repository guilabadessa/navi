import React, { useState } from 'react'
import { Eye, EyeOff, Gauge, MessageCircle, FileText, ShieldCheck, Lock } from 'lucide-react'
import { post } from '../api'

const FEATS = [
  [Gauge, 'Monitoramento em tempo real', 'Incidentes, links e disponibilidade de todos os clientes, direto do Zabbix.'],
  [MessageCircle, 'Alertas inteligentes', 'WhatsApp e e-mail com regras por cliente, host e severidade.'],
  [FileText, 'Relatórios e SLA', 'PDFs executivos e técnicos, gerados e enviados de forma automática.'],
  [ShieldCheck, 'Segurança e auditoria', 'Acesso por perfil, sessão protegida e trilha de todas as ações.'],
]

export default function Login({ onLogin }) {
  const [email, setEmail] = useState(''); const [password, setPassword] = useState('')
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false); const [show, setShow] = useState(false); const [caps, setCaps] = useState(false); const [forgot, setForgot] = useState(false); const [sent, setSent] = useState(false)
  const dark = document.documentElement.dataset.theme === 'dark'
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { onLogin(await post('/auth/login', { email: email.trim(), password })) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  const sendForgot = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { await post('/auth/forgot', { email: email.trim() }); setSent(true) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  return <div className="login">
    <div className="art">
      <img src="/cliente/brand/branco.png" alt="Orca TI" style={{ height: 44, alignSelf: 'flex-start' }} />
      <div>
        <h1>NAVI</h1>
        <div className="tag">Navegação, Orientação e Assistência</div>
        <p>O centro de inteligência do NOC Orca TI: monitoramento, incidentes, SLA, relatórios e comunicação operacional em um só lugar.</p>
        <div className="feats">{FEATS.map(([I, t, d]) => <div className="feat" key={t}><I /><div><b>{t}</b><span>{d}</span></div></div>)}</div>
      </div>
      <div style={{ fontSize: 13, color: '#8fa8ee' }}>© {new Date().getFullYear()} Orca TI · Operação de TI e Infraestrutura</div>
    </div>
    <div className="form">
      <div className="box">{forgot ? <form onSubmit={sendForgot}>
        <img src={dark ? '/cliente/brand/branco.png' : '/cliente/brand/azul.png'} alt="Orca TI" style={{ height: 34, marginBottom: 24 }} />
        <h2>Redefinir senha</h2><p className="sub" style={{ marginBottom: 22 }}>Informe seu e-mail. Se ele estiver cadastrado, você receberá um link para criar uma nova senha.</p>
        {sent ? <div className="banner info" style={{ marginBottom: 16 }}><div className="grow">Pronto! Se o e-mail existir, o link foi enviado. Verifique sua caixa de entrada (e o spam).</div></div> : <>
          <div className="row"><div><label className="f">E-MAIL</label><input type="email" autoFocus required value={email} onChange={e => setEmail(e.target.value)} /></div></div>
          {err && <div className="errbox" role="alert">{err}</div>}
          <button className="btn primary" style={{ width: '100%', justifyContent: 'center', padding: 13, fontSize: 16 }} disabled={busy}>{busy ? 'Enviando…' : 'Enviar link'}</button></>}
        <div style={{ textAlign: 'center', marginTop: 16 }}><a href="#" onClick={e => { e.preventDefault(); setForgot(false); setSent(false); setErr('') }}>← Voltar ao login</a></div>
      </form> : <form onSubmit={submit}>
        <img src={dark ? '/cliente/brand/branco.png' : '/cliente/brand/azul.png'} alt="Orca TI" style={{ height: 34, marginBottom: 24 }} />
        <h2>Acessar a plataforma</h2><p className="sub" style={{ marginBottom: 22 }}>Entre com as credenciais fornecidas pela Orca TI.</p>
        <div className="row"><div><label className="f">E-MAIL</label>
          <input type="email" autoFocus required value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" placeholder="voce@orcati.com.br" /></div></div>
        <div className="row"><div><label className="f">SENHA</label>
          <div className="pwd"><input type={show ? 'text' : 'password'} required value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password"
            onKeyUp={e => setCaps(e.getModifierState && e.getModifierState('CapsLock'))} style={{ paddingRight: 44 }} />
            <button type="button" title={show ? 'Ocultar senha' : 'Mostrar senha'} onClick={() => setShow(!show)}>{show ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
          {caps && <div className="caps">Caps Lock está ativado</div>}</div></div>
        {err && <div className="errbox" role="alert">{err}</div>}
        <button className="btn primary" style={{ width: '100%', justifyContent: 'center', padding: 13, fontSize: 16 }} disabled={busy}>{busy ? 'Entrando…' : 'Entrar'}</button>
        <div style={{ textAlign: 'center', marginTop: 14 }}><a href="#" onClick={e => { e.preventDefault(); setForgot(true); setErr('') }}>Esqueci minha senha</a></div>
        <div className="hint" style={{ display: 'flex', gap: 6, alignItems: 'center', justifyContent: 'center', marginTop: 12 }}><Lock size={13} />Conexão segura</div>
      </form>}</div>
      <div className="foot">NAVI · Plataforma de inteligência operacional</div>
    </div></div>
}
