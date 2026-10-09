import React, { useState } from 'react'
import { KeyRound, UserRound } from 'lucide-react'
import { post, put, setCsrf } from '../api'
import { Card, Field, useToast } from '../ui'

const ROLES = { ADMIN: 'Administrador', GESTOR: 'Gestor', ANALISTA_NOC: 'Analista NOC', VISUALIZADOR: 'Visualizador', CLIENTE: 'Cliente' }
const rules = (p) => [['Pelo menos 10 caracteres', p.length >= 10], ['Letras e números', /[A-Za-z]/.test(p) && /\d/.test(p)]]

// Minha conta: dados do usuario e troca de senha (staff e portal do cliente)
export default function Account({ me, onChanged }) {
  const toast = useToast()
  const [name, setName] = useState(me.name); const [savingName, setSavingName] = useState(false)
  const [cur, setCur] = useState(''); const [nw, setNw] = useState(''); const [cf, setCf] = useState(''); const [busy, setBusy] = useState(false)
  const r = rules(nw); const okPw = cur && r.every(x => x[1]) && nw === cf && nw !== cur

  const saveName = async () => {
    setSavingName(true)
    try { await put('/auth/profile', { name }); toast('Dados atualizados'); onChanged && onChanged() } catch (e) { toast(e.message, true) } finally { setSavingName(false) }
  }
  const changePw = async () => {
    setBusy(true)
    try {
      const x = await post('/auth/change-password', { current_password: cur, new_password: nw })
      setCsrf(x.csrf); setCur(''); setNw(''); setCf('')
      toast('Senha alterada. Os outros acessos desta conta foram encerrados.'); onChanged && onChanged()
    } catch (e) { toast(e.message, true) } finally { setBusy(false) }
  }

  return <div className="grid g2" style={{ alignItems: 'start' }}>
    {me.must_change_password && <div className="banner warn" style={{ gridColumn: '1 / -1' }}><KeyRound size={20} /><div className="grow"><b>Defina uma nova senha para continuar.</b> Sua senha atual é provisória.</div></div>}
    <Card title="Meus dados" actions={<UserRound size={18} />}>
      <div style={{ display: 'grid', gap: 12 }}>
        <Field label="Nome"><input value={name} onChange={e => setName(e.target.value)} maxLength={255} /></Field>
        <Field label="E-mail de acesso" hint="Para alterar o e-mail, fale com o administrador."><input value={me.email} disabled /></Field>
        <Field label="Perfil"><input value={ROLES[me.role] || me.role} disabled /></Field>
        <div><button className="btn primary" disabled={savingName || name.trim().length < 2 || name === me.name} onClick={saveName}>{savingName ? 'Salvando…' : 'Salvar dados'}</button></div>
      </div>
    </Card>
    <Card title="Alterar senha" actions={<KeyRound size={18} />}>
      <form style={{ display: 'grid', gap: 12 }} onSubmit={e => { e.preventDefault(); okPw && !busy && changePw() }}>
        <input type="text" autoComplete="username" value={me.email} readOnly hidden />
        <Field label="Senha atual"><input type="password" autoComplete="current-password" value={cur} onChange={e => setCur(e.target.value)} /></Field>
        <Field label="Nova senha"><input type="password" autoComplete="new-password" value={nw} onChange={e => setNw(e.target.value)} /></Field>
        <Field label="Confirmar nova senha"><input type="password" autoComplete="new-password" value={cf} onChange={e => setCf(e.target.value)} /></Field>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: 'var(--mut)' }}>
          {r.map(([t, ok]) => <li key={t} style={{ color: ok ? 'var(--ok, #12803b)' : undefined }}>{ok ? '✓' : '•'} {t}</li>)}
          <li style={{ color: nw && nw === cf ? 'var(--ok, #12803b)' : undefined }}>{nw && nw === cf ? '✓' : '•'} Confirmação igual à nova senha</li>
        </ul>
        <div><button type="submit" className="btn primary" disabled={!okPw || busy}>{busy ? 'Alterando…' : 'Alterar senha'}</button></div>
        <div style={{ fontSize: 12, color: 'var(--mut)' }}>Ao trocar a senha, os demais acessos desta conta (outros navegadores) são encerrados por segurança.</div>
      </form>
    </Card>
  </div>
}
