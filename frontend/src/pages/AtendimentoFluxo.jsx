import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ReactFlow, ReactFlowProvider, Background, Controls, MiniMap, Handle, Position, addEdge, useEdgesState, useNodesState, useUpdateNodeInternals } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Copy, Download, History, LayoutGrid, Play, Plus, Redo2, RotateCcw, Save, Trash2, Undo2, Upload } from 'lucide-react'
import { get, post, put } from '../api'
import { Card, Field, Loading, PageHead, Pill, useToast } from '../ui'
import { useAuth, can } from '../App'
import { getTheme } from '../theme'
import AtNav from './AtNav'

const Ctx = React.createContext({ queues: [], tags: [] })
const META = {
  start: ['Início', 'event', '#2e7d32'], message: ['Mensagem', 'task', '#1e73f8'], menu: ['Menu (opções)', 'gateway', '#7b3fe4'], ask: ['Pergunta', 'task', '#0f8b8d'],
  lookup_client: ['Consultar cliente (CNPJ)', 'task', '#0f8b8d'], condition: ['Condição', 'gateway', '#7b3fe4'], hours: ['Horário de atendimento', 'gateway', '#7b3fe4'],
  set_var: ['Definir variável', 'task', '#1e73f8'], tag: ['Aplicar etiqueta', 'task', '#d6336c'], create_ticket: ['Abrir chamado', 'task', '#d97706'],
  notify: ['Avisar números/grupos', 'task', '#1e73f8'], enqueue: ['Entrar na fila', 'end', '#bd1723'], end: ['Encerrar', 'end', '#555'],
}
const DEFAULTS = {
  start: {}, message: { text: 'Olá!' }, menu: { text: 'Digite 1 ou 2.', options: [{ key: '1', label: 'Opção 1', aliases: '' }, { key: '2', label: 'Opção 2', aliases: '' }], timeout_min: 2, max_invalid: 1 },
  ask: { text: 'Informe o dado:', var: 'resposta', validate: 'any', min_len: 1, max_attempts: 2 }, lookup_client: { var: 'cnpj', max_tries: 2 },
  condition: { var: 'client_id', op: 'not_empty', value: '' }, hours: {}, set_var: { var: 'origem', value: 'whatsapp' }, tag: { tag: '' },
  create_ticket: { subject: 'Atendimento via WhatsApp - {cliente}', body: '{descricao}', priority: 'media' },
  notify: { to: [], text: 'Novo contato: {nome}' }, enqueue: { queue: 'geral' }, end: { text: 'Atendimento encerrado.' },
}
const outs = (t, c) => ({ start: ['next'], message: ['next'], notify: ['next'], set_var: ['next'], tag: ['next'], ask: ['ok', 'invalid', 'timeout', 'back'], lookup_client: ['found', 'retry', 'not_found'],
  condition: ['true', 'false'], hours: ['open', 'closed'], create_ticket: ['next', 'error'], enqueue: [], end: [], menu: [...(c.options || []).map(o => 'opt:' + o.key), 'invalid', 'timeout'] }[t] || [])
const HL = { next: '', ok: 'ok', invalid: 'inválido', timeout: 'tempo esgotado', back: 'voltar (0)', found: 'achou', retry: 'tentar de novo', not_found: 'não achou', true: 'sim', false: 'não', error: 'erro', open: 'aberto', closed: 'fechado' }
const hlabel = (h, c) => h.startsWith('opt:') ? `${h.slice(4)} · ${((c.options || []).find(o => 'opt:' + o.key === h) || {}).label || ''}` : (HL[h] ?? h)
const summary = (t, c) => ({ message: c.text, menu: c.text, ask: c.text, notify: c.text, end: c.text, enqueue: 'Fila: ' + (c.queue || '?'), set_var: `{${c.var || ''}} = ${c.value || ''}`, tag: c.tag || '(escolha a etiqueta)',
  hours: 'Dentro ou fora do horário', lookup_client: 'CNPJ em {' + (c.var || '') + '}', condition: `{${c.var || ''}} ${c.op === 'equals' ? '= ' + c.value : c.op === 'empty' ? 'vazio?' : 'preenchido?'}`, create_ticket: c.subject, start: 'Primeira mensagem do cliente' }[t] || '')

function FlowNode({ id, data, selected }) {
  const upd = useUpdateNodeInternals(); const o = outs(data.kind, data.cfg); const [label, shape, color] = META[data.kind]
  useEffect(() => { upd(id) }, [o.join('|'), id])
  return <div className={`bp bp-${shape}${selected ? ' sel' : ''}${data.err ? ' err' : ''}`} style={{ '--c': color }} title={data.err || ''}>
    {data.kind !== 'start' && <Handle type="target" position={Position.Left} />}
    <b>{label}</b><div className="bp-sum">{(summary(data.kind, data.cfg) || '').slice(0, 70)}</div>
    {o.map((h, i) => <React.Fragment key={h}><Handle id={h} type="source" position={Position.Right} style={{ top: `${((i + 1) / (o.length + 1)) * 100}%` }} />
      {o.length > 1 && <span className="bp-h" style={{ top: `calc(${((i + 1) / (o.length + 1)) * 100}% - 8px)` }}>{hlabel(h, data.cfg)}</span>}</React.Fragment>)}
  </div>
}
const nodeTypes = { bpmn: FlowNode }

const toRF = (d) => ({
  nodes: d.nodes.map(n => ({ id: n.id, type: 'bpmn', position: { x: n.x || 0, y: n.y || 0 }, data: { kind: n.type, cfg: n.type === 'notify' ? { ...(n.data || {}), to_text: (n.data?.to || []).join('\n') } : (n.data || {}) } })),
  edges: d.edges.map(e => ({ id: e.id || `${e.source}:${e.handle}`, source: e.source, target: e.target, sourceHandle: e.handle || 'next', type: 'smoothstep', markerEnd: { type: 'arrowclosed' } })),
})
const fromRF = (nodes, edges) => ({
  nodes: nodes.map(n => {
    let data = n.data.cfg
    if (n.data.kind === 'notify') { const { to_text, ...rest } = data; data = { ...rest, to: (to_text ?? (rest.to || []).join('\n')).split(/[\n,;]+/).map(x => x.trim()).filter(Boolean) } }
    return { id: n.id, type: n.data.kind, x: Math.round(n.position.x), y: Math.round(n.position.y), data }
  }),
  edges: edges.map(e => ({ id: e.id, source: e.source, target: e.target, handle: e.sourceHandle || 'next' })),
})

function autoLayout(nodes, edges) { // camadas por distancia do inicio
  const out = {}; edges.forEach(e => { (out[e.source] = out[e.source] || []).push(e.target) })
  const depth = {}; const start = nodes.find(n => n.data.kind === 'start'); const q = start ? [start.id] : []
  if (start) depth[start.id] = 0
  while (q.length) { const u = q.shift(); (out[u] || []).forEach(v => { if (depth[v] === undefined) { depth[v] = depth[u] + 1; q.push(v) } }) }
  const maxd = Math.max(0, ...Object.values(depth)); const layers = {}
  nodes.forEach(n => { const d = depth[n.id] ?? maxd + 1; (layers[d] = layers[d] || []).push(n.id) })
  return nodes.map(n => { const d = depth[n.id] ?? maxd + 1; return { ...n, position: { x: d * 320, y: layers[d].indexOf(n.id) * 170 } } })
}

function Inspector({ node, onChange, onDelete, onDuplicate, edit }) {
  const { queues, tags } = React.useContext(Ctx)
  if (!node) return <div className="sub">Selecione um passo para editar. Arraste da bolinha de saída até outro passo para ligar. Atalhos: Ctrl+Z desfaz, Ctrl+Y refaz, Ctrl+D duplica, Delete exclui.</div>
  const { kind, cfg } = node.data; const set = (k, v) => onChange({ ...cfg, [k]: v }); const dis = !edit
  const txt = (k, label, rows = 3, hint) => <Field label={label} hint={hint}><textarea rows={rows} value={cfg[k] || ''} onChange={e => set(k, e.target.value)} disabled={dis} /></Field>
  const inp = (k, label, type = 'text', hint) => <Field label={label} hint={hint}><input type={type} value={cfg[k] ?? ''} onChange={e => set(k, type === 'number' ? (e.target.value === '' ? '' : +e.target.value) : e.target.value)} disabled={dis} /></Field>
  return <div>
    <h3 style={{ marginBottom: 8 }}>{META[kind][0]} <small className="sub">({node.id})</small></h3>
    {['message', 'end'].includes(kind) && txt('text', 'TEXTO', 4, 'Variáveis: {nome} {telefone} {cliente} {cnpj} {chamado}')}
    {kind === 'menu' && <>{txt('text', 'MENSAGEM DO MENU', 6)}
      <Field label="OPÇÕES (tecla · nome · também aceita)">{(cfg.options || []).map((o, i) => <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
        <input style={{ width: 50 }} value={o.key} disabled={dis} onChange={e => set('options', cfg.options.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
        <input value={o.label || ''} disabled={dis} onChange={e => set('options', cfg.options.map((x, j) => j === i ? { ...x, label: e.target.value } : x))} />
        <input placeholder="um, comercial" value={o.aliases || ''} disabled={dis} onChange={e => set('options', cfg.options.map((x, j) => j === i ? { ...x, aliases: e.target.value } : x))} />
        {!dis && <button className="btn" aria-label="Remover opção" onClick={() => set('options', cfg.options.filter((_, j) => j !== i))}><Trash2 size={14} /></button>}</div>)}
        {!dis && <button className="btn" onClick={() => set('options', [...(cfg.options || []), { key: String((cfg.options || []).length + 1), label: 'Nova opção', aliases: '' }])}><Plus size={14} />Opção</button>}</Field>
      <div className="row r2">{inp('timeout_min', 'SEM RESPOSTA (min)', 'number')}{inp('max_invalid', 'REPETIÇÕES SE INVÁLIDA', 'number')}</div></>}
    {kind === 'ask' && <>{txt('text', 'PERGUNTA', 3)}{txt('retry_text', 'TEXTO AO REPETIR (opcional)', 2)}
      <div className="row r2">{inp('var', 'GUARDAR EM (variável)')}<Field label="VALIDAÇÃO"><select value={cfg.validate || 'any'} onChange={e => set('validate', e.target.value)} disabled={dis}><option value="any">Qualquer texto</option><option value="text">Texto (mínimo de letras)</option><option value="cnpj">CNPJ</option></select></Field></div>
      <div className="row r2">{inp('min_len', 'MÍNIMO DE CARACTERES', 'number')}{inp('max_attempts', 'TENTATIVAS', 'number')}</div>{inp('timeout_min', 'SEM RESPOSTA (min)', 'number')}</>}
    {kind === 'lookup_client' && <>{inp('var', 'VARIÁVEL COM O CNPJ')}{inp('max_tries', 'TENTATIVAS ATÉ “NÃO ACHOU”', 'number', 'Enquanto houver tentativa, segue a saída “tentar de novo”.')}</>}
    {kind === 'condition' && <>{inp('var', 'VARIÁVEL')}<Field label="CONDIÇÃO"><select value={cfg.op || 'not_empty'} onChange={e => set('op', e.target.value)} disabled={dis}><option value="not_empty">está preenchida</option><option value="empty">está vazia</option><option value="equals">é igual a</option></select></Field>{cfg.op === 'equals' && inp('value', 'VALOR')}</>}
    {kind === 'hours' && <p className="sub">Segue “aberto” dentro do horário de atendimento e “fechado” fora dele. O horário é configurado em Atendimento &gt; Configurações &gt; Horário. No teste, use “Simular fora do horário”.</p>}
    {kind === 'set_var' && <>{inp('var', 'VARIÁVEL', 'text', 'Letras, números e _. Use depois como {nome_da_variavel}.')}{inp('value', 'VALOR', 'text', 'Aceita variáveis, ex.: {nome}')}</>}
    {kind === 'tag' && <Field label="ETIQUETA" hint="Etiquetas são criadas em Atendimento > Configurações."><select value={cfg.tag || ''} onChange={e => set('tag', e.target.value)} disabled={dis}><option value="">— escolha —</option>{tags.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}</select></Field>}
    {kind === 'create_ticket' && <>{inp('subject', 'ASSUNTO')}{txt('body', 'DESCRIÇÃO', 4, 'Aceita variáveis, ex.: {descricao}')}
      <Field label="PRIORIDADE"><select value={cfg.priority || 'media'} onChange={e => set('priority', e.target.value)} disabled={dis}>{[['baixa', 'Baixa'], ['media', 'Média'], ['alta', 'Alta'], ['critica', 'Crítica']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field></>}
    {kind === 'notify' && <>{txt('to_text', 'NÚMEROS / IDs DE GRUPO (um por linha)', 3)}{txt('text', 'MENSAGEM', 3)}</>}
    {kind === 'enqueue' && <Field label="FILA"><select value={cfg.queue || 'geral'} onChange={e => set('queue', e.target.value)} disabled={dis}>{queues.map(q => <option key={q.slug} value={q.slug}>{q.name}</option>)}</select></Field>}
    {kind !== 'start' && edit && <div style={{ display: 'flex', gap: 8, marginTop: 10 }}><button className="btn" onClick={onDuplicate}><Copy size={14} />Duplicar</button><button className="btn" onClick={onDelete}><Trash2 size={14} />Excluir</button></div>}
  </div>
}

function Simulator({ getDef }) {
  const [inputs, setInputs] = useState([]); const [text, setText] = useState(''); const [res, setRes] = useState(null); const [err, setErr] = useState(''); const [closed, setClosed] = useState(false)
  const run = async (ins, out = closed) => { try { const r = await post('/atendimento/flow/simulate', { definition: getDef(), inputs: ins, outside_hours: out }); setErr(r.errors?.length ? r.errors.map(e => e.msg).join(' · ') : ''); setRes(r) } catch (e) { setErr(e.message) } }
  const reset = () => { setInputs([]); run([]) }
  const send = () => { if (!text.trim()) return; const n = [...inputs, text.trim()]; setInputs(n); setText(''); run(n) }
  const waiting = res && res.outcome && res.outcome.kind === 'waiting'
  return <div>
    <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center', flexWrap: 'wrap' }}><button className="btn primary" onClick={reset}><Play size={14} />Iniciar teste</button>
      <label className="check"><input type="checkbox" checked={closed} onChange={e => setClosed(e.target.checked)} />Simular fora do horário</label></div>
    <span className="sub">Nada é enviado nem gravado; o cliente é consultado de verdade.</span>
    {err && <div style={{ color: 'var(--crit)', margin: '6px 0' }}>{err}</div>}
    <div className="at-body" style={{ maxHeight: 280, border: '1px solid var(--line)', borderRadius: 10, marginTop: 8 }}>{(res?.transcript || []).map((m, i) => <div key={i} className={'at-msg ' + (m.from === 'cliente' ? 'out' : 'in')} style={m.from === 'sistema' ? { background: 'transparent', fontStyle: 'italic', opacity: .8 } : {}}><div style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div></div>)}</div>
    {waiting && <div style={{ display: 'flex', gap: 8, marginTop: 8 }}><input value={text} onChange={e => setText(e.target.value)} placeholder="Resposta do cliente…" onKeyDown={e => e.key === 'Enter' && send()} /><button className="btn" onClick={send}>Enviar</button></div>}
    {res?.outcome && !waiting && <p className="sub" style={{ marginTop: 6 }}>Fim do teste. Clique em “Iniciar teste” para repetir.</p>}
  </div>
}

function Versions({ onLoad, refreshKey }) {
  const toast = useToast(); const [rows, setRows] = useState(null)
  useEffect(() => { get('/atendimento/flow/versions').then(setRows).catch(() => setRows([])) }, [refreshKey])
  const load = async (id) => { try { const v = await get('/atendimento/flow/versions/' + id); onLoad(v.definition) } catch (e) { toast(e.message, true) } }
  if (!rows) return <Loading />
  return <div>{rows.map(v => <div key={v.id} className="cfg-row" style={{ padding: '8px 0' }}><div className="grow"><b>{new Date(v.saved_at).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })}</b><div className="sub">{v.saved_by || '—'} · {v.nodes} passos</div></div>
    <button className="btn sm" onClick={() => load(v.id)}>Carregar no editor</button></div>)}{!rows.length && <p className="sub">Nenhuma versão salva ainda.</p>}
    <p className="sub" style={{ marginTop: 8 }}>Carregar não altera nada até você salvar.</p></div>
}

function Editor({ initial, edit, queues, tags }) {
  const toast = useToast(); const rf = useMemo(() => toRF(initial), [initial])
  const [nodes, setNodes, onNodesChange] = useNodesState(rf.nodes); const [edges, setEdges, onEdgesChange] = useEdgesState(rf.edges)
  const [sel, setSel] = useState(null); const [errs, setErrs] = useState([]); const [, bump] = useState(0); const [verKey, setVerKey] = useState(0); const [showVer, setShowVer] = useState(false)
  const seq = useRef(1); const past = useRef([]); const future = useRef([]); const lastSnap = useRef(0); const fileRef = useRef(null)
  const cur = useRef({ nodes, edges }); cur.current = { nodes, edges }
  const def = () => fromRF(cur.current.nodes, cur.current.edges)
  const snapshot = () => JSON.stringify({ nodes: cur.current.nodes.map(n => ({ ...n, selected: false, data: { ...n.data, err: '' } })), edges: cur.current.edges.map(e => ({ ...e, selected: false })) })
  const push = () => { past.current.push(snapshot()); if (past.current.length > 60) past.current.shift(); future.current = []; bump(x => x + 1) }
  const restore = (str) => { const x = JSON.parse(str); setNodes(x.nodes); setEdges(x.edges) }
  const undo = () => { if (!past.current.length) return; future.current.push(snapshot()); restore(past.current.pop()); bump(x => x + 1) }
  const redo = () => { if (!future.current.length) return; past.current.push(snapshot()); restore(future.current.pop()); bump(x => x + 1) }
  const load = (d) => { push(); const x = toRF(d); setNodes(x.nodes); setEdges(x.edges); setSel(null) }
  useEffect(() => {
    const t = setTimeout(async () => {
      try { const r = await post('/atendimento/flow/validate', { definition: def() }); setErrs(r.errors); const bad = Object.fromEntries(r.errors.filter(e => e.node).map(e => [e.node, e.msg]))
        setNodes(ns => ns.map(n => (n.data.err || '') === (bad[n.id] || '') ? n : { ...n, data: { ...n.data, err: bad[n.id] || '' } })) } catch { /* sem validacao */ }
    }, 600); return () => clearTimeout(t)
  }, [nodes.length, edges, JSON.stringify(nodes.map(n => n.data.cfg))]) // eslint-disable-line
  const onConnect = useCallback((c) => { push(); setEdges(es => addEdge({ ...c, type: 'smoothstep', markerEnd: { type: 'arrowclosed' } }, es.filter(e => !(e.source === c.source && e.sourceHandle === c.sourceHandle)))) }, []) // eslint-disable-line
  const isValid = useCallback((c) => c.source !== c.target && !nodes.find(n => n.id === c.target && n.data.kind === 'start'), [nodes])
  const selected = nodes.find(n => n.id === sel)
  const change = (cfg) => { if (Date.now() - lastSnap.current > 800) push(); lastSnap.current = Date.now()
    setNodes(ns => ns.map(n => {
      if (n.id !== sel) return n
      if (n.data.kind === 'menu') { const keep = new Set(outs('menu', cfg)); setEdges(es => es.filter(e => e.source !== sel || keep.has(e.sourceHandle))) }
      return { ...n, data: { ...n.data, cfg } }
    })) }
  const newId = (kind) => `${kind}_${Date.now().toString(36)}${seq.current++}`
  const add = (kind) => { if (kind === 'start') return toast('O fluxo já tem um início', true); push(); const id = newId(kind)
    setNodes(ns => [...ns.map(n => ({ ...n, selected: false })), { id, type: 'bpmn', position: { x: 80 + (ns.length % 5) * 30, y: 80 + (ns.length % 5) * 30 }, data: { kind, cfg: JSON.parse(JSON.stringify(DEFAULTS[kind])) }, selected: true }]); setSel(id) }
  const duplicate = () => { if (!selected || selected.data.kind === 'start') return; push(); const id = newId(selected.data.kind)
    setNodes(ns => [...ns.map(n => ({ ...n, selected: false })), { ...selected, id, selected: true, position: { x: selected.position.x + 40, y: selected.position.y + 60 }, data: { ...selected.data, err: '', cfg: JSON.parse(JSON.stringify(selected.data.cfg)) } }]); setSel(id) }
  const delSelected = () => { const ids = new Set(nodes.filter(n => n.selected && n.data.kind !== 'start').map(n => n.id)); if (sel && sel !== 'start' && selected?.data.kind !== 'start') ids.add(sel)
    const eids = new Set(edges.filter(e => e.selected).map(e => e.id)); if (!ids.size && !eids.size) return; push()
    setNodes(ns => ns.filter(n => !ids.has(n.id))); setEdges(es => es.filter(e => !eids.has(e.id) && !ids.has(e.source) && !ids.has(e.target))); setSel(null) }
  const organize = () => { push(); setNodes(ns => autoLayout(ns, cur.current.edges)) }
  const save = async () => { try { await put('/atendimento/flow', { definition: def() }); toast('Fluxo salvo. Já vale para as próximas conversas.'); setVerKey(k => k + 1) } catch (e) { toast(e.message, true) } }
  const reset = async () => { if (!confirm('Restaurar o fluxo padrão? Suas alterações serão perdidas (a versão atual fica no histórico de versões).')) return
    try { const r = await post('/atendimento/flow/reset'); load(r.definition); toast('Fluxo padrão restaurado') } catch (e) { toast(e.message, true) } }
  const exportJson = () => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(def(), null, 2)], { type: 'application/json' })); a.download = 'fluxo-atendimento.json'; a.click(); URL.revokeObjectURL(a.href) }
  const importJson = async (f) => { try { const d = JSON.parse(await f.text()); if (!Array.isArray(d.nodes) || !Array.isArray(d.edges)) throw new Error('Arquivo inválido'); load(d); toast('Fluxo importado no editor. Revise e salve.') } catch (e) { toast('Não foi possível importar: ' + e.message, true) } }
  const onKey = (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || !edit) return
    const k = e.key.toLowerCase()
    if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo() }
    else if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); redo() }
    else if ((e.ctrlKey || e.metaKey) && k === 'd') { e.preventDefault(); duplicate() }
    else if (k === 'delete' || k === 'backspace') { e.preventDefault(); delSelected() }
  }
  const shownEdges = useMemo(() => edges.map(e => { const n = nodes.find(x => x.id === e.source); const o = n ? outs(n.data.kind, n.data.cfg) : []
    return o.length > 1 ? { ...e, label: hlabel(e.sourceHandle || 'next', n.data.cfg), labelStyle: { fontSize: 11 }, labelBgPadding: [4, 2] } : e }), [edges, nodes])
  return <Ctx.Provider value={{ queues, tags }}><div className="fl-grid" onKeyDown={onKey} tabIndex={-1}>
    <div>
      {edit && <div className="fl-bar"><button className="btn sm" disabled={!past.current.length} onClick={undo} title="Desfazer (Ctrl+Z)"><Undo2 size={14} />Desfazer</button>
        <button className="btn sm" disabled={!future.current.length} onClick={redo} title="Refazer (Ctrl+Y)"><Redo2 size={14} />Refazer</button>
        <button className="btn sm" onClick={organize} title="Organizar o diagrama automaticamente"><LayoutGrid size={14} />Organizar</button>
        <button className="btn sm" onClick={exportJson}><Download size={14} />Exportar</button>
        <button className="btn sm" onClick={() => fileRef.current.click()}><Upload size={14} />Importar</button><input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={e => { e.target.files[0] && importJson(e.target.files[0]); e.target.value = '' }} />
        <button className="btn sm" onClick={() => setShowVer(v => !v)}><History size={14} />Versões</button></div>}
      <div className="fl-canvas">
        <ReactFlow nodes={nodes} edges={shownEdges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} isValidConnection={isValid}
          onNodeClick={(_, n) => setSel(n.id)} onPaneClick={() => setSel(null)} onNodeDragStart={() => edit && push()} nodesDraggable={edit} nodesConnectable={edit} elementsSelectable fitView minZoom={0.15}
          snapToGrid snapGrid={[20, 20]} colorMode={getTheme() === 'dark' ? 'dark' : 'light'} deleteKeyCode={null}><Background gap={20} /><Controls showInteractive={false} /><MiniMap pannable zoomable nodeColor={n => (META[n.data?.kind] || [])[2] || '#999'} /></ReactFlow>
      </div>
    </div>
    <div className="fl-side">
      {showVer && <Card title="Versões do fluxo"><Versions refreshKey={verKey} onLoad={load} /></Card>}
      {edit && <Card title="Adicionar passo"><div className="fl-pal">{Object.entries(META).filter(([k]) => k !== 'start').map(([k, [l, , c]]) => <button key={k} className="btn" style={{ borderLeft: `4px solid ${c}` }} onClick={() => add(k)}><Plus size={13} />{l}</button>)}</div></Card>}
      <Card title="Passo selecionado"><Inspector node={selected} edit={edit} onChange={change} onDelete={delSelected} onDuplicate={duplicate} /></Card>
      <Card title={errs.length ? `Problemas (${errs.length})` : 'Validação'}>{errs.length ? errs.map((e, i) => <div key={i} style={{ color: 'var(--crit)', marginBottom: 4 }}>{e.node ? <b>{e.node}: </b> : null}{e.msg}</div>) : <Pill tone="ok">Fluxo válido</Pill>}</Card>
      <Card title="Testar o fluxo"><Simulator getDef={def} /></Card>
      {edit && <div style={{ display: 'flex', gap: 8 }}><button className="btn primary" disabled={errs.length > 0} onClick={save}><Save size={15} />Salvar fluxo</button><button className="btn" onClick={reset}><RotateCcw size={15} />Restaurar padrão</button></div>}
    </div>
  </div></Ctx.Provider>
}

export default function AtendimentoFluxo() {
  const me = useAuth(); const edit = can(me, 'settings.edit'); const [d, setD] = useState(null); const [queues, setQueues] = useState([]); const [tags, setTags] = useState([]); const [err, setErr] = useState('')
  useEffect(() => { Promise.all([get('/atendimento/flow'), get('/atendimento/tags')]).then(([r, t]) => { setD(r.definition); setQueues(r.queues); setTags(t) }).catch(e => setErr(e.message)) }, [])
  return <>
    <PageHead title="Fluxo de atendimento" desc="Diagrama do atendimento por WhatsApp: o que o cliente recebe, o que é perguntado e para onde ele vai" />
    <AtNav />
    {!d ? <Loading err={err} /> : <ReactFlowProvider><Editor initial={d} edit={edit} queues={queues} tags={tags} /></ReactFlowProvider>}
  </>
}
