import React, { useState } from 'react'
import { BarChart3, Bell, Building2, ClipboardCheck, Eye, EyeOff, Gauge, HardDrive, Lock, Receipt, ShieldCheck } from 'lucide-react'
import { post } from '../api'

const CAPS = [
  [Gauge, 'Monitoramento 24x7', 'Hosts, links e serviços de todos os clientes em tempo real.'],
  [BarChart3, 'SLA e relatórios executivos', 'Disponibilidade realizada versus contratada, em PDF.'],
  [Bell, 'Alertas inteligentes', 'WhatsApp e e-mail por cliente, severidade e horário.'],
  [HardDrive, 'Backup e estações', 'Acronis e FortiClient EMS integrados ao mesmo painel.'],
  [Building2, 'Portal do cliente', 'Cada cliente acompanha apenas o seu ambiente.'],
  [Receipt, 'Financeiro integrado', 'Boletos e notas fiscais do mês, direto do faturamento.'],
]
const TRUST = [[ShieldCheck, 'Sessões protegidas'], [Lock, 'Credenciais criptografadas'], [ClipboardCheck, 'Trilha de auditoria']]

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
      <img src="/cliente/brand/branco.png" alt="Orca TI" style={{ height: 46, alignSelf: 'flex-start' }} />
      <div className="hero">
        <div className="eyebrow">Centro de operações de TI</div>
        <h1>NAVI</h1>
        <div className="tag">Inteligência operacional Orca TI</div>
        <p>Do incidente ao faturamento: toda a operação de TI dos seus clientes, com visibilidade em tempo real e relatórios prontos para a decisão.</p>
        <div className="caps">{CAPS.map(([I, t, d]) => <div className="cap" key={t}><I /><div><b>{t}</b><span>{d}</span></div></div>)}</div>
      </div>
      <div>
        <div className="trust">{TRUST.map(([I, t]) => <span key={t}><I size={15} />{t}</span>)}</div>
        <div style={{ fontSize: 13, color: '#8fa8ee', marginTop: 14 }}>© {new Date().getFullYear()} Orca TI · Operação de TI e Infraestrutura</div>
      </div>
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
        <div className="eyebrow dark">Acesso restrito</div><h2>Bem-vindo(a) de volta</h2><p className="sub" style={{ marginBottom: 22 }}>Entre com seu e-mail e senha. No primeiro acesso, use o link do convite que você recebeu por e-mail.</p>
        <div className="row"><div><label className="f">E-MAIL</label>
          <input type="email" autoFocus required value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" placeholder="nome@empresa.com.br" /></div></div>
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
      <div className="foot">Precisa de ajuda com o acesso? Fale com a equipe da Orca TI.</div>
    </div></div>
}
