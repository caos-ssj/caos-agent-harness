import React, { useEffect, useMemo, useState } from 'react'
import { Agent, Task, TaskDetail, api } from '../api'

/* The board: lanes say who holds what, the table says what happens next, and a row opens in place with
   what was delivered, the verdict and the task's trace. Order is by what needs the operator first. */

interface BoardProps {
  tasks: Task[]
  agents: Agent[]
  running: boolean
  selectedTaskId: number | null
  onSelectTask: (id: number | null) => void
  onChanged: () => void
}

const RANK: Record<string, number> = { to_review: 0, verify: 1, person: 2, sending: 3, pending: 4, sent: 5, ok: 6, superseded: 7, discarded: 8 }
const LABEL: Record<string, string> = {
  to_review: 'to review', verify: 'verify', person: 'with a person', sending: 'sending', pending: 'pending', sent: 'sent',
  ok: 'accepted', superseded: 'superseded', discarded: 'discarded', redo: 'returned',
}
const OPEN = new Set(['to_review', 'verify', 'person', 'sending', 'pending', 'sent'])

function age(ts: number, now: number): string {
  const s = Math.max(0, Math.round(now - ts))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

function routerCell(t: Task): string {
  if (!t.router) return '—'
  return `${t.router.tier} → ${t.router.action === 'route' ? t.router.system : 'a person'}`
}

export const Board: React.FC<BoardProps> = ({ tasks, agents, running, selectedTaskId, onSelectTask, onChanged }) => {
  const [lane, setLane] = useState<string | null>(null)
  const [showClosed, setShowClosed] = useState(false)
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const now = Date.now() / 1000

  useEffect(() => {
    setNote('')
    setError(null)
    if (selectedTaskId == null) return setDetail(null)
    let live = true
    api.getTask(selectedTaskId).then((d) => live && setDetail(d)).catch((e) => live && setError(e.message))
    return () => { live = false }
  }, [selectedTaskId, tasks])

  const lanes = useMemo(() => {
    const open = tasks.filter((t) => OPEN.has(t.state))
    return [
      ...agents.map((a) => ({
        id: a.name, title: a.name, art: 'board', sub: a.system || a.command,
        items: open.filter((t) => t.queue === a.name && (t.state === 'pending' || t.state === 'sending' || t.state === 'sent')),
        status: a.working ? 'working' : 'idle',
      })),
      { id: 'person', title: 'a person', art: 'person', sub: 'no measured system qualifies', items: open.filter((t) => t.state === 'person'), status: '' },
      { id: 'review', title: 'to review', art: 'review', sub: 'delivered, waiting for a verdict', items: open.filter((t) => t.state === 'to_review' || t.state === 'verify'), status: '' },
    ]
  }, [tasks, agents])

  const rows = useMemo(() => {
    let list = tasks.filter((t) => showClosed || OPEN.has(t.state))
    if (lane === 'person') list = list.filter((t) => t.state === 'person')
    else if (lane === 'review') list = list.filter((t) => t.state === 'to_review' || t.state === 'verify')
    else if (lane) list = list.filter((t) => t.queue === lane)
    return [...list].sort((a, b) => (RANK[a.state] ?? 9) - (RANK[b.state] ?? 9) || b.id - a.id)
  }, [tasks, lane, showClosed])

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      setNote('')
      onChanged()
    } catch (e: any) {
      setError(e.message || 'The board refused that action')
    } finally {
      setBusy(false)
    }
  }
  const verdict = (id: number, v: 'ok' | 'redo' | 'verify' | 'superseded') => {
    if (v === 'redo' && !note.trim()) return setError('A redo needs a note: say what to fix.')
    return act(() => api.reviewTask(id, v, note.trim() || undefined))
  }

  return (
    <div className="board">
      <div className="lanes" role="list" aria-label="Queues">
        {lanes.map((l) => (
          <button
            key={l.id}
            type="button"
            role="listitem"
            aria-pressed={lane === l.id}
            onClick={() => setLane(lane === l.id ? null : l.id)}
            className={`lane ${lane === l.id ? 'lane-on' : ''} ${l.id === 'review' && l.items.length ? 'lane-due' : ''}`}
          >
            <img src={`/art/${l.art}.svg`} alt="" aria-hidden="true" className="lane-art" />
            <span className="lane-head">
              <span className="lane-name">{l.title}</span>
              <span className="lane-count">{l.items.length}</span>
            </span>
            <span className="lane-sub">{l.status ? `${l.status} · ${l.sub}` : l.sub}</span>
            <span className="lane-chips">
              {l.items.slice(0, 3).map((t) => (
                <span key={t.id} className="lane-chip">
                  <b>{String(t.id).padStart(2, '0')}</b> {t.text}
                </span>
              ))}
              {l.items.length > 3 && <span className="lane-more">+{l.items.length - 3} more</span>}
              {l.items.length === 0 && <span className="lane-more">empty</span>}
            </span>
          </button>
        ))}
      </div>

      <div className="departures-bar">
        <span>
          {rows.length} {rows.length === 1 ? 'task' : 'tasks'}
          {lane ? ` in ${lane === 'review' ? 'review' : lane === 'person' ? 'the queue of a person' : lane}` : ''}
          {running ? ' · a run is in progress' : ''}
        </span>
        <label>
          <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} /> show closed
        </label>
      </div>

      <div className="departures" role="table" aria-label="Tasks">
        <div className="dep-row dep-head" role="row">
          <span role="columnheader">ID</span>
          <span role="columnheader">State</span>
          <span role="columnheader">Task</span>
          <span role="columnheader">Queue</span>
          <span role="columnheader">Router</span>
          <span role="columnheader">Age</span>
        </div>
        {rows.length === 0 && (
          <div className="dep-empty">
            <img src="/art/traces.svg" alt="" aria-hidden="true" />
            <p>
              Nothing here yet. Add a task with a queue, or with a cost-of-error tier and let the router pick the agent, or a person.
            </p>
          </div>
        )}
        {rows.map((t) => {
          const open = t.id === selectedTaskId
          const d = open && detail && detail.id === t.id ? detail : null
          return (
            <React.Fragment key={t.id}>
              <button type="button" role="row" aria-expanded={open} onClick={() => onSelectTask(open ? null : t.id)} className={`dep-row dep-task st-${t.state} ${open ? 'dep-open' : ''}`}>
                <span role="cell" className="dep-id">{String(t.id).padStart(2, '0')}</span>
                <span role="cell" className="dep-state">{LABEL[t.state] ?? t.state}</span>
                <span role="cell" className="dep-text">{t.text}</span>
                <span role="cell">{t.queue === 'person' ? 'a person' : t.queue}{t.skill ? ` · ${t.skill}` : ''}</span>
                <span role="cell">{routerCell(t)}</span>
                <span role="cell" className="dep-age">{age(t.created, now)}</span>
              </button>
              {open && (
                <div className="dep-detail">
                  {!d && !error && <p className="dep-muted">Loading the task…</p>}
                  {d && (
                    <>
                      <div className="dep-cols">
                        <section>
                          <h3>Asked</h3>
                          <p className="dep-body">{d.text}</p>
                          <h3>Delivered</h3>
                          {d.result != null ? (
                            <pre className="dep-result">{d.result || '(the agent printed nothing)'}</pre>
                          ) : (
                            <p className="dep-muted">
                              {d.state === 'person' ? 'Waiting for a person. The trace on the right says why the router sent it here.' : 'Nothing delivered yet. Run the pending tasks to send it to its agent.'}
                            </p>
                          )}
                          {d.review_note && <p className="dep-note">Reviewer’s note: {d.review_note}</p>}
                        </section>
                        <section>
                          <h3>Trace</h3>
                          <ol className="dep-trace">
                            {d.timeline.map((e) => (
                              <li key={e.seq}>
                                <span className={`tr-src tr-${e.source}`}>{e.source}</span>
                                <span className="tr-what">{e.status || e.kind}{e.name ? ` · ${e.name}` : ''}</span>
                                {e.reason && <span className="tr-why">{e.reason}</span>}
                              </li>
                            ))}
                          </ol>
                        </section>
                      </div>
                      {(d.state === 'to_review' || d.state === 'verify') && (
                        <div className="dep-verdict">
                          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note for the verdict (required for a redo)" aria-label="Note for the verdict" />
                          <button type="button" disabled={busy} className="v-ok" onClick={() => verdict(d.id, 'ok')}>Accept</button>
                          <button type="button" disabled={busy} onClick={() => verdict(d.id, 'redo')}>Return with note</button>
                          {d.state !== 'verify' && <button type="button" disabled={busy} onClick={() => verdict(d.id, 'verify')}>Needs evidence</button>}
                          <button type="button" disabled={busy} onClick={() => verdict(d.id, 'superseded')}>Superseded</button>
                        </div>
                      )}
                      {(d.state === 'pending' || d.state === 'person') && (
                        <div className="dep-verdict">
                          <span className="dep-muted">Still in the queue.</span>
                          <button type="button" disabled={busy} onClick={() => act(() => api.discardTask(d.id))}>Discard</button>
                        </div>
                      )}
                    </>
                  )}
                  {error && <p className="dep-error" role="alert">{error}</p>}
                </div>
              )}
            </React.Fragment>
          )
        })}
      </div>
    </div>
  )
}
