import React from 'react'
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { render, waitFor, cleanup, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import fs from 'fs'
import App from '../src/App'
import { ToastProvider } from '../src/ui'

const [TOKEN, CSRF] = fs.readFileSync('/work/sess.txt', 'utf8').trim().split('\n')
const API = 'http://127.0.0.1:8100'
beforeAll(() => {
  global.fetch = (url, opt = {}) => fetch_(url, opt)
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
  window.scrollTo = () => {}; Element.prototype.scrollIntoView = () => {}; window.confirm = () => false; window.prompt = () => null
  window.matchMedia = window.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  URL.createObjectURL = () => 'blob:x'
})
const realFetch = globalThis.fetch
function fetch_(url, opt) {
  const headers = { ...(opt.headers || {}), Cookie: `navi_session=${TOKEN}`, 'X-CSRF-Token': CSRF }
  return realFetch(API + String(url).replace(/^(?=\/)/, ''), { ...opt, headers })
}
class Boundary extends React.Component {
  state = { err: null }
  static getDerivedStateFromError(err) { return { err } }
  render() { return this.state.err ? <pre id="boom">{String(this.state.err.stack || this.state.err).slice(0, 900)}</pre> : this.props.children }
}
afterEach(cleanup)

const ROUTES = ['/', '/clientes', '/clientes/2', '/clientes?cobertura=1', '/monitoramento', '/eventos', '/eventos?kind=backup&days=', '/protecao', '/alertas', '/relatorios', '/rotinas', '/sla', '/whatsapp', '/email', '/navi-ia', '/usuarios', '/auditoria', '/configuracoes']
describe('telas', () => {
  for (const path of ROUTES) {
    it(path, async () => {
      const errs = []; const oe = console.error; console.error = (...a) => { errs.push(a.map(String).join(' ').slice(0, 300)); }
      const { container } = render(<Boundary><MemoryRouter initialEntries={[path]}><ToastProvider><App /></ToastProvider></MemoryRouter></Boundary>)
      await waitFor(() => { expect(container.textContent).not.toContain('Carregando…') ; expect(container.querySelector('.top, #boom')).toBeTruthy() }, { timeout: 15000 })
      await new Promise(r => setTimeout(r, 600))
      // navega pelas abas e abre os formularios (Novo/Nova/Convidar/Editar) procurando erros de renderizacao
      const check = async (what) => { await new Promise(r => setTimeout(r, 350)); const b = container.querySelector('#boom'); if (b) throw new Error('ERRO DE RENDER em ' + path + ' apos ' + what + ':\n' + b.textContent) }
      for (const tab of [...container.querySelectorAll('.tabs button')]) { fireEvent.click(tab); await check('aba ' + tab.textContent) }
      for (const btn of [...container.querySelectorAll('button')].filter(b => /^(Novo|Nova|Convidar|Editar|Testar)/.test(b.textContent.trim()) && !/Testar/.test(b.textContent))) {
        fireEvent.click(btn); await check('botao ' + btn.textContent.trim())
        const x = container.querySelector('.modal .hd button, .drawer button'); if (x) fireEvent.click(x)
      }
      console.error = oe
      const boom = container.querySelector('#boom')
      if (boom) throw new Error('ERRO DE RENDER em ' + path + ':\n' + boom.textContent)
      const fatal = errs.filter(e => /Warning: (Each child|React has detected a change in the order of Hooks|Rendered (more|fewer) hooks)|Minified React error|Cannot read|is not defined|is not a function/.test(e))
      if (fatal.length) throw new Error('console.error em ' + path + ':\n' + fatal.join('\n'))
      expect(container.querySelector('.content').textContent.length).toBeGreaterThan(20)
    }, 30000)
  }
})
