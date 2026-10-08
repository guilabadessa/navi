import React, { useEffect, useState } from 'react'
import { get, post, put, fmtDT } from '../api'
import { Card, Field, Loading, PageHead, Pill, Tabs, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'
import { maskCNPJ, maskPhone, cnpjHint } from '../mask'

function Save({ onClick, test, busy }) { return <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>{test && <button className="btn" onClick={test}>Testar conexão</button>}<button className="btn primary" disabled={busy} onClick={onClick}>Salvar</button></div> }

function ZabbixTab({ edit }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/zabbix/settings'), [], 15000); const [url, setUrl] = useState(''); const [token, setToken] = useState(''); const [res, setRes] = useState(null); const [busy, setBusy] = useState('')
  useEffect(() => { if (data) setUrl(data.url) }, [data?.url]) // eslint-disable-line
  if (!data) return <Loading />
  const o = data.objects; const ls = data.last_sync
  const run = async (k, fn) => { setBusy(k); try { await fn() } catch (e) { toast(e.message, true) } finally { setBusy('') } }
  return <div className="grid g2">
    <Card title="Integração Zabbix"><div className="row"><Field label="URL DA API"><input value={url} onChange={e => setUrl(e.target.value)} /></Field></div>
      <div className="row"><Field label="API TOKEN" hint={data.token_set ? 'Token configurado (oculto). Preencha somente para substituir.' : 'Gere em Zabbix → Users → API tokens.'}><input type="password" autoComplete="off" value={token} placeholder={data.token_set ? '••••••••••••••••' : ''} onChange={e => setToken(e.target.value)} /></Field></div>
      {res && <div style={{ marginBottom: 10 }}><Pill tone={res.ok ? 'ok' : 'bad'}>{res.ok ? `Conectado · Zabbix ${res.version}` : 'Falha'}</Pill> <span className="sub">{res.detail}</span></div>}
      {edit && <Save busy={busy === 's'} onClick={() => run('s', async () => { await put('/zabbix/settings', { url, token: token || null }); setToken(''); toast('Configuração salva'); reload() })}
        test={() => run('t', async () => setRes(await post('/zabbix/test')))} />}</Card>
    <Card title="Sincronização"><div className="kv" style={{ marginBottom: 14 }}><b>Última</b><span>{ls ? fmtDT(ls.finished_at || ls.started_at) : 'nunca'}</span><b>Status</b><span>{ls ? <Pill tone={ls.status === 'ok' ? 'ok' : 'bad'}>{ls.status}</Pill> : '—'} {ls?.error && <span className="sub">{ls.error}</span>}</span>
      <b>Hosts</b><span>{o.hosts}</span><b>Host groups</b><span>{o.host_groups}</span><b>Triggers</b><span>{o.triggers}</span><b>Itens</b><span>{o.items}</span></div>
      {edit && <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}><button className="btn primary" disabled={!!busy} onClick={() => run('y', async () => { toast('Sincronizando…'); const r = await post('/zabbix/sync'); toast(`Sincronizado: ${r.counts.hosts} hosts, ${r.counts.host_groups} grupos`); reload() })}>{busy === 'y' ? 'Sincronizando…' : 'Sincronizar agora'}</button>
        <button className="btn" disabled={!!busy} onClick={() => run('i', async () => { toast('Sincronizando itens (pode demorar)…'); const r = await post('/zabbix/sync?items=true'); toast(`${r.counts.items} itens sincronizados`); reload() })}>{busy === 'i' ? 'Aguarde…' : 'Sincronizar itens'}</button></div>}
      <p className="hint" style={{ marginTop: 12 }}>A sincronização é incremental e nunca apaga dados locais: objetos que somem da API apenas são marcados como inativos.</p></Card></div>
}

function EvoTab({ edit }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/settings/evolution'), []); const [f, setF] = useState({ url: '', instance: '', api_key: '' }); const [res, setRes] = useState(null)
  useEffect(() => { if (data) setF(x => ({ ...x, url: data.url, instance: data.instance })) }, [data])
  if (!data) return <Loading />
  return <Card title="Evolution API (WhatsApp)"><div className="row r2"><Field label="URL BASE"><input value={f.url} onChange={e => setF({ ...f, url: e.target.value })} /></Field><Field label="INSTÂNCIA"><input value={f.instance} onChange={e => setF({ ...f, instance: e.target.value })} /></Field></div>
    <div className="row"><Field label="API KEY" hint={data.api_key_set ? 'Configurada (oculta). Preencha somente para substituir.' : 'Não configurada.'}><input type="password" autoComplete="off" value={f.api_key} onChange={e => setF({ ...f, api_key: e.target.value })} /></Field></div>
    {res && <div style={{ marginBottom: 10 }}><Pill tone={res.ok ? 'ok' : 'bad'}>{res.ok ? 'Conectada' : 'Falha'}</Pill> <span className="sub">{res.detail}</span></div>}
    {edit && <Save onClick={async () => { try { await put('/settings/evolution', { ...f, api_key: f.api_key || null }); setF({ ...f, api_key: '' }); toast('Salvo'); reload() } catch (e) { toast(e.message, true) } }} test={async () => setRes(await post('/settings/evolution/test'))} />}</Card>
}

function SmtpTab({ edit }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/settings/smtp'), []); const [f, setF] = useState({ host: '', port: 587, user: '', from: '', password: '' })
  useEffect(() => { if (data) setF(x => ({ ...x, host: data.host, port: data.port, user: data.user, from: data.from })) }, [data])
  if (!data) return <Loading />
  return <Card title="SMTP"><div className="row r3"><Field label="SERVIDOR"><input value={f.host} onChange={e => setF({ ...f, host: e.target.value })} /></Field><Field label="PORTA"><input type="number" value={f.port} onChange={e => setF({ ...f, port: +e.target.value })} /></Field><Field label="USUÁRIO"><input value={f.user} onChange={e => setF({ ...f, user: e.target.value })} /></Field></div>
    <div className="row r2"><Field label="REMETENTE (From)"><input value={f.from} onChange={e => setF({ ...f, from: e.target.value })} /></Field><Field label="SENHA" hint={data.password_set ? 'Configurada (oculta).' : 'Não configurada.'}><input type="password" autoComplete="off" value={f.password} onChange={e => setF({ ...f, password: e.target.value })} /></Field></div>
    {edit && <Save onClick={async () => { try { await put('/settings/smtp', { ...f, password: f.password || null }); setF({ ...f, password: '' }); toast('Salvo'); reload() } catch (e) { toast(e.message, true) } }} />}
    <p className="hint">Para testar o envio use o menu E-mail.</p></Card>
}

function LetterTab({ edit }) {
  const toast = useToast(); const { data } = useLoad(() => get('/settings/letterhead'), []); const [f, setF] = useState(null)
  useEffect(() => { if (data) setF(data) }, [data])
  if (!f) return <Loading />
  const s = k => e => setF({ ...f, [k]: e.target.value })
  return <Card title="Papel timbrado — modelo Orca TI"><div className="row r2"><Field label="EMPRESA"><input value={f.company} onChange={s('company')} /></Field><Field label="CNPJ" hint={cnpjHint(f.cnpj)}><input inputMode="numeric" value={f.cnpj || ''} onChange={e => setF({ ...f, cnpj: maskCNPJ(e.target.value) })} placeholder="00.000.000/0000-00" /></Field></div>
    <div className="row r3"><Field label="ENDEREÇO"><input value={f.address || ''} onChange={s('address')} /></Field><Field label="TELEFONE"><input inputMode="tel" value={f.phone || ''} onChange={e => setF({ ...f, phone: maskPhone(e.target.value) })} placeholder="(00) 0000-0000" /></Field><Field label="SITE"><input value={f.site || ''} onChange={s('site')} /></Field></div>
    <Field label="TEXTO INSTITUCIONAL (rodapé do relatório)"><textarea value={f.text || ''} onChange={s('text')} /></Field>
    {edit && <Save onClick={async () => { try { await put('/settings/letterhead', f); toast('Salvo') } catch (e) { toast(e.message, true) } }} />}</Card>
}

function WebhookTab({ edit }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/settings/webhook'), []); const [tok, setTok] = useState('')
  if (!data) return <Loading />
  const url = location.origin + data.path
  return <Card title="Webhook de eventos do Zabbix (tempo real)"><p className="sub" style={{ marginBottom: 12 }}>Configure um Media Type do tipo Webhook no Zabbix que envie um POST JSON a esta URL com o cabeçalho <code>X-Navi-Token</code>. Pode coexistir com o Media Type atual (Evolution).</p>
    <div className="kv"><b>URL</b><code>{url}</code><b>Token</b><span>{data.token_set ? <Pill tone="ok">configurado</Pill> : <Pill tone="warn">não configurado</Pill>}</span></div>
    {tok && <div className="card" style={{ padding: 14, margin: '14px 0', borderColor: 'var(--blue)' }}><b>Novo token (exibido uma única vez):</b><div className="mono" style={{ wordBreak: 'break-all', marginTop: 6 }}>{tok}</div></div>}
    {edit && <button className="btn primary" style={{ marginTop: 14 }} onClick={async () => { if (!confirm('Gerar novo token? O anterior deixará de funcionar.')) return; try { setTok((await post('/settings/webhook/rotate')).token); reload() } catch (e) { toast(e.message, true) } }}>{data.token_set ? 'Rotacionar token' : 'Gerar token'}</button>}
    <h3 style={{ margin: '24px 0 8px' }}>Payload esperado</h3>
    <pre style={{ background: '#0b1230', color: '#cfe0ff', padding: 16, borderRadius: 12, overflow: 'auto', fontSize: 13 }}>{`{
  "eventid": "{EVENT.ID}", "status": "PROBLEM | RESOLVED",
  "hostid": "{HOST.ID}", "host": "{HOST.NAME}", "ip": "{HOST.IP}",
  "triggerid": "{TRIGGER.ID}", "trigger": "{EVENT.NAME}",
  "itemid": "{ITEM.ID1}", "item": "{ITEM.NAME1}",
  "severity": "{EVENT.NSEVERITY}", "opdata": "{EVENT.OPDATA}",
  "clock": <epoch do início>, "recovery_clock": <epoch da recuperação>,
  "r_eventid": "{EVENT.RECOVERY.ID}"
}`}</pre></Card>
}

export default function Settings() {
  const me = useAuth(); const [tab, setTab] = useState('zbx'); const edit = can(me, 'settings.edit')
  return <>
    <PageHead title="Configurações" desc="Integrações, papel timbrado e webhook" />
    <Tabs value={tab} onChange={setTab} tabs={[['zbx', 'Zabbix'], ['evo', 'Evolution API'], ['smtp', 'E-mail (SMTP)'], ['lh', 'Papel timbrado'], ['wh', 'Webhook']]} />
    {tab === 'zbx' && <ZabbixTab edit={edit} />}{tab === 'evo' && <EvoTab edit={edit} />}{tab === 'smtp' && <SmtpTab edit={edit} />}{tab === 'lh' && <LetterTab edit={edit} />}{tab === 'wh' && <WebhookTab edit={edit} />}</>
}
