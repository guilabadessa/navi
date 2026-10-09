import React, { useState } from 'react'
import { FlaskConical, KeyRound, Link2, Plus, RefreshCw, X } from 'lucide-react'
import { get, post, put, del } from '../api'
import { Card, Check, Field, Loading, Pill, Table, useLoad, useToast } from '../ui'
import { useAuth, can } from '../App'
import { maskCNPJ } from '../mask'

function Links() {
  const toast = useToast(); const { data, reload } = useLoad(() => get('/finance/links'), []); const [sel, setSel] = useState({}); const [q, setQ] = useState('')
  if (!data) return <Loading />
  const add = async (cid, pid) => { try { await put(`/finance/clients/${cid}/link`, { person_id: pid }); toast('CNPJ vinculado ao cliente'); setSel(x => ({ ...x, [cid]: '' })); reload() } catch (e) { toast(e.message, true) } }
  const remove = async (cid, p) => { if (!confirm(`Remover ${p.name} deste cliente? Os títulos e notas desse CNPJ saem do portal dele.`)) return; try { await del(`/finance/clients/${cid}/link/${p.id}`); toast('CNPJ removido do cliente'); reload() } catch (e) { toast(e.message, true) } }
  const rows = data.clients.filter(c => !q || c.name.toLowerCase().includes(q.toLowerCase()))
  return <Card title="Clientes da NAVI × CNPJs do Conta Azul" pad={false} actions={<input style={{ width: 220 }} placeholder="Buscar cliente…" value={q} onChange={e => setQ(e.target.value)} />}>
    <div className="sub" style={{ padding: '10px 20px 0' }}>O vínculo é feito <b>automaticamente pelo CNPJ</b> do cadastro do cliente. Um cliente pode ter <b>vários CNPJs</b>: adicione os demais abaixo e o portal mostra o financeiro de todos juntos. Quando o CNPJ não coincide, a NAVI apenas <b>sugere</b> (mesma raiz de CNPJ ou nome parecido) e você confirma.</div>
    <Table rows={rows} empty="Nenhum cliente." cols={[
      { h: 'Cliente', r: r => <><b>{r.name}</b><div className="sub mono">{r.cnpj ? maskCNPJ(r.cnpj) : <Pill tone="warn">sem CNPJ</Pill>}</div></> },
      { h: 'CNPJs vinculados (Conta Azul)', r: r => r.persons.length ? <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>{r.persons.map(p => <div key={p.id} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <span>{p.name} <span className="sub mono">{p.doc ? maskCNPJ(p.doc) : 'sem documento'}</span></span><Pill tone={p.match === 'cnpj' ? 'ok' : 'info'}>{p.match === 'cnpj' ? 'por CNPJ' : 'manual'}</Pill>
        <button className="btn sm danger" title="Remover este CNPJ do cliente" onClick={() => remove(r.client_id, p)}><X size={13} /></button></div>)}</div> : <span className="sub">nenhum</span> },
      { h: 'Adicionar CNPJ', r: r => <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {r.suggestions.map(sg => <button key={sg.id} className="btn sm" title={`${sg.why}: ${sg.name}`} onClick={() => add(r.client_id, sg.id)}><Link2 size={14} />{sg.name.slice(0, 30)} <span className="sub">({sg.why})</span></button>)}
        <div style={{ display: 'flex', gap: 6 }}><select style={{ width: 200 }} value={sel[r.client_id] || ''} onChange={e => setSel({ ...sel, [r.client_id]: e.target.value })}><option value="">Escolher cadastro…</option>{data.people.filter(p => !p.taken).map(p => <option key={p.id} value={p.id}>{p.name}{p.doc ? ' · ' + p.doc : ''}</option>)}</select>
          <button className="btn sm" disabled={!sel[r.client_id]} onClick={() => add(r.client_id, sel[r.client_id])}><Plus size={14} />Adicionar</button></div></div> }]} /></Card>
}

export default function ContaAzulTab({ edit }) {
  const toast = useToast(); const me = useAuth(); const { data, reload } = useLoad(() => get('/finance/config'), []); const [x, setX] = useState(null); const [code, setCode] = useState(''); const [busy, setBusy] = useState('')
  React.useEffect(() => { if (data && !x) setX({ ...data, client_secret: '' }) }, [data]) // eslint-disable-line
  if (!x) return <Loading />
  const set = (k, v) => setX({ ...x, [k]: v })
  const run = async (k, fn) => { setBusy(k); try { await fn() } catch (e) { toast(e.message, true) } finally { setBusy('') } }
  const save = () => run('save', async () => { await put('/finance/config', { client_id: x.client_id, client_secret: x.client_secret || null, redirect_uri: x.redirect_uri, enabled: x.enabled }); toast('Configuração salva'); setX(null); reload() })
  const auth = () => run('auth', async () => { const r = await post('/finance/authorize', { code }); toast(r.detail, !r.ok); if (r.ok) { setCode(''); setX(null); reload() } })
  const test = () => run('test', async () => { const r = await post('/finance/test'); toast(r.detail, !r.ok) })
  const sync = () => run('sync', async () => { const r = await post('/finance/sync'); toast(r.skipped ? 'Integração desativada ou não autorizada' : `Sincronizado · ${r.people} cadastros · ${r.linked} vínculo(s) por CNPJ · ${r.titles ?? 0} título(s) · ${r.notes ?? 0} nota(s)`, !!r.skipped) })
  return <div style={{ display: 'grid', gap: 16 }}>
    <Card title="Conta Azul (faturamento)" actions={<><button className="btn sm" disabled={!!busy} onClick={test}><FlaskConical />{busy === 'test' ? 'Testando…' : 'Testar conexão'}</button>
      {can(me, 'finance.view') && <button className="btn sm" disabled={!!busy} onClick={sync}><RefreshCw />{busy === 'sync' ? 'Sincronizando…' : 'Sincronizar agora'}</button>}</>}>
      {x.auth_error && <div className="banner bad"><div className="grow">A autorização do Conta Azul foi recusada ou expirou. Gere um novo código abaixo.</div></div>}
      <Check label="Integrar com o Conta Azul (financeiro no portal do cliente)" checked={x.enabled} onChange={v => set('enabled', v)} />
      <div className="row r3" style={{ marginTop: 12 }}><Field label="ID DO CLIENTE (CLIENT ID)"><input value={x.client_id} onChange={e => set('client_id', e.target.value)} /></Field>
        <Field label="SEGREDO (CLIENT SECRET)" hint={x.secret_set ? 'Já configurado — deixe em branco para manter.' : 'Obrigatório.'}><input type="password" autoComplete="new-password" value={x.client_secret} onChange={e => set('client_secret', e.target.value)} placeholder={x.secret_set ? '••••••••' : ''} /></Field>
        <Field label="URL DE REDIRECIONAMENTO" hint="Deve ser igual à cadastrada no aplicativo do Conta Azul."><input value={x.redirect_uri} onChange={e => set('redirect_uri', e.target.value)} /></Field></div>
      <p className="hint">A NAVI apenas <b>consulta</b> (GET) pessoas, títulos a receber e notas fiscais. Último sincronismo: {x.last_sync ? new Date(x.last_sync).toLocaleString('pt-BR') : 'nunca'}.</p>
      <button className="btn primary" disabled={!!busy || !edit} onClick={save}>Salvar configuração</button></Card>
    {edit && x.authorize_url && <Card title="Autorização" actions={x.authorized && !x.auth_error ? <Pill tone="ok">autorizado</Pill> : <Pill tone="warn">pendente</Pill>}>
      <ol className="sub" style={{ margin: '0 0 12px 18px', lineHeight: 1.7 }}>
        <li>Clique em <b>Abrir login do Conta Azul</b> e entre com um usuário do ERP com acesso ao financeiro.</li>
        <li>Você será levado à URL de redirecionamento. Copie o <b>endereço completo</b> da barra do navegador (ou só o valor de <span className="mono">code=</span>).</li>
        <li>Cole abaixo e clique em <b>Autorizar</b>. O código vale por 3 minutos e só pode ser usado uma vez; depois disso a renovação é automática.</li></ol>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}><a className="btn" href={x.authorize_url} target="_blank" rel="noreferrer"><KeyRound size={15} />Abrir login do Conta Azul</a>
        <input style={{ flex: 1, minWidth: 260 }} placeholder="Cole aqui o endereço de retorno ou o código" value={code} onChange={e => setCode(e.target.value)} />
        <button className="btn primary" disabled={!!busy || code.length < 3} onClick={auth}>{busy === 'auth' ? 'Autorizando…' : 'Autorizar'}</button></div></Card>}
    {can(me, 'finance.view') && <Links />}</div>
}
