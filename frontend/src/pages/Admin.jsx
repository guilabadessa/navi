import React, { useState } from 'react'
import { Plus, Pencil, Send, Mail, Trash2 } from 'lucide-react'
import { get, post, put, del, fmtDT } from '../api'
import { useAuth, can } from '../App'
import { Card, Check, Field, Loading, Modal, PageHead, Pager, Pill, Table, useLoad, useToast } from '../ui'

const ROLES = { ADMIN: 'Administrador', GESTOR: 'Gestor', ANALISTA_NOC: 'Analista NOC', VISUALIZADOR: 'Visualizador', CLIENTE: 'Cliente (portal)' }
const DESC = { ADMIN: 'Acesso total', GESTOR: 'Clientes, relatórios, alertas, dashboard', ANALISTA_NOC: 'Eventos, hosts, alertas, relatórios', VISUALIZADOR: 'Somente leitura',
  CLIENTE: 'Portal somente leitura: vê apenas os dados do cliente selecionado' }

function UserForm({ u, onClose, onSaved }) {
  const [x, setX] = useState({ email: '', name: '', role: 'VISUALIZADOR', active: true, client_id: null, ...u }); const toast = useToast()
  const clients = useLoad(() => get('/clients'), []); const me = useAuth(); const finMe = can(me, 'finance.view'); const finKey = x.role === 'CLIENTE' ? 'portal.finance' : 'finance.view'
  const save = async () => {
    try {
      const b = { email: x.email, name: x.name, role: x.role, active: x.active, client_id: x.role === 'CLIENTE' ? (x.client_id ? +x.client_id : null) : null, extra_perms: x.extra_perms || [] }
      const r = x.id ? await put('/users/' + x.id, b) : await post('/users', b)
      toast(x.id ? 'Usuário atualizado' : 'Convite enviado · ' + (r.email_status || ''), !!(r.email_status || '').startsWith('erro')); onSaved()
    } catch (e) { toast(e.message, true) }
  }
  return <Modal title={x.id ? 'Editar usuário' : 'Convidar usuário'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button>
    <button className="btn primary" onClick={save}><Send />{x.id ? 'Salvar' : 'Enviar convite'}</button></>}>
    <div className="row r2"><Field label="NOME"><input value={x.name} onChange={e => setX({ ...x, name: e.target.value })} /></Field><Field label="E-MAIL"><input value={x.email} disabled={!!x.id} onChange={e => setX({ ...x, email: e.target.value })} /></Field></div>
    <div className="row r2"><Field label="PERFIL / PERMISSÃO" hint={DESC[x.role]}><select value={x.role} onChange={e => setX({ ...x, role: e.target.value })}>{Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      {x.role === 'CLIENTE' ? <Field label="CLIENTE QUE ELE ACOMPANHA *" hint="Verá somente os hosts, incidentes, backup, endpoints e relatórios deste cliente."><select value={x.client_id || ''} onChange={e => setX({ ...x, client_id: e.target.value })}><option value="">Selecione…</option>{(clients.data || []).map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select></Field> : <div />}</div>
    {finMe && x.role !== 'ADMIN' && <div style={{ marginBottom: 12 }}><Check label={x.role === 'CLIENTE' ? 'Pode ver o financeiro do cliente (boletos, títulos e notas fiscais)' : 'Pode ver o financeiro dos clientes (Conta Azul)'} checked={(x.extra_perms || []).includes(finKey)} onChange={v => setX({ ...x, extra_perms: [...(x.extra_perms || []).filter(p => p !== finKey), ...(v ? [finKey] : [])] })} /></div>}
    {x.id ? <Check label="Usuário ativo" checked={x.active} onChange={v => setX({ ...x, active: v })} />
      : <div className="banner info" style={{ marginBottom: 0 }}><Mail size={18} /><div className="grow">A pessoa receberá um <b>e-mail com um link pessoal</b> para criar a própria senha (válido por 72 horas). Nenhuma senha é definida ou exibida aqui.</div></div>}
  </Modal>
}

export function UsersPage() {
  const toast = useToast(); const { data, err, reload } = useLoad(() => get('/users'), []); const [ed, setEd] = useState(null)
  const resend = async (u) => {
    try { const r = await post(`/users/${u.id}/invite`); toast((u.invite_pending ? 'Convite reenviado' : 'Link de redefinição enviado') + ' · ' + r.email_status, (r.email_status || '').startsWith('erro')) } catch (e) { toast(e.message, true) }
  }
  const remove = async (u) => {
    if (!confirm(`Excluir o usuário ${u.name} (${u.email})? Ele perde o acesso imediatamente. O histórico de auditoria é mantido.`)) return
    try { await del('/users/' + u.id); toast('Usuário excluído'); reload() } catch (e) { toast(e.message, true) }
  }
  return <>
    <PageHead title="Usuários" desc="Convide pessoas por e-mail e defina o perfil de acesso; clientes acessam um portal somente leitura"><button className="btn primary" onClick={() => setEd({})}><Plus />Convidar usuário</button></PageHead>
    <Card pad={false}>{data ? <Table rows={data} cols={[{ h: 'Nome', r: r => <b>{r.name}</b> }, { h: 'E-mail', k: 'email' },
      { h: 'Perfil', r: r => <><Pill tone={r.role === 'CLIENTE' ? 'warn' : 'info'}>{ROLES[r.role]}</Pill>{r.client_name && <div className="sub">{r.client_name}</div>}</> },
      { h: 'Último acesso', r: r => r.invite_pending ? <span className="sub">nunca acessou</span> : fmtDT(r.last_login) },
      { h: 'Estado', r: r => !r.active ? <Pill tone="mut">inativo</Pill> : r.invite_pending ? <Pill tone="warn">convite pendente</Pill> : <Pill tone="ok">ativo</Pill> },
      { h: '', r: r => <div style={{ display: 'flex', gap: 6 }}><button className="btn sm" title={r.invite_pending ? 'Reenviar convite' : 'Enviar link para redefinir a senha'} disabled={!r.active} onClick={() => resend(r)}><Send />{r.invite_pending ? 'Reenviar' : 'Redefinir'}</button>
        <button className="btn sm" onClick={() => setEd(r)}><Pencil />Editar</button>
        <button className="btn sm danger" title="Excluir usuário" onClick={() => remove(r)}><Trash2 /></button></div> }]} /> : <Loading err={err} />}</Card>
    {ed && <UserForm u={ed} onClose={() => setEd(null)} onSaved={() => { setEd(null); reload() }} />}</>
}

export function AuditPage() {
  const [page, setPage] = useState(1); const [action, setAction] = useState(''); const [user, setUser] = useState('')
  const { data, err } = useLoad(() => get(`/audit?page=${page}&size=50&action=${action}&user=${encodeURIComponent(user)}`), [page, action, user])
  return <>
    <PageHead title="Auditoria" desc="Quem fez o quê, quando, de qual IP e com qual resultado. Os registros ficam guardados por 2 anos" />
    <div className="bar"><div className="grow"><input placeholder="Filtrar por usuário…" value={user} onChange={e => { setUser(e.target.value); setPage(1) }} /></div>
      <select value={action} onChange={e => { setAction(e.target.value); setPage(1) }}><option value="">Todas as ações</option>{(data?.actions || []).map(a => <option key={a}>{a}</option>)}</select></div>
    <Card pad={false}>{data ? <><Table rows={data.items} cols={[{ h: 'Data/hora', r: r => new Date(r.ts).toLocaleString('pt-BR') }, { h: 'Usuário', k: 'user_email' }, { h: 'Ação', r: r => <code>{r.action}</code> }, { h: 'Recurso', r: r => [r.resource, r.resource_id].filter(Boolean).join(' #') },
      { h: 'IP', k: 'ip', cls: 'mono' }, { h: 'Resultado', r: r => <Pill tone={r.result === 'ok' ? 'ok' : 'bad'}>{r.result}</Pill> }, { h: 'Detalhe', r: r => <div className="trunc sub">{r.detail ? JSON.stringify(r.detail) : ''}</div> }]} />
      <div style={{ padding: '0 16px 12px' }}><Pager page={page} size={50} total={data.total} onPage={setPage} /></div></> : <Loading err={err} />}</Card></>
}
