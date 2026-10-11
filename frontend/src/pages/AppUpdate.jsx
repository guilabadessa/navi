import React, { useEffect, useState } from 'react'

const native = () => !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform())

// App Android: avisa quando existe um APK mais novo no servidor (so aparece dentro do app)
export default function AppUpdate() {
  const [v, setV] = useState(null); const [hide, setHide] = useState(false)
  useEffect(() => {
    if (!native()) return
    const P = window.Capacitor.Plugins
    Promise.all([P.App.getInfo(), fetch('/cliente/app/version').then(r => r.json())])
      .then(([cur, last]) => { if (last && Number(last.code) > Number(cur.build)) setV(last) }).catch(() => {})
  }, [])
  if (!v || hide) return null
  const open = () => { try { window.Capacitor.Plugins.Browser.open({ url: window.location.origin + '/cliente/app/navi.apk' }) } catch (_) { window.location.href = '/cliente/app/navi.apk' } }
  return <div className="banner warn" role="status" style={{ margin: 12 }}>
    <div className="grow"><b>Nova versão do app disponível{v.name ? ` (${v.name})` : ''}.</b> Baixe e instale por cima da atual; seus dados e login são mantidos.</div>
    <button className="btn primary sm" onClick={open}>Baixar</button><button className="btn sm" onClick={() => setHide(true)}>Depois</button></div>
}
