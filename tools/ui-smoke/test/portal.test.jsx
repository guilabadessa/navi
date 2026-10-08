import React from 'react'
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { render, waitFor, cleanup, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import fs from 'fs'
import App from '../src/App'
import { ToastProvider } from '../src/ui'
const [TOKEN, CSRF] = fs.readFileSync('/work/sess_cli.txt', 'utf8').trim().split('\n')
const realFetch = globalThis.fetch
beforeAll(() => {
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
  window.scrollTo = () => {}; Element.prototype.scrollIntoView = () => {}
  global.fetch = (url, opt = {}) => realFetch('http://127.0.0.1:8100' + url, { ...opt, headers: { ...(opt.headers || {}), Cookie: `navi_session=${TOKEN}`, 'X-CSRF-Token': CSRF } })
})
class Boundary extends React.Component { state = { err: null }; static getDerivedStateFromError(err) { return { err } }
  render() { return this.state.err ? <pre id="boom">{String(this.state.err.stack || this.state.err).slice(0, 700)}</pre> : this.props.children } }
afterEach(cleanup)
describe('portal do cliente', () => {
  it('renderiza todas as abas', async () => {
    const { container } = render(<Boundary><MemoryRouter initialEntries={['/']}><ToastProvider><App /></ToastProvider></MemoryRouter></Boundary>)
    await waitFor(() => expect(container.querySelector('.tabs, #boom')).toBeTruthy(), { timeout: 15000 })
    for (const t of [...container.querySelectorAll('.tabs button')]) { fireEvent.click(t); await new Promise(r => setTimeout(r, 300)); if (container.querySelector('#boom')) throw new Error(container.querySelector('#boom').textContent) }
    expect([...container.querySelectorAll('.tabs button')].map(b => b.textContent)).toContain('Backup')
    expect(container.textContent).not.toContain('Gestão'); expect(container.querySelector('.side')).toBeNull()
  }, 40000)
})
describe('login e convite', () => {
  it('login', async () => {
    global.fetch = () => Promise.resolve(new Response(JSON.stringify({ detail: 'Não autenticado' }), { status: 401, headers: { 'content-type': 'application/json' } }))
    const { container } = render(<Boundary><MemoryRouter initialEntries={['/']}><ToastProvider><App /></ToastProvider></MemoryRouter></Boundary>)
    await waitFor(() => expect(container.querySelector('.login, #boom')).toBeTruthy())
    expect(container.querySelector('#boom')).toBeNull(); fireEvent.click([...container.querySelectorAll('a')].find(a => /Esqueci/.test(a.textContent)))
    await waitFor(() => expect(container.textContent).toContain('Redefinir senha'))
  })
  it('convite invalido', async () => {
    global.fetch = () => Promise.resolve(new Response(JSON.stringify({ detail: 'Este link expirou' }), { status: 410, headers: { 'content-type': 'application/json' } }))
    const { container } = render(<Boundary><MemoryRouter initialEntries={['/convite/abc']}><ToastProvider><App /></ToastProvider></MemoryRouter></Boundary>)
    await waitFor(() => expect(container.textContent).toContain('Link inválido'))
  })
})
