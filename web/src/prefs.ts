import { useCallback, useState } from 'react'
import { View } from './lib'

export type RoutingProfile = 'local-first' | 'hybrid' | 'cloud-max'
export type DensityMode = 'compact' | 'comfortable' | 'wide'
export type GlowIntensity = 'subtle' | 'medium' | 'high'

export interface Prefs {
  density: DensityMode
  text: 'standard' | 'large'
  glow: GlowIntensity
  start: View
  notify: boolean
  /** Short tones on milestones (start, landed, rejected, failed, waits for you). */
  sound: boolean
  /** `fluid` animates; `focus` stills every decorative motion. Starts in `fluid` whatever the system asks. */
  motion: 'fluid' | 'focus'
  /** Whether the right-hand inspector of Console starts open. */
  inspector: boolean
  profile: RoutingProfile
}

export const DEFAULT_PREFS: Prefs = { density: 'compact', text: 'standard', glow: 'medium', start: 'console', notify: false, sound: true, motion: 'fluid', inspector: true, profile: 'hybrid' }
const KEY = 'caos_prefs'
const VALID_VIEWS: View[] = ['run', 'console', 'board', 'providers', 'metrics', 'skills', 'share']
const PROFILES: RoutingProfile[] = ['local-first', 'hybrid', 'cloud-max']
const DENSITIES: DensityMode[] = ['compact', 'comfortable', 'wide']
const GLOWS: GlowIntensity[] = ['subtle', 'medium', 'high']

export function readPrefs(raw: Record<string, unknown>): Prefs {
  const mapped = raw.start === 'measured' ? 'metrics' : raw.start
  return {
    density: DENSITIES.includes(raw.density as DensityMode) ? (raw.density as DensityMode) : 'compact',
    text: raw.text === 'large' ? 'large' : 'standard',
    glow: GLOWS.includes(raw.glow as GlowIntensity) ? (raw.glow as GlowIntensity) : 'medium',
    notify: raw.notify === true,
    sound: raw.sound !== false,
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
