import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ReactFlow, ReactFlowProvider, Background, Controls, Handle, Position, addEdge, useEdgesState, useNodesState, useUpdateNodeInternals } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Link } from 'react-router-dom'
import { ArrowLeft, Play, Plus, RotateCcw, Save, Trash2 } from 'lucide-react'
import { get, post, put } from '../api'
import { Card, Field, Loading, PageHead, Pill, useToast } from '../ui'
import { useAuth, can } from '../App'
import { getTheme } from '../theme'

const QUEUES = [['comercial', 'Comercial'], ['financeiro', 'Financeiro'], ['suporte', 'Suporte'], ['geral', 'Geral']]
const META = {
  start: ['Início', 'event', '#2e7d32'], message: ['Mensagem', 'task', '#1e73f8'], menu: ['Menu (opções)', 'gateway', '#7b3fe4'], ask: ['Pergunta', 'task', '#0f8b8d'],
  lookup_client: ['Consultar cliente (CNPJ)', 'task', '#0f8b8d'], condition: ['Condição', 'gateway', '#7b3fe4'], create_ticket: ['Abrir chamado', 'task', '#d97706'],
  notify: ['Avisar números/grupos', 'task', '#1e73f8'], enqueue: ['Entrar na fila', 'end', '#bd1723'], end: ['Encerrar', 'end', '#555'],
}
const DEFAULTS = {
  start: {}, message: { text: 'Olá!' }, menu: { text: 'Digite 1 ou 2.', options: [{ key: '1', label: 'Opção 1', aliases: '' }, { key: '2', label: 'Opção 2', aliases: '' }], timeout_min: 2, max_invalid: 1 },
  ask: { text: 'Informe o dado:', var: 'resposta', validate: 'any', min_len: 1, max_attempts: 2 }, lookup_client: { var: 'cnpj', max_tries: 2 },
  condition: { var: 'client_id', op: 'not_empty', value: '' }, create_ticket: { subject: 'Atendimento via WhatsApp - {cliente}', body: '{descricao}', priority: 'media' },
  notify: { to: [], text: 'Novo contato: {nome}' }, enqueue: { queue: 'geral' }, end: { text: 'Atendimento encerrado.' },
}
const outs = (t, c) => ({ start: ['next'], message: ['next'], notify: ['next'], ask: ['ok', 'invalid', 'timeout', 'back'], lookup_client: ['found', 'retry', 'not_found'], condition: ['true', 'false'],
  create_ticket: ['next', 'error'], enqueue: [], end: [], menu: [...(c.options || []).map(o => 'opt:' + o.key), 'invalid', 'timeout'] }[t] || [])
const HL = { next: '', ok: 'ok', invalid: 'inválido', timeout: 'tempo esgotado', back: 'voltar (0)', found: 'achou', retry: 'tentar de novo', not_found: 'não achou', true: 'sim', false: 'não', error: 'erro' }
const hlabel = (h, c) => h.startsWith('opt:') ? `${h.slice(4)} · ${((c.options || []).find(o => 'opt:' + o.key === h) || {}).label || ''}` : (HL[h] ?? h)
const summary = (t, c) => ({ message: c.text, menu: c.text, ask: c.text, notify: c.text, end: c.text, enqueue: 'Fila: ' + (QUEUES.find(q => q[0] === c.queue) || ['', '?'])[1],
  lookup_client: 'CNPJ em {' + (c.var || '') + '}', condition: `{${c.var || ''}} ${c.op === 'equals' ? '= ' + c.value : c.op === 'empty' ? 'vazio?' : 'preenchido?'}`, create_ticket: c.subject, start: 'Primeira mensagem do cliente' }[t] || '')

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
  nodes: d.nodes.map(n => ({ id: n.id, type: 'bpmn', position: { x: n.x || 0, y: n.y || 0 }, data: { kind: n.type, cfg: n.data || {} } })),
  edges: d.edges.map(e => ({ id: e.id || `${e.source}:${e.handle}`, source: e.source, target: e.target, sourceHandle: e.handle || 'next', type: 'smoothstep', markerEnd: { type: 'arrowclosed' } })),
})
const fromRF = (nodes, edges) => ({
  nodes: nodes.map(n => ({ id: n.id, type: n.data.kind, x: Math.round(n.position.x), y: Math.round(n.position.y), data: n.data.cfg })),
  edges: edges.map(e => ({ id: e.id, source: e.source, target: e.target, handle: e.sourceHandle || 'next' })),
})

function Inspector({ node, onChange, onDelete, edit }) {
  if (!node) return <div className="sub">Selecione um passo para editar. Arraste da bolinha de saída até outro passo para ligar.</div>
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
    {kind === 'create_ticket' && <>{inp('subject', 'ASSUNTO')}{txt('body', 'DESCRIÇÃO', 4, 'Aceita variáveis, ex.: {descricao}')}
      <Field label="PRIORIDADE"><select value={cfg.priority || 'media'} onChange={e => set('priority', e.target.value)} disabled={dis}>{[['baixa', 'Baixa'], ['media', 'Média'], ['alta', 'Alta'], ['critica', 'Crítica']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field></>}
    {kind === 'notify' && <>{txt('to_text', 'NÚMEROS / IDs DE GRUPO (um por linha)', 3)}{txt('text', 'MENSAGEM', 3)}</>}
    {kind === 'enqueue' && <Field label="FILA"><select value={cfg.queue || 'geral'} onChange={e => set('queue', e.target.value)} disabled={dis}>{QUEUES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>}
    {kind !== 'start' && edit && <button className="btn" style={{ marginTop: 10 }} onClick={onDelete}><Trash2 size={14} />Excluir passo</button>}
  </div>
}

function Simulator({ getDef }) {
  const [inputs, setInputs] = useState([]); const [text, setText] = useState(''); const [res, setRes] = useState(null); const [err, setErr] = useState('')
  const run = async (ins) => { try { const r = await post('/atendimento/flow/simulate', { definition: getDef(), inputs: ins }); setErr(r.errors?.length ? r.errors.map(e => e.msg).join(' · ') : ''); setRes(r) } catch (e) { setErr(e.message) } }
  const reset = () => { setInputs([]); run([]) }
  const send = () => { if (!text.trim()) return; const n = [...inputs, text.trim()]; setInputs(n); setText(''); run(n) }
  const waiting = res && res.outcome && res.outcome.kind === 'waiting'
  return <div>
    <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}><button className="btn primary" onClick={reset}><Play size={14} />Iniciar teste</button><span className="sub">Nada é enviado nem gravado; o cliente é consultado de verdade.</span></div>
    {err && <div style={{ color: 'var(--crit)', marginBottom: 6 }}>{err}</div>}
    <div className="at-body" style={{ maxHeight: 280, border: '1px solid var(--line)', borderRadius: 10 }}>{(res?.transcript || []).map((m, i) => <div key={i} className={'at-msg ' + (m.from === 'cliente' ? 'out' : 'in')} style={m.from === 'sistema' ? { background: 'transparent', fontStyle: 'italic', opacity: .8 } : {}}><div style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div></div>)}</div>
    {waiting && <div style={{ display: 'flex', gap: 8, marginTop: 8 }}><input value={text} onChange={e => setText(e.target.value)} placeholder="Resposta do cliente…" onKeyDown={e => e.key === 'Enter' && send()} /><button className="btn" onClick={send}>Enviar</button></div>}
    {res?.outcome && !waiting && <p className="sub" style={{ marginTop: 6 }}>Fim do teste. Clique em “Iniciar teste” para repetir.</p>}
  </div>
}

function Editor({ initial, edit }) {
  const toast = useToast(); const rf = useMemo(() => toRF(initial), [initial])
  const [nodes, setNodes, onNodesChange] = useNodesState(rf.nodes); const [edges, setEdges, onEdgesChange] = useEdgesState(rf.edges)
  const [sel, setSel] = useState(null); const [errs, setErrs] = useState([]); const seq = useRef(1)
  const cur = useRef({ nodes, edges }); cur.current = { nodes, edges }
  const getDef = () => fromRF(cur.current.nodes, cur.current.edges)
  const def = () => { const d = getDef(); d.nodes.forEach(n => { if (n.type === 'notify') { n.data = { ...n.data, to: (n.data.to_text ?? (n.data.to || []).join('\n')).split(/[\n,;]+/).map(x => x.trim()).filter(Boolean) }; delete n.data.to_text } }); return d }
  useEffect(() => { // validacao com atraso: marca os passos com erro
    const t = setTimeout(async () => {
      try { const r = await post('/atendimento/flow/validate', { definition: def() }); setErrs(r.errors); const bad = Object.fromEntries(r.errors.filter(e => e.node).map(e => [e.node, e.msg]))
        setNodes(ns => ns.map(n => (n.data.err || '') === (bad[n.id] || '') ? n : { ...n, data: { ...n.data, err: bad[n.id] || '' } })) } catch { /* sem validacao */ }
    }, 600); return () => clearTimeout(t)
  }, [nodes.length, edges, JSON.stringify(nodes.map(n => n.data.cfg))]) // eslint-disable-line
  const onConnect = useCallback((c) => setEdges(es => addEdge({ ...c, type: 'smoothstep', markerEnd: { type: 'arrowclosed' } }, es.filter(e => !(e.source === c.source && e.sourceHandle === c.sourceHandle)))), [])
  const isValid = useCallback((c) => c.source !== c.target && !nodes.find(n => n.id === c.target && n.data.kind === 'start'), [nodes])
  const selected = nodes.find(n => n.id === sel)
  const change = (cfg) => setNodes(ns => ns.map(n => {
    if (n.id !== sel) return n
    if (n.data.kind === 'menu') { const keep = new Set(outs('menu', cfg)); setEdges(es => es.filter(e => e.source !== sel || keep.has(e.sourceHandle))) }
    return { ...n, data: { ...n.data, cfg } }
  }))
  const add = (kind) => { if (kind === 'start') return toast('O fluxo já tem um início', true); const id = `${kind}_${Date.now().toString(36)}${seq.current++}`
    setNodes(ns => [...ns, { id, type: 'bpmn', position: { x: 80 + (ns.length % 5) * 30, y: 80 + (ns.length % 5) * 30 }, data: { kind, cfg: JSON.parse(JSON.stringify(DEFAULTS[kind])) } }]); setSel(id) }
  const del = () => { setNodes(ns => ns.filter(n => n.id !== sel)); setEdges(es => es.filter(e => e.source !== sel && e.target !== sel)); setSel(null) }
  const save = async () => { try { await put('/atendimento/flow', { definition: def() }); toast('Fluxo salvo. Já vale para as próximas conversas.') } catch (e) { toast(e.message, true) } }
  const reset = async () => { if (!confirm('Restaurar o fluxo padrão? Suas alterações serão perdidas.')) return
    try { const r = await post('/atendimento/flow/reset'); const x = toRF(r.definition); setNodes(x.nodes); setEdges(x.edges); setSel(null); toast('Fluxo padrão restaurado') } catch (e) { toast(e.message, true) } }
  useEffect(() => { // a lista de destinos do aviso e editada como texto
    setNodes(ns => ns.map(n => n.data.kind === 'notify' && n.data.cfg.to_text === undefined ? { ...n, data: { ...n.data, cfg: { ...n.data.cfg, to_text: (n.data.cfg.to || []).join('\n') } } } : n))
  }, [])
  return <div className="fl-grid">
    <div className="fl-canvas">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} isValidConnection={isValid}
        onNodeClick={(_, n) => setSel(n.id)} onPaneClick={() => setSel(null)} nodesDraggable={edit} nodesConnectable={edit} elementsSelectable fitView minZoom={0.2} colorMode={getTheme() === 'dark' ? 'dark' : 'light'}
        deleteKeyCode={edit ? ['Backspace', 'Delete'] : null}><Background /><Controls showInteractive={false} /></ReactFlow>
    </div>
    <div className="fl-side">
      {edit && <Card title="Adicionar passo"><div className="fl-pal">{Object.entries(META).filter(([k]) => k !== 'start').map(([k, [l, , c]]) => <button key={k} className="btn" style={{ borderLeft: `4px solid ${c}` }} onClick={() => add(k)}><Plus size={13} />{l}</button>)}</div></Card>}
      <Card title="Passo selecionado"><Inspector node={selected} edit={edit} onChange={change} onDelete={del} /></Card>
      <Card title={errs.length ? `Problemas (${errs.length})` : 'Validação'}>{errs.length ? errs.map((e, i) => <div key={i} style={{ color: 'var(--crit)', marginBottom: 4 }}>{e.node ? <b>{e.node}: </b> : null}{e.msg}</div>) : <Pill tone="ok">Fluxo válido</Pill>}</Card>
      <Card title="Testar o fluxo"><Simulator getDef={def} /></Card>
      {edit && <div style={{ display: 'flex', gap: 8 }}><button className="btn primary" disabled={errs.length > 0} onClick={save}><Save size={15} />Salvar fluxo</button><button className="btn" onClick={reset}><RotateCcw size={15} />Restaurar padrão</button></div>}
    </div>
  </div>
}

export default function AtendimentoFluxo() {
  const me = useAuth(); const edit = can(me, 'settings.edit'); const [d, setD] = useState(null); const [err, setErr] = useState('')
  useEffect(() => { get('/atendimento/flow').then(r => setD(r.definition)).catch(e => setErr(e.message)) }, [])
  return <>
    <PageHead title="Fluxo de atendimento" desc="Diagrama do atendimento por WhatsApp: o que o cliente recebe, o que é perguntado e para onde ele vai"><Link className="btn" to="/atendimento"><ArrowLeft size={15} />Voltar ao atendimento</Link></PageHead>
    {!d ? <Loading err={err} /> : <ReactFlowProvider><Editor initial={d} edit={edit} /></ReactFlowProvider>}
  </>
}
