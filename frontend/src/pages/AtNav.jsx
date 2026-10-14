import React from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth, can } from '../App'

// Navegacao do modulo de atendimento (abas no topo, como o Kommo)
export default function AtNav() {
  const me = useAuth()
  const items = [['/atendimento', 'Conversas', true], ['/atendimento/historico', 'Histórico'], ['/atendimento/fluxo', 'Fluxo'], ['/atendimento/configuracoes', 'Configurações']]
  return <nav className="at-nav" aria-label="Atendimento">{items.filter(([to]) => to !== '/atendimento/configuracoes' || can(me, 'atendimento.view')).map(([to, label, end]) =>
    <NavLink key={to} to={to} end={!!end} className={({ isActive }) => isActive ? 'on' : ''}>{label}</NavLink>)}</nav>
}
