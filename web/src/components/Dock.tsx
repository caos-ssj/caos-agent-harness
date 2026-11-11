import React, { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { api, Task, TaskDetail } from '../api'
import { NEEDS, clock, pad, queueName, routeText, stateLabel } from '../lib'

interface DockProps {
  task: Task | null
  empty: React.ReactNode
  open: boolean
  onClose: () => void
  onChanged: () => void
  onVerdictDone: (id: number) => void
}

/* One task's whole life: what was asked, who got it and why, what came back, and the verdict. */
export const Dock: React.FC<DockProps> = ({ task, empty, open, onClose, onChanged, onVerdictDone }) => {
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const sig = task ? `${task.state}:${task.review}:${task.delivered}:${task.queue}` : ''

  useEffect(() => { setNote(''); setError(null) }, [task?.id])
  // On a narrow screen the trace is a sheet: move focus into it when it opens.
  useEffect(() => { if (open && window.matchMedia('(max-width: 980px)').matches) heading.current?.focus() }, [open, task?.id])
  useEffect(() => {
    if (!task) { setDetail(null); return }
    let live = true
    api.getTask(task.id).then((d) => live && setDetail(d)).catch((e) => live && setError(e.message))
    return () => { live = false }
  }, [task?.id, sig])

  if (!task) return <section className={`dock ${open ? '' : 'closed'}`} aria-label="Task trace">{empty}</section>
  const d = detail && detail.id === task.id ? detail : null
  const routerWhy = d?.timeline.find((e) => e.source === 'router' && e.reason)?.reason
  const reviewable = task.state === 'to_review' || task.state === 'verify'
  const needs = NEEDS.has(task.state)

  const act = async (fn: () => Promise<unknown>, advance = false) => {
    setBusy(true); setError(null)
    try { await fn(); setNote(''); onChanged(); if (advance) onVerdictDone(task.id) }
    catch (e: any) { setError(e.message || 'The board refused that action.') }
    finally { setBusy(false) }
  }
  const verdict = (v: 'ok' | 'redo' | 'verify' | 'superseded') => {
    if (v === 'redo' && !note.trim()) return setError('A returned task needs a note: say what to fix.')
    return act(() => api.reviewTask(task.id, v, note.trim() || undefined), true)
  }

  return (
    <section className={`dock ${open ? '' : 'closed'}`} aria-label={`Task ${task.id}`}>
      <div className="dock-head">
        <h2 className="dock-title" tabIndex={-1} ref={heading}>{task.text}</h2>
        <div className="dock-meta">
          <span>task {pad(task.id)}</span>
          <span className={`dock-state ${needs ? 'needs' : ''}`}>{stateLabel(task)}</span>
        </div>
        <button type="button" className="btn btn-quiet btn-sm dock-close" onClick={onClose} aria-label="Close the trace"><X size={16} aria-hidden="true" /></button>
      </div>
      <div className="dock-body" key={task.id}>
        <h3>Who got it</h3>
        <p className="body"><b style={{ fontWeight: 600 }}>{queueName(task.queue)}</b>{task.router ? `, by the router: ${routeText(task)}` : task.queue === 'person' ? ', by your choice' : ', picked by you'}{task.skill ? `. Skill: ${task.skill}.` : '.'}</p>
        {routerWhy && <p className="muted" style={{ marginTop: 4 }}>{routerWhy.charAt(0).toUpperCase() + routerWhy.slice(1)}.</p>}
        <h3>Delivered</h3>
        {d?.result != null ? <pre className="delivered">{d.result || '(the agent printed nothing)'}</pre>
          : <p className="muted">{task.state === 'person' ? 'Waiting for a person. The trace below says why the router sent it here.' : 'Nothing delivered yet. Run the pending tasks to send it to its agent.'}</p>}
        {task.review_note && <p className="reviewer-note">Reviewer’s note: {task.review_note}</p>}
        <h3>Trace</h3>
        {!d && !error && <p className="muted">Reading the trace…</p>}
        {d && (
          <ol className="trace">
            {d.timeline.map((e, i) => (
              <li key={e.seq} className={e.source} style={{ ['--i' as any]: Math.min(i, 8) }}>
                <span className="src">{e.source}</span>
                <span className="what">{e.status || e.kind}{e.name ? ` · ${e.name}` : ''}</span>
                <span className="at">{clock(e.ts)}</span>
                {e.reason && <span className="why">{e.reason}</span>}
              </li>
            ))}
          </ol>
        )}
      </div>
      {(reviewable || task.state === 'pending' || task.state === 'person') && (
        <div className="verdict">
          {reviewable ? (
            <>
              <input className="verdict-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why? A note is required when you return it" aria-label="Note for the verdict" />
              <div className="verdict-row">
                <button type="button" className="btn btn-primary" disabled={busy} onClick={() => verdict('ok')}>Accept</button>
                <button type="button" className="btn" disabled={busy} onClick={() => verdict('redo')}>Return</button>
                {task.state !== 'verify' && <button type="button" className="btn" disabled={busy} onClick={() => verdict('verify')}>Needs evidence</button>}
                <span className="spacer" />
                <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => verdict('superseded')}>Superseded</button>
              </div>
            </>
          ) : (
            <div className="verdict-row">
              <span className="muted" style={{ fontSize: 15 }}>Still in the queue.</span>
              <span className="spacer" />
              <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => act(() => api.discardTask(task.id), true)}>Discard</button>
            </div>
          )}
          {error && <p className="verdict-err" role="alert">{error}</p>}
        </div>
      )}
      {!reviewable && task.state !== 'pending' && task.state !== 'person' && error && <p className="verdict-err" role="alert" style={{ padding: '0 20px 14px' }}>{error}</p>}
    </section>
  )
}
