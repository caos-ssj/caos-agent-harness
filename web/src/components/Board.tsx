import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  CheckCircle2,
  Columns3,
  Download,
  FileCode2,
  Gauge,
  GripVertical,
  List,
  Play,
  Plus,
  RotateCcw,
  ScanSearch,
  Search,
  X,
} from '../icons'
import { Agent, api, Effort, GlobalBoardResponse, RouterResponse, StateResponse, Task, TaskDetail } from '../api'
import { age, byNeed, CLOSED, clock, group, isSpecialKey, NEEDS, pad, queueName, stateLabel } from '../lib'
import { cleanQuote, composeReason, NOTE_LINES_MAX, NOTE_MAX, ReviewNote, ReviewNoteList, useSelectionQuote } from './ReviewNotes'
import { Accordion } from './Accordion'
import { ConfirmButton } from './ConfirmButton'
import { DiffViewer } from './DiffViewer'
import { FirstSteps } from './FirstSteps'
import { BoardOverview } from './BoardOverview'
import { useFresh } from '../hooks'
import { FamilyEmblem } from '../emblems'
import { useRunOverview } from '../runData'
import { steps } from './RunView'
import { exportJson, exportMarkdown } from '../exportTrace'

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
  newTaskSignal?: number
  /** `global`: every registered project's open tasks, read only; a click opens that project. */
  scope?: 'project' | 'global'
  onOpenWorkspaceTask?: (path: string, id: number) => void
}

function extractDiffBlocks(text?: string | null): string {
  if (!text) return ''
  const matches = Array.from(text.matchAll(/```diff\n([\s\S]*?)```/g))
  if (matches.length > 0) return matches.map((m) => m[1].trim()).join('\n\n')
  if (/^diff --git\s/m.test(text)) return text
  return ''
}

export const Board: React.FC<BoardProps> = ({
  router: _router,
  state,
  selectedId,
  onSelect,
  onChanged,
  onRun,
  runnable,
  filter,
  onFilter,
  newTaskSignal,
  scope: boardScope = 'project',
  onOpenWorkspaceTask,
}) => {
  const [layout, setLayout] = useState<'list' | 'kanban'>(() => {
    try { return localStorage.getItem('caos_board_layout') === 'kanban' ? 'kanban' : 'list' } catch { return 'list' }
  })
  const [q, setQ] = useState('')
  const [scope, setScope] = useState<'all' | 'needs' | 'moving' | 'closed'>('all')
  const [globalBoard, setGlobalBoard] = useState<GlobalBoardResponse | null>(null)
  const [showNew, setShowNew] = useState(false)
  const [newText, setNewText] = useState('')
  const [newQueue, setNewQueue] = useState('')
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [detailTab, setDetailTab] = useState<'delivery' | 'diff' | 'trace'>('delivery')
  const [wsDiff, setWsDiff] = useState('')
  const [note, setNote] = useState('')
  const [notes, setNotes] = useState<ReviewNote[]>([])       // inline notes on the delivery and on diff lines: they leave together, as one return
  const [focusNote, setFocusNote] = useState<number | null>(null)
  const noteSeq = useRef(0)
  const [newEffort, setNewEffort] = useState<Effort | ''>('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [dragId, setDragId] = useState<number | null>(null)
  const run = useRunOverview().data   // who each agent is, and where each task is in its review round
  const [dropAt, setDropAt] = useState<{ id: number; after: boolean } | null>(null)   // where a dragged task would land: before or after this row
  const [movedId, setMovedId] = useState<number | null>(null)                         // the row that was just dropped: it settles once
  const [starting, setStarting] = useState<Set<number>>(() => new Set())              // "Run now" pressed, the board has not answered yet
  const [flash, setFlash] = useState<{ kind: 'ok' | 'redo' | 'verify' | 'superseded'; id: number; n: number } | null>(null)
  const noteRef = useRef<HTMLInputElement>(null)
  const deliveredRef = useRef<HTMLPreElement>(null)

  const tasks = state?.tasks ?? []
  const agents: Agent[] = (state?.agents ?? []).filter((a) => !a.test || a.pending > 0 || a.working > 0)   // test engines (cat) stay out of the pickers until they have work
  const now = state?.now ?? Date.now() / 1000
  const sel = tasks.find((t) => t.id === selectedId) ?? null
  const selReviewable = !!sel && (sel.state === 'to_review' || sel.state === 'verify')
  const [picked, clearPicked] = useSelectionQuote(deliveredRef, selReviewable && detailTab === 'delivery')
  const runningIds = useMemo(() => new Set(state?.running_tasks ?? []), [state?.running_tasks])
  const busyAgents = useMemo(() => new Set((state?.agents ?? []).filter((a) => a.working > 0).map((a) => a.name)), [state?.agents])

  useEffect(() => { if (newTaskSignal) setShowNew(true) }, [newTaskSignal])
  useEffect(() => {
    if (boardScope !== 'global') return
    let alive = true
    const load = () => api.getGlobalBoard().then((g) => { if (alive) setGlobalBoard(g) }).catch(() => undefined)
    void load()
    const t = window.setInterval(load, 10000)
    return () => { alive = false; window.clearInterval(t) }
  }, [boardScope])
  useEffect(() => { setNote(''); setNotes([]); setFocusNote(null); setErr(null); setDetailTab('delivery') }, [selectedId])
  useEffect(() => {
    if (!flash) return
    const t = window.setTimeout(() => setFlash(null), 3200)
    return () => window.clearTimeout(t)
  }, [flash])
  useEffect(() => {
    if (movedId == null) return
    const t = window.setTimeout(() => setMovedId(null), 700)
    return () => window.clearTimeout(t)
  }, [movedId])
  useEffect(() => {
    if (selectedId == null) { setDetail(null); return }
    api.getTask(selectedId).then(setDetail).catch((e) => setErr(e.message))
  }, [selectedId, sel?.state, sel?.review, sel?.delivered])
  useEffect(() => {
    if (selectedId != null && detailTab === 'diff') {
      api.getWorkspaceDiff(sel?.worktree_key || undefined).then((d) => setWsDiff(d.diff || '')).catch(() => setWsDiff(''))
    }
  }, [selectedId, detailTab, sel?.worktree_key])

  const switchLayout = (next: 'list' | 'kanban') => {
    setLayout(next)
    try { localStorage.setItem('caos_board_layout', next) } catch { /* ignore */ }
  }

  const rows = useMemo(() => {
    const pick = (t: Task) =>
      filter === 'needs' ? NEEDS.has(t.state)
        : filter === 'person' ? t.state === 'person'
          : filter === 'review' ? t.state === 'to_review' || t.state === 'verify'
            : filter ? t.queue === filter : true
    const term = q.trim().toLowerCase()
    const hit = (t: Task) => !term || t.text.toLowerCase().includes(term) || String(t.id) === term.replace(/^#/, '') || t.queue.toLowerCase().includes(term)
    const inScope = (t: Task) => scope === 'all' || group(t) === scope
    // Tasks that wait to be sent are listed in the order they will run (their place in the queue); everything else, newest first.
    const waiting = (t: Task) => t.state === 'pending' || t.state === 'person'
    const order = (a: Task, b: Task) => (waiting(a) && waiting(b) && a.state === b.state ? (a.position ?? a.id) - (b.position ?? b.id) || a.id - b.id : byNeed(a, b))
    return [...tasks].filter(pick).filter(hit).filter(inScope).sort(order)
  }, [tasks, filter, q, scope])

  /** The tasks of one queue that have not been sent, in the order they will run. */
  const laneOf = (queue: string) => tasks.filter((t) => t.status === 'pending' && t.queue === queue).sort((a, b) => (a.position ?? a.id) - (b.position ?? b.id) || a.id - b.id)

  // Orchestration: a task that split into subtasks says how many of them are in; a subtask points at the one that split it.
  const kids = useMemo(() => {
    const m = new Map<number, Task[]>()
    for (const t of tasks) if (t.parent_id != null) m.set(t.parent_id, [...(m.get(t.parent_id) ?? []), t])
    return m
  }, [tasks])
  const groupLabel = (id: number): string | null => {
    const k = kids.get(id)
    if (!k?.length) return null
    const ready = k.filter((c) => c.delivered || c.state === 'ok' || c.state === 'superseded').length
    return `${ready}/${k.length} listas`
  }

  const openRows = useMemo(() => rows.filter((t) => !CLOSED.has(t.state)), [rows])
  const closedRows = useMemo(() => rows.filter((t) => CLOSED.has(t.state)), [rows])
  const freshIds = useFresh(openRows.map((t) => t.id))

  const kanbanCols = useMemo(() => ({
    pending: openRows.filter((t) => t.state === 'pending'),
    moving: openRows.filter((t) => t.state === 'sending' || t.state === 'sent' || t.state === 'redo'),
    review: openRows.filter((t) => t.state === 'to_review' || t.state === 'verify'),
    person: openRows.filter((t) => t.state === 'person'),
  }), [openRows])

  const verdict = async (id: number, v: 'ok' | 'redo' | 'verify' | 'superseded', quickReason?: string) => {
    const sent = quickReason ? 0 : notes.length
    const full = (quickReason || composeReason(note, notes)).trim()
    if ((v === 'redo' || v === 'ok') && !full) {
      setErr(v === 'ok' ? 'Indica un motivo breve para aceptar.' : 'Indica qué corregir al devolver.')
      noteRef.current?.focus()
      return
    }
    if (full.length > NOTE_MAX || full.split('\n').length > NOTE_LINES_MAX) {
      setErr(`Las notas juntas no caben en una devolución (${full.length} de ${NOTE_MAX} caracteres). Acorta o quita alguna.`)
      return
    }
    setBusy(true)
    setErr(null)
    try {
      await api.reviewTask(id, v, full || undefined)
      setNote('')
      setNotes([])
      setFlash({ kind: v, id, n: sent })
      onChanged()
      const next = openRows.find((t) => t.id !== id && NEEDS.has(t.state))
      onSelect(next ? next.id : null)
    } catch (e: any) {
      setErr(e.message || 'No se pudo registrar el veredicto')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isSpecialKey(e)) return
      const i = openRows.findIndex((t) => t.id === selectedId)
      if (e.key === 'j') { const n = openRows[Math.min(openRows.length - 1, i + 1)]; if (n) onSelect(n.id) }
      else if (e.key === 'k') { const n = openRows[Math.max(0, i - 1)]; if (n) onSelect(n.id) }
      else if (e.key === 'n') { e.preventDefault(); setShowNew(true) }
      else if (e.key === 'a' && sel && (sel.state === 'to_review' || sel.state === 'verify')) { void verdict(sel.id, 'ok', 'Revisado con j/k/a') }
      else if (e.key === 'r' && sel && (sel.state === 'to_review' || sel.state === 'verify')) { e.preventDefault(); noteRef.current?.focus() }
      else if (e.key === 'Escape') onSelect(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openRows, selectedId, sel])

  const createTask = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newText.trim()) return
    const targetQ = newQueue || agents[0]?.name || 'person'
    try {
      const res = await api.addTask({ text: newText.trim(), queue: targetQ, effort: newEffortOff ? '' : newEffort })
      setNewText('')
      setNewEffort('')
      setShowNew(false)
      setErr(null)
      onChanged()
      onSelect(res.id)
    } catch (e2: any) {
      setErr(e2.message || 'No se pudo crear la tarea')
    }
  }
  // The effort a new task can ask for depends on the tool behind its queue: where the tool takes none, the selector says why.
  const newAgent = agents.find((a) => a.name === (newQueue || agents[0]?.name))
  const newEffortOff: string | null = newQueue === 'person' || !newAgent ? 'Una persona no recibe nivel de esfuerzo'
    : newAgent.effort_support && !newAgent.effort_support.supported ? newAgent.effort_support.reason : null

  const moveToQueue = async (id: number, targetQueue: string) => {
    setDragId(null)
    setDropAt(null)
    if (tasks.find((t) => t.id === id)?.queue === targetQueue) return
    try {
      await api.moveTask(id, targetQueue)
      onChanged()
    } catch (e: any) {
      setErr(e.message || 'No se pudo mover la tarea')
    }
  }

  const addNote = (quote: string, from: ReviewNote['from']) => {
    const q = cleanQuote(quote)
    if (!q) return
    const dup = notes.find((n) => n.quote === q)
    if (dup) { setFocusNote(null); window.setTimeout(() => setFocusNote(dup.id), 0); return }
    if (notes.length + 1 >= NOTE_LINES_MAX) { setErr(`Una devolución lleva como mucho ${NOTE_LINES_MAX - 1} notas.`); return }
    const id = ++noteSeq.current
    setNotes((p) => [...p, { id, quote: q, note: '', from }])
    setFocusNote(id)
    setErr(null)
  }

  const runNow = async (id: number) => {
    setStarting((p) => new Set(p).add(id))
    setErr(null)
    try {
      await api.runTask(id)
      onChanged()
    } catch (e: any) {
      setErr(e.message || 'No se pudo ejecutar la tarea')
    } finally {
      window.setTimeout(() => setStarting((p) => { const n = new Set(p); n.delete(id); return n }), 600)
    }
  }
  /** Why a pending task cannot be run by itself right now, or null when it can. */
  const cannotRun = (t: Task): string | null =>
    state?.running ? 'Hay una ejecución de todas las pendientes en curso'
      : busyAgents.has(t.queue) ? `${t.queue} está ocupado con otra tarea`
        : null
  const isRunning = (t: Task) => t.state === 'sending' || runningIds.has(t.id) || starting.has(t.id)

  const reorder = async (id: number, before: number | null) => {
    setDragId(null)
    setDropAt(null)
    try {
      const r = await api.reorderTask(id, before)
      if (r.moved) setMovedId(id)
      onChanged()
    } catch (e: any) {
      setErr(e.message || 'No se pudo reordenar la tarea')
    }
  }
  /** A dragged task can land on `t` when both wait in the same queue: reordering stays inside one queue. */
  const dragged = dragId != null ? tasks.find((x) => x.id === dragId) ?? null : null
  const canDropOn = (t: Task) => !!dragged && dragged.id !== t.id && dragged.status === 'pending' && t.status === 'pending' && dragged.queue === t.queue
  const dropHandlers = (t: Task) => ({
    onDragOver: (e: React.DragEvent<HTMLElement>) => {
      if (!canDropOn(t)) return
      e.preventDefault()
      e.stopPropagation()
      const r = e.currentTarget.getBoundingClientRect()
      const after = e.clientY > r.top + r.height / 2
      if (dropAt?.id !== t.id || dropAt.after !== after) setDropAt({ id: t.id, after })
    },
    onDragLeave: (e: React.DragEvent<HTMLElement>) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null) && dropAt?.id === t.id) setDropAt(null) },
    onDrop: (e: React.DragEvent<HTMLElement>) => {
      if (!canDropOn(t) || !dragged) return
      e.preventDefault()
      e.stopPropagation()
      const lane = laneOf(t.queue).filter((x) => x.id !== dragged.id)
      const i = lane.findIndex((x) => x.id === t.id)
      const after = dropAt?.id === t.id ? dropAt.after : false
      void reorder(dragged.id, after ? lane[i + 1]?.id ?? null : t.id)
    },
    onDragEnd: () => { setDragId(null); setDropAt(null) },
  })
  /** The keyboard's way to reorder: one place up or down inside the task's own queue. */
  const nudge = (t: Task, dir: -1 | 1) => {
    const lane = laneOf(t.queue)
    const i = lane.findIndex((x) => x.id === t.id)
    const j = i + dir
    if (i < 0 || j < 0 || j >= lane.length) return
    void reorder(t.id, dir < 0 ? lane[j].id : lane[j + 1]?.id ?? null)
  }
  const dropClass = (t: Task) => (dropAt?.id === t.id ? (dropAt.after ? 'drop-after' : 'drop-before') : '') + (movedId === t.id ? ' just-moved' : '')
  const grip = (t: Task) => (
    <button
      type="button"
      className="grip"
      title="Arrastra para reordenar dentro de su cola (o Alt + ↑/↓)"
      aria-label={`Reordenar #${pad(t.id)} dentro de la cola ${queueName(t.queue)}: Alt + flecha arriba o abajo`}
      onKeyDown={(e) => {
        if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return
        e.preventDefault()
        e.stopPropagation()
        nudge(t, e.key === 'ArrowUp' ? -1 : 1)
      }}
    >
      <GripVertical className="icon icon-sm" weight="bold" />
    </button>
  )

  const familyOf = (t: Task): string => {
    const key = t.agent ?? t.queue ?? ''
    if (run?.families[key]) return run.families[key]
    const s = `${key} ${t.router?.system ?? ''}`.toLowerCase()
    if (s.includes('claude')) return 'claude'
    if (s.includes('gemini') || s.includes('agy') || s.includes('antigravity')) return 'agy'
    if (s.includes('codex') || s.includes('gpt')) return 'codex'
    if (s.includes('opencode')) return 'opencode'
    if (s.includes('ollama') || s.includes('qwen') || s.includes('llama') || s.includes('local')) return 'local'
    return 'tool'
  }

  const renderCompactRow = (t: Task) => {
    const isOpen = t.id === selectedId
    const reviewable = t.state === 'to_review' || t.state === 'verify'
    const movable = t.status === 'pending'
    const running = isRunning(t)
    const blocked = cannotRun(t)
    const fam = familyOf(t)
    const cycle = run?.cycles.find((x) => x.tasks.includes(t.id))
    return (
      <div
        key={t.id}
        data-status={t.status}
        data-state={t.state}
        draggable={movable}
        onDragStart={(e) => { setDragId(t.id); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', `#${pad(t.id)}`) }}
        {...(movable ? dropHandlers(t) : {})}
        className={`board-row ${isOpen ? 'is-open' : ''} ${NEEDS.has(t.state) ? 'is-needs' : ''} ${freshIds.has(t.id) ? 'fresh' : ''} ${running ? 'is-running' : ''} ${dragId === t.id ? 'is-dragging' : ''} ${dropClass(t)}`}
      >
        {movable ? grip(t) : <span className="grip-gap" aria-hidden="true" />}
        <button type="button" className="board-row-main" aria-expanded={isOpen} onClick={() => onSelect(isOpen ? null : t.id)}>
          <span className="board-row-id mono muted">#{pad(t.id)}</span>
          <span className="board-row-title">
            {t.parent_id != null && <span className="group-badge child" title={`Subtarea de #${pad(t.parent_id)}`}>↳ #{pad(t.parent_id)}</span>}
            {groupLabel(t.id) && <span className="group-badge parent" title="Subtareas entregadas de esta orquestación">{groupLabel(t.id)}</span>}
            {t.text}
          </span>
          <span className="board-row-right">
            <span className={`fam fam-${fam} row-who`}>
              <FamilyEmblem family={fam} size={14} />
              <span className="row-who-name mono">{t.router?.system || queueName(t.queue)}</span>
            </span>
            {cycle && (
              <span className="mini-track" title={cycle.reason}>
                {steps(cycle).filter((s) => s.label !== 'Fusión').map((s) => <i key={s.label} className={s.tone} />)}
              </span>
            )}
            <span className={`pill-mini ${NEEDS.has(t.state) ? 'amber' : t.state === 'ok' ? 'sage' : t.state === 'redo' ? 'coral' : 'steel'}`}>
              {running && <span className="run-dot" aria-hidden="true" />}
              {running && t.state !== 'sending' ? 'sending' : stateLabel(t)}
            </span>
            <span className="mono muted row-age">{age(t.created, now)}</span>
          </span>
        </button>
        <div className="board-row-hover">
          <button type="button" className="btn btn-quiet btn-xs" onClick={() => onSelect(isOpen ? null : t.id)}>
            {isOpen ? 'Cerrar' : 'Abrir'}
          </button>
          {t.state === 'pending' && !running && (
            <button type="button" className="btn btn-xs" onClick={() => void runNow(t.id)} disabled={!!blocked} title={blocked ?? `Ejecuta solo #${pad(t.id)}; las demás pendientes no se tocan`}>
              <Play className="icon icon-xs" weight="fill" />Ejecutar ahora
            </button>
          )}
          {reviewable && (
            <button type="button" className="btn btn-xs btn-sage" onClick={() => verdict(t.id, 'ok', 'Aprobado rápido')}>
              Aceptar
            </button>
          )}
        </div>
      </div>
    )
  }

  const renderDetailPane = (t: Task) => {
    const d = detail && detail.id === t.id ? detail : null
    const reviewable = t.state === 'to_review' || t.state === 'verify'
    const deliveryDiff = extractDiffBlocks(d?.result)
    const running = isRunning(t)
    const blocked = cannotRun(t)
    const agent = (state?.agents ?? []).find((a) => a.name === t.queue)
    const effortOff = t.effort && agent && agent.effort_support && !agent.effort_support.supported ? agent.effort_support.reason : null
    return (
      <section className="card split-detail" aria-label={`Detalle tarea #${pad(t.id)}`}>
        <div className="split-detail-head">
          <div>
            <span className="mono muted">#{pad(t.id)} · {queueName(t.queue)}</span>
            {t.parent_id != null && <button type="button" className="group-badge child linkish" onClick={() => onSelect(t.parent_id)} title="Ir a la tarea que la repartió">↳ subtarea de #{pad(t.parent_id)}</button>}
            {groupLabel(t.id) && <span className="group-badge parent">{groupLabel(t.id)}</span>}
            <h3>{t.text}</h3>
            {t.criteria && <p className="criteria-line"><span className="mono">Criterio</span> {t.criteria}</p>}
            {t.worktree_key && <p className="mono muted criteria-line">worktree {t.worktree_key}</p>}
            {t.effort && (
              <p className="criteria-line effort-line" title={effortOff ?? undefined}>
                <Gauge className="icon icon-sm" /><span className="mono">Esfuerzo</span> <span>{t.effort}</span>
                {effortOff && <span className="muted"><span>· no se aplica:</span> {effortOff}</span>}
              </p>
            )}
            {(kids.get(t.id) ?? []).length > 0 && (
              <ul className="kids-list" aria-label="Subtareas">
                {kids.get(t.id)!.map((c) => (
                  <li key={c.id}><button type="button" className="linkish" onClick={() => onSelect(c.id)}><span className="mono">#{pad(c.id)}</span> {queueName(c.queue)} · {stateLabel(c)}</button></li>
                ))}
              </ul>
            )}
          </div>
          <div className="seg" role="tablist" aria-label="Inspección">
            <button type="button" role="tab" aria-selected={detailTab === 'delivery'} onClick={() => setDetailTab('delivery')}>Entrega</button>
            <button type="button" role="tab" aria-selected={detailTab === 'diff'} onClick={() => setDetailTab('diff')}><FileCode2 className="icon icon-xs" />Diff</button>
            <button type="button" role="tab" aria-selected={detailTab === 'trace'} onClick={() => setDetailTab('trace')}>{`Traza (${d?.timeline.length ?? 0})`}</button>
          </div>
          <button type="button" className="btn btn-quiet btn-icon btn-xs" onClick={() => onSelect(null)} aria-label="Cerrar detalle"><X className="icon icon-sm" /></button>
        </div>

        {detailTab === 'delivery' && (
          <div className="split-detail-body delivered-host">
            {running && <p className="run-line" role="status"><span className="run-dot" aria-hidden="true" />{queueName(t.queue)} está trabajando en esta tarea…</p>}
            <pre className="delivered" ref={deliveredRef} tabIndex={reviewable ? 0 : undefined} aria-label={reviewable ? 'Resultado entregado. Selecciona texto para anotarlo.' : undefined}>{d?.result ?? (t.state === 'person' ? 'Esperando decisión humana.' : 'Sin entrega todavía.')}</pre>
            {reviewable && picked && (
              <button
                type="button"
                className="quote-plus"
                style={{ top: picked.top, left: picked.left }}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => { addNote(picked.text, 'text'); window.getSelection()?.removeAllRanges(); clearPicked() }}
                title="Anotar esta selección"
                aria-label="Anotar el texto seleccionado"
              >
                <Plus className="icon icon-sm" weight="bold" />
              </button>
            )}
            {reviewable && d?.result && notes.length === 0 && <p className="hint quote-hint">Selecciona texto del resultado y pulsa + para anotarlo. Las notas se envían juntas al devolver.</p>}
            {t.review_note && <p className="reviewer-note"><span>Nota previa:</span> <span className="prev-note">{t.review_note}</span></p>}
          </div>
        )}

        {detailTab === 'diff' && (
          <div className="split-detail-body">
            <DiffViewer
              diffText={deliveryDiff || wsDiff}
              onAnnotateLine={reviewable ? (ln) => addNote(ln, 'diff') : undefined}
              annotateLabel="Anotar esta línea"
            />
          </div>
        )}

        {detailTab === 'trace' && d && (
          <div className="split-detail-body">
            <div className="verdict-row" style={{ marginBottom: 8 }}>
              <button type="button" className="btn btn-quiet btn-xs" onClick={() => exportMarkdown(d)}><Download className="icon icon-xs" />MD</button>
              <button type="button" className="btn btn-quiet btn-xs" onClick={() => exportJson(d)}>JSON</button>
            </div>
            <ol className="trace">
              {d.timeline.map((e) => (
                <li key={e.seq} className={e.source}>
                  <span className="src">{e.source}</span>
                  <span className="what">{e.status || e.kind}{e.name ? ` · ${e.name}` : ''}</span>
                  <span className="at">{clock(e.ts)}</span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {(reviewable || t.state === 'pending' || t.state === 'person') && (
          <div className="verdict">
            {reviewable ? (
              <>
                <ReviewNoteList
                  notes={notes}
                  focusId={focusNote}
                  onChange={(id, text) => setNotes((p) => p.map((n) => (n.id === id ? { ...n, note: text } : n)))}
                  onRemove={(id) => setNotes((p) => p.filter((n) => n.id !== id))}
                  onDone={() => noteRef.current?.focus()}
                />
                <input ref={noteRef} className="field field-sm" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1200} placeholder={notes.length ? 'Nota general (opcional)…' : 'Motivo o qué corregir…'} aria-label="Motivo del veredicto" />
                <div className="verdict-row">
                  <button type="button" className="btn btn-sage btn-xs" disabled={busy} onClick={() => verdict(t.id, 'ok')}><CheckCircle2 className="icon icon-sm" />Aceptar (a)</button>
                  <button type="button" className="btn btn-xs" disabled={busy} onClick={() => verdict(t.id, 'redo')}><RotateCcw className="icon icon-sm" />{notes.length ? `Devolver con notas (${notes.length})` : 'Devolver'}</button>
                  <button type="button" className="btn btn-xs" disabled={busy} onClick={() => verdict(t.id, 'verify')}><ScanSearch className="icon icon-sm" />Pedir evidencia</button>
                  <span className="spacer" />
                  <button type="button" className="btn btn-quiet btn-xs" disabled={busy} onClick={() => verdict(t.id, 'superseded')}>Superada</button>
                </div>
              </>
            ) : (
              <div className="verdict-row">
                <span className="muted mono">{running ? `Enviándose a ${queueName(t.queue)}` : `Pendiente en cola ${queueName(t.queue)}`}</span>
                <span className="spacer" />
                {t.state === 'pending' && !running && (
                  <button type="button" className="btn btn-amber btn-xs" onClick={() => void runNow(t.id)} disabled={!!blocked} title={blocked ?? 'Ejecuta solo esta tarea; las demás pendientes no se tocan'}>
                    <Play className="icon icon-xs" weight="fill" />Ejecutar ahora
                  </button>
                )}
                <ConfirmButton className="btn btn-quiet btn-xs" question={`¿Descartar #${pad(t.id)}?`} confirmLabel="Descartar" onConfirm={() => api.discardTask(t.id).then(() => { onChanged(); onSelect(null) })}>
                  Descartar
                </ConfirmButton>
              </div>
            )}
          </div>
        )}
      </section>
    )
  }

  const openGlobalTask = (path: string, current: boolean, id: number) => {
    if (current) onSelect(id)
    else onOpenWorkspaceTask?.(path, id)
  }

  const header = (
    <div className="page-bar board-bar">
      <h1>Board</h1>
      <div className="page-bar-right">
        {boardScope === 'global' && <span className="chip steel-chip" title="Lectura local de las bases de tareas de cada proyecto registrado">solo lectura · clic abre el proyecto</span>}
        <div className="seg" role="group" aria-label="Vista Board">
          <button type="button" aria-pressed={layout === 'list'} onClick={() => switchLayout('list')}><List className="icon icon-sm" />Lista</button>
          <button type="button" aria-pressed={layout === 'kanban'} onClick={() => switchLayout('kanban')}><Columns3 className="icon icon-sm" />Kanban</button>
        </div>
        {runnable > 0 && boardScope === 'project' && (
          <button type="button" className="btn btn-amber btn-sm" onClick={onRun} disabled={!!state?.running}>
            <Play className="icon icon-sm" weight="fill" />{`Ejecutar ${runnable}`}
          </button>
        )}
        {boardScope === 'project' && (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setShowNew((v) => !v)}>
            <Plus className="icon icon-sm" />Nueva tarea
          </button>
        )}
      </div>
    </div>
  )

  if (boardScope === 'global') {
    const wsList = globalBoard?.workspaces ?? []
    const totalNeeds = wsList.reduce((n, w) => n + w.counts.needs_you, 0)
    return (
      <div className="board-page">
        {header}
        <div className="ov-tiles board-counters" aria-label="Contadores globales">
          <div className={`ov-tile act ${totalNeeds ? 'has' : ''}`}><b className="mono">{totalNeeds}</b><span>Esperan en total</span></div>
          <div className="ov-tile steel"><b className="mono">{wsList.length}</b><span>Proyectos</span></div>
          <div className="ov-tile steel"><b className="mono">{wsList.reduce((n, w) => n + w.counts.open, 0)}</b><span>Abiertas</span></div>
          <div className="ov-tile"><b className="mono">{wsList.filter((w) => w.error).length}</b><span>Sin tablero</span></div>
        </div>
        <div className={`board-split ${layout}`}>
          <div className="board-left">
            {!globalBoard && <p className="muted mono">Leyendo los proyectos registrados…</p>}
          {wsList.map((w) => (
            <section key={w.path} className="card global-ws">
              <header className="global-ws-head">
                <b>{w.name}</b>
                {w.current && <span className="chip">este proyecto</span>}
                <span className="mono muted">{w.counts.open} abiertas</span>
                {w.counts.needs_you > 0 && <span className="chip amber-chip">{w.counts.needs_you} esperan</span>}
                {w.error && <span className="chip dim">{w.error}</span>}
                {!w.current && <button type="button" className="btn btn-quiet btn-xs" style={{ marginLeft: 'auto' }} onClick={() => onOpenWorkspaceTask?.(w.path, w.tasks[0]?.id ?? 0)}>Abrir proyecto</button>}
              </header>
              {w.tasks.map((t) => (
                <button key={t.id} type="button" data-status={t.state} className={`board-row global-row ${t.needs_you ? 'is-needs' : ''}`} onClick={() => openGlobalTask(w.path, w.current, t.id)}>
                  <span className="mono muted">#{pad(t.id)}</span>
                  <span className={`pill-mini ${t.needs_you ? 'amber' : 'steel'}`}>{stateLabel({ state: t.state as Task['state'], review: null })}</span>
                  <span className="board-row-title">{t.text}</span>
                  <span className="mono muted">{queueName(t.queue)}</span>
                </button>
              ))}
              {w.tasks.length === 0 && !w.error && <p className="muted mono global-empty">Sin tareas abiertas.</p>}
            </section>
          ))}
        </div>
        <div className="board-right">
          <section className="board-overview card" aria-label="Resumen global">
            <div className="ov-block"><h3>Cómo leer esta vista</h3>
              <p className="muted ov-empty">Es una lectura local de cada tablero, sin escribir nada. Un clic en una tarea cambia a ese proyecto y la abre con su detalle, su diff y su veredicto.</p>
            </div>
          </section>
        </div>
        </div>
      </div>
    )
  }

  const tiles: Array<[string, number | undefined, string]> = state ? [
    ['Esperando por ti', state.summary?.needs_you ?? tasks.filter((t) => NEEDS.has(t.state)).length, 'act'],
    ['En ejecución', tasks.filter((t) => isRunning(t)).length, 'steel'],
    ['Pendientes', tasks.filter((t) => t.state === 'pending' || t.state === 'redo').length, 'steel'],
    ['Con una persona', state.summary?.with_person ?? tasks.filter((t) => t.state === 'person').length, 'act'],
  ] : [
    ['Esperando por ti', undefined, 'act'],
    ['En ejecución', undefined, 'steel'],
    ['Pendientes', undefined, 'steel'],
    ['Con una persona', undefined, 'act'],
  ]

  return (
    <div className="board-page">
      {header}
      <div className="ov-tiles board-counters" aria-label="Contadores del Board">
        {tiles.map(([label, n, cls]) => (
          <div key={label} className={`ov-tile ${cls} ${n ? 'has' : ''}`}><b className="mono">{n ?? '—'}</b><span>{label}</span></div>
        ))}
      </div>
      <div className={`board-split ${layout}`}>
        <div className="board-left">

        {showNew && (
          <form className="card compact-card inline-form" onSubmit={createTask}>
            <input className="field field-sm" autoFocus value={newText} onChange={(e) => setNewText(e.target.value)} placeholder="Describe la tarea concreta…" required />
            <select className="select select-sm" value={newQueue} onChange={(e) => setNewQueue(e.target.value)}>
              <option value="">Auto ({agents[0]?.name || 'person'})</option>
              {agents.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
              <option value="person">Persona</option>
            </select>
            <select className="select select-sm" value={newEffortOff ? '' : newEffort} onChange={(e) => setNewEffort(e.target.value as Effort | '')} disabled={!!newEffortOff} aria-label="Esfuerzo de esta tarea" aria-describedby="new-effort-why" title={newEffortOff ?? newAgent?.effort_support?.reason}>
              <option value="">{`Esfuerzo: por defecto${newAgent?.effort ? ` (${newAgent.effort})` : ''}`}</option>
              <option value="low">Esfuerzo: low</option>
              <option value="medium">Esfuerzo: medium</option>
              <option value="high">Esfuerzo: high</option>
            </select>
            <button type="submit" className="btn btn-sage btn-sm">Crear</button>
            <button type="button" className="btn btn-quiet btn-sm" onClick={() => setShowNew(false)}>Cancelar</button>
            <p className="hint new-effort-why" id="new-effort-why">
              {newEffortOff ? <><span>{`Sin selector de esfuerzo para ${newQueue === 'person' || !newAgent ? 'esta cola' : newAgent.name}:`}</span> <span>{newEffortOff}</span></> : <><span>Esfuerzo:</span> <span>{newAgent?.effort_support?.reason}</span></>}
            </p>
          </form>
        )}

        {tasks.length === 0 && (
          <FirstSteps tasks={tasks} agents={agents} runnable={runnable} running={!!state?.running} onAdd={() => setShowNew(true)} onRun={onRun} />
        )}

        {err && <div className="banner err" role="alert"><span>{err}</span><button type="button" className="btn btn-quiet btn-icon btn-xs" onClick={() => setErr(null)} aria-label="Cerrar el aviso"><X className="icon icon-sm" /></button></div>}
        <div className="board-flash" role="status" aria-live="polite">
          {flash && (
            <span className={`flash-line ${flash.kind}`} key={`${flash.kind}-${flash.id}`}>
              {flash.kind === 'ok' && (
                <svg className="flash-check" viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="8.25" /><path d="M6.2 10.4l2.6 2.6 5-5.4" /></svg>
              )}
              <span className="mono">#{pad(flash.id)}</span>
              <span>{flash.kind === 'ok' ? 'aceptada' : flash.kind === 'redo' ? (flash.n > 0 ? `devuelta con ${flash.n} nota(s)` : 'devuelta a su agente') : flash.kind === 'verify' ? 'queda a la espera de evidencia' : 'marcada como superada'}</span>
            </span>
          )}
        </div>

        <div className="toolbar compact-toolbar" role="search">
          <label className="search-inline">
            <Search className="icon icon-sm" aria-hidden="true" />
            <input className="field field-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar #id, texto o cola…" />
          </label>
          <div className="seg" role="group" aria-label="Filtro estado">
            {(['all', 'needs', 'moving', 'closed'] as const).map((k) => (
              <button key={k} type="button" aria-pressed={scope === k} onClick={() => setScope(k)}>
                {k === 'all' ? 'Abiertas' : k === 'needs' ? 'Esperando' : k === 'moving' ? 'En curso' : 'Cerradas'}
              </button>
            ))}
          </div>
          {filter && (
            <button type="button" className="btn btn-quiet btn-xs" onClick={() => onFilter(null)}>
              <X className="icon icon-xs" />Cola: {filter}
            </button>
          )}
        </div>

        <div className="acc-stack">
          {layout === 'list' ? (
            <div className="board-list-card card">
              {openRows.map(renderCompactRow)}
              {openRows.length === 0 && tasks.length > 0 && (
                <div className="muted mono" style={{ padding: '14px 12px' }}>Sin tareas abiertas en este filtro. Pulsa `j/k` o abre Cerradas abajo.</div>
              )}
            </div>
          ) : (
            <div className="kanban-4col">
              {[
                // A task dropped on "Pendiente" leaves the person's queue for the first agent; one that already waits for an agent stays in its queue.
                { key: 'pending', title: 'Pendiente', needs: false, items: kanbanCols.pending, dropQueue: dragged?.queue === 'person' ? agents[0]?.name ?? null : null },
                { key: 'moving', title: 'En curso', needs: false, items: kanbanCols.moving, dropQueue: null },
                { key: 'review', title: 'A revisar', needs: true, items: kanbanCols.review, dropQueue: null },
                { key: 'person', title: 'Persona', needs: true, items: kanbanCols.person, dropQueue: dragged && dragged.queue !== 'person' ? 'person' : null },
              ].map((col) => (
                <section
                  key={col.key}
                  className={`kanban-col card ${col.needs && col.items.length ? 'needs' : ''} ${col.dropQueue ? 'can-drop' : ''}`}
                  aria-label={`${col.title}: ${col.items.length}`}
                  onDragOver={(e) => { if (col.dropQueue && dragId != null) e.preventDefault() }}
                  onDrop={() => { if (col.dropQueue && dragId != null) void moveToQueue(dragId, col.dropQueue) }}
                >
                  <div className="kanban-head">
                    <b>{col.title}</b>
                    <span className="mono muted">{col.items.length}</span>
                  </div>
                  <div className="kanban-cards">
                    {col.items.map((t) => (
                      <div
                        key={t.id}
                        draggable={t.status === 'pending'}
                        onDragStart={(e) => { setDragId(t.id); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', `#${pad(t.id)}`) }}
                        {...(t.status === 'pending' ? dropHandlers(t) : {})}
                        className={`kanban-card ${t.id === selectedId ? 'selected' : ''} ${isRunning(t) ? 'is-running' : ''} ${dragId === t.id ? 'is-dragging' : ''} ${dropClass(t)}`}
                      >
                        <div className="kanban-card-top">
                          {t.status === 'pending' && grip(t)}
                          <span className="mono muted">#{pad(t.id)}</span>
                          {isRunning(t) && <span className="run-dot" aria-hidden="true" />}
                          <span className="mono muted kanban-queue">{queueName(t.queue)}</span>
                        </div>
                        <button type="button" className="kanban-card-open" aria-expanded={t.id === selectedId} onClick={() => onSelect(t.id === selectedId ? null : t.id)}>{t.text}</button>
                        {t.state === 'pending' && !isRunning(t) && (
                          <button type="button" className="btn btn-xs kanban-run" onClick={() => void runNow(t.id)} disabled={!!cannotRun(t)} title={cannotRun(t) ?? `Ejecuta solo #${pad(t.id)}; las demás pendientes no se tocan`}>
                            <Play className="icon icon-xs" weight="fill" />Ejecutar ahora
                          </button>
                        )}
                      </div>
                    ))}
                    {col.items.length === 0 && <p className="kanban-empty muted">{col.key === 'pending' ? 'Nada en cola.' : col.key === 'moving' ? 'Nada en curso.' : col.key === 'review' ? 'Nada que revisar.' : 'Nadie espera.'}</p>}
                  </div>
                </section>
              ))}
            </div>
          )}

          <Accordion id="board-queues" title="Colas y agentes del proyecto" count={agents.length + 1} defaultOpen={false}>
            <div className="tiers-compact">
              {agents.map((a) => (
                <button key={a.name} type="button" className="tier-mini" onClick={() => onFilter(filter === a.name ? null : a.name)}>
                  <b>{a.name}</b>
                  <span className="mono steel">{a.system || a.model || 'CLI'}</span>
                  <span className="mono muted">{a.pending} pend</span>
                </button>
              ))}
              <button type="button" className="tier-mini" onClick={() => onFilter(filter === 'person' ? null : 'person')}>
                <b>Persona</b>
                <span className="mono amber">humano</span>
                <span className="mono muted">{`${tasks.filter((t) => t.state === 'person').length} espera`}</span>
              </button>
            </div>
          </Accordion>

          {closedRows.length > 0 && (
            <Accordion id="board-closed" title="Cerradas" count={closedRows.length} defaultOpen={scope === 'closed'}>
              <div className="board-list-card">{closedRows.slice(0, 40).map(renderCompactRow)}</div>
            </Accordion>
          )}
        </div>
      </div>

      <div className="board-right">
        {sel ? renderDetailPane(sel) : <BoardOverview tasks={tasks} root={state?.root ?? ''} onSelect={(id) => onSelect(id)} />}
      </div>
      </div>
    </div>
  )
}
