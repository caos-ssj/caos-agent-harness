import { useCallback, useState } from 'react'

/* Saved views of the board: a name for a combination of queue, scope and search. Kept in this browser only. */
export interface SavedView { name: string; queue: string | null; scope: string; q: string }
const KEY = 'caos_views'

export function useSavedViews(): [SavedView[], (v: SavedView) => void, (name: string) => void] {
  const [views, setViews] = useState<SavedView[]>(() => {
    try { const raw = JSON.parse(localStorage.getItem(KEY) || '[]'); return Array.isArray(raw) ? raw.filter((v) => v && typeof v.name === 'string' && typeof v.q === 'string' && ['all', 'needs', 'moving', 'closed'].includes(v.scope) && (v.queue === null || typeof v.queue === 'string')).slice(0, 12) : [] } catch { return [] }
  })
  const persist = (next: SavedView[]) => { try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* private mode */ } return next }
  const add = useCallback((v: SavedView) => setViews((cur) => persist([...cur.filter((x) => x.name !== v.name), v].slice(-12))), [])
  const remove = useCallback((name: string) => setViews((cur) => persist(cur.filter((x) => x.name !== name))), [])
  return [views, add, remove]
}
