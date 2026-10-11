// Service worker minimo: habilita instalacao e (fase 2) recebe push. Sem cache de dados.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()))
self.addEventListener('fetch', () => {})
self.addEventListener('push', e => {
  let d = {}; try { d = e.data.json() } catch (_) {}
  e.waitUntil(self.registration.showNotification(d.title || 'NAVI', {
    body: d.body || '', icon: '/cliente/brand/pwa-192.png', badge: '/cliente/brand/simbolo_branco.png', data: { url: d.url || '/cliente/' } }))
})
self.addEventListener('notificationclick', e => {
  e.notification.close()
  e.waitUntil(self.clients.openWindow(e.notification.data.url))
})
