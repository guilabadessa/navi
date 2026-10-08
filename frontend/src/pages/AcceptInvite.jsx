import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Eye, EyeOff, CheckCircle2, XCircle } from 'lucide-react'
import { get, post } from '../api'

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
  return <div className="login"><div className="art">
    <img src="/cliente/brand/branco.png" alt="Orca TI" style={{ height: 44, alignSelf: 'flex-start' }} />
    <div><h1>NAVI</h1><div className="tag">Navegação, Orientação e Assistência</div><p>Defina sua senha para ativar o acesso à plataforma.</p></div>
    <div style={{ fontSize: 13, color: '#8fa8ee' }}>© {new Date().getFullYear()} Orca TI</div></div>
    <div className="form"><div className="box">
      {!info && !err && <p className="sub">Validando convite…</p>}
      {err && !info && <><h2>Link inválido</h2><div className="errbox" style={{ marginTop: 16 }}>{err}</div><button className="btn" onClick={() => nav('/')}>Ir para o login</button></>}
      {info && <form onSubmit={submit}>
        <h2>{info.pending ? 'Bem-vindo(a)!' : 'Redefinir senha'}</h2>
        <p className="sub" style={{ marginBottom: 20 }}>Olá, <b>{info.name}</b>. Crie uma senha para <b>{info.email}</b>.</p>
        <div className="row"><div><label className="f">NOVA SENHA</label><div className="pwd"><input type={show ? 'text' : 'password'} autoFocus required value={pw} onChange={e => setPw(e.target.value)} autoComplete="new-password" style={{ paddingRight: 44 }} />
          <button type="button" onClick={() => setShow(!show)}>{show ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></div></div>
        <div className="row"><div><label className="f">CONFIRMAR SENHA</label><input type={show ? 'text' : 'password'} required value={pw2} onChange={e => setPw2(e.target.value)} autoComplete="new-password" /></div></div>
        <div style={{ marginBottom: 16, fontSize: 13.5 }}>{[...rules(pw), ['As senhas coincidem', pw.length > 0 && pw === pw2]].map(([t, v]) =>
          <div key={t} style={{ display: 'flex', gap: 8, alignItems: 'center', color: v ? 'var(--ok)' : 'var(--mut)' }}>{v ? <CheckCircle2 size={15} /> : <XCircle size={15} />}{t}</div>)}</div>
        {err && <div className="errbox">{err}</div>}
        <button className="btn primary" style={{ width: '100%', justifyContent: 'center', padding: 13, fontSize: 16 }} disabled={busy || !ok}>{busy ? 'Salvando…' : 'Definir senha e entrar'}</button>
      </form>}
    </div></div></div>
}
