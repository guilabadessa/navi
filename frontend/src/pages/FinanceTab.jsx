import React, { useState } from 'react'
import { FileText, Receipt } from 'lucide-react'
import { get, fmtDT } from '../api'
import { Card, Loading, Pill, Stat, Table, useLoad } from '../ui'

export const brl = (v) => (v == null ? '—' : Number(v).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }))
const day = (v) => (v ? v.split('-').reverse().join('/') : '—')
const ST = { aberto: ['info', 'em aberto'], vencido: ['bad', 'vencido'], pago: ['ok', 'pago'], cancelado: ['mut', 'cancelado'] }
const NST = { emitida: ['ok', 'emitida'], cancelada: ['mut', 'cancelada'] }
// A pagina da fatura do Conta Azul reune boleto e nota fiscal: a API nao fornece o PDF da nota separado da cobranca.
const LBL = { boleto: 'Boleto / fatura', fatura: 'Fatura', pdf: 'Fatura', xml: 'XML' }

// Financeiro do cliente (Conta Azul): mostra por padrao o MES ATUAL; atrasos de meses anteriores ficam em destaque.
export default function FinanceTab({ clientId }) {
  const [month, setMonth] = useState(''); const [showCanc, setShowCanc] = useState(false)
  const q = (clientId ? 'client_id=' + clientId : '') + (month ? (clientId ? '&' : '') + 'month=' + month : '')
  const { data: f, err } = useLoad(() => get('/portal/finance' + (q ? '?' + q : '')), [clientId, month], 120000)
  if (!f) return <Loading err={err} />
  if (f.linked === false) return <div className="banner info"><div className="grow">O financeiro deste cliente ainda não está vinculado. Fale com a Orca TI.</div></div>
  const s = f.summary; const lq = clientId ? '?client_id=' + clientId : ''
  const links = (r) => (r.links || []).map(t => <a key={t} className="btn sm" style={{ marginRight: 6 }} target="_blank" rel="noreferrer"
    href={`/cliente/api/portal/finance/${r.id}/${t}${lq}`}>{t === 'boleto' ? <Receipt size={14} /> : <FileText size={14} />}{LBL[t] || t}</a>)
  const tcols = [
    { h: 'Situação', r: r => { const [t, l] = ST[r.status] || ['mut', r.status]; return <Pill tone={t}>{l}</Pill> } },
    { h: 'Descrição', r: r => <div className="trunc" title={r.description}>{r.description || '—'}</div> },
    { h: 'Nota', r: r => r.nfse ? <span className="chip">NFS-e {r.nfse}</span> : <span className="sub">—</span> },
    { h: 'Vencimento', r: r => day(r.due_date) }, { h: 'Valor', r: r => <b>{brl(r.amount)}</b> }, { h: 'Pago', r: r => brl(r.paid) }, { h: '', r: r => links(r) }]
  const notes = f.notes.filter(n => showCanc || n.status !== 'cancelada')
  return <>
    <div className="bar"><b style={{ fontSize: 17, fontFamily: 'var(--head)' }}>{f.month_label}</b><div className="grow" />
      <select style={{ width: 'auto' }} value={f.month} onChange={e => setMonth(e.target.value)}>{f.months.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}<option value="all">Todos os períodos</option></select></div>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat label="A pagar no mês" value={brl(Math.max(0, (s.month_total || 0) - (s.month_paid || 0)))} desc={`${brl(s.month_total)} faturado · ${brl(s.month_paid)} pago`} />
      <Stat label="Em atraso" value={brl(s.overdue_total)} tone={s.overdue_count ? 'bad' : 'ok'} desc={s.overdue_count ? `${s.overdue_count} título(s) vencido(s)` : 'Nenhum título em atraso'} />
      <Stat label="Próximo vencimento" value={day(s.next_due)} desc={`${s.open_count} título(s) em aberto no total`} />
      <Stat label="Atualizado" value={f.last_sync ? fmtDT(f.last_sync) : '—'} desc="Sincronização com o faturamento" />
    </div>
    {f.late.length > 0 && <Card title={`⚠️ Em atraso de meses anteriores (${f.late.length})`} pad={false} style={{ marginBottom: 16 }}><Table rows={f.late} cols={tcols} /></Card>}
    <Card title="Boletos e cobranças do período" pad={false}><Table rows={f.titles} empty="Nenhum título neste período." cols={tcols} /></Card>
    <Card title="Notas fiscais emitidas" pad={false} style={{ marginTop: 16 }} actions={<label className="check"><input type="checkbox" checked={showCanc} onChange={e => setShowCanc(e.target.checked)} />mostrar canceladas</label>}>
      <Table rows={notes} empty="Nenhuma nota fiscal neste período." cols={[
        { h: 'Número', r: r => <b>{r.number || '—'}</b> }, { h: 'Descrição', r: r => <div className="trunc" title={r.description}>{r.description}</div> },
        { h: 'Competência', r: r => day(r.issue_date) }, { h: 'Valor', r: r => brl(r.amount) },
        { h: 'Situação', r: r => { const [t, l] = NST[r.status] || ['mut', r.status]; return <Pill tone={t}>{l}</Pill> } }]} />
      <div className="sub" style={{ padding: '10px 20px 14px' }}>O arquivo da nota acompanha a <b>fatura</b> (link em cada cobrança acima): o Conta Azul reúne boleto e nota na mesma página.</div></Card>
  </>
}
