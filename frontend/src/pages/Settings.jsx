import React, { useEffect, useState } from 'react'
import { get, post, put, del, upload, fmtDT } from '../api'
import { Card, Check, Field, Loading, PageHead, Pill, Tabs, useLoad, useToast } from '../ui'
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
      <b>Hosts</b><span>{o.hosts}</span><b>Host groups</b><span>{o.host_groups}</span><b>Triggers</b><span>{o.triggers} <span className="sub">(consulta ao vivo)</span></span><b>Itens</b><span>{o.items} <span className="sub">(consulta ao vivo)</span></span></div>
      {edit && <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}><button className="btn primary" disabled={!!busy} onClick={() => run('y', async () => { toast('Sincronizando…'); const r = await post('/zabbix/sync'); toast(`Sincronizado: ${r.counts.hosts} hosts, ${r.counts.host_groups} grupos`); reload() })}>{busy === 'y' ? 'Sincronizando…' : 'Sincronizar agora'}</button>
</div>}
      <p className="hint" style={{ marginTop: 12 }}>A NAVI espelha apenas grupos e hosts. Itens, triggers e o histórico de relatórios são consultados diretamente na API do Zabbix, e o que deixa de existir no Zabbix também é removido da NAVI. Eventos resolvidos são mantidos por 90 dias.</p></Card></div>
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
  const toast = useToast(); const { data, reload } = useLoad(() => get('/settings/smtp'), [])
  const [f, setF] = useState({ host: '', port: 587, user: '', from: '', from_name: '', password: '', sig_enabled: false, sig_mode: 'text', sig_text: '' })
  const [kind, setKind] = useState('report'); const [html, setHtml] = useState(''); const [imgv, setImgv] = useState(0); const [to, setTo] = useState('')
  useEffect(() => { if (data) setF(x => ({ ...x, host: data.host, port: data.port, user: data.user, from: data.from, from_name: data.from_name, sig_enabled: data.sig_enabled, sig_mode: data.sig_mode, sig_text: data.sig_text || '' })) }, [data])
  const preview = async (k = kind) => { try { setKind(k); setHtml((await post('/settings/smtp/preview', { kind: k })).html) } catch (e) { toast(e.message, true) } }
  useEffect(() => { if (data) preview(kind) }, [data]) // eslint-disable-line
  if (!data) return <Loading />
  const save = async () => { try { await put('/settings/smtp', { ...f, password: f.password || null }); setF({ ...f, password: '' }); toast('Salvo'); await reload(); preview() } catch (e) { toast(e.message, true) } }
  return <div className="grid g2" style={{ alignItems: 'start' }}>
    <div style={{ display: 'grid', gap: 16 }}>
      <Card title="Servidor SMTP"><div className="row r3"><Field label="SERVIDOR"><input value={f.host} onChange={e => setF({ ...f, host: e.target.value })} /></Field><Field label="PORTA"><input type="number" value={f.port} onChange={e => setF({ ...f, port: +e.target.value })} /></Field><Field label="USUÁRIO"><input value={f.user} onChange={e => setF({ ...f, user: e.target.value })} /></Field></div>
        <div className="row r3"><Field label="REMETENTE (E-MAIL)"><input value={f.from} onChange={e => setF({ ...f, from: e.target.value })} /></Field><Field label="NOME DO REMETENTE"><input value={f.from_name} onChange={e => setF({ ...f, from_name: e.target.value })} placeholder="NOC Orca TI" /></Field>
          <Field label="SENHA" hint={data.password_set ? 'Configurada (oculta).' : 'Não configurada.'}><input type="password" autoComplete="off" value={f.password} onChange={e => setF({ ...f, password: e.target.value })} /></Field></div></Card>
      <Card title="Assinatura de e-mail">
        <div className="row"><Check label="Anexar assinatura em todos os e-mails da NAVI (relatórios, avisos, acessos de usuários)" checked={f.sig_enabled} onChange={v => setF({ ...f, sig_enabled: v })} /></div>
        <div className="row" style={{ display: 'flex', gap: 22 }}>{[['text', 'Assinatura em texto'], ['image', 'Assinatura como imagem']].map(([k, l]) => <label key={k} className="check"><input type="radio" name="sig" checked={f.sig_mode === k} onChange={() => setF({ ...f, sig_mode: k })} />{l}</label>)}</div>
        {f.sig_mode === 'text' && <Field label="TEXTO DA ASSINATURA" hint="A primeira linha fica em destaque. Ex.: nome, cargo, telefone e site em linhas separadas."><textarea style={{ minHeight: 120 }} value={f.sig_text} onChange={e => setF({ ...f, sig_text: e.target.value })} placeholder={'NOC Orca TI\nCentral de Monitoramento\n(14) 0000-0000 · orcati.com.br'} /></Field>}
        {f.sig_mode === 'image' && <div>
          {data.sig_image ? <div style={{ border: '1px dashed #cdd5ea', borderRadius: 12, padding: 14, marginBottom: 10, background: '#fff' }}><img key={imgv} src={`/navi/api/settings/smtp/signature-image?v=${imgv}`} alt="Assinatura" style={{ maxWidth: '100%', maxHeight: 160 }} /></div> : <p className="hint" style={{ marginBottom: 8 }}>Nenhuma imagem enviada.</p>}
          {edit && <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><input type="file" accept="image/png,image/jpeg,image/gif,image/webp" style={{ maxWidth: 300 }} onChange={async e => { const file = e.target.files[0]; if (!file) return; try { await upload('/settings/smtp/signature-image', file); toast('Imagem enviada'); setImgv(v => v + 1); await reload(); preview() } catch (x) { toast(x.message, true) } e.target.value = '' }} />
            {data.sig_image && <button className="btn sm danger" onClick={async () => { await del('/settings/smtp/signature-image'); setImgv(v => v + 1); await reload(); preview() }}>Remover imagem</button>}</div>}
          <p className="hint">PNG, JPG, GIF ou WEBP até 1,5 MB (largura ajustada para 640 px automaticamente).</p></div>}
        {edit && <div style={{ marginTop: 12 }}><button className="btn primary" onClick={save}>Salvar configurações</button></div>}</Card>
      {edit && <Card title="Enviar e-mail de teste"><div className="row r2" style={{ marginBottom: 0 }}><Field label="DESTINATÁRIO"><input value={to} onChange={e => setTo(e.target.value)} placeholder="voce@orcati.com.br" /></Field>
        <div style={{ paddingTop: 22 }}><button className="btn" disabled={!to} onClick={async () => { try { const r = await post('/settings/smtp/test', { to }); toast(r.detail, !r.ok) } catch (e) { toast(e.message, true) } }}>Enviar teste</button></div></div></Card>}
    </div>
    <Card title="Pré-visualização do e-mail" actions={<select style={{ width: 'auto' }} value={kind} onChange={e => preview(e.target.value)}><option value="report">Relatório ao cliente</option><option value="notice">Aviso</option><option value="invite">Convite de acesso</option></select>}>
      <p className="hint" style={{ marginBottom: 10 }}>Salve para ver a assinatura atualizada. Nos e-mails de clientes aparece somente o nome fantasia.</p>
      <iframe title="preview" sandbox="" srcDoc={html} style={{ width: '100%', height: 640, border: '1px solid var(--line)', borderRadius: 12, background: '#f3f5fb' }} /></Card></div>
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
