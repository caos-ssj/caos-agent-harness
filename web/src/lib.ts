import { Task } from './api'

/* Words and groupings shared by every view, so the board, the palette and the ledger say the same thing. */

export type View = 'desk' | 'console' | 'library'

export const NEEDS = new Set(['to_review', 'verify', 'person'])
export const MOVING = new Set(['pending', 'sending', 'sent'])
export const CLOSED = new Set(['ok', 'superseded', 'discarded'])

export const STATE_LABEL: Record<string, string> = {
  to_review: 'to review', verify: 'verify', person: 'with a person', sending: 'sending', pending: 'pending', sent: 'sent, no delivery',
  ok: 'accepted', superseded: 'superseded', discarded: 'discarded', redo: 'returned',
}

export function stateLabel(t: Pick<Task, 'state' | 'review'>): string {
  if (t.state === 'pending' && t.review === 'redo') return 'returned'
  return STATE_LABEL[t.state] ?? t.state
}

export function group(t: Pick<Task, 'state'>): 'needs' | 'moving' | 'closed' {
  return NEEDS.has(t.state) ? 'needs' : CLOSED.has(t.state) ? 'closed' : 'moving'
}

const RANK: Record<string, number> = { to_review: 0, verify: 1, person: 2, sending: 3, pending: 4, sent: 5, ok: 6, superseded: 7, discarded: 8 }
export const byNeed = (a: Task, b: Task) => (RANK[a.state] ?? 9) - (RANK[b.state] ?? 9) || b.id - a.id

export function age(ts: number, now: number): string {
  const s = Math.max(0, Math.round(now - ts))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

export const clock = (ts: number) => new Date(ts * 1000).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
export const pad = (id: number) => String(id).padStart(2, '0')
export const queueName = (q: string) => (q === 'person' ? 'a person' : q)

export function routeText(t: Task): string {
  if (!t.router) return t.queue === 'person' ? 'to a person' : `queue ${t.queue}`
  return `${t.router.tier} → ${t.router.action === 'route' ? t.router.system : 'a person'}`
}

export const isSpecialKey = (e: KeyboardEvent) => {
  const el = e.target as HTMLElement | null
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)
}

export const fmt = (n: number) => n.toLocaleString('en-US')
