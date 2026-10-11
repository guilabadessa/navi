import React, { useEffect, useState } from 'react'
import { Bell, KeyRound, UserRound } from 'lucide-react'
import { get, post, put, setCsrf } from '../api'
import { Card, Field, useToast } from '../ui'

const ROLES = { ADMIN: 'Administrador', GESTOR: 'Gestor', ANALISTA_NOC: 'Analista NOC', VISUALIZADOR: 'Visualizador', CLIENTE: 'Cliente' }
const rules = (p) => [['Pelo menos 10 caracteres', p.length >= 10], ['Letras e números', /[A-Za-z]/.test(p) && /\d/.test(p)]]

const b64 = (k) => Uint8Array.from(atob(k.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(k.length / 4) * 4, '=')), c => c.charCodeAt(0))
const native = () => !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform())
const PN = () => window.Capacitor.Plugins.PushNotifications
const FCM_KEY = 'navi_fcm_token'
const ls = { get: () => { try { return localStorage.getItem(FCM_KEY) } catch (_) { return null } }, set: (v) => { try { v ? localStorage.setItem(FCM_KEY, v) : localStorage.removeItem(FCM_KEY) } catch (_) {} } }
const pushOk = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

// Notificacoes push neste aparelho (incidentes Media ou superior)
function PushCard() {
  const toast = useToast()
  const [st, setSt] = useState('...'); const [busy, setBusy] = useState(false)
  const refresh = async () => {
    if (native()) return setSt(ls.get() ? 'on' : 'off')
    if (!pushOk()) return setSt('unsupported')
    if (Notification.permission === 'denied') return setSt('denied')
    const reg = await navigator.serviceWorker.getRegistration('/cliente/')
    setSt(reg && await reg.pushManager.getSubscription() ? 'on' : 'off')
  }
  useEffect(() => { refresh().catch(() => setSt('off')) }, [])
  const enable = async () => {
    setBusy(true)
    try {
      if (native()) {
        const p = PN(); const perm = await p.requestPermissions()
        if (perm.receive !== 'granted') { setSt('denied'); return }
        const token = await new Promise((ok, no) => {
          p.addListener('registration', t => ok(t.value)); p.addListener('registrationError', e => no(new Error(e.error || 'Falha ao registrar no Firebase')))
          p.register()
        })
        await post('/push/fcm', { token }); ls.set(token); setSt('on'); toast('Notificações ativadas neste aparelho')
        return
      }
      if (await Notification.requestPermission() !== 'granted') { setSt('denied'); return }
      const reg = await navigator.serviceWorker.ready
      const { key } = await get('/push/key')
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(key) })
      const j = sub.toJSON()
      await post('/push/subscribe', { endpoint: j.endpoint, p256dh: j.keys.p256dh, auth: j.keys.auth })
      setSt('on'); toast('Notificações ativadas neste aparelho')
    } catch (e) { toast(e.message, true) } finally { setBusy(false) }
  }
  const disable = async () => {
    setBusy(true)
    try {
      if (native()) { const t = ls.get(); if (t) await post('/push/unsubscribe', { endpoint: 'fcm:' + t }).catch(() => {}); ls.set(null); setSt('off'); toast('Notificações desativadas neste aparelho'); return }
      const reg = await navigator.serviceWorker.getRegistration('/cliente/'); const sub = reg && await reg.pushManager.getSubscription()
      if (sub) { await post('/push/unsubscribe', { endpoint: sub.endpoint }).catch(() => {}); await sub.unsubscribe() }
      setSt('off'); toast('Notificações desativadas neste aparelho')
    } catch (e) { toast(e.message, true) } finally { setBusy(false) }
  }
  const test = async () => { try { await post('/push/test'); toast('Teste enviado') } catch (e) { toast(e.message, true) } }
  const msg = { unsupported: 'Este navegador não suporta notificações. No Android use o Chrome; no iPhone, instale o app na tela inicial (iOS 16.4+).', denied: 'As notificações estão bloqueadas para este site. Libere nas configurações do navegador e volte aqui.' }[st]
  return <Card title="Notificações no aparelho" actions={<Bell size={18} />}>
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ fontSize: 13, color: 'var(--mut)' }}>Receba um aviso neste aparelho quando abrir um incidente de severidade Média ou superior (dentro do que o seu acesso permite).</div>
      {msg ? <div className="banner warn"><div className="grow">{msg}</div></div>
        : <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {st === 'on' ? <><button className="btn" disabled={busy} onClick={disable}>Desativar</button><button className="btn" onClick={test}>Enviar teste</button></>
            : <button className="btn primary" disabled={busy || st === '...'} onClick={enable}>{busy ? 'Ativando…' : 'Ativar notificações'}</button>}
        </div>}
    </div>
  </Card>
}

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
    <PushCard />
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
