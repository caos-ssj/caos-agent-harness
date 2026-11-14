import { useEffect, useState } from 'react'
import { api, RunOverview } from './api'
import { playTone } from './tones'

/* One poll of the run overview shared by everything on the Run view (stations, verification panel), and the moment of the
   person's previous visit, so "since your last visit" means the same thing everywhere. */

const KEY = 'caos_last_visit'
const now = () => Date.now() / 1000
let previous = 0
try { previous = Number(localStorage.getItem(KEY)) || 0 } catch { previous = 0 }
if (typeof document !== 'undefined') {
  const stamp = () => { try { localStorage.setItem(KEY, String(now())) } catch { /* private mode */ } }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') stamp() })
  window.addEventListener('pagehide', stamp)
}
export const lastVisit = (): number => previous

type Listener = (d: RunOverview | null, err: string | null) => void
const listeners = new Set<Listener>()
let data: RunOverview | null = null
let error: string | null = null
let timer: number | null = null

export function refreshRun(): Promise<void> {
  return api.getRunOverview(previous).then((d) => {
    if (data) {   // a count that went up since the last poll is an event worth a tone; the first load is silent
      if (d.shift.landed > data.shift.landed) playTone('landed')
      else if (d.shift.failed > data.shift.failed || d.shift.rejected > data.shift.rejected) playTone('failed')
      else if (d.shift.needs_you > data.shift.needs_you) playTone('needs')
    }
    data = d; error = null
  }).catch((e) => { error = e?.message || 'No se pudo cargar' }).then(() => { listeners.forEach((l) => l(data, error)) })
}

/** The overview, refreshed every 8 s while something on screen uses it; faster (2 s) while any agent is running. */
export function useRunOverview(): { data: RunOverview | null; error: string | null; refresh: () => Promise<void> } {
  const [state, setState] = useState<{ data: RunOverview | null; error: string | null }>({ data, error })
  useEffect(() => {
    const l: Listener = (d, e) => setState({ data: d, error: e })
    listeners.add(l)
    const tick = () => { void refreshRun().then(() => { if (listeners.size) timer = window.setTimeout(tick, data?.stations?.some((s) => s.running) ? 2000 : 8000) }) }
    if (listeners.size === 1) tick()
    return () => { listeners.delete(l); if (!listeners.size && timer !== null) { window.clearTimeout(timer); timer = null } }
  }, [])
  return { ...state, refresh: refreshRun }
}

/* The agent the verification panel is narrowed to (press a station to set it, press it again to clear). */
let focus: string | null = null
const focusListeners = new Set<(a: string | null) => void>()
export function useFocusAgent(): [string | null, (a: string | null) => void] {
  const [a, setA] = useState<string | null>(focus)
  useEffect(() => { focusListeners.add(setA); return () => { focusListeners.delete(setA) } }, [])
  return [a, (next) => { focus = next; focusListeners.forEach((l) => l(next)) }]
}
