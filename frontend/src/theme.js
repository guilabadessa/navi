const KEY = 'navi.theme'
export const getTheme = () => { try { return localStorage.getItem(KEY) || 'light' } catch { return 'light' } }
export const applyTheme = (t = getTheme()) => { document.documentElement.dataset.theme = t }
export const toggleTheme = () => { const t = getTheme() === 'dark' ? 'light' : 'dark'; try { localStorage.setItem(KEY, t) } catch { /* ignore */ } applyTheme(t); return t }
export const tvMode = (on) => { document.body.classList.toggle('tv', on); try { localStorage.setItem('navi.tv', on ? '1' : '0') } catch { /* ignore */ } }
export const getTv = () => { try { return localStorage.getItem('navi.tv') === '1' } catch { return false } }
