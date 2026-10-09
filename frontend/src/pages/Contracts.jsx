import React from 'react'
import { FileText } from 'lucide-react'
import { Card } from '../ui'

const dt = (v) => v ? new Date(v + 'T12:00:00').toLocaleDateString('pt-BR') : '—'

// Servicos contratados (contratos ativos do Conta Azul). No portal: so os servicos e a quantidade (sem numero, vigencia ou valores).
// `meta` (equipe): mostra tambem numero e vigencia de cada contrato.
export default function Contracts({ items, title = 'Serviços contratados', meta = false }) {
  if (!items || !items.length) return null
  const line = (i, k) => <li key={k}><b>{i.name}</b>{i.qty ? <span className="sub"> · Qtd.: {i.qty}</span> : null}</li>
  const none = <div className="sub" style={{ marginTop: 4 }}>Sem descrição cadastrada no contrato.</div>
  return <Card title={title} actions={<FileText size={18} />} style={{ marginBottom: 16 }}>
    {meta ? <div style={{ display: 'grid', gap: 14 }}>{items.map(c => <div key={c.number} style={{ borderLeft: '3px solid var(--blue)', paddingLeft: 12 }}>
      <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>Contrato nº {c.number} · vigência {dt(c.start)} a {dt(c.end)}</div>
      {c.items?.length ? <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{c.items.map((i, k) => line(i, k))}</ul> : none}</div>)}</div>
      : (() => { const all = items.flatMap(c => c.items || []); return all.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{all.map((i, k) => line(i, k))}</ul> : none })()}</Card>
}
