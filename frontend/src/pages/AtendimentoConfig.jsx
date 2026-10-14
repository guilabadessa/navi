import React, { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from 'lucide-react'
import { get, post, put, del } from '../api'
import { Card, Check, Field, Loading, Modal, PageHead, Pill, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'
import AtNav from './AtNav'

const COLORS = ['#1e73f8', '#0f8b8d', '#7b3fe4', '#d97706', '#bd1723', '#2e7d32', '#6b7a99', '#d6336c']
const splitList = (t) => t.split(/[\n,;]+/).map(x => x.trim()).filter(Boolean)

function ColorPick({ value, onChange, disabled }) {
  return <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>{COLORS.map(c => <button key={c} type="button" aria-label={'Cor ' + c} disabled={disabled} onClick={() => onChange(c)}
    style={{ width: 24, height: 24, borderRadius: '50%', background: c, border: value === c ? '3px solid var(--navy)' : '2px solid transparent', cursor: 'pointer' }} />)}
    <input type="color" value={value} onChange={e => onChange(e.target.value)} disabled={disabled} aria-label="Outra cor" style={{ width: 32, height: 28, padding: 0, border: 0 }} /></div>
}

function QueueForm({ q, onClose, onSaved }) {
  const toast = useToast()
  const [x, setX] = useState({ name: '', color: '#1e73f8', active: true, alert_enabled: false, alert_to: '', wait_alert_min: '', ...q, alert_to: (q?.alert_to || []).join('\n'), wait_alert_min: q?.wait_alert_min ?? '' })
  const save = async () => {
    const body = { name: x.name, color: x.color, active: x.active, alert_enabled: x.alert_enabled, alert_to: splitList(x.alert_to), wait_alert_min: x.wait_alert_min === '' ? null : +x.wait_alert_min }
    try { q?.id ? await put('/atendimento/queue-defs/' + q.id, body) : await post('/atendimento/queue-defs', body); toast('Fila salva'); onSaved() } catch (e) { toast(e.message, true) }
  }
  return <Modal title={q?.id ? 'Editar fila' : 'Nova fila'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" disabled={!x.name.trim()} onClick={save}>Salvar</button></>}>
    <Field label="NOME DA FILA *"><input autoFocus value={x.name} onChange={e => setX({ ...x, name: e.target.value })} placeholder="Ex.: Comercial, Financeiro, RH…" /></Field>
    <Field label="COR"><ColorPick value={x.color} onChange={c => setX({ ...x, color: c })} /></Field>
    <Check label={x.system ? 'Fila ativa (a fila Geral do sistema não pode ser desativada)' : 'Fila ativa'} checked={x.active} onChange={v => !x.system && setX({ ...x, active: v })} />
    <h3 style={{ margin: '16px 0 6px' }}>Avisar quando alguém entrar na fila</h3>
    <Check label="Enviar aviso por WhatsApp" checked={x.alert_enabled} onChange={v => setX({ ...x, alert_enabled: v })} />
    <Field label="NÚMEROS OU IDs DE GRUPO (um por linha)" hint="Ex.: 120363...@g.us ou (14) 99999-9999"><textarea style={{ minHeight: 80 }} value={x.alert_to} onChange={e => setX({ ...x, alert_to: e.target.value })} disabled={!x.alert_enabled} /></Field>
    <Field label="ESPERA EM ALERTA (min)" hint="Vazio usa o tempo padrão das configurações gerais. A fila fica vermelha no monitor acima deste tempo."><input type="number" min="1" max="240" value={x.wait_alert_min} onChange={e => setX({ ...x, wait_alert_min: e.target.value })} /></Field>
  </Modal>
}

function QueuesSection({ edit }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/atendimento/queue-defs'), []); const [ed, setEd] = useState(null)
  if (!data) return <Loading />
  const move = async (i, d) => { const ids = data.map(x => x.id); const j = i + d; if (j < 0 || j >= ids.length) return; [ids[i], ids[j]] = [ids[j], ids[i]]
    try { await put('/atendimento/queue-defs/order', { ids }); reload() } catch (e) { toast(e.message, true) } }
  const remove = async (q) => { if (!confirm(`Excluir a fila “${q.name}”?`)) return; try { await del('/atendimento/queue-defs/' + q.id); toast('Fila excluída'); reload() } catch (e) { toast(e.message, true) } }
  return <Card title="Filas de atendimento" actions={edit && <button className="btn primary" onClick={() => setEd({})}><Plus size={15} />Nova fila</button>} pad={false}>
    <p className="sub" style={{ padding: '12px 14px' }}>Cada fila é um setor. Todos os analistas veem todas as filas; a fila define apenas para onde o cliente vai e quem é avisado. Use as filas no <b>Fluxo</b> (passo “Entrar na fila”).</p>
    {data.map((q, i) => <div key={q.id} className="cfg-row">
      <i className="cfg-dot" style={{ background: q.color }} />
      <div className="grow"><b>{q.name}</b> {q.system && <Pill tone="info">sistema</Pill>} {!q.active && <Pill tone="mut">inativa</Pill>}
        <div className="sub">{q.open} conversa(s) aberta(s) · {q.alert_enabled && q.alert_to.length ? `avisa ${q.alert_to.length} destino(s)` : 'sem aviso'} · espera em alerta {q.wait_alert_min ? q.wait_alert_min + ' min' : 'padrão'}</div></div>
      {edit && <><button className="btn" aria-label="Subir" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={14} /></button>
        <button className="btn" aria-label="Descer" disabled={i === data.length - 1} onClick={() => move(i, 1)}><ArrowDown size={14} /></button>
        <button className="btn" onClick={() => setEd(q)}><Pencil size={14} />Editar</button>
        {!q.system && <button className="btn" aria-label="Excluir" onClick={() => remove(q)}><Trash2 size={14} /></button>}</>}
    </div>)}
    {ed && <QueueForm q={ed} onClose={() => setEd(null)} onSaved={() => { setEd(null); reload() }} />}
  </Card>
}

function useCfg() {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/atendimento/config'), []); const [f, setF] = useState(null)
  useEffect(() => { if (data) setF(data) }, [data])
  const save = async (patch) => { try { await put('/atendimento/config', { ...f, ...patch }); toast('Salvo'); reload() } catch (e) { toast(e.message, true) } }
  return { f, setF, save }
}

function RepliesSection({ edit }) {
  const { f, setF, save } = useCfg(); const [ed, setEd] = useState(null)
  if (!f) return <Loading />
  const list = f.quick_replies || []
  const commit = (next) => { setF({ ...f, quick_replies: next }); save({ quick_replies: next }) }
  return <Card title="Respostas prontas" actions={edit && <button className="btn primary" onClick={() => setEd({ i: -1, title: '', text: '' })}><Plus size={15} />Nova resposta</button>} pad={false}>
    <p className="sub" style={{ padding: '12px 14px' }}>Textos que o analista insere no chat com um clique.</p>
    {list.map((r, i) => <div key={i} className="cfg-row"><div className="grow"><b>{r.title}</b><div className="sub" style={{ whiteSpace: 'pre-wrap' }}>{r.text}</div></div>
      {edit && <><button className="btn" onClick={() => setEd({ i, ...r })}><Pencil size={14} />Editar</button><button className="btn" aria-label="Excluir" onClick={() => confirm('Excluir esta resposta?') && commit(list.filter((_, j) => j !== i))}><Trash2 size={14} /></button></>}</div>)}
    {!list.length && <div className="empty">Nenhuma resposta pronta.</div>}
    {ed && <Modal title={ed.i < 0 ? 'Nova resposta pronta' : 'Editar resposta'} onClose={() => setEd(null)} footer={<><button className="btn" onClick={() => setEd(null)}>Cancelar</button>
      <button className="btn primary" disabled={!ed.title.trim() || !ed.text.trim()} onClick={() => { const r = { title: ed.title.trim(), text: ed.text.trim() }; commit(ed.i < 0 ? [...list, r] : list.map((x, j) => j === ed.i ? r : x)); setEd(null) }}>Salvar</button></>}>
      <Field label="TÍTULO"><input autoFocus value={ed.title} onChange={e => setEd({ ...ed, title: e.target.value })} maxLength={60} /></Field>
      <Field label="TEXTO"><textarea style={{ minHeight: 110 }} value={ed.text} onChange={e => setEd({ ...ed, text: e.target.value })} maxLength={1000} /></Field></Modal>}
  </Card>
}

function GeneralSection({ edit }) {
  const { f, setF, save } = useCfg()
  if (!f) return <Loading />
  const set = (k, v) => setF({ ...f, [k]: v })
  return <Card title="Geral">
    <div className="row r2"><Field label="TEMPO PADRÃO SEM RESPOSTA NO FLUXO (min)" hint="Vale para os passos do fluxo que não definem o próprio tempo."><input type="number" min="1" max="60" value={f.menu_timeout_min} onChange={e => set('menu_timeout_min', +e.target.value)} disabled={!edit} /></Field>
      <Field label="ESPERA EM ALERTA PADRÃO (min)" hint="A fila fica vermelha no monitor acima deste tempo (cada fila pode ter o seu)."><input type="number" min="1" max="240" value={f.wait_alert_min} onChange={e => set('wait_alert_min', +e.target.value)} disabled={!edit} /></Field></div>
    <Field label="MENSAGEM AO ENCERRAR (quando o analista encerra)"><input value={f.closing_message} onChange={e => set('closing_message', e.target.value)} disabled={!edit} /></Field>
    <div className="row r2"><Field label="ENCERRAR POR INATIVIDADE (horas)" hint="Sem mensagem de ninguém por esse tempo, o atendimento é encerrado. 0 desliga."><input type="number" min="0" max="720" value={f.inactivity_hours} onChange={e => set('inactivity_hours', +e.target.value)} disabled={!edit} /></Field>
      <Field label="MENSAGEM DE INATIVIDADE"><input value={f.inactivity_message} onChange={e => set('inactivity_message', e.target.value)} disabled={!edit} /></Field></div>
    {edit && <button className="btn primary" onClick={() => save({})}>Salvar</button>}
  </Card>
}

const SECTIONS = [['filas', 'Filas', QueuesSection], ['respostas', 'Respostas prontas', RepliesSection], ['geral', 'Geral', GeneralSection]]

export default function AtendimentoConfig() {
  const me = useAuth(); const edit = can(me, 'settings.edit'); const [sec, setSec] = useState('filas')
  const Cur = SECTIONS.find(s => s[0] === sec)[2]
  return <>
    <PageHead title="Configurações do atendimento" desc="Filas, respostas prontas e regras gerais do atendimento por WhatsApp" />
    <AtNav />
    {!edit && <p className="sub" style={{ marginBottom: 12 }}>Você pode visualizar. Somente quem tem permissão de configuração altera.</p>}
    <div className="cfg-grid"><div className="cfg-side">{SECTIONS.map(([k, l]) => <button key={k} className={sec === k ? 'on' : ''} onClick={() => setSec(k)}>{l}</button>)}</div>
      <div><Cur edit={edit} /></div></div>
  </>
}
