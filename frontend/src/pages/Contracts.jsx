import React from 'react'
import { FileText } from 'lucide-react'
import { Card } from '../ui'

const dt = (v) => v ? new Date(v + 'T12:00:00').toLocaleDateString('pt-BR') : '—'

// Servicos contratados (contratos ativos do Conta Azul): descricao do servico e vigencia, sem valores
export default function Contracts({ items, title = 'Serviços contratados' }) {
  if (!items || !items.length) return null
  return <Card title={title} actions={<FileText size={18} />} style={{ marginBottom: 16 }}>
    <div style={{ display: 'grid', gap: 14 }}>{items.map(c => <div key={c.number} style={{ borderLeft: '3px solid var(--blue)', paddingLeft: 12 }}>
      <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>Contrato nº {c.number} · vigência {dt(c.start)} a {dt(c.end)}</div>
      {(c.items?.length || c.lines.length) ? <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{(c.items || []).map((i, k) => <li key={'i' + k}><b>{i.name}</b>{i.qty ? <span className="sub"> · Qtd.: {i.qty}</span> : null}</li>)}{c.lines.map((l, i) => <li key={i}>{l}</li>)}</ul> : <div className="sub" style={{ marginTop: 4 }}>Sem descrição cadastrada no contrato.</div>}</div>)}</div></Card>
}
