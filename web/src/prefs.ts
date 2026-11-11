import { useCallback, useState } from 'react'
import { View } from './lib'

/* What can be personalised, and only that: density changes how many tasks fit on a screen, and the start view is where
   the page opens. Both live in this browser's localStorage; nothing is sent anywhere. */
export interface Prefs { density: 'comfortable' | 'compact'; start: View }
export const DEFAULT_PREFS: Prefs = { density: 'comfortable', start: 'desk' }
const KEY = 'caos_prefs'

export function usePrefs(): [Prefs, (p: Partial<Prefs>) => void, () => void] {
  const [prefs, setPrefs] = useState<Prefs>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) || '{}')
      return {
        density: raw.density === 'compact' ? 'compact' : 'comfortable',
        start: ['desk', 'console', 'library'].includes(raw.start) ? raw.start : 'desk',
      }
    } catch { return DEFAULT_PREFS }
  })
  const save = (next: Prefs) => { try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* private mode: keep it in memory */ } }
  const update = useCallback((p: Partial<Prefs>) => setPrefs((prev) => { const next = { ...prev, ...p }; save(next); return next }), [])
  const reset = useCallback(() => { setPrefs(DEFAULT_PREFS); try { localStorage.removeItem(KEY) } catch { /* ignore */ } }, [])
  return [prefs, update, reset]
}
