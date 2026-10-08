import React, { useState } from 'react'
import { get, post, fmtDT } from '../api'
import { Card, Field, Loading, PageHead, Pager, Pill, Stat, Table, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'
import { Link } from 'react-router-dom'

export function WhatsApp() {
  const me = useAuth(); const toast = useToast(); const [page, setPage] = useState(1); const [st, setSt] = useState(''); const [to, setTo] = useState(''); const [text, setText] = useState('Teste de envio — NAVI Orca TI ✅')
  const { data, err } = useLoad(() => get(`/alerts/dispatches?page=${page}&size=40${st ? '&status=' + st : ''}`), [page, st], 15000)
  const health = useLoad(() => get('/settings/status'), [], 30000)
  const evo = health.data?.evolution
  const test = async () => { try { const r = await post('/alerts/test-whatsapp', { to, text }); toast(r.detail, !r.ok) } catch (e) { toast(e.message, true) } }
  return <>
    <PageHead title="WhatsApp" desc="Integração com a Evolution API e log de mensagens enviadas"><Link className="btn" to="/configuracoes">Configurar Evolution</Link></PageHead>
    <div className="grid g3" style={{ marginBottom: 16 }}>
      <Stat label="Conexão Evolution" value={evo ? (evo.ok ? 'Conectada' : 'Com problema') : '—'} tone={evo ? (evo.ok ? 'ok' : 'bad') : ''} desc={evo?.detail} />
      <Stat label="Mensagens (página)" value={data ? data.total : '—'} desc="total no filtro atual" />
      <Stat label="Falhas" value={data ? data.items.filter(i => i.status === 'failed').length : '—'} tone="warn" desc="na página atual" /></div>
    {can(me, 'alerts.edit') && <Card title="Enviar mensagem de teste" style={{ marginBottom: 16 }}><div className="row r3" style={{ marginBottom: 0 }}><Field label="DESTINO (número ou JID do grupo)"><input value={to} onChange={e => setTo(e.target.value)} placeholder="120363406164560822@g.us" /></Field>
      <Field label="MENSAGEM"><input value={text} onChange={e => setText(e.target.value)} /></Field><div style={{ paddingTop: 22 }}><button className="btn primary" disabled={!to} onClick={test}>Enviar teste</button></div></div></Card>}
    <div className="bar"><select value={st} onChange={e => { setSt(e.target.value); setPage(1) }}><option value="">Todos os status</option><option value="pending">Pendentes</option><option value="sent">Enviados</option><option value="failed">Falhas</option><option value="skipped">Ignorados</option></select></div>
    <Card pad={false}>{data ? <><Table rows={data.items} empty="Nenhuma mensagem registrada ainda." cols={[
      { h: 'Quando', r: r => fmtDT(r.sent_at || r.due_at) }, { h: 'Tipo', r: r => <Pill tone={r.kind === 'problem' ? 'bad' : 'ok'}>{r.kind === 'problem' ? 'alerta' : 'recuperação'}</Pill> }, { h: 'Host', k: 'host' },
      { h: 'Problema', r: r => <div className="trunc">{r.trigger}</div> }, { h: 'Destino', r: r => <span className="mono sub">{r.dest_jid}</span> },
      { h: 'Status', r: r => <Pill tone={r.status === 'sent' ? 'ok' : r.status === 'failed' ? 'bad' : 'warn'}>{r.status}</Pill> }, { h: 'Obs.', r: r => <div className="trunc sub" style={{ maxWidth: 220 }} title={r.error}>{r.error}</div> }]} />
      <div style={{ padding: '0 16px 12px' }}><Pager page={page} size={40} total={data.total} onPage={setPage} /></div></> : <Loading err={err} />}</Card></>
}

export function Email() {
  const me = useAuth(); const toast = useToast(); const [to, setTo] = useState('')
  const smtp = useLoad(() => get('/settings/smtp'), []); const health = useLoad(() => get('/settings/status'), [], 30000); const runs = useLoad(() => get('/reports/runs?size=15'), [])
  const h = health.data?.email
  return <>
    <PageHead title="E-mail" desc="SMTP para relatórios e notificações"><Link className="btn" to="/configuracoes">Configurar SMTP</Link></PageHead>
    <div className="grid g3" style={{ marginBottom: 16 }}>
      <Stat label="SMTP" value={h ? (h.ok ? 'Autenticado' : 'Com problema') : '—'} tone={h ? (h.ok ? 'ok' : 'bad') : ''} desc={h?.detail} />
      <Stat label="Servidor" value={smtp.data ? smtp.data.host || '—' : '—'} desc={smtp.data ? `porta ${smtp.data.port} · ${smtp.data.user}` : ''} />
      <Stat label="Remetente" value={smtp.data ? (smtp.data.from || smtp.data.user || '—') : '—'} /></div>
    {can(me, 'settings.edit') && <Card title="Enviar e-mail de teste" style={{ marginBottom: 16 }}><div className="row r2" style={{ marginBottom: 0 }}><Field label="DESTINATÁRIO"><input value={to} onChange={e => setTo(e.target.value)} placeholder="voce@orcati.com.br" /></Field>
      <div style={{ paddingTop: 22 }}><button className="btn primary" disabled={!to} onClick={async () => { try { const r = await post('/settings/smtp/test', { to }); toast(r.detail, !r.ok) } catch (e) { toast(e.message, true) } }}>Enviar teste</button></div></div></Card>}
    <Card title="Últimos relatórios enviados por e-mail" pad={false}>{runs.data ? <Table rows={runs.data.items.filter(r => r.email_status)} empty="Nenhum envio por e-mail ainda." cols={[{ h: 'Quando', r: r => fmtDT(r.generated_at) }, { h: 'Relatório', k: 'name' }, { h: 'Cliente', k: 'client_name' }, { h: 'Resultado', k: 'email_status' }]} /> : <Loading />}</Card></>
}
