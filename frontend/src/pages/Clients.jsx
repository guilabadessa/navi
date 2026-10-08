import React, { useState } from 'react'
import { useNavigate, useParams, Link, useSearchParams } from 'react-router-dom'
import Coverage from './Coverage'
import PortalAccess from './PortalAccess'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Plus, Pencil, Trash2, Users, Eye } from 'lucide-react'
import Portal from './Portal'
import { get, post, put, del, upload, fmtDT, fmtDur, fmtPct, SEV } from '../api'
import { Card, Check, Field, Loading, Modal, MultiPick, PageHead, Pill, SevBadge, Stat, StatusBadge, Table, Tabs, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'
import { maskCNPJ, maskPhone, maskTarget, cnpjHint } from '../mask'

export async function deleteClient(c, toast) {
  try {
    const i = await get(`/clients/${c.id}/impact`)
    const itens = [[i.reports, 'relatório(s) e rotina(s)'], [i.pdfs, 'PDF(s) gerado(s)'], [i.rules, 'regra(s) de alerta'], [i.windows, 'janela(s) de manutenção'], [i.portal_users, 'usuário(s) do portal']]
      .filter(([n]) => n).map(([n, l]) => `• ${n} ${l}`).join('\n')
    const ok = confirm(`Excluir DEFINITIVAMENTE o cliente "${c.trade_name}"?\n\nSerão removidos junto:\n${itens || '• nenhum item vinculado'}\n\nOs ${i.events} evento(s) do histórico permanecem, apenas sem cliente. O Zabbix não é alterado.\n\nEsta ação não pode ser desfeita.`)
    if (!ok) return false
    await del('/clients/' + c.id); toast('Cliente excluído'); return true
  } catch (e) { toast(e.message, true); return false }
}

const blank = { trade_name: '', legal_name: '', cnpj: '', state_registration: '', address: '', city: '', state: '', contact_name: '', email: '', phone: '',
  whatsapp: '', whatsapp_group_jid: '', report_emails: '', notes: '', sla_target: 99.5, service_hours: '', status: 'ativo', wa_enabled: false,
  wa_min_severity: 3, wa_delay_s: 0, wa_send_recovery: true, wa_hours: '', group_ids: [], host_ids: [], contacts: [] }

function ClientForm({ initial, onClose, onSaved }) {
  const [c, setC] = useState({ ...blank, ...initial }); const [tab, setTab] = useState('dados'); const toast = useToast(); const [busy, setBusy] = useState(false)
  const { data: groups } = useLoad(() => get('/zabbix/groups'), [])
  const { data: tpls } = useLoad(() => get('/alerts/templates'), [])
  const set = (k) => (e) => setC({ ...c, [k]: e && e.target ? e.target.value : e })
  const save = async () => {
    if (busy) return
    setBusy(true)
    try {
      const body = { ...c, sla_target: Number(c.sla_target), wa_delay_s: Number(c.wa_delay_s), wa_min_severity: Number(c.wa_min_severity),
        maintenance_until: c.maintenance_until || null }
      const r = c.id ? await put('/clients/' + c.id, body) : await post('/clients', body)
      toast('Cliente salvo'); onSaved(r)
    } catch (e) { toast(e.message, true); setBusy(false) }
  }
  const setContact = (i, k, v) => { const l = [...c.contacts]; l[i] = { ...l[i], [k]: v }; setC({ ...c, contacts: l }) }
  return <Modal wide title={c.id ? 'Editar cliente' : 'Novo cliente'} onClose={onClose}
    footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" disabled={busy} onClick={save}>{busy ? 'Salvando…' : 'Salvar'}</button></>}>
    <Tabs value={tab} onChange={setTab} tabs={[['dados', 'Dados'], ['groups', 'Host Groups'], ['wa', 'Alertas'], ['rel', 'Relatórios / SLA'], ['contatos', 'Contatos'], ...(c.id ? [['portal', 'Acesso ao portal']] : [])]} />
    {tab === 'dados' && <>
      <div className="row r2"><Field label="NOME FANTASIA *"><input value={c.trade_name} onChange={set('trade_name')} /></Field><Field label="RAZÃO SOCIAL"><input value={c.legal_name || ''} onChange={set('legal_name')} /></Field></div>
      <div className="row r3"><Field label="CNPJ" hint={cnpjHint(c.cnpj)}><input inputMode="numeric" value={c.cnpj || ''} onChange={e => setC({ ...c, cnpj: maskCNPJ(e.target.value) })} placeholder="00.000.000/0000-00" /></Field><Field label="INSCRIÇÃO ESTADUAL"><input value={c.state_registration || ''} onChange={set('state_registration')} /></Field>
        <Field label="STATUS"><select value={c.status} onChange={set('status')}><option value="ativo">Ativo</option><option value="inativo">Inativo</option></select></Field></div>
      <div className="row r3"><Field label="ENDEREÇO"><input value={c.address || ''} onChange={set('address')} /></Field><Field label="CIDADE"><input value={c.city || ''} onChange={set('city')} /></Field><Field label="UF"><input maxLength={2} value={c.state || ''} onChange={e => setC({ ...c, state: e.target.value.toUpperCase() })} /></Field></div>
      <div className="row r3"><Field label="CONTATO"><input value={c.contact_name || ''} onChange={set('contact_name')} /></Field><Field label="E-MAIL"><input value={c.email || ''} onChange={set('email')} /></Field><Field label="TELEFONE"><input inputMode="tel" value={c.phone || ''} onChange={e => setC({ ...c, phone: maskPhone(e.target.value) })} placeholder="(00) 00000-0000" /></Field></div>
      <Field label="OBSERVAÇÕES"><textarea value={c.notes || ''} onChange={set('notes')} /></Field></>}
    {tab === 'groups' && <><p className="sub" style={{ marginBottom: 12 }}>Associe um ou mais Host Groups do Zabbix a este cliente. Eventos e relatórios dos hosts desses grupos passam a pertencer ao cliente.</p>
      {groups ? <MultiPick value={c.group_ids} onChange={v => setC({ ...c, group_ids: v })} placeholder="Buscar host group…"
        options={groups.map(g => ({ value: g.groupid, label: g.name, sub: g.clients.length ? 'em uso: ' + g.clients.join(', ') : g.host_count + ' host(s)' }))} /> : <Loading />}</>}
    {tab === 'wa' && <>
      <div className="row" style={{ display: 'flex', gap: 28, flexWrap: 'wrap' }}><Check label="Enviar alertas deste cliente por WhatsApp" checked={c.wa_enabled} onChange={v => setC({ ...c, wa_enabled: v })} />
        <Check label="Enviar alertas deste cliente por e-mail" checked={c.mail_enabled} onChange={v => setC({ ...c, mail_enabled: v })} /></div>
      <div className="row"><Field label="E-MAILS DE ALERTA" hint="Separe por vírgula. Vazio = usa os e-mails de relatório ou o e-mail do cliente."><input value={c.alert_emails || ''} onChange={set('alert_emails')} placeholder="noc@cliente.com.br, ti@cliente.com.br" disabled={!c.mail_enabled} /></Field></div>
      <div className="row r2"><Field label="GRUPO WHATSAPP (JID)" hint="Formato 1203630…@g.us. Sem grupo, usa o celular abaixo."><input value={c.whatsapp_group_jid || ''} onChange={set('whatsapp_group_jid')} placeholder="120363406164560822@g.us" /></Field>
        <Field label="WHATSAPP DO CLIENTE"><input inputMode="tel" value={c.whatsapp || ''} onChange={e => setC({ ...c, whatsapp: maskPhone(e.target.value) })} placeholder="(00) 00000-0000" /></Field></div>
      <div className="row r4"><Field label="SEVERIDADE MÍNIMA (WhatsApp e e-mail)"><select value={c.wa_min_severity} onChange={set('wa_min_severity')}>{SEV.map((s, i) => <option key={i} value={i}>{s}</option>)}</select></Field>
        <Field label="ATRASO ANTES DO ENVIO"><select value={c.wa_delay_s} onChange={set('wa_delay_s')}>{[[0, 'Imediato'], [60, '1 minuto'], [120, '2 minutos'], [300, '5 minutos'], [600, '10 minutos'], [900, '15 minutos']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
        <Field label="HORÁRIO (vazio = 24x7)" hint="ex.: 08:00-18:00"><input value={c.wa_hours || ''} onChange={set('wa_hours')} /></Field>
        <Field label="EM MANUTENÇÃO ATÉ"><input type="datetime-local" value={(c.maintenance_until || '').slice(0, 16)} onChange={e => setC({ ...c, maintenance_until: e.target.value ? new Date(e.target.value).toISOString() : null })} /></Field></div>
      <div className="row"><Check label="Enviar aviso de recuperação (RESOLVED)" checked={c.wa_send_recovery} onChange={v => setC({ ...c, wa_send_recovery: v })} /></div>
      <div className="row r2"><Field label="TEMPLATE DE ALERTA"><select value={c.wa_problem_template_id || ''} onChange={e => setC({ ...c, wa_problem_template_id: e.target.value ? Number(e.target.value) : null })}><option value="">Padrão</option>{(tpls || []).filter(t => t.kind === 'problem').map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
        <Field label="TEMPLATE DE RECUPERAÇÃO"><select value={c.wa_recovery_template_id || ''} onChange={e => setC({ ...c, wa_recovery_template_id: e.target.value ? Number(e.target.value) : null })}><option value="">Padrão</option>{(tpls || []).filter(t => t.kind === 'recovery').map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field></div></>}
    {tab === 'rel' && <>
      <div className="row r3"><Field label="SLA CONTRATADO (%)"><input type="number" step="0.01" min="0" max="100" value={c.sla_target} onChange={set('sla_target')} /></Field>
        <Field label="HORÁRIO DE ATENDIMENTO"><input value={c.service_hours || ''} onChange={set('service_hours')} placeholder="24x7 / Seg-Sex 8h-18h" /></Field></div>
      <Field label="E-MAILS PARA RELATÓRIOS" hint="Separe por vírgula"><textarea value={c.report_emails || ''} onChange={set('report_emails')} /></Field>
      {c.id && <div style={{ marginTop: 14 }}><label className="f">LOGO DO CLIENTE</label><input type="file" accept="image/*" onChange={async e => { try { await upload(`/clients/${c.id}/logo`, e.target.files[0]); toast('Logo enviada') } catch (x) { toast(x.message, true) } }} /></div>}</>}
    {tab === 'portal' && c.id && <PortalAccess client={c} />}
    {tab === 'contatos' && <>
      {c.contacts.map((x, i) => <div className="row r4" key={i}><input placeholder="Nome" value={x.name || ''} onChange={e => setContact(i, 'name', e.target.value)} /><input placeholder="Função" value={x.role || ''} onChange={e => setContact(i, 'role', e.target.value)} />
        <input placeholder="E-mail" value={x.email || ''} onChange={e => setContact(i, 'email', e.target.value)} /><div style={{ display: 'flex', gap: 6 }}><input placeholder="(00) 00000-0000" value={x.phone || ''} onChange={e => setContact(i, 'phone', maskPhone(e.target.value))} />
          <button className="btn sm danger" onClick={() => setC({ ...c, contacts: c.contacts.filter((_, j) => j !== i) })}>✕</button></div></div>)}
      <button className="btn" onClick={() => setC({ ...c, contacts: [...c.contacts, {}] })}><Plus />Adicionar contato</button></>}
  </Modal>
}

export function Clients() {
  const toast = useToast(); const me = useAuth(); const nav = useNavigate(); const [q, setQ] = useState(''); const [edit, setEdit] = useState(null); const [sp] = useSearchParams(); const [portalFor, setPortalFor] = useState(null)
  const { data, err, reload } = useLoad(() => get('/clients' + (q ? '?q=' + encodeURIComponent(q) : '')), [q])
  const open = async (id) => setEdit(await get('/clients/' + id))
  return <>
    <PageHead title="Clientes" desc="Cadastro de clientes e associação aos Host Groups do Zabbix">
      {can(me, 'clients.edit') && <button className="btn primary" onClick={() => setEdit({})}><Plus />Novo cliente</button>}</PageHead>
    {data && can(me, 'clients.edit') && <Coverage clients={data} open={sp.has('cobertura')} onChanged={reload} />}
    <div className="bar"><div className="grow"><input placeholder="Buscar por nome ou CNPJ…" value={q} onChange={e => setQ(e.target.value)} /></div></div>
    <Card pad={false}>{data ? <Table rows={data} onRow={r => nav('/clientes/' + r.id)} cols={[
      { h: 'Cliente', r: r => <><b>{r.trade_name}</b><div className="sub">{r.legal_name}</div></> }, { h: 'CNPJ', k: 'cnpj' }, { h: 'Cidade', r: r => [r.city, r.state].filter(Boolean).join('/') },
      { h: 'Host Groups', k: 'group_count' }, { h: 'SLA', r: r => fmtPct(r.sla_target) },
      { h: 'WhatsApp', r: r => r.wa_enabled ? <Pill tone="ok">ativo</Pill> : <Pill>desligado</Pill> },
      { h: 'Portal', r: r => can(me, 'clients.edit') ? <button className="btn sm" title="Usuários do cliente com acesso ao portal" onClick={e => { e.stopPropagation(); setPortalFor(r) }}><Users size={14} />{r.portal_users || 0}</button> : (r.portal_users || 0) },
      { h: 'Em aberto', r: r => r.open_events ? <Pill tone="bad">{r.open_events}</Pill> : <Pill tone="ok">0</Pill> },
      { h: 'Status', r: r => <Pill tone={r.status === 'ativo' ? 'info' : 'mut'}>{r.status}</Pill> },
      { h: '', r: r => can(me, 'clients.edit') && <div style={{ display: 'flex', gap: 6 }}><button className="btn sm" onClick={e => { e.stopPropagation(); open(r.id) }}><Pencil />Editar</button>
        <button className="btn sm danger" title="Excluir cliente" onClick={async e => { e.stopPropagation(); if (await deleteClient(r, toast)) reload() }}><Trash2 /></button></div> }]} /> : <Loading err={err} />}</Card>
    {portalFor && <Modal wide title={`Acesso ao portal · ${portalFor.trade_name}`} onClose={() => { setPortalFor(null); reload() }}><PortalAccess client={portalFor} bare /></Modal>}
    {edit && <ClientForm initial={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}</>
}

export function ClientDetail() {
  const { id } = useParams(); const me = useAuth(); const toast = useToast(); const nav = useNavigate(); const [preview, setPreview] = useState(false); const [days, setDays] = useState(30); const [edit, setEdit] = useState(null)
  const { data: d, err, reload } = useLoad(() => get(`/clients/${id}/dashboard?days=${days}`), [id, days], 30000)
  if (!d) return <Loading err={err} />
  const s = d.kpis.summary; const c = d.client
  const dd = Object.entries(d.kpis.by_day).map(([k, v]) => ({ d: k.slice(5).split('-').reverse().join('/'), v }))
  return <>
    <PageHead title={c.trade_name} desc={[c.legal_name, c.cnpj].filter(Boolean).join(' · ')}>
      <Link className="btn" to="/clientes">← Clientes</Link>
      <select style={{ width: 'auto' }} value={days} onChange={e => setDays(+e.target.value)}>{[7, 30, 90].map(x => <option key={x} value={x}>Últimos {x} dias</option>)}</select>
      {can(me, 'clients.edit') && <button className="btn primary" onClick={async () => setEdit(await get('/clients/' + id))}><Pencil />Editar</button>}
      <button className="btn" title="Ver exatamente o que o cliente enxerga no portal" onClick={() => setPreview(true)}><Eye />Ver portal do cliente</button>
      {can(me, 'clients.edit') && <button className="btn danger" onClick={async () => { if (await deleteClient(c, toast)) nav('/clientes') }}><Trash2 />Excluir</button>}</PageHead>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <Stat label="Disponibilidade" value={fmtPct(s.availability, 3)} tone={s.sla_met === false ? 'bad' : 'ok'} desc={`SLA contratado ${fmtPct(c.sla_target)} · ${s.sla_met === false ? 'não atingido' : 'atingido'}`} />
      <Stat label="Incidentes" value={s.incidents} desc={`${s.resolved} resolvidos · ${s.open} em aberto`} tone={s.open ? 'warn' : ''} />
      <Stat label="MTTR / MTBF" value={fmtDur(s.mttr_s)} desc={`MTBF ${fmtDur(s.mtbf_s)}`} />
      <Stat label="Hosts / Links" value={`${s.hosts_total} / ${d.links}`} desc={`${s.hosts_affected} afetado(s) no período`} />
    </div>
    {(d.backup?.enabled || d.endpoints?.enabled) && <div className="grid g2" style={{ marginBottom: 16 }}>
      {d.backup?.enabled && <Card title="Backup (Acronis)" actions={<Link className="btn sm" to="/protecao">Abrir painel</Link>}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>{Object.entries(d.backup.counts).map(([k, v]) => <Pill key={k} tone={k === 'ok' ? 'ok' : k === 'sem dados' || k === 'ignorado' ? 'mut' : 'bad'}>{v} {k === 'ok' ? 'em dia' : k}</Pill>)}</div>
        {d.backup.alerts.length ? d.backup.alerts.slice(0, 5).map(a => <div key={a.id} className="sub" style={{ padding: '3px 0' }}><SevBadge n={a.severity} /> <b>{a.host}</b> — {a.trigger_name}</div>) : <div className="sub">✅ Nenhum problema de backup.</div>}</Card>}
      {d.endpoints?.enabled && <Card title="Estações (FortiClient EMS)" actions={<Link className="btn sm" to="/protecao">Abrir painel</Link>}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>{Object.entries(d.endpoints.counts).map(([k, v]) => <Pill key={k} tone={k === 'online' ? 'ok' : k === 'offline' || k === 'ignorado' ? 'mut' : 'warn'}>{v} {k}</Pill>)}</div>
        {d.endpoints.alerts.length ? d.endpoints.alerts.slice(0, 5).map(a => <div key={a.id} className="sub" style={{ padding: '3px 0' }}><SevBadge n={a.severity} /> <b>{a.host}</b> — {a.trigger_name}</div>) : <div className="sub">✅ Nenhum problema nas estações.</div>}</Card>}
    </div>}
    <div className="grid g-2-1" style={{ marginBottom: 16 }}>
      <Card title="Incidentes por dia"><div style={{ height: 230 }}><ResponsiveContainer><BarChart data={dd}><CartesianGrid vertical={false} stroke="#eef1f8" /><XAxis dataKey="d" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} width={30} tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="v" name="Incidentes" fill="#1e73f8" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer></div></Card>
      <Card title="Configuração de alertas"><div className="kv"><b>WhatsApp</b><span>{c.wa_enabled ? 'ativo' : 'desligado'}</span><b>Grupo</b><span className="mono" style={{ fontSize: 13 }}>{c.whatsapp_group_jid || '—'}</span>
        <b>Sev. mínima</b><span>{SEV[c.wa_min_severity]}</span><b>Atraso</b><span>{c.wa_delay_s}s</span><b>Recovery</b><span>{c.wa_send_recovery ? 'sim' : 'não'}</span><b>Regras</b><span>{d.rules.length} personalizada(s)</span></div></Card>
    </div>
    <Card title={`Eventos ativos (${d.active_events.length})`} pad={false} style={{ marginBottom: 16 }}>
      <Table rows={d.active_events} empty="Nenhum evento ativo." cols={[{ h: 'Sev.', r: r => <SevBadge n={r.severity} /> }, { h: 'Host', k: 'host' }, { h: 'Problema', r: r => <div className="trunc">{r.trigger_name}</div> }, { h: 'Início', r: r => fmtDT(r.started_at) }]} /></Card>
    <div className="grid g2">
      <Card title="Hosts" pad={false}><Table rows={d.hosts} cols={[{ h: '', r: r => <i className="dot" style={{ background: r.available === 2 ? '#bd1723' : r.available === 1 ? '#16a34a' : '#b8c0d8' }} /> , w: 30 }, { h: 'Host', k: 'name' }, { h: 'IP', k: 'ip' }]} /></Card>
      <Card title="Histórico recente" pad={false}><Table rows={d.history.slice(0, 15)} cols={[{ h: 'Host', k: 'host' }, { h: 'Início', r: r => fmtDT(r.started_at) }, { h: 'Duração', r: r => fmtDur(r.duration_s) }, { h: '', r: r => <StatusBadge s={r.status} /> }]} /></Card>
    </div>
    {can(me, 'clients.edit') && <div style={{ marginTop: 16 }}><PortalAccess client={c} /></div>}
    {preview && <Modal wide title={`Portal de ${c.trade_name} (pré-visualização)`} onClose={() => setPreview(false)}><div className="portal-embed"><Portal clientId={c.id} embedded /></div></Modal>}
    {edit && <ClientForm initial={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}</>
}
