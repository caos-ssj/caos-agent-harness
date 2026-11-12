import { useCallback, useState } from 'react'
import { View } from './lib'

export type RoutingProfile = 'local-first' | 'hybrid' | 'cloud-max'

export interface Prefs {
  density: 'comfortable' | 'compact'
  text: 'standard' | 'large'
  start: View
  notify: boolean
  /** `fluid` animates; `focus` stills every decorative motion. Starts in `fluid` whatever the system asks. */
  motion: 'fluid' | 'focus'
  /** Whether the right-hand inspector of Console starts open. */
  inspector: boolean
  profile: RoutingProfile
}

export const DEFAULT_PREFS: Prefs = { density: 'compact', text: 'standard', start: 'console', notify: false, motion: 'fluid', inspector: true, profile: 'hybrid' }
const KEY = 'caos_prefs'
const VALID_VIEWS: View[] = ['console', 'board', 'providers', 'metrics', 'skills', 'share']
const PROFILES: RoutingProfile[] = ['local-first', 'hybrid', 'cloud-max']

export function readPrefs(raw: Record<string, unknown>): Prefs {
  const mapped = raw.start === 'measured' ? 'metrics' : raw.start
  return {
    density: raw.density === 'comfortable' ? 'comfortable' : 'compact',
    text: raw.text === 'large' ? 'large' : 'standard',
    notify: raw.notify === true,
    start: VALID_VIEWS.includes(mapped as View) ? (mapped as View) : 'console',
    motion: raw.motion === 'focus' ? 'focus' : 'fluid',
    inspector: raw.inspector !== false,
    profile: PROFILES.includes(raw.profile as RoutingProfile) ? (raw.profile as RoutingProfile) : 'hybrid',
  }
}

export function usePrefs(): [Prefs, (p: Partial<Prefs>) => void, () => void] {
  const [prefs, setPrefs] = useState<Prefs>(() => {
    try {
      return readPrefs(JSON.parse(localStorage.getItem(KEY) || '{}'))
    } catch {
      return DEFAULT_PREFS
    }
  })
  const save = (next: Prefs) => {
    try {
      localStorage.setItem(KEY, JSON.stringify(next))
    } catch {
      /* private mode */
    }
  }
  const update = useCallback((p: Partial<Prefs>) => setPrefs((prev) => {
    const next = { ...prev, ...p }
    save(next)
    return next
  }), [])
  const reset = useCallback(() => {
    setPrefs(DEFAULT_PREFS)
    try {
      localStorage.removeItem(KEY)
    } catch {
      /* ignore */
    }
  }, [])
  return [prefs, update, reset]
}
