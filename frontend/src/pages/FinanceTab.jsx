import React, { useState } from 'react'
import { ExternalLink, FileText, Receipt } from 'lucide-react'
import { get, fmtDT } from '../api'
import { Card, Loading, Pill, Stat, Table, useLoad } from '../ui'

export const brl = (v) => (v == null ? '—' : Number(v).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }))
const day = (v) => (v ? v.split('-').reverse().join('/') : '—')
const ST = { aberto: ['info', 'em aberto'], vencido: ['bad', 'vencido'], pago: ['ok', 'pago'], cancelado: ['mut', 'cancelado'] }
const LBL = { pdf: 'PDF', xml: 'XML', boleto: 'Boleto' }

// Financeiro do cliente (Conta Azul). Visivel somente com a permissao de financeiro; o servidor valida a cada chamada.
export default function FinanceTab({ clientId }) {
  const q = clientId ? '?client_id=' + clientId : ''
  const { data: f, err } = useLoad(() => get('/portal/finance' + q), [clientId], 120000); const [view, setView] = useState('open')
  if (!f) return <Loading err={err} />
  if (!f.linked) return <div className="banner info"><div className="grow">O financeiro deste cliente ainda não está vinculado. Fale com a Orca TI.</div></div>
  const s = f.summary
  const links = (r, kind) => (r.links || []).map(t => <a key={t} className="btn sm" style={{ marginRight: 6 }} target="_blank" rel="noreferrer"
    href={`/cliente/api/portal/finance/${r.id}/${t}${q}`}>{t === 'boleto' ? <Receipt size={14} /> : <FileText size={14} />}{LBL[t] || t}</a>)
  const titles = f.titles.filter(t => view === 'all' || t.status === 'aberto' || t.status === 'vencido')
  return <>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat label="Em aberto" value={brl(s.open_total)} desc={`${s.open_count} título(s)`} />
      <Stat label="Vencido" value={brl(s.overdue_total)} tone={s.overdue_count ? 'bad' : 'ok'} desc={s.overdue_count ? `${s.overdue_count} título(s) em atraso` : 'Nenhum título em atraso'} />
      <Stat label="Próximo vencimento" value={day(s.next_due)} desc="entre os títulos em aberto" />
      <Stat label="Atualizado" value={f.last_sync ? fmtDT(f.last_sync) : '—'} desc="Sincronização com o faturamento" />
    </div>
    <Card title="Boletos e cobranças" pad={false} actions={<select style={{ width: 'auto' }} value={view} onChange={e => setView(e.target.value)}><option value="open">Em aberto e vencidos</option><option value="all">Todos</option></select>}>
      <Table rows={titles} empty="Nenhum título." cols={[
        { h: 'Situação', r: r => { const [t, l] = ST[r.status] || ['mut', r.status]; return <Pill tone={t}>{l}</Pill> } },
        { h: 'Descrição', r: r => <div className="trunc" title={r.description}>{r.description || '—'}</div> },
        { h: 'Vencimento', r: r => day(r.due_date) }, { h: 'Valor', r: r => <b>{brl(r.amount)}</b> }, { h: 'Pago', r: r => brl(r.paid) },
        { h: '', r: r => links(r) }]} /></Card>
    <Card title="Notas fiscais" pad={false} style={{ marginTop: 16 }}>
      <Table rows={f.notes} empty="Nenhuma nota fiscal emitida no período." cols={[
        { h: 'Número', r: r => <b>{r.number || '—'}</b> }, { h: 'Descrição', r: r => <div className="trunc" title={r.description}>{r.description}</div> },
        { h: 'Emissão', r: r => day(r.issue_date) }, { h: 'Valor', r: r => brl(r.amount) }, { h: 'Situação', k: 'status' }, { h: '', r: r => links(r) }]} /></Card>
  </>
}
