import React from 'react'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'

// Mesma regra do servidor (services/destinations.py): de onde vem cada destino de envio
export function destOf(c) {
  if (!c) return null
  const wa = c.whatsapp_group_jid ? [c.whatsapp_group_jid, 'grupo'] : c.whatsapp ? [c.whatsapp, 'celular'] : [null, null]
  const al = c.alert_emails && c.alert_emails.trim() ? [c.alert_emails, 'aba Alertas'] : c.report_emails && c.report_emails.trim() ? [c.report_emails, 'e-mails de relatório (cadastro antigo)'] : [null, null]
  const rep = (c.report_emails || '').trim() || al[0] || null
  return { client: c.trade_name, wa: wa[0], wa_kind: wa[1], report_emails: rep, alert_emails: al[0], alert_origin: al[1] }
}

const Row = ({ label, value, extra, need }) => <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '3px 0', fontSize: 13 }}>
  {value ? <CheckCircle2 size={15} style={{ color: '#16a34a', marginTop: 2, flex: 'none' }} /> : <AlertTriangle size={15} style={{ color: need ? '#bd1723' : '#d97706', marginTop: 2, flex: 'none' }} />}
  <div><b>{label}:</b> {value ? <span className="mono" style={{ wordBreak: 'break-all' }}>{value}</span> : <span style={{ color: need ? '#bd1723' : 'var(--mut)' }}>não cadastrado</span>}{extra && <span style={{ color: 'var(--mut)' }}> · {extra}</span>}</div></div>

// Quadro "Para onde a NAVI envia" (cadastro do cliente, relatorios e rotinas)
export function DestBox({ c, title = 'Para onde a NAVI envia para este cliente', only }) {
  const d = destOf(c); if (!d) return null
  const show = k => !only || only.includes(k)
  return <div className="card" style={{ padding: '10px 14px', margin: '0 0 14px', borderLeft: '3px solid var(--blue)' }}>
    <div className="l" style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--mut)', fontWeight: 600, marginBottom: 4 }}>{title}</div>
    {show('wa') && <Row label="WhatsApp (alertas e relatórios)" value={d.wa} extra={d.wa_kind} />}
    {show('alert') && <Row label="E-mails (alertas)" value={d.alert_emails} extra={d.alert_origin && 'origem: ' + d.alert_origin} need />}
    {show('report') && <Row label="E-mails (relatórios e rotinas)" value={d.report_emails} need />}
  </div>
}

// Destino efetivo de uma rotina/relatorio ("client" = cadastro do cliente)
export function resolveDest(client, wa, email) {
  const d = destOf(client)
  return { wa: wa === 'client' ? d?.wa : (wa || null), waSrc: wa === 'client' ? (d?.wa ? `cadastro do cliente (${d.wa_kind})` : null) : 'informado manualmente',
    email: email === 'client' ? d?.report_emails : (email || null), emailSrc: email === 'client' ? 'cadastro do cliente' : 'informado manualmente' }
}
export function ResolvedLine({ client, wa, email }) {
  const r = resolveDest(client, wa, email)
  return <div style={{ fontSize: 12.5, margin: '2px 0 12px' }}>
    <div style={{ color: wa ? (r.wa ? '#12803b' : '#bd1723') : 'var(--mut)' }}>{wa ? (r.wa ? `✓ WhatsApp irá para ${r.wa} — ${r.waSrc}` : '⚠ WhatsApp solicitado, mas o cliente não tem grupo nem celular cadastrado') : '— WhatsApp: não será enviado'}</div>
    <div style={{ color: email ? (r.email ? '#12803b' : '#bd1723') : 'var(--mut)' }}>{email ? (r.email ? `✓ E-mail irá para ${r.email} — ${r.emailSrc}` : '⚠ E-mail solicitado, mas o cliente não tem e-mail cadastrado na aba Alertas') : '— E-mail: não será enviado'}</div></div>
}
