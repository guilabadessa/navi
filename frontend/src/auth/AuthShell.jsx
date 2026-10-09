import React from 'react'
import './auth.css'

// Moldura comum de login, redefinicao de senha e convite: marca no canto e cartao de acesso.
export default function AuthShell({ children }) {
  return <div className="login lg-root">
    <header className="lg-top"><img src="/cliente/brand/branco.png" alt="Orca TI" /></header>
    <main className="lg-main">
      <div className="lg-title"><h1>NAVI</h1><p>Inteligência operacional da Orca TI</p></div>
      <div className="lg-card">{children}</div>
      <div className="lg-help">Precisa de ajuda com o acesso? Fale com a equipe da Orca TI.</div>
    </main>
    <footer className="lg-foot">© {new Date().getFullYear()} Orca TI · Operação de TI e Infraestrutura</footer>
  </div>
}
