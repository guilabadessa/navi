import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './fonts.css'
import './styles.css'
import App from './App'
import { ErrorBoundary, ToastProvider } from './ui'
import { applyTheme, getTv, tvMode } from './theme'

applyTheme(); tvMode(getTv())

createRoot(document.getElementById('root')).render(
  <BrowserRouter basename="/cliente"><ToastProvider><ErrorBoundary><App /></ErrorBoundary></ToastProvider></BrowserRouter>)

if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/cliente/sw.js', { scope: '/cliente/' }).catch(() => {}))

// App Android: ao tocar na notificacao, abre o endereco enviado pelo servidor
if (window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()) {
  try { window.Capacitor.Plugins.PushNotifications.addListener('pushNotificationActionPerformed', a => { const u = a.notification && a.notification.data && a.notification.data.url; if (u && u.startsWith('/cliente/')) window.location.href = u }) } catch (_) {}
}
