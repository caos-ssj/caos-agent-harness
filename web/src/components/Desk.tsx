import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api, RouterResponse, StateResponse, Task } from '../api'
import { CLOSED, NEEDS, age, byNeed, group, isSpecialKey, pad, queueName, routeText, stateLabel } from '../lib'
import { NewTask, NewTaskHandle } from './NewTask'
import { FirstSteps } from './FirstSteps'
import { Dock } from './Dock'

interface DeskProps {
  state: StateResponse | null
  selectedId: number | null
  onSelect: (id: number | null) => void
  onChanged: () => void
  onRun: () => void
  runnable: number
  filter: string | null
  onFilter: (f: string | null) => void
  focusComposer: number
}

/* The desk: queues on the left say who holds what, the list in the middle says what needs you first, and the dock on
   the right is the selected task's whole life. */
export const Desk: React.FC<DeskProps> = ({ state, selectedId, onSelect, onChanged, onRun, runnable, filter, onFilter, focusComposer }) => {
  const [showClosed, setShowClosed] = useState(false)
  const [dockOpen, setDockOpen] = useState(false)
  const [stepsHidden, setStepsHidden] = useState(() => { try { return localStorage.getItem('caos_steps_hidden') === '1' } catch { return false } })
  const [router, setRouter] = useState<RouterResponse | null>(null)
  const composer = useRef<NewTaskHandle>(null)
  const tasks = state?.tasks ?? []
  const agents = state?.agents ?? []
  const now = state?.now ?? Date.now() / 1000

  useEffect(() => { api.getRouter().then(setRouter).catch(() => setRouter(null)) }, [])
  useEffect(() => { if (focusComposer) composer.current?.focus() }, [focusComposer])

  const open = useMemo(() => tasks.filter((t) => !CLOSED.has(t.state)), [tasks])
  const queues = useMemo(() => [
    { id: '*', name: 'All open', art: 'board', sub: 'every queue, closed ones hidden', count: open.length, due: false, live: false },
    ...agents.map((a) => ({ id: a.name, name: a.name, art: 'router', sub: `${a.working ? 'sending' : 'idle'} · ${a.system || a.command}`, count: open.filter((t) => t.queue === a.name).length, due: false, live: a.working > 0 })),
    { id: 'person', name: 'a person', art: 'person', sub: 'no measured system qualifies', count: open.filter((t) => t.state === 'person').length, due: true, live: false },
    { id: 'review', name: 'to review', art: 'review', sub: 'delivered, waiting for a verdict', count: open.filter((t) => t.state === 'to_review' || t.state === 'verify').length, due: true, live: false },
  ], [open, agents])

  const rows = useMemo(() => {
    const pick = (t: Task) => (filter === 'needs' ? NEEDS.has(t.state) : filter === 'person' ? t.state === 'person' : filter === 'review' ? t.state === 'to_review' || t.state === 'verify' : filter && filter !== '*' ? t.queue === filter : true)
    return [...tasks].filter(pick).sort(byNeed)
  }, [tasks, filter])
  const needs = rows.filter((t) => group(t) === 'needs')
  const moving = rows.filter((t) => group(t) === 'moving')
  const closed = rows.filter((t) => group(t) === 'closed')

  // Open on the first thing that needs the operator, so the trace is never an empty box on a working board.
  useEffect(() => {
    if (selectedId == null || !tasks.some((t) => t.id === selectedId)) {
      const first = [...tasks].sort(byNeed)[0]
      if (first) onSelect(first.id)
    }
  }, [tasks, selectedId])

  const selected = tasks.find((t) => t.id === selectedId) ?? null
  const flat = [...needs, ...moving, ...(showClosed ? closed : [])]

  // j / k move through the list, n writes a task, Esc closes the trace on a narrow screen.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'Escape') { setDockOpen(false); (document.querySelector('.task[aria-current="true"]') as HTMLElement | null)?.focus(); return }
      if (isSpecialKey(e)) return
      const i = flat.findIndex((t) => t.id === selectedId)
      if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); const n = flat[Math.min(flat.length - 1, i + 1)]; if (n) onSelect(n.id) }
      if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); const n = flat[Math.max(0, i - 1)]; if (n) onSelect(n.id) }
      if (e.key === 'n') { e.preventDefault(); composer.current?.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [flat, selectedId])

  useEffect(() => { document.querySelector('.task[aria-current="true"]')?.scrollIntoView({ block: 'nearest' }) }, [selectedId])

  const advance = (id: number) => {
    const next = needs.find((t) => t.id !== id)
    if (next) onSelect(next.id)
  }
  const hideSteps = () => { setStepsHidden(true); try { localStorage.setItem('caos_steps_hidden', '1') } catch { /* ignore */ } }
  const ever = tasks.some((t) => t.review)
  const showSteps = tasks.length === 0 || (!ever && !stepsHidden)

  const row = (t: Task, i: number) => (
    <button
      key={t.id}
      type="button"
      className={`task ${group(t) === 'needs' ? 'needs' : ''} ${group(t) === 'closed' ? 'closed' : ''} ${t.state}`}
      aria-current={t.id === selectedId ? 'true' : undefined}
      style={{ animationDelay: `${Math.min(i, 10) * 22}ms` }}
      onClick={() => { onSelect(t.id); setDockOpen(true) }}
    >
      <span className="task-id">{pad(t.id)}</span>
      <span className="task-title">{t.text}</span>
      <span className="task-age" title={new Date(t.created * 1000).toLocaleString('en-US')}>{age(t.created, now)}</span>
      <span className="task-meta"><span className="st">{stateLabel(t)}</span><span className="route">{t.state === 'person' ? routeText(t) : `${queueName(t.queue)} · ${t.router ? routeText(t) : 'picked by you'}`}</span></span>
    </button>
  )

  const tierRows = router?.tiers ?? []
  let idx = 0

  return (
    <div className="desk">
      <section className="queues" aria-label="Queues">
        <div className="col-head"><h2>Queues</h2><span className="aside">who holds what</span></div>
        <div className="scroll">
          {queues.map((q) => (
            <button key={q.id} type="button" className={`q-row ${q.due && q.count ? 'due' : ''} ${q.count === 0 ? 'idle' : ''}`} aria-pressed={q.id === '*' ? !filter : filter === q.id} onClick={() => onFilter(q.id === '*' || filter === q.id ? null : q.id)}>
              <span className="q-name">{q.live && <span className="q-live" aria-hidden="true" />}{q.name}</span>
              <span className="q-count">{q.count}</span>
              <span className="q-sub">{q.sub}</span>
            </button>
          ))}
          {tierRows.length > 0 && (
            <div className="tiers">
              <h3>Who takes what</h3>
              <p>The router picks by what a wrong answer costs.</p>
              <dl>
                {tierRows.map((r) => (
                  <React.Fragment key={r.tier}>
                    <dt>{r.tier}</dt>
                    <dd className={r.action === 'route' ? '' : 'person'}>{r.action === 'route' ? r.system : 'a person'}</dd>
                  </React.Fragment>
                ))}
              </dl>
              <div className="src">from router.json · make route</div>
            </div>
          )}
        </div>
      </section>

      <section className="tasks" aria-label="Tasks">
        <div className="col-head"><h2>{filter === 'needs' ? 'Waiting for you' : filter && filter !== '*' ? queueName(filter === 'review' ? 'to review' : filter) : 'Tasks'}</h2><span className="aside">{rows.length} {rows.length === 1 ? 'task' : 'tasks'}{state?.running ? ' · a run is in progress' : ''}</span></div>
        <NewTask ref={composer} agents={agents} skills={state?.skills ?? []} tiers={state?.tiers ?? ['low', 'medium', 'high', 'critical']} onCreated={(id) => { onChanged(); onSelect(id); setFilterAll() }} />
        <div className="scroll" aria-label="Tasks by what needs you first">
          {showSteps && <FirstSteps tasks={tasks} agents={agents} runnable={runnable} running={!!state?.running} onAdd={() => composer.current?.focus()} onRun={onRun} onDismiss={tasks.length ? hideSteps : undefined} />}
          {needs.length > 0 && <div className="group-head due"><span>Needs you</span><span className="n">{needs.length}</span></div>}
          {needs.map((t) => row(t, idx++))}
          {moving.length > 0 && <div className="group-head"><span>In motion</span><span className="n">{moving.length}</span></div>}
          {moving.map((t) => row(t, idx++))}
          {closed.length > 0 && (
            <div className="group-head"><span>Closed</span><span className="n">{closed.length}</span><button type="button" onClick={() => setShowClosed(!showClosed)} aria-expanded={showClosed}>{showClosed ? 'hide' : 'show'}</button></div>
          )}
          {showClosed && closed.map((t) => row(t, idx++))}
          {tasks.length > 0 && rows.length === 0 && (
            <div className="plate-empty">
              <img src={`/art/${filter === 'person' ? 'person' : filter === 'review' || filter === 'needs' ? 'review' : 'board'}.svg`} alt="" aria-hidden="true" />
              <p>{filter === 'needs' || filter === 'review' ? 'Nothing is waiting for a verdict.' : filter === 'person' ? 'No task is waiting for a person.' : 'Nothing in this queue.'} Pick another queue on the left, or add a task above.</p>
            </div>
          )}
          {tasks.length > 0 && !filter && needs.length === 0 && (
            <div className="plate-empty">
              <img src="/art/review.svg" alt="" aria-hidden="true" />
              <p>Nothing is waiting for you. What is in motion will land here when it is delivered.</p>
            </div>
          )}
        </div>
      </section>

      <Dock
        task={selected}
        open={dockOpen}
        onClose={() => setDockOpen(false)}
        onChanged={onChanged}
        onVerdictDone={advance}
        empty={
          <div className="dock-empty">
            <img className="empty-art" src="/art/traces.svg" alt="" aria-hidden="true" style={{ marginTop: 8 }} />
            <p>Pick a task and its whole life shows here: who got it and why, what came back, and the verdict.</p>
            <div className="hints"><span className="kbd">j</span><span>next task</span><span className="kbd">k</span><span>previous task</span><span className="kbd">n</span><span>new task</span><span className="kbd">⌘K</span><span>everything else</span></div>
          </div>
        }
      />
    </div>
  )

  function setFilterAll() { if (filter && filter !== '*') onFilter(null) }
}
