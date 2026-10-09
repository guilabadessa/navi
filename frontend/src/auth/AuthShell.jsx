import React from 'react'
import { BarChart3, CheckCircle2, Cloud, HardDrive, Lock, MonitorCheck, Receipt, ShieldCheck, ShieldPlus } from 'lucide-react'
import './auth.css'

const POINTS = [
  'Situação dos seus serviços em tempo real',
  'Incidentes por categoria, com o tempo em aberto',
  'Relatórios executivos mensais em PDF',
  'Contratos, boletos e notas fiscais em um só lugar',
]
const SERVICES = [[MonitorCheck, 'Infraestrutura'], [HardDrive, 'Backup'], [ShieldPlus, 'Endpoints'], [Cloud, 'Cloud Orca']]

// Moldura comum de login, redefinicao de senha e convite: formulario a esquerda, painel de marca a direita.
export default function AuthShell({ children }) {
  return <div className="login lg-root">
    <section className="lg-form">
      <header><img src="/cliente/brand/azul.png" alt="Orca TI" /></header>
      <main><div className="lg-card">{children}</div></main>
      <footer>
        <div className="lg-secure"><ShieldCheck size={14} />Conexão segura · sessões protegidas · acessos auditados</div>
        <div>Precisa de ajuda com o acesso? Fale com a equipe da Orca TI.</div>
        <div>© {new Date().getFullYear()} Orca TI</div>
      </footer>
    </section>
    <aside className="lg-brandpanel" aria-label="Sobre o NAVI">
      <div className="lg-bp">
        <div className="lg-prod">NAVI<span>Plataforma de operações de TI</span></div>
        <h2>Toda a operação de TI do seu ambiente, com clareza e em tempo real.</h2>
        <ul>{POINTS.map(p => <li key={p}><CheckCircle2 size={18} />{p}</li>)}</ul>
        <div className="lg-preview" aria-hidden="true">
          <div className="lg-pv-head"><b>Situação dos serviços</b><span><i />Ao vivo</span></div>
          {SERVICES.map(([I, n]) => <div className="lg-pv-row" key={n}><I size={17} /><span>{n}</span><em><i />Operando normalmente</em></div>)}
          <div className="lg-pv-foot"><BarChart3 size={15} />Relatório mensal<span /><Receipt size={15} />Financeiro<span /><Lock size={15} />Acesso seguro</div>
        </div>
      </div>
    </aside>
  </div>
}
