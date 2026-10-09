import React, { useState } from 'react'
import { Pencil, Play, Plus, Trash2 } from 'lucide-react'
import { get, post, put, del, fmtDT, fmtDur } from '../api'
import { Card, Check, Field, Loading, Modal, PageHead, Pill, Table, Tabs, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'
import { ResolvedLine } from './Dest'

const WD = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
const FREQ = { daily: 'Diário', weekly: 'Semanal', monthly: 'Mensal', custom: 'Personalizado' }
const PER = { prev_day: 'Dia anterior', prev_week: 'Semana anterior', prev_month: 'Mês anterior', last_n_days: 'Últimos N dias' }

function Form({ s, reports, clients, onClose, onSaved }) {
  const [x, setX] = useState({ name: '', report_id: reports[0]?.id, frequency: 'monthly', run_time: '08:00', weekday: 0, month_day: 1, interval_days: 7, period_mode: 'prev_month', period_days: 7, wa_dest: 'client', email_to: 'client', email_cc: '', email_bcc: '', subject: 'Relatório Mensal de Disponibilidade — {CLIENTE} — {PERIODO}', enabled: true, ...s })
  const toast = useToast(); const set = k => e => setX({ ...x, [k]: e.target.value }); const n = k => e => setX({ ...x, [k]: e.target.value === '' ? null : Number(e.target.value) })
  const save = async () => { try { const b = { ...x, wa_dest: x.wa_dest || null, email_to: x.email_to || null, email_cc: x.email_cc || null, email_bcc: x.email_bcc || null }
    x.id ? await put('/routines/schedules/' + x.id, b) : await post('/routines/schedules', b); toast('Rotina salva'); onSaved() } catch (e) { toast(e.message, true) } }
  return <Modal title={x.id ? 'Editar rotina' : 'Nova rotina de relatório'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" onClick={save}>Salvar</button></>}>
    <div className="row r2"><Field label="NOME *"><input value={x.name} onChange={set('name')} placeholder="SLA Mensal — Cliente X" /></Field>
      <Field label="RELATÓRIO"><select value={x.report_id || ''} onChange={n('report_id')}>{reports.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></Field></div>
    <div className="row r4"><Field label="FREQUÊNCIA"><select value={x.frequency} onChange={set('frequency')}>{Object.entries(FREQ).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="HORÁRIO"><input type="time" value={x.run_time} onChange={set('run_time')} /></Field>
      {x.frequency === 'weekly' && <Field label="DIA DA SEMANA"><select value={x.weekday} onChange={n('weekday')}>{WD.map((d, i) => <option key={i} value={i}>{d}</option>)}</select></Field>}
      {x.frequency === 'monthly' && <Field label="DIA DO MÊS"><input type="number" min="1" max="31" value={x.month_day} onChange={n('month_day')} /></Field>}
      {x.frequency === 'custom' && <Field label="A CADA (dias)"><input type="number" min="1" value={x.interval_days} onChange={n('interval_days')} /></Field>}</div>
    <div className="row r3"><Field label="PERÍODO COBERTO"><select value={x.period_mode} onChange={set('period_mode')}>{Object.entries(PER).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      {x.period_mode === 'last_n_days' && <Field label="N DIAS"><input type="number" min="1" value={x.period_days} onChange={n('period_days')} /></Field>}</div>
    <div className="row r2"><Field label="DESTINO WHATSAPP" hint='"client" = grupo/celular do cadastro do cliente; ou informe um JID/número'><input value={x.wa_dest || ''} onChange={set('wa_dest')} /></Field><Field label="E-MAIL (Para)" hint='"client" = e-mails de relatório do cadastro do cliente; ou informe endereços separados por vírgula'><input value={x.email_to || ''} onChange={set('email_to')} /></Field></div>
    <div className="row r2"><Field label="CC"><input value={x.email_cc || ''} onChange={set('email_cc')} /></Field><Field label="BCC"><input value={x.email_bcc || ''} onChange={set('email_bcc')} /></Field></div>
    <ResolvedLine client={clients.find(c => c.id === (reports.find(r => r.id === x.report_id) || {}).client_id)} wa={x.wa_dest} email={x.email_to} />
    <Field label="ASSUNTO DO E-MAIL" hint="Macros: {CLIENTE} {PERIODO}"><input value={x.subject} onChange={set('subject')} /></Field>
    <div style={{ marginTop: 12 }}><Check label="Rotina habilitada" checked={x.enabled} onChange={v => setX({ ...x, enabled: v })} /></div></Modal>
}

function Dest({ r }) {
  if (!r) return null
  return <div style={{ fontSize: 12.5, maxWidth: 260 }}>
    {r.wa ? <div title={r.wa_kind}>WhatsApp: <span className="mono">{r.wa}</span></div> : null}
    {r.email ? <div className="trunc" title={r.email}>E-mail: {r.email}</div> : null}
    {r.warnings.map(w => <div key={w} style={{ color: '#bd1723' }}>⚠ {w}</div>)}
    {r.client && !r.warnings.length && <div className="sub">cliente: {r.client}</div>}</div>
}

export default function Routines() {
  const me = useAuth(); const toast = useToast(); const [tab, setTab] = useState('sch'); const [ed, setEd] = useState(null)
  const sch = useLoad(() => get('/routines/schedules'), []); const jobs = useLoad(() => get('/routines/jobs'), [], 15000); const reps = useLoad(() => get('/reports'), []); const cls = useLoad(() => get('/clients'), [])
  const edit = can(me, 'routines.edit')
  const run = async (s) => { try { toast('Gerando e enviando…'); await post(`/routines/schedules/${s.id}/run`); toast('Execução concluída'); sch.reload() } catch (e) { toast(e.message, true) } }
  return <>
    <PageHead title="Rotinas" desc="Relatórios agendados e tarefas automáticas da plataforma, com o resultado da última execução">
      {edit && tab === 'sch' && <button className="btn primary" onClick={() => setEd({})} disabled={!reps.data?.length}><Plus />Nova rotina</button>}</PageHead>
    <Tabs value={tab} onChange={setTab} tabs={[['sch', 'Relatórios agendados'], ['jobs', 'Rotinas do sistema']]} />
    {tab === 'sch' && <Card pad={false}>{sch.data ? <Table rows={sch.data} empty={reps.data?.length ? 'Nenhuma rotina agendada.' : 'Crie um relatório primeiro (menu Relatórios).'} cols={[
      { h: 'Rotina', r: r => <b>{r.name}</b> }, { h: 'Relatório', k: 'report_name' }, { h: 'Frequência', r: r => `${FREQ[r.frequency]} · ${r.run_time}` }, { h: 'Período', r: r => PER[r.period_mode] },
      { h: 'Envia para', r: r => <Dest r={r.resolved} /> }, { h: 'Próxima', r: r => fmtDT(r.next_run) }, { h: 'Última', r: r => <><div>{fmtDT(r.last_run)}</div><div className="sub">{r.last_status}</div></> }, { h: 'Estado', r: r => <Pill tone={r.enabled ? 'ok' : 'mut'}>{r.enabled ? 'ativa' : 'pausada'}</Pill> },
      { h: '', r: r => edit && <div style={{ display: 'flex', gap: 6 }}><button className="btn sm primary" title="Executar agora" onClick={() => run(r)}><Play /></button><button className="btn sm" onClick={() => setEd(r)}><Pencil /></button>
        <button className="btn sm danger" onClick={async () => { if (confirm('Excluir rotina?')) { await del('/routines/schedules/' + r.id); sch.reload() } }}><Trash2 /></button></div> }]} /> : <Loading />}</Card>}
    {tab === 'jobs' && <Card pad={false}>{jobs.data ? <Table rows={jobs.data} cols={[{ h: 'Rotina', r: r => <b>{r.label}</b> }, { h: 'Frequência', r: r => 'a cada ' + fmtDur(r.interval_s) }, { h: 'Última execução', r: r => fmtDT(r.last_run) }, { h: 'Próxima', r: r => fmtDT(r.next_run) },
      { h: 'Duração', r: r => r.last_duration_ms != null ? r.last_duration_ms + ' ms' : '—' }, { h: 'Status', r: r => r.status ? <Pill tone={r.status === 'ok' ? 'ok' : 'bad'}>{r.status}</Pill> : <Pill>aguardando</Pill> },
      { h: 'Erro', r: r => r.error ? <div className="trunc" style={{ color: 'var(--crit)', maxWidth: 280 }} title={r.error}>{r.error}</div> : '' },
      { h: 'Habilitada', r: r => <input type="checkbox" style={{ width: 'auto' }} checked={r.enabled} disabled={!edit} onChange={async e => { await put(`/routines/jobs/${r.name}?enabled=${e.target.checked}`); jobs.reload() }} /> }]} /> : <Loading />}</Card>}
    {ed && reps.data && cls.data && <Form s={ed} reports={reps.data} clients={cls.data} onClose={() => setEd(null)} onSaved={() => { setEd(null); sch.reload() }} />}</>
}
