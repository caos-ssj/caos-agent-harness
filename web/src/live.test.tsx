import { afterEach, describe, expect, it, vi } from 'vitest'
import { liveSupported, watchEvents, watchRun } from './api'

class FakeSource {
  static all: FakeSource[] = []
  listeners: Record<string, Array<(e: MessageEvent) => void>> = {}
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  constructor(public url: string) { FakeSource.all.push(this) }
  addEventListener(type: string, fn: (e: MessageEvent) => void) { (this.listeners[type] ||= []).push(fn) }
  emit(type: string, data: unknown) { for (const fn of this.listeners[type] ?? []) fn({ data: typeof data === 'string' ? data : JSON.stringify(data) } as MessageEvent) }
  close() { this.closed = true }
}

afterEach(() => { vi.unstubAllGlobals(); FakeSource.all = [] })

describe('live updates', () => {
  it('has no stream where the browser has no EventSource (jsdom), so callers keep polling', () => {
    expect(typeof EventSource).toBe('undefined')
    expect(liveSupported()).toBe(false)
    expect(watchEvents(() => undefined)).toBeNull()
    expect(watchRun('a'.repeat(32), () => undefined)).toBeNull()
  })

  it('passes board, run and session versions as they arrive and survives a malformed event', () => {
    vi.stubGlobal('EventSource', FakeSource)
    const seen: Array<Record<string, number>> = []
    const states: boolean[] = []
    const h = watchEvents((v) => seen.push(v), (c) => states.push(c))!
    const es = FakeSource.all[0]
    expect(es.url).toBe('/api/events')
    es.onopen?.()
    es.emit('change', { board: 1, runs: 0, sessions: 0 })
    es.emit('change', 'not json {')
    es.emit('change', { board: 2, runs: 1, sessions: 0 })
    es.onerror?.()
    expect(seen).toEqual([{ board: 1, runs: 0, sessions: 0 }, { board: 2, runs: 1, sessions: 0 }])
    expect(states).toEqual([true, false])
    h.close()
    expect(es.closed).toBe(true)
  })

  it('follows one run until it ends and then closes the stream so the browser does not reconnect to it', () => {
    vi.stubGlobal('EventSource', FakeSource)
    const runs: string[] = []
    const id = 'b'.repeat(32)
    watchRun(id, (r) => runs.push(r.status))
    const es = FakeSource.all[0]
    expect(es.url).toBe(`/api/runs/${id}/events`)
    es.emit('run', { status: 'running' })
    expect(es.closed).toBe(false)
    es.emit('run', { status: 'completed' })
    expect(runs).toEqual(['running', 'completed'])
    expect(es.closed).toBe(true)
  })
})
