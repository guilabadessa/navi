import React, { useState } from 'react'
import { get, post, fmtDT } from '../api'
import { Card, Field, Loading, PageHead, Pager, Pill, Stat, Table, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'
import { Link } from 'react-router-dom'
import { maskTarget } from '../mask'

// Barra discreta: estado da integracao, servidor e envio de teste (substitui os cartoes grandes)
const Dot = ({ ok }) => <i className="dot" style={{ background: ok == null ? '#b8c0d8' : ok ? '#16a34a' : '#bd1723' }} />

export function WhatsApp() {
  const me = useAuth(); const toast = useToast(); const [page, setPage] = useState(1); const [st, setSt] = useState(''); const [to, setTo] = useState(''); const [text, setText] = useState('Teste de envio — NAVI Orca TI ✅'); const [busy, setBusy] = useState(false)
  const { data, err } = useLoad(() => get(`/alerts/dispatches?channel=whatsapp&page=${page}&size=40${st ? '&status=' + st : ''}`), [page, st], 15000)
  const health = useLoad(() => get('/settings/status'), [], 30000); const cfg = useLoad(() => get('/settings/evolution').catch(() => null), [])
  const evo = health.data?.evolution
  const test = async () => { setBusy(true); try { const r = await post('/alerts/test-whatsapp', { to, text }); toast(r.detail, !r.ok) } catch (e) { toast(e.message, true) } finally { setBusy(false) } }
  return <>
    <PageHead title="WhatsApp" desc="Histórico das mensagens de alerta enviadas pelo WhatsApp"><Link className="btn sm" to="/configuracoes">Configurar Evolution</Link></PageHead>
    <div className="chanbar">
      <span title={evo?.detail}><Dot ok={evo ? evo.ok : null} /> {evo ? (evo.ok ? 'Conectado' : 'Com problema') : 'Verificando…'}</span>
      {cfg.data && <span>Servidor: <b>{(cfg.data.url || '—').replace(/^https?:\/\//, '')}</b>{cfg.data.instance ? ` · instância ${cfg.data.instance}` : ''}</span>}
      <span>{data ? `${data.total} mensagem(ns)` : ''}</span>
      {can(me, 'alerts.edit') && <span className="chantest"><input placeholder="Número ou grupo para teste" value={to} onChange={e => setTo(maskTarget(e.target.value))} /><input placeholder="Mensagem" value={text} onChange={e => setText(e.target.value)} /><button className="btn sm" disabled={!to || busy} onClick={test}>{busy ? 'Enviando…' : 'Enviar teste'}</button></span>}</div>
    <div className="bar"><select value={st} onChange={e => { setSt(e.target.value); setPage(1) }}><option value="">Todos os status</option><option value="pending">Pendentes</option><option value="sent">Enviados</option><option value="failed">Falhas</option><option value="skipped">Ignorados</option></select></div>
    <Card pad={false}>{data ? <><Table rows={data.items} empty="Nenhuma mensagem registrada ainda." cols={[
      { h: 'Quando', r: r => fmtDT(r.sent_at || r.due_at) }, { h: 'Tipo', r: r => <Pill tone={r.kind === 'recovery' ? 'ok' : r.kind === 'escalation' ? 'warn' : 'bad'}>{r.kind === 'problem' ? 'alerta' : r.kind === 'recovery' ? 'recuperação' : 'escalonamento'}</Pill> }, { h: 'Host', k: 'host' },
      { h: 'Problema', r: r => <div className="trunc">{r.trigger}</div> }, { h: 'Destino', r: r => <span className="mono sub">{r.dest_jid}</span> },
      { h: 'Status', r: r => <Pill tone={r.status === 'sent' ? 'ok' : r.status === 'failed' ? 'bad' : 'warn'}>{r.status}</Pill> }, { h: 'Obs.', r: r => <div className="trunc sub" style={{ maxWidth: 220 }} title={r.error}>{r.error}</div> }]} />
      <div style={{ padding: '0 16px 12px' }}><Pager page={page} size={40} total={data.total} onPage={setPage} /></div></> : <Loading err={err} />}</Card></>
}

export function Email() {
  const me = useAuth(); const toast = useToast(); const [to, setTo] = useState(''); const [page, setPage] = useState(1); const [st, setSt] = useState(''); const [busy, setBusy] = useState(false)
  const smtp = useLoad(() => get('/settings/smtp').catch(() => null), []); const health = useLoad(() => get('/settings/status'), [], 30000)
  const sent = useLoad(() => get(`/alerts/dispatches?channel=email&page=${page}&size=30${st ? '&status=' + st : ''}`), [page, st], 15000); const runs = useLoad(() => get('/reports/runs?size=15'), [])
  const h = health.data?.email
  const test = async () => { setBusy(true); try { const r = await post('/settings/smtp/test', { to }); toast(r.detail, !r.ok) } catch (e) { toast(e.message, true) } finally { setBusy(false) } }
  return <>
    <PageHead title="E-mail" desc="Histórico dos e-mails de alerta e dos relatórios enviados"><Link className="btn sm" to="/configuracoes">Configurar SMTP</Link></PageHead>
    <div className="chanbar">
      <span title={h?.detail}><Dot ok={h ? h.ok : null} /> {h ? (h.ok ? 'SMTP autenticado' : 'SMTP com problema') : 'Verificando…'}</span>
      {smtp.data && <span>Servidor: <b>{smtp.data.host || '—'}</b>{smtp.data.port ? `:${smtp.data.port}` : ''}</span>}
      {smtp.data && <span>Remetente: <b>{smtp.data.from || smtp.data.user || '—'}</b></span>}
      {can(me, 'settings.edit') && <span className="chantest"><input placeholder="E-mail para teste" value={to} onChange={e => setTo(e.target.value)} /><button className="btn sm" disabled={!to || busy} onClick={test}>{busy ? 'Enviando…' : 'Enviar teste'}</button></span>}</div>
    <div className="bar"><select value={st} onChange={e => { setSt(e.target.value); setPage(1) }}><option value="">Todos os status</option><option value="pending">Pendentes</option><option value="sent">Enviados</option><option value="failed">Falhas</option><option value="skipped">Ignorados</option></select></div>
    <Card title="E-mails de alerta" pad={false} style={{ marginBottom: 16 }}>{sent.data ? <><Table rows={sent.data.items} empty="Nenhum e-mail de alerta registrado ainda." cols={[
      { h: 'Quando', r: r => fmtDT(r.sent_at || r.due_at) }, { h: 'Tipo', r: r => <Pill tone={r.kind === 'recovery' ? 'ok' : r.kind === 'escalation' ? 'warn' : 'bad'}>{r.kind === 'problem' ? 'alerta' : r.kind === 'recovery' ? 'recuperação' : 'escalonamento'}</Pill> }, { h: 'Host', k: 'host' },
      { h: 'Problema', r: r => <div className="trunc">{r.trigger}</div> }, { h: 'Destino', r: r => <div className="trunc mono sub" style={{ maxWidth: 220 }} title={r.dest_jid}>{r.dest_jid}</div> },
      { h: 'Status', r: r => <Pill tone={r.status === 'sent' ? 'ok' : r.status === 'failed' ? 'bad' : 'warn'}>{r.status}</Pill> }, { h: 'Obs.', r: r => <div className="trunc sub" style={{ maxWidth: 220 }} title={r.error}>{r.error}</div> }]} />
      <div style={{ padding: '0 16px 12px' }}><Pager page={page} size={30} total={sent.data.total} onPage={setPage} /></div></> : <Loading err={sent.err} />}</Card>
    <Card title="Relatórios enviados por e-mail" pad={false}>{runs.data ? <Table rows={runs.data.items.filter(r => r.email_status)} empty="Nenhum envio por e-mail ainda." cols={[{ h: 'Quando', r: r => fmtDT(r.generated_at) }, { h: 'Relatório', k: 'name' }, { h: 'Cliente', k: 'client_name' }, { h: 'Resultado', k: 'email_status' }]} /> : <Loading />}</Card></>
}
