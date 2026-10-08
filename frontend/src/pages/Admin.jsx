import React, { useState } from 'react'
import { Plus, Pencil } from 'lucide-react'
import { get, post, put, fmtDT } from '../api'
import { Card, Check, Field, Loading, Modal, PageHead, Pager, Pill, Table, useLoad, useToast } from '../ui'

const ROLES = { ADMIN: 'Administrador', GESTOR: 'Gestor', ANALISTA_NOC: 'Analista NOC', VISUALIZADOR: 'Visualizador' }
const DESC = { ADMIN: 'Acesso total', GESTOR: 'Clientes, relatórios, alertas, dashboard', ANALISTA_NOC: 'Eventos, hosts, alertas, relatórios', VISUALIZADOR: 'Somente leitura' }

function UserForm({ u, onClose, onSaved }) {
  const [x, setX] = useState({ email: '', name: '', role: 'VISUALIZADOR', active: true, password: '', send_email: !u.id, ...u }); const toast = useToast()
  const save = async () => { try { const b = { ...x, password: x.password || null }; const r = x.id ? await put('/users/' + x.id, b) : await post('/users', b); toast('Usuário salvo' + (r.email_status ? ' · e-mail: ' + r.email_status : ''), !!(r.email_status || '').startsWith('erro')); onSaved() } catch (e) { toast(e.message, true) } }
  return <Modal title={x.id ? 'Editar usuário' : 'Novo usuário'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" onClick={save}>Salvar</button></>}>
    <div className="row r2"><Field label="NOME"><input value={x.name} onChange={e => setX({ ...x, name: e.target.value })} /></Field><Field label="E-MAIL"><input value={x.email} disabled={!!x.id} onChange={e => setX({ ...x, email: e.target.value })} /></Field></div>
    <div className="row r2"><Field label="PERFIL" hint={DESC[x.role]}><select value={x.role} onChange={e => setX({ ...x, role: e.target.value })}>{Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label={x.id ? 'NOVA SENHA (opcional)' : 'SENHA INICIAL *'} hint="Mínimo de 10 caracteres. O usuário deverá trocá-la."><input type="password" autoComplete="new-password" value={x.password} onChange={e => setX({ ...x, password: e.target.value })} /></Field></div>
    <div style={{ display: 'grid', gap: 10 }}><Check label="Usuário ativo" checked={x.active} onChange={v => setX({ ...x, active: v })} />
      <Check label={x.id ? 'Enviar a nova senha por e-mail ao usuário' : 'Enviar os dados de acesso por e-mail ao usuário'} checked={x.send_email} onChange={v => setX({ ...x, send_email: v })} />
      {x.send_email && <p className="hint">O e-mail usa o modelo padrão da NAVI com a senha temporária; o usuário deverá alterá-la no primeiro acesso.</p>}</div></Modal>
}

export function UsersPage() {
  const { data, err, reload } = useLoad(() => get('/users'), []); const [ed, setEd] = useState(null)
  return <>
    <PageHead title="Usuários" desc="Contas Orca TI e perfis de acesso"><button className="btn primary" onClick={() => setEd({})}><Plus />Novo usuário</button></PageHead>
    <Card pad={false}>{data ? <Table rows={data} cols={[{ h: 'Nome', r: r => <b>{r.name}</b> }, { h: 'E-mail', k: 'email' }, { h: 'Perfil', r: r => <Pill tone="info">{ROLES[r.role]}</Pill> }, { h: 'Último acesso', r: r => fmtDT(r.last_login) },
      { h: 'Estado', r: r => <Pill tone={r.active ? 'ok' : 'mut'}>{r.active ? 'ativo' : 'inativo'}</Pill> }, { h: '', r: r => <button className="btn sm" onClick={() => setEd(r)}><Pencil />Editar</button> }]} /> : <Loading err={err} />}</Card>
    {ed && <UserForm u={ed} onClose={() => setEd(null)} onSaved={() => { setEd(null); reload() }} />}</>
}

export function AuditPage() {
  const [page, setPage] = useState(1); const [action, setAction] = useState(''); const [user, setUser] = useState('')
  const { data, err } = useLoad(() => get(`/audit?page=${page}&size=50&action=${action}&user=${encodeURIComponent(user)}`), [page, action, user])
  return <>
    <PageHead title="Auditoria" desc="Registro de ações: usuário, ação, data/hora, IP, recurso e resultado" />
    <div className="bar"><div className="grow"><input placeholder="Filtrar por usuário…" value={user} onChange={e => { setUser(e.target.value); setPage(1) }} /></div>
      <select value={action} onChange={e => { setAction(e.target.value); setPage(1) }}><option value="">Todas as ações</option>{(data?.actions || []).map(a => <option key={a}>{a}</option>)}</select></div>
    <Card pad={false}>{data ? <><Table rows={data.items} cols={[{ h: 'Data/hora', r: r => new Date(r.ts).toLocaleString('pt-BR') }, { h: 'Usuário', k: 'user_email' }, { h: 'Ação', r: r => <code>{r.action}</code> }, { h: 'Recurso', r: r => [r.resource, r.resource_id].filter(Boolean).join(' #') },
      { h: 'IP', k: 'ip', cls: 'mono' }, { h: 'Resultado', r: r => <Pill tone={r.result === 'ok' ? 'ok' : 'bad'}>{r.result}</Pill> }, { h: 'Detalhe', r: r => <div className="trunc sub">{r.detail ? JSON.stringify(r.detail) : ''}</div> }]} />
      <div style={{ padding: '0 16px 12px' }}><Pager page={page} size={50} total={data.total} onPage={setPage} /></div></> : <Loading err={err} />}</Card></>
}
