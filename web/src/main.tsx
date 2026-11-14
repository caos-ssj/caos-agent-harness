import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import { startTranslator } from './i18n'
import './theme.css'
import './base.css'
import './views.css'

startTranslator()

/* The reflection on a hovered surface follows the cursor: one listener writes where the pointer is, in that surface's own space. */
const LIT = '.card, .kpi-card, .prov-card, .stn, .skill-item, .board-row, .ov-tile, .glass'
window.addEventListener('pointermove', (e) => {
  const el = (e.target as Element | null)?.closest?.(LIT) as HTMLElement | null
  if (!el) return
  const r = el.getBoundingClientRect()
  el.style.setProperty('--mx', `${e.clientX - r.left}px`)
  el.style.setProperty('--my', `${e.clientY - r.top}px`)
}, { passive: true })

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
