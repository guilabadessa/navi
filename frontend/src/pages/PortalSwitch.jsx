import React, { useState } from 'react'
import { get } from '../api'
import { Loading, PageHead, useLoad } from '../ui'
import Portal from './Portal'

const KEY = 'navi.portal.client'
const saved = () => { try { return localStorage.getItem(KEY) || '' } catch { return '' } }

// A equipe Orca transita entre os portais dos clientes e ve exatamente o que o cliente ve (inclusive o financeiro, se tiver a permissao).
export default function PortalSwitch() {
  const { data: clients } = useLoad(() => get('/clients'), []); const [cid, setCid] = useState(saved()); const [sev, setSev] = useState(4)
  const pick = (v) => { setCid(v); try { localStorage.setItem(KEY, v) } catch { /* sem armazenamento local */ } }
  if (!clients) return <Loading />
  const list = clients.filter(c => c.status === 'ativo')
  const cur = list.find(c => String(c.id) === String(cid))
  return <>
    <PageHead title="Portal do cliente" desc="Navegue entre os clientes e veja o portal exatamente como cada um deles vê"
      ><select style={{ width: 'auto', minWidth: 260 }} value={cur ? cur.id : ''} onChange={e => pick(e.target.value)}><option value="">Selecione um cliente…</option>{list.map(c => <option key={c.id} value={c.id}>{c.trade_name}</option>)}</select><select style={{ width: 'auto' }} value={sev} onChange={e => setSev(+e.target.value)} title="Severidade mínima que o usuário do cliente enxerga">{[5, 4, 3, 2, 1, 0].map(n => <option key={n} value={n}>Severidade ≥ {['Não classificado', 'Informação', 'Atenção', 'Média', 'Alta', 'Desastre'][n]}</option>)}</select></PageHead>
    {cur ? <div className="portal-embed"><Portal key={cur.id + '-' + sev} clientId={cur.id} minSev={sev} embedded /></div> : <div className="banner info"><div className="grow">Selecione um cliente para abrir o portal dele.</div></div>}
  </>
}
