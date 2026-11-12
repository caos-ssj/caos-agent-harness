import type React from 'react'
import { BoardStats, BoardSummary, Task } from './api'

/* Shared words, state mappings, and helpers aligned between Web and TUI. */

export type View = 'console' | 'board' | 'providers' | 'metrics' | 'skills' | 'share'

export const NEEDS = new Set(['to_review', 'verify', 'person'])
export const MOVING = new Set(['pending', 'sending', 'sent'])
export const CLOSED = new Set(['ok', 'superseded', 'discarded'])

export const STATE_LABEL: Record<string, string> = {
  to_review: 'to review',
  verify: 'verify',
  person: 'with a person',
  sending: 'sending',
  pending: 'pending',
  sent: 'sent, no delivery',
  ok: 'accepted',
  superseded: 'superseded',
  discarded: 'discarded',
  redo: 'returned',
}

export function stateLabel(t: Pick<Task, 'state' | 'review'>): string {
  if (t.state === 'pending' && t.review === 'redo') return 'returned'
  return STATE_LABEL[t.state] ?? t.state
}

export function group(t: Pick<Task, 'state'>): 'needs' | 'moving' | 'closed' {
  return NEEDS.has(t.state) ? 'needs' : CLOSED.has(t.state) ? 'closed' : 'moving'
}

const RANK: Record<string, number> = {
  to_review: 0,
  verify: 1,
  person: 2,
  sending: 3,
  pending: 4,
  sent: 5,
  ok: 6,
  superseded: 7,
  discarded: 8,
}
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

export function boardCounts(state: { tasks?: Task[]; summary?: BoardSummary; stats?: BoardStats } | null | undefined) {
  const tasks = state?.tasks ?? []
  const sm = state?.summary
  const needs = sm ? sm.needs_you : tasks.filter((t) => NEEDS.has(t.state)).length
  const toReview = sm ? sm.to_review : tasks.filter((t) => t.state === 'to_review' || t.state === 'verify').length
  const withPerson = sm ? sm.with_person : tasks.filter((t) => t.state === 'person').length
  const runnable = sm ? sm.runnable : tasks.filter((t) => t.state === 'pending' && t.queue !== 'person').length
  const st = state?.stats
  const total = st ? st.tasks : tasks.length
  const closed = st ? (st.review?.ok ?? 0) + (st.review?.superseded ?? 0) + (st.by_status?.discarded ?? 0) : tasks.filter((t) => CLOSED.has(t.state)).length
  const moving = Math.max(0, total - needs - closed)
  return { needs, toReview, withPerson, runnable, total, closed, moving }
}

export const pctOf = (n: number, total: number) => (total > 0 ? `${Math.round((n / total) * 100)}%` : null)

export function onTabKeys(e: React.KeyboardEvent<HTMLElement>) {
  const tabs = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]'))
  const i = tabs.indexOf(document.activeElement as HTMLElement)
  if (i < 0) return
  const n = e.key === 'ArrowRight' ? (i + 1) % tabs.length : e.key === 'ArrowLeft' ? (i - 1 + tabs.length) % tabs.length : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : -1
  if (n < 0) return
  e.preventDefault()
  tabs[n].focus()
  tabs[n].click()
}

/** Terminal colour and cursor codes, removed: a step's output is shown as text, never as stray `[31m`. */
export const stripAnsi = (text: string) => text.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '').replace(/\x1b\][^\x07]*\x07/g, '').replace(/\r(?!\n)/g, '\n')

/** "hace 5 min" style, in Spanish, for the activity feed. */
export function ago(tsSeconds: number, nowMs: number = Date.now()): string {
  const s = Math.max(0, Math.round(nowMs / 1000 - tsSeconds))
  if (s < 45) return 'ahora'
  if (s < 3600) return `hace ${Math.max(1, Math.round(s / 60))} min`
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`
  return `hace ${Math.round(s / 86400)} d`
}
