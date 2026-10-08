import React, { useState } from 'react'
import { FlaskConical, RefreshCw } from 'lucide-react'
import { get, post, put } from '../api'
import { Card, Check, Field, Loading, useLoad, useToast } from '../ui'

export default function ProtectionConfig({ section }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/protection/config'), []); const [x, setX] = useState(null); const [busy, setBusy] = useState('')
  React.useEffect(() => { if (data && !x) setX({ ...data, acronis_secret: '', ems_password: '' }) }, [data]) // eslint-disable-line
  if (!x) return <Loading />
  const set = (k, v) => setX({ ...x, [k]: v })
  const save = async () => { try { await put('/protection/config', { ...x, acronis_secret: x.acronis_secret || null, ems_password: x.ems_password || null, ems_offline_days: +x.ems_offline_days, stale_h: +x.stale_h, offline_min: +x.offline_min, ems_port: +x.ems_port }); toast('Configuração salva'); setX(null); reload() } catch (e) { toast(e.message, true) } }
  const test = async (s) => { setBusy(s); try { const r = await post('/protection/test/' + s); toast(r.detail, !r.ok) } catch (e) { toast(e.message, true) } finally { setBusy('') } }
  const syncEms = async () => { setBusy('syncems'); try { const r = await post('/protection/sync/ems'); toast(`Sincronizado · ${r.endpoints} endpoints · ${r.new} novo(s) problema(s) · ${r.resolved} resolvido(s)`) } catch (e) { toast(e.message, true) } finally { setBusy('') } }
  const sync = async () => { setBusy('sync'); try { const r = await post('/protection/sync/acronis'); toast(`Sincronizado · ${r.assets} itens · ${r.new} novo(s) problema(s) · ${r.resolved} resolvido(s)`) } catch (e) { toast(e.message, true) } finally { setBusy('') } }
  return <div style={{ display: 'grid', gap: 16 }}>
    {section === 'acronis' && <Card title="Acronis Cyber Protect Cloud" actions={<><button className="btn sm" disabled={!!busy} onClick={() => test('acronis')}><FlaskConical />{busy === 'acronis' ? 'Testando…' : 'Testar conexão'}</button><button className="btn sm" disabled={!!busy} onClick={sync}><RefreshCw />{busy === 'sync' ? 'Sincronizando…' : 'Sincronizar agora'}</button></>}>
      <Check label="Monitorar o Acronis" checked={x.acronis_enabled} onChange={v => set('acronis_enabled', v)} />
      <div className="row r3" style={{ marginTop: 12 }}><Field label="URL DO DATACENTER"><input value={x.acronis_url} onChange={e => set('acronis_url', e.target.value)} /></Field>
        <Field label="ID DO CLIENTE (API)"><input value={x.acronis_client_id} onChange={e => set('acronis_client_id', e.target.value)} /></Field>
        <Field label="SEGREDO" hint={x.acronis_secret_set ? 'Já configurado — deixe em branco para manter.' : 'Obrigatório.'}><input type="password" autoComplete="new-password" value={x.acronis_secret} onChange={e => set('acronis_secret', e.target.value)} placeholder={x.acronis_secret_set ? '••••••••' : ''} /></Field></div>
      <div className="row r2"><Field label="ALERTAR SE NÃO HOUVER BACKUP COM SUCESSO HÁ (HORAS)" hint="Use um valor maior que o intervalo dos seus planos (ex.: 72h para planos diários)."><input type="number" min="1" value={x.stale_h} onChange={e => set('stale_h', e.target.value)} /></Field>
        <Field label="ALERTAR AGENTE OFFLINE APÓS (MINUTOS)"><input type="number" min="5" value={x.offline_min} onChange={e => set('offline_min', e.target.value)} /></Field></div>
      <p className="hint">Recomendação de segurança: use no Acronis um usuário de API com perfil <b>somente leitura</b>. A NAVI só faz consultas (GET).</p></Card>}
    {section === 'ems' && <Card title="FortiClient EMS (endpoints)" actions={<><button className="btn sm" disabled={!!busy} onClick={() => test('ems')}><FlaskConical />{busy === 'ems' ? 'Testando…' : 'Testar conexão'}</button><button className="btn sm" disabled={!!busy} onClick={syncEms}><RefreshCw />{busy === 'syncems' ? 'Sincronizando…' : 'Sincronizar agora'}</button></>}>
      {x.ems_blocked && <div className="banner bad"><div className="grow">O EMS recusou o login anterior. Informe a senha correta, salve e teste.</div></div>}
      <Check label="Monitorar o EMS" checked={x.ems_enabled} onChange={v => set('ems_enabled', v)} />
      <div className="row r3" style={{ marginTop: 12 }}><Field label="ENDEREÇO (IP OU DNS)"><input value={x.ems_host} onChange={e => set('ems_host', e.target.value)} placeholder="172.16.31.205" /></Field>
        <Field label="PORTA HTTPS"><input type="number" value={x.ems_port} onChange={e => set('ems_port', e.target.value)} /></Field>
        <Field label="ALERTAR SEM CONTATO APÓS (DIAS)"><input type="number" min="1" value={x.ems_offline_days} onChange={e => set('ems_offline_days', e.target.value)} /></Field></div>
      <div className="row r2"><Field label="USUÁRIO" hint="Use um usuário somente leitura do EMS."><input value={x.ems_user || ''} onChange={e => set('ems_user', e.target.value)} /></Field>
        <Field label="SENHA" hint={x.ems_password_set ? 'Já configurada — deixe em branco para manter.' : ''}><input type="password" autoComplete="new-password" value={x.ems_password} onChange={e => set('ems_password', e.target.value)} placeholder={x.ems_password_set ? '••••••••' : ''} /></Field></div></Card>}
    <div><button className="btn primary" onClick={save}>Salvar configuração</button></div></div>
}

