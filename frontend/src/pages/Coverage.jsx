import React, { useState } from 'react'
import { Link2 } from 'lucide-react'
import { get, post } from '../api'
import { Card, Loading, Pill, Table, useLoad, useToast } from '../ui'

// Host groups do Zabbix ainda sem cliente: associar em lote
export default function Coverage({ clients, onChanged, open }) {
  const toast = useToast(); const { data, err, reload } = useLoad(() => get('/coverage'), [])
  const [sel, setSel] = useState({}); const [cid, setCid] = useState('')
  const ids = Object.keys(sel).filter(k => sel[k])
  if (!data) return <Loading err={err} />
  if (!data.groups.length && !open) return null
  const assign = async () => {
    try {
      const r = await post('/coverage/assign', { client_id: +cid, groupids: ids })
      toast(`${r.added} grupo(s) associado(s) · ${r.events_relinked} evento(s) vinculados ao cliente`); setSel({}); reload(); onChanged && onChanged()
    } catch (e) { toast(e.message, true) }
  }
  return <Card title={`Cobertura — ${data.groups.length} host group(s) sem cliente`} style={{ marginBottom: 16, borderColor: '#f3d28a' }}
    actions={<Pill tone="warn">{data.hosts_uncovered}/{data.hosts_total} hosts sem cliente</Pill>} pad={false}>
    <div className="sub" style={{ padding: '10px 20px 0' }}>Hosts sem cliente não geram alerta nem relatório. Marque os grupos, escolha o cliente e associe.
      {' '}{data.events_without_client_30d} evento(s) dos últimos 30 dias estão sem cliente.</div>
    <Table rows={data.groups} empty="Tudo associado. 🎉" cols={[
      { h: '', r: r => <input type="checkbox" style={{ width: 'auto' }} checked={!!sel[r.groupid]} onChange={e => setSel({ ...sel, [r.groupid]: e.target.checked })} />, w: 40 },
      { h: 'Host group', r: r => <b>{r.name}</b> }, { h: 'Hosts', k: 'hosts' }, { h: 'Eventos (30d)', k: 'events_30d' },
      { h: 'Exemplos', r: r => <span className="sub">{r.sample.join(', ')}</span> }]} />
    <div className="bar" style={{ padding: '12px 20px', margin: 0 }}>
      <select value={cid} onChange={e => setCid(e.target.value)}><option value="">Escolha o cliente…</option>{clients.map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select>
      <button className="btn primary" disabled={!cid || !ids.length} onClick={assign}><Link2 />Associar {ids.length || ''} grupo(s)</button>
      <span className="hint">Cliente novo? Cadastre-o primeiro em “Novo cliente”.</span></div></Card>
}
