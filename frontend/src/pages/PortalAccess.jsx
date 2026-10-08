import React, { useState } from 'react'
import { Mail, Plus, Send, Trash2 } from 'lucide-react'
import { get, post, del, patch, fmtDT } from '../api'
import { useAuth, can } from '../App'
import { Card, Check, Field, Loading, Modal, Pill, Table, useLoad, useToast } from '../ui'

// Pessoas do cliente com acesso ao portal (somente leitura, restrito ao proprio cliente)
export default function PortalAccess({ client, bare }) {
  const toast = useToast(); const me = useAuth(); const finOk = can(me, 'finance.view'); const { data, reload } = useLoad(() => get(`/clients/${client.id}/portal-users`), [client.id])
  const [inv, setInv] = useState(null); const [busy, setBusy] = useState(false)
  const send = async () => {
    if (busy) return
    setBusy(true)
    try { const r = await post(`/clients/${client.id}/portal-users`, inv); toast('Convite enviado · ' + r.email_status, (r.email_status || '').startsWith('erro')); setInv(null); reload() }
    catch (e) { toast(e.message, true) } finally { setBusy(false) }
  }
  const resend = async (u) => { try { const r = await post(`/clients/${client.id}/portal-users/${u.id}/invite`); toast((u.invite_pending ? 'Convite reenviado' : 'Link de redefinição enviado') + ' · ' + r.email_status) } catch (e) { toast(e.message, true) } }
  const toggleFin = async (u) => { try { await patch(`/clients/${client.id}/portal-users/${u.id}`, { finance: !u.finance }); toast(u.finance ? 'Acesso ao financeiro removido' : 'Acesso ao financeiro concedido'); reload() } catch (e) { toast(e.message, true) } }
  const remove = async (u) => { if (!confirm(`Remover o acesso de ${u.name} (${u.email}) ao portal?`)) return; try { await del(`/clients/${client.id}/portal-users/${u.id}`); toast('Acesso removido'); reload() } catch (e) { toast(e.message, true) } }
  return <Card title="Acesso ao portal do cliente" style={{ marginBottom: 16 }} pad={false}
    actions={<button className="btn primary sm" onClick={() => setInv({ name: '', email: '', finance: false })}><Plus />Convidar usuário do cliente</button>}>
    <div className="sub" style={{ padding: '10px 20px 0' }}>As pessoas convidadas recebem um e-mail para criar a senha e passam a ver <b>somente os dados de {client.trade_name}</b>: disponibilidade, incidentes, hosts, backup e relatórios. Não enxergam outros clientes nem configurações.</div>
    {data ? <Table rows={data} empty="Ninguém do cliente tem acesso ainda. Convide a primeira pessoa." cols={[
      { h: 'Nome', r: r => <b>{r.name}</b> }, { h: 'E-mail', k: 'email' },
      { h: 'Último acesso', r: r => r.invite_pending ? <span className="sub">nunca acessou</span> : fmtDT(r.last_login) },
      { h: 'Financeiro', r: r => finOk ? <label className="check" title="Boletos, títulos e notas fiscais"><input type="checkbox" checked={!!r.finance} onChange={() => toggleFin(r)} />{r.finance ? 'liberado' : 'sem acesso'}</label> : <Pill tone={r.finance ? 'ok' : 'mut'}>{r.finance ? 'liberado' : 'sem acesso'}</Pill> },
      { h: 'Estado', r: r => !r.active ? <Pill tone="mut">inativo</Pill> : r.invite_pending ? <Pill tone="warn">convite pendente</Pill> : <Pill tone="ok">ativo</Pill> },
      { h: '', r: r => <div style={{ display: 'flex', gap: 6 }}><button className="btn sm" onClick={() => resend(r)}><Send />{r.invite_pending ? 'Reenviar' : 'Redefinir'}</button>
        <button className="btn sm danger" title="Remover acesso" onClick={() => remove(r)}><Trash2 /></button></div> }]} /> : <Loading />}
    {inv && <Modal title={`Convidar usuário de ${client.trade_name}`} onClose={() => setInv(null)} footer={<><button className="btn" onClick={() => setInv(null)}>Cancelar</button><button className="btn primary" disabled={busy || !inv.name || !inv.email} onClick={send}><Mail />{busy ? 'Enviando…' : 'Enviar convite'}</button></>}>
      <div className="row r2"><Field label="NOME"><input value={inv.name} onChange={e => setInv({ ...inv, name: e.target.value })} autoFocus /></Field><Field label="E-MAIL"><input type="email" value={inv.email} onChange={e => setInv({ ...inv, email: e.target.value })} /></Field></div>
      {finOk && <div style={{ margin: '4px 0 12px' }}><Check label="Pode ver o financeiro (boletos, títulos e notas fiscais)" checked={inv.finance} onChange={v => setInv({ ...inv, finance: v })} /><p className="hint">Deixe desmarcado para quem só acompanha o monitoramento.</p></div>}
      <div className="banner info" style={{ marginBottom: 0 }}><Mail size={18} /><div className="grow">A pessoa recebe um e-mail com um link pessoal (72h) para criar a própria senha. Nenhuma senha é definida aqui.</div></div></Modal>}
  </Card>
}
