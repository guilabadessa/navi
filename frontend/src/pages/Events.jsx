import React, { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Download, Bookmark, BellOff, Bell } from 'lucide-react'
import { get, put, post, del, download, fmtDT, fmtDur, SEV } from '../api'
import { Card, Drawer, Field, KIND, KindPill, LiveDur, Loading, Modal, PERIODS, PageHead, Pager, Pill, SevBadge, StatusBadge, Table, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'

function Diag({ id }) {
  const { data: d, err } = useLoad(() => get('/alerts/diagnose/' + id), [id])
  if (err) return null
  if (!d) return null
  return <div className="card" style={{ padding: 16, marginTop: 18, borderColor: d.will_alert ? '#bfe5cb' : '#f3d3a0' }}>
    <h3 style={{ marginBottom: 10 }}>{d.will_alert ? '✅ Este evento atende às regras de alerta' : '⚠ Este evento NÃO gera alerta de WhatsApp'}</h3>
    {d.checks.map((c, i) => <div key={i} style={{ display: 'flex', gap: 10, padding: '6px 0', borderTop: i ? '1px solid #eef1f8' : 'none', fontSize: 14 }}>
      <span style={{ color: c.ok ? 'var(--ok)' : 'var(--crit)', fontWeight: 700 }}>{c.ok ? '✔' : '✖'}</span><div><b>{c.label}</b><div className="sub">{c.detail}</div></div></div>)}</div>
}

const DURATIONS = [['1', '1 hora'], ['4', '4 horas'], ['24', '24 horas'], ['168', '7 dias'], ['720', '30 dias'], ['', 'Para sempre']]
const untilTxt = (s) => s.until ? 'até ' + fmtDT(s.until) : 'para sempre'

// Silenciar alertas: o evento continua registrado, mas nao gera mensagem (problema, recuperacao, escalonamento e resumo)
function SilenceModal({ events, onClose, onDone }) {
  const toast = useToast(); const first = events[0]
  const [scope, setScope] = useState('host'); const [hours, setHours] = useState('24'); const [reason, setReason] = useState(''); const [busy, setBusy] = useState(false)
  const many = events.length > 1; const kind = first.kind || 'infra'
  const opts = [['host', 'Todos os problemas deste host', many ? 'cada host dos eventos selecionados' : first.host],
    ['problem_host', 'Só este problema neste host', many ? 'cada problema selecionado' : first.trigger_name],
    ['problem', 'Este problema em todos os hosts', many ? 'cada problema selecionado' : first.trigger_name]]
  const go = async () => {
    setBusy(true)
    try { await post('/event-silences', { event_ids: events.map(e => e.id), scope, hours: hours ? +hours : null, reason: reason.trim() || null }); toast('Alertas silenciados'); onDone() }
    catch (e) { toast(e.message, true) } finally { setBusy(false) }
  }
  return <Modal title={many ? `Silenciar alertas (${events.length} eventos)` : 'Silenciar alertas'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn primary" disabled={busy} onClick={go}><BellOff size={15} />Silenciar</button></>}>
    <p className="sub" style={{ marginBottom: 10 }}>Os eventos continuam registrados aqui, mas deixam de gerar mensagem de alerta, recuperação, escalonamento e resumo diário.</p>
    <Field label="O QUE SILENCIAR">{opts.map(([v, l, d]) => <label key={v} className="check" style={{ display: 'block', marginBottom: 6 }}><input type="radio" name="scope" checked={scope === v} onChange={() => setScope(v)} /> <b>{l}</b><div className="sub" style={{ marginLeft: 22 }}>{d}</div></label>)}</Field>
    <Field label="POR QUANTO TEMPO"><select value={hours} onChange={e => setHours(e.target.value)}>{DURATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
    <Field label="MOTIVO (opcional)"><input value={reason} maxLength={255} onChange={e => setReason(e.target.value)} placeholder="Ex.: troca do equipamento, janela combinada com o cliente" /></Field>
    {scope === 'host' && !hours && ['backup', 'endpoint'].includes(kind) && <p className="sub">A máquina também será marcada como <b>ignorada</b> em Backup e Endpoints (o mesmo “ignorar” de lá). Ao reativar aqui, ela volta a ser monitorada.</p>}
  </Modal>
}

function SilencedList({ onClose, onChanged }) {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/event-silences'), [])
  const off = async (s) => { if (!confirm('Reativar os alertas deste silêncio?')) return; try { await del('/event-silences/' + s.id); toast('Alertas reativados'); reload(); onChanged() } catch (e) { toast(e.message, true) } }
  return <Drawer title="Alertas silenciados" onClose={onClose}>{!data ? <Loading /> : data.length ? data.map(s => <div key={s.id} className="card" style={{ padding: 14, marginBottom: 10 }}>
    <div style={{ display: 'flex', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}><Pill tone="warn">{s.scope_label}</Pill><KindPill k={s.kind} /><Pill tone="mut">{untilTxt(s)}</Pill>{s.ignored_asset && <Pill tone="info">máquina ignorada em Backup/Endpoints</Pill>}</div>
    {s.host && <div><b>Host:</b> {s.host}</div>}{(s.trigger_name || s.triggerid) && <div><b>Problema:</b> {s.trigger_name || `trigger ${s.triggerid}`}</div>}
    {s.reason && <div className="sub">Motivo: {s.reason}</div>}<div className="sub">Por {s.created_by || '—'} em {fmtDT(s.created_at)} · {s.open_events} evento(s) em aberto silenciado(s)</div>
    <button className="btn sm" style={{ marginTop: 8 }} onClick={() => off(s)}><Bell size={14} />Reativar alertas</button></div>) : <div className="sub">Nenhum alerta silenciado no momento.</div>}</Drawer>
}

function Detail({ id, onClose, onSilence, onChanged }) {
  const me = useAuth(); const toast = useToast(); const { data: e, err } = useLoad(() => get('/events/' + id), [id]); const [n, setN] = useState(null)
  const reactivate = async () => { if (!confirm('Reativar os alertas deste silêncio?')) return; try { await del('/event-silences/' + e.silenced.id); toast('Alertas reativados'); onChanged() } catch (x) { toast(x.message, true) } }
  return <Drawer title={`Evento ${e ? e.zbx_eventid : ''}`} onClose={onClose}>{!e ? <Loading err={err} /> : <>
    <div style={{ marginBottom: 14, display: 'flex', gap: 8 }}><StatusBadge s={e.status} /><SevBadge n={e.severity} /></div>
    <div className="kv"><b>Cliente</b><span>{e.client_id ? <a href={`/cliente/clientes/${e.client_id}`} onClick={ev => { ev.preventDefault(); window.location.assign(`/cliente/clientes/${e.client_id}`) }}>{e.client_name}</a> : <span style={{ color: 'var(--orange)' }}>sem cliente associado</span>}</span>
      <b>Tecnologia</b><span><KindPill k={e.kind} /></span><b>{ITEM[e.kind || 'infra']}</b><span>{e.host}</span>{e.ip && <><b>IP</b><span>{e.ip}</span></>}<b>{(e.kind || 'infra') === 'infra' ? 'Trigger' : 'Problema'}</b><span>{e.trigger_name}</span><b>{(e.kind || 'infra') === 'infra' ? 'Item' : 'Detalhe'}</b><span>{e.item_name || '—'}</span>
      <b>Grupos</b><span>{(e.group_names || []).map(g => <span className="chip" key={g}>{g}</span>)}</span><b>Início</b><span>{fmtDT(e.started_at)}</span><b>Recuperação</b><span>{e.recovered_at ? fmtDT(e.recovered_at) : 'em aberto'}</span>
      <b>Duração</b><span>{e.status === 'PROBLEM' ? <LiveDur since={e.started_at} /> : fmtDur(e.duration_s)}</span><b>Valor</b><span>{e.opdata || '—'}</span><b>Fonte</b><span>{e.source}</span><b>WhatsApp</b><span>{e.wa_status || '—'} {e.wa_message_id && <span className="sub mono">· {e.wa_message_id.slice(0, 14)}…</span>}</span></div>
    {e.silenced ? <div className="card" style={{ padding: 14, marginBottom: 12, borderColor: '#f3d3a0' }}><b><BellOff size={14} /> Alertas silenciados</b> ({untilTxt(e.silenced)}){e.silenced.reason ? ' · ' + e.silenced.reason : ''}
      {can(me, 'events.edit') && <div style={{ marginTop: 8 }}><button className="btn sm" onClick={reactivate}><Bell size={14} />Reativar alertas</button></div>}</div>
      : can(me, 'events.edit') && <button className="btn" style={{ marginBottom: 12 }} onClick={() => onSilence([e])}><BellOff size={15} />Silenciar alertas…</button>}
    {e.recurrence && e.recurrence.last_30d > 1 && <div className="sub" style={{ marginBottom: 10 }}>↻ Este problema ocorreu <b>{e.recurrence.last_7d}</b> vez(es) nos últimos 7 dias e <b>{e.recurrence.last_30d}</b> nos últimos 30 neste host.</div>}
    <Diag id={id} />
    <h3 style={{ margin: '22px 0 8px' }}>Mensagens enviadas</h3>
    {e.dispatches.length ? e.dispatches.map(d => <div key={d.id} className="card" style={{ padding: 14, marginBottom: 10 }}><div style={{ display: 'flex', gap: 8, marginBottom: 8 }}><Pill tone={d.kind === 'problem' ? 'bad' : 'ok'}>{d.kind}</Pill><Pill tone={d.status === 'sent' ? 'ok' : d.status === 'failed' ? 'bad' : 'warn'}>{d.status}</Pill><span className="sub">{fmtDT(d.sent_at || d.due_at)}</span></div>
      <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontFamily: 'inherit', fontSize: 14 }}>{d.text || '(aguardando envio)'}</pre>{d.error && <div style={{ color: 'var(--crit)', marginTop: 6 }}>{d.error}</div>}</div>) : <div className="sub">Nenhuma mensagem para este evento.</div>}
    <h3 style={{ margin: '22px 0 8px' }}>Observações</h3>
    <textarea value={n ?? e.notes ?? ''} onChange={x => setN(x.target.value)} disabled={!can(me, 'events.edit')} />
    {can(me, 'events.edit') && <button className="btn primary" style={{ marginTop: 10 }} onClick={async () => { await put(`/events/${id}/notes`, { notes: n ?? e.notes }); toast('Observação salva') }}>Salvar observação</button>}
  </>}</Drawer>
}

const ITEM = { infra: 'Host', backup: 'Item de backup', endpoint: 'Endpoint', cloud: 'Máquina' }
const SAVED = 'navi.events.saved'
const loadSaved = () => { try { return JSON.parse(localStorage.getItem(SAVED) || '[]') } catch { return [] } }

export default function Events() {
  const [sp] = useSearchParams()
  const [status, setStatus] = useState(sp.get('status') || ''); const [q, setQ] = useState(sp.get('q') || ''); const [sev, setSev] = useState(sp.get('min_severity') || ''); const [page, setPage] = useState(1)
  const [days, setDays] = useState(sp.has('days') ? sp.get('days') : '0.0417'); const [sel, setSel] = useState(sp.get('open') ? Number(sp.get('open')) : null); const [cl, setCl] = useState(sp.get('client_id') || '')
  const [saved, setSaved] = useState(loadSaved()); const toast = useToast(); const [kind, setKind] = useState(sp.get('kind') || '')
  const me = useAuth(); const canEdit = can(me, 'events.edit'); const [silF, setSilF] = useState(sp.get('silenced') || ''); const [picked, setPicked] = useState({}); const [silFor, setSilFor] = useState(null); const [showSil, setShowSil] = useState(false)
  const clients = useLoad(() => get('/clients'), [])
  const since = days ? new Date(Date.now() - days * 864e5).toISOString() : ''
  const qs = `kind=${kind}&status=${status}&silenced=${silF}&q=${encodeURIComponent(q)}${sev !== '' ? '&min_severity=' + sev : ''}${cl ? '&client_id=' + cl : ''}${since ? '&since=' + encodeURIComponent(since) : ''}`
  const { data, err, reload } = useLoad(() => get(`/events?page=${page}&size=50&${qs}`), [page, kind, status, q, sev, days, cl, silF], 15000)
  const summ = useLoad(() => get(`/events/summary?kind=${kind}${cl && cl !== '-1' ? '&client_id=' + cl : ''}`), [kind, cl], 30000)
  const refresh = () => { reload(); summ.reload(); setPicked({}) }
  const pickedEvs = (data?.items || []).filter(r => picked[r.id])
  const apply = (f) => { setStatus(f.status); setQ(f.q); setSev(f.sev); setCl(f.cl); setDays(f.days); setPage(1) }
  const saveFilter = () => {
    const name = prompt('Nome do filtro salvo (ex.: Links caídos):'); if (!name) return
    const l = [...saved.filter(x => x.name !== name), { name, status, q, sev, cl, days }]
    setSaved(l); try { localStorage.setItem(SAVED, JSON.stringify(l)) } catch { /* ignore */ }; toast('Filtro salvo')
  }
  const rmFilter = (name) => { const l = saved.filter(x => x.name !== name); setSaved(l); try { localStorage.setItem(SAVED, JSON.stringify(l)) } catch { /* ignore */ } }
  const clear = () => { setKind(''); setSilF(''); apply({ status: '', q: '', sev: '', cl: '', days: '0.0417' }) }
  const dirty = kind || status || q || sev !== '' || cl || days !== '0.0417' || silF
  return <>
    <PageHead title="Eventos e Incidentes" desc="Ocorrências de todos os clientes (problema e recuperação ligados pelo Event ID do Zabbix). Filtre, exporte em CSV e abra o detalhe">
      <button className="btn" onClick={() => setShowSil(true)}><BellOff />Silenciados{summ.data && summ.data.silenced ? ` (${summ.data.silenced})` : ''}</button>
      <button className="btn" onClick={saveFilter}><Bookmark />Salvar filtro</button>
      <button className="btn" onClick={() => download(`/events-export?${qs}`, 'eventos-navi.csv').catch(e => toast(e.message, true))}><Download />Exportar CSV</button></PageHead>
    {summ.data && <div className="sevchips">{[5, 4, 3, 2, 1].map(n => <button key={n} className={'sevchip' + (sev === String(n) ? ' on' : '')} disabled={!summ.data.by_severity[n]} onClick={() => { setSev(sev === String(n) ? '' : String(n)); setStatus('PROBLEM'); setPage(1) }}><SevBadge n={n} /><b>{summ.data.by_severity[n] || 0}</b></button>)}
      <span className="sub">{summ.data.open} em aberto{summ.data.silenced ? ` · ${summ.data.silenced} silenciado(s)` : ''}</span></div>}
    <div className="bar"><div className="grow"><input placeholder="Buscar host, IP, trigger ou item…" value={q} onChange={e => { setQ(e.target.value); setPage(1) }} /></div>
      <select value={kind} onChange={e => { setKind(e.target.value); setPage(1) }}><option value="">Todas as origens</option><option value="infra">Infraestrutura (Zabbix)</option><option value="backup">Backup (Acronis)</option><option value="endpoint">Endpoints (EMS e Acronis)</option><option value="cloud">Cloud Orca</option></select>
      <select value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}><option value="">Todos</option><option value="PROBLEM">Em aberto</option><option value="RESOLVED">Resolvidos</option></select>
      <select value={silF} onChange={e => { setSilF(e.target.value); setPage(1) }} aria-label="Silenciados"><option value="">Alertas: todos</option><option value="hide">Ocultar silenciados</option><option value="only">Só silenciados</option></select>
      <select value={sev} onChange={e => { setSev(e.target.value); setPage(1) }}><option value="">Qualquer severidade</option>{SEV.map((s, i) => <option key={i} value={i}>≥ {s}</option>)}</select>
      <select value={cl} onChange={e => { setCl(e.target.value); setPage(1) }}><option value="">Todos os clientes</option><option value="-1">Sem cliente associado</option>{(clients.data || []).map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select>
      <select value={days} onChange={e => { setDays(e.target.value); setPage(1) }} aria-label="Período">{PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}<option value="">Todo o histórico</option></select>
      {dirty && <button className="btn sm" onClick={clear}>Limpar filtros</button>}</div>
    {saved.length > 0 && <div style={{ marginBottom: 14 }}><span className="sub">Filtros salvos: </span>{saved.map(f => <span key={f.name} className="chip" style={{ cursor: 'pointer' }} onClick={() => apply(f)}>{f.name} <span title="Remover" onClick={e => { e.stopPropagation(); rmFilter(f.name) }}>✕</span></span>)}</div>}
    {canEdit && pickedEvs.length > 0 && <div className="bar" style={{ background: 'rgba(30,115,248,.1)' }}><b>{pickedEvs.length} selecionado(s)</b><button className="btn sm primary" onClick={() => setSilFor(pickedEvs)}><BellOff size={14} />Silenciar alertas</button><button className="btn sm" onClick={() => setPicked({})}>Limpar seleção</button></div>}
    <Card pad={false}>{data ? <><Table rows={data.items} onRow={r => setSel(r.id)} cols={[
      ...(canEdit ? [{ h: <input type="checkbox" aria-label="Selecionar a página" checked={data.items.length > 0 && data.items.every(r => picked[r.id])} onChange={e => setPicked(e.target.checked ? Object.fromEntries(data.items.map(r => [r.id, true])) : {})} onClick={e => e.stopPropagation()} />,
        r: r => <input type="checkbox" aria-label="Selecionar evento" checked={!!picked[r.id]} onChange={e => setPicked({ ...picked, [r.id]: e.target.checked })} onClick={e => e.stopPropagation()} /> }] : []),
      { h: 'Status', r: r => <><StatusBadge s={r.status} />{r.silenced && <div title={`Alertas silenciados ${untilTxt(r.silenced)}${r.silenced.reason ? ' · ' + r.silenced.reason : ''}`}><Pill tone="mut"><BellOff size={11} /> silenciado</Pill></div>}</> }, { h: 'Sev.', r: r => <SevBadge n={r.severity} /> }, { h: 'Origem', r: r => <KindPill k={r.kind} /> },
      { h: 'Cliente', r: r => r.client_name ? <div className="trunc" style={{ maxWidth: 190 }} title={r.client_name}><b>{r.client_name}</b></div> : <span style={{ color: 'var(--orange)' }}>sem cliente</span> },
      { h: 'Host / item', r: r => <><div className="trunc" style={{ maxWidth: 200 }} title={r.host}><b>{r.host}</b></div>{r.ip && <div className="sub mono">{r.ip}</div>}</> },
      { h: 'Problema', r: r => <div className="trunc" title={r.trigger_name}>{r.trigger_name}</div> }, { h: 'Início', r: r => fmtDT(r.started_at), cls: 'nw' }, { h: 'Recuperação', r: r => fmtDT(r.recovered_at), cls: 'nw' },
      { h: 'Duração', r: r => r.status === 'PROBLEM' ? <LiveDur since={r.started_at} /> : fmtDur(r.duration_s), cls: 'mono nw' }, { h: 'WhatsApp', r: r => r.wa_status ? <Pill tone={r.wa_status === 'failed' ? 'bad' : r.wa_status === 'sent' ? 'ok' : 'warn'}>{r.wa_status}</Pill> : '—' },
      ...(canEdit ? [{ h: '', r: r => !r.silenced && <button className="btn sm" title="Silenciar alertas" aria-label="Silenciar alertas" onClick={e => { e.stopPropagation(); setSilFor([r]) }}><BellOff size={14} /></button> }] : [])]} />
      <div style={{ padding: '0 16px 12px' }}><Pager page={page} size={50} total={data.total} onPage={setPage} /></div></> : <Loading err={err} />}</Card>
    {sel && <Detail id={sel} onClose={() => setSel(null)} onSilence={evs => setSilFor(evs)} onChanged={() => { setSel(null); refresh() }} />}
    {silFor && <SilenceModal events={silFor} onClose={() => setSilFor(null)} onDone={() => { setSilFor(null); setSel(null); refresh() }} />}
    {showSil && <SilencedList onClose={() => setShowSil(false)} onChanged={refresh} />}</>
}
