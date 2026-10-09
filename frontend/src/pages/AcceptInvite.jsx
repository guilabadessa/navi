import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Circle, Eye, EyeOff, Lock } from 'lucide-react'
import { get, post } from '../api'
import AuthShell from '../auth/AuthShell'

const rules = (p) => [['Mínimo de 10 caracteres', p.length >= 10], ['Letras maiúsculas e minúsculas', /[a-z]/.test(p) && /[A-Z]/.test(p)], ['Pelo menos um número', /\d/.test(p)]]

export default function AcceptInvite({ onLogin }) {
  const { token } = useParams(); const nav = useNavigate()
  const [info, setInfo] = useState(null); const [err, setErr] = useState(''); const [pw, setPw] = useState(''); const [pw2, setPw2] = useState('')
  const [show, setShow] = useState(false); const [busy, setBusy] = useState(false)
  useEffect(() => { get('/auth/invite/' + token).then(setInfo).catch(e => setErr(e.message)) }, [token])
  const ok = rules(pw).every(r => r[1]) && pw === pw2
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { onLogin(await post('/auth/accept-invite', { token, password: pw })); nav('/', { replace: true }) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  return <AuthShell>
    <img src="/cliente/brand/branco.png" alt="Orca TI" className="lg-brand" />
    {!info && !err && <p className="lg-sub"><i className="lg-spin" style={{ display: 'inline-block', verticalAlign: -4, marginRight: 8, borderColor: '#c5cde3', borderTopColor: '#1e73f8' }} />Validando convite…</p>}
    {err && !info && <><h2>Link inválido</h2><div className="lg-err" role="alert" style={{ marginTop: 14 }}><AlertTriangle size={16} />{err}</div><button className="lg-btn" onClick={() => nav('/')}>Ir para o login</button></>}
    {info && <form onSubmit={submit}>
      <div className="lg-kicker">{info.pending ? 'Primeiro acesso' : 'Nova senha'}</div>
      <h2>{info.pending ? 'Bem-vindo(a)!' : 'Redefinir senha'}</h2>
      <p className="lg-sub">Olá, <b>{info.name}</b>. Crie uma senha para <b>{info.email}</b>.</p>
      <div className="lg-field"><label htmlFor="lg-n1">NOVA SENHA</label><div className="lg-input pw"><Lock className="lead" />
        <input id="lg-n1" type={show ? 'text' : 'password'} autoFocus required value={pw} onChange={e => setPw(e.target.value)} autoComplete="new-password" />
        <button type="button" className="eye" aria-label={show ? 'Ocultar senha' : 'Mostrar senha'} onClick={() => setShow(!show)}>{show ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></div>
      <div className="lg-field"><label htmlFor="lg-n2">CONFIRMAR SENHA</label><div className="lg-input"><Lock className="lead" />
        <input id="lg-n2" type={show ? 'text' : 'password'} required value={pw2} onChange={e => setPw2(e.target.value)} autoComplete="new-password" /></div></div>
      <div className="lg-rules">{[...rules(pw), ['As senhas coincidem', pw.length > 0 && pw === pw2]].map(([t, v]) => <div key={t} className={v ? 'ok' : ''}>{v ? <CheckCircle2 size={15} /> : <Circle size={15} />}{t}</div>)}</div>
      {err && <div className="lg-err" role="alert"><AlertTriangle size={16} />{err}</div>}
      <button className="lg-btn" disabled={busy || !ok}>{busy ? <><i className="lg-spin" />Salvando…</> : 'Definir senha e entrar'}</button>
    </form>}
  </AuthShell>
}
