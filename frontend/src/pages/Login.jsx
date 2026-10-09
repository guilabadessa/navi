import React, { useState } from 'react'
import { AlertTriangle, ArrowLeft, CheckCircle2, Eye, EyeOff, Lock, Mail, ShieldCheck } from 'lucide-react'
import { post } from '../api'
import AuthShell from '../auth/AuthShell'

const wait = (ms) => new Promise(r => setTimeout(r, ms))

export default function Login({ onLogin }) {
  const [email, setEmail] = useState(''); const [password, setPassword] = useState('')
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false); const [done, setDone] = useState(false)
  const [show, setShow] = useState(false); const [caps, setCaps] = useState(false); const [forgot, setForgot] = useState(false); const [sent, setSent] = useState(false); const [shake, setShake] = useState(0)
  const fail = (x) => { setErr(x.message || 'Não foi possível concluir. Tente novamente.'); setShake(n => n + 1) }
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { const me = await post('/auth/login', { email: email.trim(), password }); setDone(true); await wait(550); onLogin(me) } catch (x) { fail(x); setBusy(false) }
  }
  const sendForgot = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { await post('/auth/forgot', { email: email.trim() }); setSent(true) } catch (x) { fail(x) } finally { setBusy(false) }
  }
  const back = (e) => { e.preventDefault(); setForgot(false); setSent(false); setErr('') }
  const Err = () => err ? <div className="lg-err" role="alert"><AlertTriangle size={16} />{err}</div> : null
  const Emailf = <div className="lg-field"><label htmlFor="lg-email">E-MAIL</label><div className="lg-input"><Mail className="lead" />
    <input id="lg-email" type="email" autoFocus required value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" placeholder="nome@empresa.com.br" /></div></div>
  return <AuthShell>
    <div key={shake}>{forgot ? <form onSubmit={sendForgot}>
      <img src="/cliente/brand/branco.png" alt="Orca TI" className="lg-brand" />
      <h2>Redefinir senha</h2><p className="lg-sub">Informe seu e-mail. Se ele estiver cadastrado, você receberá um link para criar uma nova senha.</p>
      {sent ? <div className="lg-ok"><CheckCircle2 size={18} /><div>Pronto! Se o e-mail existir, o link foi enviado. Verifique sua caixa de entrada (e o spam).</div></div> : <>
        {Emailf}<Err />
        <button className="lg-btn" disabled={busy}>{busy ? <><i className="lg-spin" />Enviando…</> : 'Enviar link'}</button></>}
      <div className="lg-center"><button type="button" className="lg-link" onClick={back}><ArrowLeft size={14} style={{ verticalAlign: -2 }} /> Voltar ao login</button></div>
    </form> : <form onSubmit={submit}>
      <img src="/cliente/brand/branco.png" alt="Orca TI" className="lg-brand" />
      <div className="lg-kicker">Acesso restrito</div><h2>Bem-vindo(a) de volta</h2>
      <p className="lg-sub">Equipe Orca e clientes entram por aqui. No primeiro acesso, use o link do convite enviado por e-mail.</p>
      {Emailf}
      <div className="lg-field"><label htmlFor="lg-pw">SENHA</label><div className="lg-input pw"><Lock className="lead" />
        <input id="lg-pw" type={show ? 'text' : 'password'} required value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" placeholder="Sua senha"
          onKeyUp={e => setCaps(!!(e.getModifierState && e.getModifierState('CapsLock')))} />
        <button type="button" className="eye" aria-label={show ? 'Ocultar senha' : 'Mostrar senha'} onClick={() => setShow(!show)}>{show ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
        {caps && <div className="lg-warn">Caps Lock está ativado</div>}</div>
      <Err />
      <button className={'lg-btn' + (done ? ' done' : '')} disabled={busy || done}>{done ? <><CheckCircle2 size={19} />Acesso confirmado</> : busy ? <><i className="lg-spin" />Entrando…</> : 'Entrar'}</button>
      <div className="lg-center"><button type="button" className="lg-link" onClick={() => { setForgot(true); setErr('') }}>Esqueci minha senha</button></div>
      <div className="lg-secure"><ShieldCheck size={13} />Conexão segura · sessão protegida</div>
    </form>}</div>
  </AuthShell>
}
