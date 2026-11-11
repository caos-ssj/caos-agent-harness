import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Archive, CheckCircle2, ChevronDown, ChevronRight, CircleSlash, Clock, Eye, Loader, Play, Plus, RotateCcw, ScanSearch, Send, UserRound, X } from 'lucide-react'
import { api, Agent, RouterResponse, SkillInfo, StateResponse, Task, TaskDetail } from '../api'
import { PageHead } from './PageHead'
import { CLOSED, NEEDS, age, byNeed, clock, group, isSpecialKey, pad, queueName, routeText, stateLabel } from '../lib'
import { FirstSteps } from './FirstSteps'

/* The board. Lanes say who holds what and how much of it needs you; the list says what to do first; a row opens in
   place with what was asked, what came back, the trace and the verdict. */

const ICON: Record<string, React.ElementType> = { to_review: Eye, verify: ScanSearch, person: UserRound, sending: Loader, pending: Clock, returned: RotateCcw, sent: Send, ok: CheckCircle2, superseded: Archive, discarded: CircleSlash }
const stateKey = (t: Task) => (t.state === 'pending' && t.review === 'redo' ? 'returned' : t.state)

interface BoardProps {
  router: RouterResponse | null
  state: StateResponse | null
  selectedId: number | null
  onSelect: (id: number | null) => void
  onChanged: () => void
  onRun: () => void
  runnable: number
  filter: string | null
  onFilter: (f: string | null) => void
  newTaskSignal: number
}

const StatePill: React.FC<{ t: Task }> = ({ t }) => {
  const Icon = ICON[stateKey(t)] ?? Clock
  return <span className={`pill ${group(t) === 'needs' ? 'needs' : group(t) === 'closed' ? 'closed' : 'moving'}`}><Icon aria-hidden="true" />{stateLabel(t)}</span>
}

/* One form to add work: what, who gets it, and an optional skill. The router can choose, by what a wrong answer costs. */
const NewTask: React.FC<{ router: RouterResponse | null; agents: Agent[]; skills: SkillInfo[]; tiers: string[]; onCreated: (id: number) => void; onClose: () => void; focus: number }> = ({ router, agents, skills, tiers, onCreated, onClose, focus }) => {
  const [text, setText] = useState('')
  const [who, setWho] = useState('')
  const [skill, setSkill] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<{ msg: string; err?: boolean } | null>(null)
  const field = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { field.current?.focus() }, [focus])
  // Until the operator chooses, the default is the first agent this project defines; with none, the router decides.
  const chosen = who || (agents.length ? `agent:${agents[0].name}` : tiers.length ? `tier:${tiers.includes('medium') ? 'medium' : tiers[0]}` : '')
  const submit = async () => {
    if (!text.trim() || busy) return
    setBusy(true); setNote(null)
    try {
      const [kind, value] = chosen.split(':')
      const res = await api.addTask({ text: text.trim(), skill: skill || undefined, ...(kind === 'tier' ? { tier: value } : { queue: value }) })
      setText('')
      setNote({ msg: `Added as task ${res.id} for ${queueName(res.queue)}. ${res.why.charAt(0).toUpperCase()}${res.why.slice(1)}.` })
      onCreated(res.id)
    } catch (e: any) { setNote({ msg: e.message || 'The board refused the task.', err: true }) } finally { setBusy(false) }
  }
  return (
    <form className="card newtask" onSubmit={(e) => { e.preventDefault(); submit() }} aria-label="Add a task">
      <h2>New task</h2>
      <textarea ref={field} aria-label="Task" value={text} placeholder="Say what you need, in your own words. For example: check that the memory module reconnects after a failure, and report what you find."
        onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if ((e.key === 'Enter' && (e.metaKey || e.ctrlKey))) { e.preventDefault(); submit() } }} />
      <div className="newtask-bar">
        <select className="select" aria-label="Who gets it" value={chosen} onChange={(e) => setWho(e.target.value)}>
          {agents.length > 0 && <optgroup label="An agent from harness.toml">{agents.map((a) => { const m = router?.profiles.find((p) => p.system === a.system); return <option key={a.name} value={`agent:${a.name}`}>{a.name}{a.system ? ` · ${a.system}` : ''}{m ? ` · lower bound ${(m.precision_lo * 100).toFixed(0)}%` : ''}</option> })}</optgroup>}
          <optgroup label="The router decides, by what a wrong answer costs">{tiers.map((t) => { const r = router?.tiers.find((x) => x.tier === t); return <option key={t} value={`tier:${t}`}>cost of an error: {t}{r ? ` → ${r.action === 'route' ? r.system : 'a person'}` : ''}</option> })}</optgroup>
          <optgroup label="Human review"><option value="agent:person">a person, no agent</option></optgroup>
        </select>
        <select className="select" aria-label="Skill to load first" value={skill} onChange={(e) => setSkill(e.target.value)}>
          <option value="">no skill</option>
          {skills.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </select>
        <span className="grow" />
        <button type="button" className="btn btn-quiet" onClick={onClose}>Close</button>
        <button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}><Plus className="icon" aria-hidden="true" />{busy ? 'Adding…' : 'Add to the board'}</button>
      </div>
      <p className="note" style={{ color: 'var(--ink-3)', marginTop: 8 }}>⌘↵ adds it. It stays open until you review what comes back.</p>
      {note && <p className={`note ${note.err ? 'err' : ''}`} role={note.err ? 'alert' : 'status'}>{note.msg}</p>}
    </form>
  )
}

export const Board: React.FC<BoardProps> = ({ router, state, selectedId, onSelect, onChanged, onRun, runnable, filter, onFilter, newTaskSignal }) => {
  const [showClosed, setShowClosed] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [stepsHidden, setStepsHidden] = useState(() => { try { return localStorage.getItem('caos_steps_hidden') === '1' } catch { return false } })
  const tasks = state?.tasks ?? []
  const agents = state?.agents ?? []
  const now = state?.now ?? Date.now() / 1000
  const sel = tasks.find((t) => t.id === selectedId) ?? null
  const sig = sel ? `${sel.state}:${sel.review}:${sel.delivered}:${sel.queue}` : ''

  useEffect(() => { if (newTaskSignal) setShowNew(true) }, [newTaskSignal])
  useEffect(() => { setNote(''); setError(null) }, [selectedId])
  useEffect(() => {
    if (selectedId == null) return setDetail(null)
    let live = true
    api.getTask(selectedId).then((d) => live && setDetail(d)).catch((e) => live && setError(e.message))
    return () => { live = false }
  }, [selectedId, sig])

  const open = useMemo(() => tasks.filter((t) => !CLOSED.has(t.state)), [tasks])
  type Lane = { id: string; title: string; art: string; kind: 'agent' | 'person' | 'review'; model: string | null; precision: number | null; lower: number | null; serves: string[]; live: boolean; items: Task[]; due: boolean; blurb: string }
  const lanes = useMemo<Lane[]>(() => [
    ...agents.map((a): Lane => {
      const m = router?.profiles.find((p) => p.system === a.system)
      return { id: a.name, title: a.name, art: 'board', kind: 'agent', model: a.system || null, precision: m?.precision ?? null, lower: m?.precision_lo ?? null, serves: (router?.tiers ?? []).filter((t) => t.agent === a.name).map((t) => t.tier), live: a.working > 0, items: open.filter((t) => t.queue === a.name), due: false, blurb: a.system ? '' : `runs ${a.command}` }
    }),
    { id: 'person', title: 'A person', art: 'person', kind: 'person', model: null, precision: null, lower: null, serves: (router?.tiers ?? []).filter((t) => t.action !== 'route').map((t) => t.tier), live: false, items: open.filter((t) => t.state === 'person'), due: true, blurb: 'Decides what no measured model is reliable enough for.' },
    { id: 'review', title: 'To review', art: 'review', kind: 'review', model: null, precision: null, lower: null, serves: [], live: false, items: open.filter((t) => t.state === 'to_review' || t.state === 'verify'), due: true, blurb: 'Delivered by an agent. Nothing closes until you give a verdict.' },
  ], [open, agents, router])
  const agentLanes = lanes.filter((l) => l.kind === 'agent')
  const waitLanes = lanes.filter((l) => l.kind !== 'agent')

  const rows = useMemo(() => {
    const pick = (t: Task) => (filter === 'needs' ? NEEDS.has(t.state) : filter === 'person' ? t.state === 'person' : filter === 'review' ? t.state === 'to_review' || t.state === 'verify' : filter ? t.queue === filter : true)
    return [...tasks].filter(pick).sort(byNeed)
  }, [tasks, filter])
  const needs = rows.filter((t) => group(t) === 'needs')
  const moving = rows.filter((t) => group(t) === 'moving')
  const closed = rows.filter((t) => group(t) === 'closed')
  const flat = [...needs, ...moving, ...(showClosed ? closed : [])]
  const ever = tasks.some((t) => t.review)
  const showSteps = tasks.length === 0 || (!ever && !stepsHidden)

  // j / k move through the list, n writes a task, Esc closes the open row.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isSpecialKey(e)) return
      const i = flat.findIndex((t) => t.id === selectedId)
      if (e.key === 'j') { const n = flat[Math.min(flat.length - 1, i + 1)]; if (n) onSelect(n.id) }
      else if (e.key === 'k') { const n = flat[Math.max(0, i - 1)]; if (n) onSelect(n.id) }
      else if (e.key === 'n') { e.preventDefault(); setShowNew(true) }
      else if (e.key === 'Escape') onSelect(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [flat, selectedId])
  useEffect(() => { document.querySelector('.task.open')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [selectedId])

  const act = async (fn: () => Promise<unknown>, id: number) => {
    setBusy(true); setError(null)
    try { await fn(); setNote(''); onChanged(); const next = needs.find((t) => t.id !== id); onSelect(next ? next.id : null) }
    catch (e: any) { setError(e.message || 'The board refused that action.') } finally { setBusy(false) }
  }
  const verdict = (id: number, v: 'ok' | 'redo' | 'verify' | 'superseded') => {
    if (v === 'redo' && !note.trim()) return setError('A returned task needs a note: say what to fix.')
    return act(() => api.reviewTask(id, v, note.trim() || undefined), id)
  }
  const hideSteps = () => { setStepsHidden(true); try { localStorage.setItem('caos_steps_hidden', '1') } catch { /* ignore */ } }

  const row = (t: Task, i: number) => {
    const isOpen = t.id === selectedId
    const d = isOpen && detail && detail.id === t.id ? detail : null
    const routerWhy = d?.timeline.find((e) => e.source === 'router' && e.reason)?.reason
    const reviewable = t.state === 'to_review' || t.state === 'verify'
    return (
      <div key={t.id} className={`task ${isOpen ? 'open' : ''} ${group(t)} ${t.state}`} style={{ animationDelay: `${Math.min(i, 10) * 22}ms` }}>
        <button type="button" className="task-row" aria-expanded={isOpen} onClick={() => onSelect(isOpen ? null : t.id)}>
          <span className="task-id">{pad(t.id)}</span>
          <span className="task-title">{t.text}</span>
          <span className="pill-cell"><StatePill t={t} /></span>
          <span className="task-age" title={new Date(t.created * 1000).toLocaleString('en-US')}>{age(t.created, now)}</span>
          <ChevronRight className="icon chev" aria-hidden="true" />
          <span className="task-sub">{t.router ? <span>For <b>{queueName(t.queue)}</b>: the router chose <span className="mono">{t.router.action === 'route' ? t.router.system : 'a person'}</span> for cost of error “{t.router.tier}”</span> : t.queue === 'person' ? <span>Sent to <b>a person</b> by you</span> : <span>Assigned to <b>{queueName(t.queue)}</b> by you</span>}</span>
        </button>
        {isOpen && (
          <div className="detail">
            <div className="detail-grid">
              <section>
                <h3>Asked</h3>
                <p className="body">{t.text}</p>
                <h3>Who got it</h3>
                <p className="body"><b style={{ fontWeight: 600 }}>{queueName(t.queue)}</b>{t.router ? `, by the router: ${routeText(t)}` : t.queue === 'person' ? ', by your choice' : ', picked by you'}{t.skill ? `. Skill: ${t.skill}.` : '.'}</p>
                {routerWhy && <p className="muted" style={{ marginTop: 4 }}>{routerWhy.charAt(0).toUpperCase() + routerWhy.slice(1)}.</p>}
                <h3>Delivered</h3>
                {d?.result != null ? <pre className="delivered">{d.result || '(the agent printed nothing)'}</pre>
                  : <p className="muted">{t.state === 'person' ? 'Waiting for a person. The trace says why the router sent it here.' : 'Nothing delivered yet. Run the pending tasks to send it to its agent.'}</p>}
                {t.review_note && <p className="reviewer-note">Reviewer’s note: {t.review_note}</p>}
              </section>
              <section>
                <h3>Trace</h3>
                {!d && !error && <p className="muted">Reading the trace…</p>}
                {d && (
                  <ol className="trace">
                    {d.timeline.map((e, n) => (
                      <li key={e.seq} className={e.source} style={{ ['--i' as any]: Math.min(n, 8) }}>
                        <span className="src">{e.source}</span>
                        <span className="what">{e.status || e.kind}{e.name ? ` · ${e.name}` : ''}</span>
                        <span className="at">{clock(e.ts)}</span>
                        {e.reason && <span className="why">{e.reason}</span>}
                      </li>
                    ))}
                  </ol>
                )}
              </section>
            </div>
            {(reviewable || t.state === 'pending' || t.state === 'person') && (
              <div className="verdict">
                {reviewable ? (
                  <>
                    <input className="field" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why? A note is required when you return it" aria-label="Note for the verdict" />
                    <div className="verdict-row">
                      <button type="button" className="btn btn-primary" disabled={busy} onClick={() => verdict(t.id, 'ok')}><CheckCircle2 className="icon" aria-hidden="true" />Accept</button>
                      <button type="button" className="btn" disabled={busy} onClick={() => verdict(t.id, 'redo')}><RotateCcw className="icon" aria-hidden="true" />Return with note</button>
                      {t.state !== 'verify' && <button type="button" className="btn" disabled={busy} onClick={() => verdict(t.id, 'verify')}><ScanSearch className="icon" aria-hidden="true" />Needs evidence</button>}
                      <span className="spacer" />
                      <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => verdict(t.id, 'superseded')}>Superseded</button>
                    </div>
                  </>
                ) : (
                  <div className="verdict-row"><span style={{ color: 'var(--ink-2)' }}>Still in the queue.</span><span className="spacer" /><button type="button" className="btn btn-quiet" disabled={busy} onClick={() => act(() => api.discardTask(t.id), t.id)}><X className="icon" aria-hidden="true" />Discard</button></div>
                )}
                {error && <p className="verdict-err" role="alert">{error}</p>}
              </div>
            )}
            {error && !(reviewable || t.state === 'pending' || t.state === 'person') && <p className="verdict-err" role="alert">{error}</p>}
          </div>
        )}
      </div>
    )
  }

  const laneCard = (l: Lane) => (
    <button key={l.id} type="button" className={`lane ${l.due && l.items.length ? 'due' : ''}`} aria-pressed={filter === l.id} onClick={() => onFilter(filter === l.id ? null : l.id)}>
      <img src={`/art/${l.art}.svg`} alt="" aria-hidden="true" className="lane-art" />
      <span className="lane-head"><span className="lane-name">{l.title}</span><span className="lane-count" aria-label={`${l.items.length} open`}>{l.items.length}</span></span>
      {l.kind === 'agent' && (
        <dl className="kv">
          <div><dt>Model</dt><dd>{l.model ? <b className="mono">{l.model}</b> : <span className="mute">{l.blurb}</span>}</dd></div>
          {l.model && <div><dt>Measured</dt><dd>{l.precision != null ? <><b>{(l.precision * 100).toFixed(1)}%</b> precise, at least <b>{(l.lower! * 100).toFixed(1)}%</b> sure</> : <span className="mute">not measured</span>}</dd></div>}
          <div><dt>Router sends</dt><dd>{l.serves.length ? <>cost of error <b>{l.serves.join(', ')}</b></> : <span className="mute">nothing: only tasks you give it by name</span>}</dd></div>
        </dl>
      )}
      {l.kind !== 'agent' && (
        <p className="lane-blurb">{l.blurb}{l.kind === 'person' && l.serves.length > 0 && <> The router sends it cost of error <b>{l.serves.join(', ')}</b>.</>}</p>
      )}
      <span className="lane-foot">
        <span className="dots" aria-hidden="true">
          {l.items.slice(0, 12).map((t) => <i key={t.id} className={NEEDS.has(t.state) ? 'needs' : 'moving'} />)}
          {l.items.length > 12 && <em>+{l.items.length - 12}</em>}
          {l.items.length === 0 && <em>no open tasks</em>}
        </span>
        {l.live && <span className="lane-live"><i className="live" aria-hidden="true" />sending now</span>}
      </span>
    </button>
  )

  let idx = 0
  return (
    <div className="page"><div className="page-inner">
      <PageHead title="Board" art="workspace" lead="Each card is an agent, a person, or the review queue. The dots are its open tasks; below them, the tasks, with what needs you first.">
          <button type="button" className="btn" onClick={onRun} disabled={!!state?.running || runnable === 0}><Play className="icon" style={{ width: 15, height: 15 }} fill="currentColor" aria-hidden="true" />{state?.running ? 'Running…' : runnable ? `Run ${runnable} pending` : 'Nothing to run'}</button>
          <button type="button" className="btn btn-primary" aria-expanded={showNew} onClick={() => setShowNew(!showNew)}><Plus className="icon" aria-hidden="true" />New task</button>
      </PageHead>

      {showNew && <NewTask router={router} agents={agents} skills={state?.skills ?? []} tiers={state?.tiers ?? ['low', 'medium', 'high', 'critical']} focus={newTaskSignal} onClose={() => setShowNew(false)} onCreated={(id) => { onChanged(); onSelect(id); if (filter) onFilter(null) }} />}
      {showSteps && <FirstSteps tasks={tasks} agents={agents} runnable={runnable} running={!!state?.running} onAdd={() => setShowNew(true)} onRun={onRun} onDismiss={tasks.length ? hideSteps : undefined} />}

      {needs.length > 0 && !filter && (
        <div className="card nextup">
          <div className="nextup-text"><b>{pad(needs[0].id)} · {needs[0].text}</b><span className="mute">Next for you · {stateLabel(needs[0])}{needs.length > 1 ? ` · ${needs.length - 1} more waiting below` : ''}</span></div>
          <button type="button" className="btn btn-primary" onClick={() => onSelect(needs[0].id)}>Open task {pad(needs[0].id)}<ChevronRight className="icon" aria-hidden="true" /></button>
        </div>
      )}

      <div className="lane-groups">
        <section aria-labelledby="g-agents">
          <div className="lane-group-head"><h2 id="g-agents">Agents</h2><span>who works the tasks, and which model each one runs</span></div>
          <div className="lanes" role="group" aria-label="Agent queues">{agentLanes.map((l) => laneCard(l))}</div>
        </section>
        <section aria-labelledby="g-wait">
          <div className="lane-group-head"><h2 id="g-wait">Waiting for you</h2><span>what only you can move forward</span></div>
          <div className="lanes" role="group" aria-label="Queues that wait for you">{waitLanes.map((l) => laneCard(l))}</div>
        </section>
      </div>
      <div className="legend-line" aria-hidden="true"><span><i style={{ background: 'var(--warm)' }} />needs you</span><span><i style={{ border: '1.5px solid var(--ink-2)' }} />in motion</span><span>Click a card to show only its tasks.</span></div>
      {filter && <div className="filter-bar"><span>Showing only: <b>{filter === 'needs' ? 'what needs you' : filter === 'review' ? 'to review' : filter === 'person' ? 'a person' : filter}</b></span><button type="button" className="btn btn-quiet btn-sm" onClick={() => onFilter(null)}><X className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />Show everything</button></div>}

      {needs.length > 0 && <div className="group-head due"><span>Needs you</span><span className="n">{needs.length}</span></div>}
      <div className="task-list">{needs.map((t) => row(t, idx++))}</div>
      {moving.length > 0 && <div className="group-head"><span>In motion</span><span className="n">{moving.length}</span></div>}
      <div className="task-list">{moving.map((t) => row(t, idx++))}</div>
      {closed.length > 0 && (
        <div className="group-head"><span>Closed</span><span className="n">{closed.length}</span>
          <button type="button" className="toggle" onClick={() => setShowClosed(!showClosed)} aria-expanded={showClosed}>{showClosed ? 'Hide' : 'Show'}<ChevronDown className="icon" style={{ width: 15, height: 15, transform: showClosed ? 'rotate(180deg)' : 'none' }} aria-hidden="true" /></button>
        </div>
      )}
      {showClosed && <div className="task-list">{closed.map((t) => row(t, idx++))}</div>}

      {tasks.length > 0 && rows.length === 0 && (
        <div className="empty-card" style={{ marginTop: 24 }}>
          <img src={`/art/${filter === 'person' ? 'person' : filter === 'review' || filter === 'needs' ? 'review' : 'board'}.svg`} alt="" aria-hidden="true" />
          <p>{filter === 'needs' || filter === 'review' ? 'Nothing is waiting for a verdict.' : filter === 'person' ? 'No task is waiting for a person.' : 'Nothing in this queue.'} Pick another queue above, or add a task.</p>
        </div>
      )}
      {tasks.length > 0 && !filter && needs.length === 0 && (
        <div className="empty-card" style={{ marginTop: 24 }}>
          <img src="/art/review.svg" alt="" aria-hidden="true" />
          <p>Nothing is waiting for you. What is in motion will land here when it is delivered.</p>
        </div>
      )}
    </div></div>
  )
}
