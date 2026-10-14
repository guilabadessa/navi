const BASE = '/cliente/api'
let csrf = ''
export const setCsrf = (t) => { csrf = t || '' }

// Evita envio duplicado: um clique duplo em "Salvar" reaproveita a requisicao que ja esta em andamento
const inflight = new Map()
export function api(path, opts = {}) {
  const method = opts.method || 'GET'
  if (method === 'GET' || opts.raw) return doApi(path, opts)
  const key = method + ' ' + path + ' ' + JSON.stringify(opts.body ?? null)
  if (inflight.has(key)) return inflight.get(key)
  const p = doApi(path, opts).finally(() => inflight.delete(key))
  inflight.set(key, p)
  return p
}

async function doApi(path, { method = 'GET', body, raw } = {}) {
  const opt = { method, credentials: 'same-origin', headers: {} }
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body) }
  if (method !== 'GET') opt.headers['X-CSRF-Token'] = csrf
  const r = await fetch(BASE + path, opt)
  if (r.status === 401 && !path.startsWith('/auth/login')) { window.dispatchEvent(new Event('navi:unauth')); throw new Error('Sessão expirada') }
  if (raw) return r
  const ct = r.headers.get('content-type') || ''
  const data = ct.includes('json') ? await r.json() : await r.text()
  if (!r.ok) {
    const d = data && data.detail
    const msg = Array.isArray(d) ? d.map(x => `${(x.loc || []).slice(-1)[0]}: ${x.msg}`).join('; ') : (d || `Erro ${r.status}`)
    throw new Error(msg)
  }
  return data
}
export const get = (p) => api(p)
export const post = (p, body = {}) => api(p, { method: 'POST', body })
export const put = (p, body = {}) => api(p, { method: 'PUT', body })
export const patch = (p, body = {}) => api(p, { method: 'PATCH', body })
export const del = (p) => api(p, { method: 'DELETE' })

export async function upload(path, file) {
  const fd = new FormData(); fd.append('file', file)
  const r = await fetch(BASE + path, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf } })
  if (!r.ok) throw new Error((await r.json()).detail || 'Falha no upload')
  return r.json()
}
export async function uploadForm(path, fd) {
  const r = await fetch(BASE + path, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf } })
  if (!r.ok) { let d = ''; try { d = (await r.json()).detail } catch { /* corpo nao e json */ } throw new Error(d || 'Falha no envio') }
  return r.json()
}
export async function download(path, name) {
  const r = await api(path, { raw: true })
  if (!r.ok) throw new Error('Falha no download')
  const blob = await r.blob(); const a = document.createElement('a')
  a.href = URL.createObjectURL(blob); a.download = name || 'arquivo'; a.click(); URL.revokeObjectURL(a.href)
}

// ---- formatadores ----
export const SEV = ['Não classificado', 'Informação', 'Atenção', 'Média', 'Alta', 'Desastre']
export const fmtDur = (s) => {
  if (s === null || s === undefined) return '—'
  s = Math.round(s); const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), x = s % 60
  const p = []; if (d) p.push(d + 'd'); if (h) p.push(h + 'h'); if (m) p.push(m + 'min'); if (x || !p.length) p.push(x + 's')
  return p.slice(0, 3).join(' ')
}
export const fmtDT = (v) => v ? new Date(v).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '—'
export const fmtPct = (v, d = 2) => v === null || v === undefined ? '—' : Number(v).toFixed(d).replace('.', ',') + '%'
export const fmtNum = (v) => v === null || v === undefined ? '—' : Number(v).toLocaleString('pt-BR')
