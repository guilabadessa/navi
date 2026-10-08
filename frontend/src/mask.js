// Mascaras de digitacao (BR)
export const onlyDigits = (v) => (v || '').replace(/\D/g, '')

export function maskCNPJ(v) {
  const d = onlyDigits(v).slice(0, 14)
  return d.replace(/^(\d{2})(\d)/, '$1.$2').replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3').replace(/\.(\d{3})(\d)/, '.$1/$2').replace(/(\d{4})(\d)/, '$1-$2')
}
export function maskPhone(v) {
  let d = onlyDigits(v)
  if (d.length > 11 && d.startsWith('55')) d = d.slice(2)
  d = d.slice(0, 11)
  if (d.length <= 2) return d.length ? `(${d}` : ''
  if (d.length <= 6) return `(${d.slice(0, 2)}) ${d.slice(2)}`
  if (d.length <= 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`
  return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`
}
export function cnpjOk(v) {
  const d = onlyDigits(v); if (d.length !== 14 || /^(\d)\1+$/.test(d)) return false
  const dv = (n) => { const w = n === 12 ? [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] : [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    const r = [...d.slice(0, n)].reduce((a, c, i) => a + +c * w[i], 0) % 11; return r < 2 ? 0 : 11 - r }
  return +d[12] === dv(12) && +d[13] === dv(13)
}
export const cnpjHint = (v) => { const d = onlyDigits(v); return d.length === 14 && !cnpjOk(v) ? '⚠ Dígito verificador não confere — confira o CNPJ' : null }

// Destino de WhatsApp: telefone vira (00) 00000-0000; JID de grupo (@g.us / id longo) fica como esta
export function maskTarget(v) {
  v = v || ''
  if (v.includes('@') || /[a-zA-Z]/.test(v)) return v
  const d = onlyDigits(v)
  if (d.length >= 14 || /^\d+-\d+$/.test(v.trim())) return v.trim()
  return maskPhone(v)
}
