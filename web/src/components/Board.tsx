import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  CheckCircle2,
  Columns3,
  Download,
  FileCode2,
  List,
  Play,
  Plus,
  RotateCcw,
  ScanSearch,
  Search,
  X,
} from '../icons'
import { Agent, api, GlobalBoardResponse, RouterResponse, StateResponse, Task, TaskDetail } from '../api'
import { age, byNeed, CLOSED, clock, group, isSpecialKey, NEEDS, pad, queueName, stateLabel } from '../lib'
import { Accordion } from './Accordion'
import { ConfirmButton } from './ConfirmButton'
import { DiffViewer } from './DiffViewer'
import { FirstSteps } from './FirstSteps'
import { BoardOverview } from './BoardOverview'
import { useFresh } from '../hooks'
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
  const [pickedNotes, setPickedNotes] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [dragId, setDragId] = useState<number | null>(null)
  const noteRef = useRef<HTMLInputElement>(null)

  const tasks = state?.tasks ?? []
  const agents: Agent[] = (state?.agents ?? []).filter((a) => !a.test || a.pending > 0 || a.working > 0)   // test engines (cat) stay out of the pickers until they have work
  const now = state?.now ?? Date.now() / 1000
  const sel = tasks.find((t) => t.id === selectedId) ?? null

  useEffect(() => { if (newTaskSignal) setShowNew(true) }, [newTaskSignal])
  useEffect(() => {
    if (boardScope !== 'global') return
    let alive = true
    const load = () => api.getGlobalBoard().then((g) => { if (alive) setGlobalBoard(g) }).catch(() => undefined)
    void load()
    const t = window.setInterval(load, 10000)
    return () => { alive = false; window.clearInterval(t) }
  }, [boardScope])
  useEffect(() => { setNote(''); setPickedNotes([]); setErr(null); setDetailTab('delivery') }, [selectedId])
  useEffect(() => {
    if (selectedId == null) { setDetail(null); return }
    api.getTask(selectedId).then(setDetail).catch((e) => setErr(e.message))
  }, [selectedId, sel?.state, sel?.review, sel?.delivered])
  useEffect(() => {
    if (selectedId != null && detailTab === 'diff') {
      api.getWorkspaceDiff().then((d) => setWsDiff(d.diff || '')).catch(() => setWsDiff(''))
    }
  }, [selectedId, detailTab])

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
    return [...tasks].filter(pick).filter(hit).filter(inScope).sort(byNeed)
  }, [tasks, filter, q, scope])

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
    const full = (quickReason || [note.trim(), ...pickedNotes.map((n) => `“${n}”`)].filter(Boolean).join(' · ')).trim()
    if ((v === 'redo' || v === 'ok') && !full) {
      setErr(v === 'ok' ? 'Indica un motivo breve para aceptar.' : 'Indica qué corregir al devolver.')
      noteRef.current?.focus()
      return
    }
    setBusy(true)
    setErr(null)
    try {
      await api.reviewTask(id, v, full || undefined)
      setNote('')
      setPickedNotes([])
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
    const res = await api.addTask({ text: newText.trim(), queue: targetQ })
    setNewText('')
    setShowNew(false)
    onChanged()
    onSelect(res.id)
  }

  const moveToQueue = async (id: number, targetQueue: string) => {
    setDragId(null)
    try {
      await api.moveTask(id, targetQueue)
      onChanged()
    } catch (e: any) {
      setErr(e.message || 'No se pudo mover la tarea')
    }
  }

  const renderCompactRow = (t: Task) => {
    const isOpen = t.id === selectedId
    const reviewable = t.state === 'to_review' || t.state === 'verify'
    return (
      <div
        key={t.id}
        draggable={t.state === 'pending' || t.state === 'person'}
        onDragStart={() => setDragId(t.id)}
        className={`board-row ${isOpen ? 'is-open' : ''} ${NEEDS.has(t.state) ? 'is-needs' : ''} ${freshIds.has(t.id) ? 'fresh' : ''}`}
      >
        <button type="button" className="board-row-main" onClick={() => onSelect(isOpen ? null : t.id)}>
          <span className="mono muted">#{pad(t.id)}</span>
          <span className="mono muted age-col">{age(t.created, now)}</span>
          <span className={`pill-mini ${NEEDS.has(t.state) ? 'amber' : t.state === 'ok' ? 'sage' : t.state === 'redo' ? 'coral' : 'steel'}`}>
            {stateLabel(t)}
          </span>
          <span className="board-row-title">
            {t.parent_id != null && <span className="group-badge child" title={`Subtarea de #${pad(t.parent_id)}`}>↳ #{pad(t.parent_id)}</span>}
            {groupLabel(t.id) && <span className="group-badge parent" title="Subtareas entregadas de esta orquestación">{groupLabel(t.id)}</span>}
            {t.text}
          </span>
          <span className="mono muted queue-col">{t.router?.system || queueName(t.queue)}</span>
        </button>
        <div className="board-row-hover">
          <button type="button" className="btn btn-quiet btn-xs" onClick={() => onSelect(isOpen ? null : t.id)}>
            {isOpen ? 'Cerrar' : 'Abrir'}
          </button>
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
            <button type="button" role="tab" aria-selected={detailTab === 'diff'} onClick={() => setDetailTab('diff')}><FileCode2 className="icon" style={{ width: 12, height: 12 }} />Diff</button>
            <button type="button" role="tab" aria-selected={detailTab === 'trace'} onClick={() => setDetailTab('trace')}>Traza ({d?.timeline.length ?? 0})</button>
          </div>
          <button type="button" className="btn btn-quiet btn-icon btn-xs" onClick={() => onSelect(null)} aria-label="Cerrar detalle"><X className="icon" style={{ width: 14, height: 14 }} /></button>
        </div>

        {detailTab === 'delivery' && (
          <div className="split-detail-body">
            <pre className="delivered">{d?.result ?? (t.state === 'person' ? 'Esperando decisión humana.' : 'Sin entrega todavía.')}</pre>
            {t.review_note && <p className="reviewer-note">Nota previa: {t.review_note}</p>}
          </div>
        )}

        {detailTab === 'diff' && (
          <div className="split-detail-body">
            <DiffViewer
              diffText={deliveryDiff || wsDiff}
              onAnnotateLine={reviewable ? (ln) => setPickedNotes((p) => (p.includes(ln) ? p : [...p, ln])) : undefined}
              annotateLabel="Citar en Devolver"
            />
          </div>
        )}

        {detailTab === 'trace' && d && (
          <div className="split-detail-body">
            <div className="verdict-row" style={{ marginBottom: 8 }}>
              <button type="button" className="btn btn-quiet btn-xs" onClick={() => exportMarkdown(d)}><Download className="icon" style={{ width: 12, height: 12 }} />MD</button>
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
            {pickedNotes.length > 0 && (
              <div className="picked-chips">
                {pickedNotes.map((pn, idx) => (
                  <span key={idx} className="view-chip">
                    {pn.slice(0, 48)}
                    <button type="button" onClick={() => setPickedNotes((p) => p.filter((_, j) => j !== idx))}><X className="icon" style={{ width: 11, height: 11 }} /></button>
                  </span>
                ))}
              </div>
            )}
            {reviewable ? (
              <>
                <input ref={noteRef} className="field field-sm" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Motivo o qué corregir…" aria-label="Motivo del veredicto" />
                <div className="verdict-row">
                  <button type="button" className="btn btn-primary btn-xs" disabled={busy} onClick={() => verdict(t.id, 'ok')}><CheckCircle2 className="icon" style={{ width: 13, height: 13 }} />Aceptar (a)</button>
                  <button type="button" className="btn btn-xs" disabled={busy} onClick={() => verdict(t.id, 'redo')}><RotateCcw className="icon" style={{ width: 13, height: 13 }} />Devolver</button>
                  <button type="button" className="btn btn-xs" disabled={busy} onClick={() => verdict(t.id, 'verify')}><ScanSearch className="icon" style={{ width: 13, height: 13 }} />Pedir evidencia</button>
                  <span className="spacer" />
                  <button type="button" className="btn btn-quiet btn-xs" disabled={busy} onClick={() => verdict(t.id, 'superseded')}>Superada</button>
                </div>
              </>
            ) : (
              <div className="verdict-row">
                <span className="muted mono">Pendiente en cola {t.queue}</span>
                <span className="spacer" />
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
          <button type="button" aria-pressed={layout === 'list'} onClick={() => switchLayout('list')}><List className="icon" style={{ width: 13, height: 13 }} />Lista</button>
          <button type="button" aria-pressed={layout === 'kanban'} onClick={() => switchLayout('kanban')}><Columns3 className="icon" style={{ width: 13, height: 13 }} />Kanban</button>
        </div>
        {runnable > 0 && boardScope === 'project' && (
          <button type="button" className="btn btn-amber btn-sm" onClick={onRun} disabled={!!state?.running}>
            <Play className="icon" style={{ width: 13, height: 13 }} fill="currentColor" />Ejecutar {runnable}
          </button>
        )}
        {boardScope === 'project' && (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setShowNew((v) => !v)}>
            <Plus className="icon" style={{ width: 14, height: 14 }} />Nueva tarea
          </button>
        )}
      </div>
    </div>
  )

  if (boardScope === 'global') {
    const wsList = globalBoard?.workspaces ?? []
    const totalNeeds = wsList.reduce((n, w) => n + w.counts.needs_you, 0)
    return (
      <div className={`board-split ${layout}`}>
        <div className="board-left">
          {header}
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
                <button key={t.id} type="button" className={`board-row global-row ${t.needs_you ? 'is-needs' : ''}`} onClick={() => openGlobalTask(w.path, w.current, t.id)}>
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
            <div className="ov-tiles">
              <div className={`ov-tile act ${totalNeeds ? 'has' : ''}`}><b className="mono">{totalNeeds}</b><span>Esperan en total</span></div>
              <div className="ov-tile steel"><b className="mono">{wsList.length}</b><span>Proyectos</span></div>
              <div className="ov-tile steel"><b className="mono">{wsList.reduce((n, w) => n + w.counts.open, 0)}</b><span>Abiertas</span></div>
              <div className="ov-tile"><b className="mono">{wsList.filter((w) => w.error).length}</b><span>Sin tablero</span></div>
            </div>
            <div className="ov-block"><h3>Cómo leer esta vista</h3>
              <p className="muted ov-empty">Es una lectura local de cada tablero, sin escribir nada. Un clic en una tarea cambia a ese proyecto y la abre con su detalle, su diff y su veredicto.</p>
            </div>
          </section>
        </div>
      </div>
    )
  }

  return (
    <div className={`board-split ${layout}`}>
      <div className="board-left">
        {header}

        {showNew && (
          <form className="card compact-card inline-form" onSubmit={createTask}>
            <input className="field field-sm" autoFocus value={newText} onChange={(e) => setNewText(e.target.value)} placeholder="Describe la tarea concreta…" required />
            <select className="select select-sm" value={newQueue} onChange={(e) => setNewQueue(e.target.value)}>
              <option value="">Auto ({agents[0]?.name || 'person'})</option>
              {agents.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
              <option value="person">Persona</option>
            </select>
            <button type="submit" className="btn btn-primary btn-sm">Crear</button>
            <button type="button" className="btn btn-quiet btn-sm" onClick={() => setShowNew(false)}>Cancelar</button>
          </form>
        )}

        {tasks.length === 0 && (
          <FirstSteps tasks={tasks} agents={agents} runnable={runnable} running={!!state?.running} onAdd={() => setShowNew(true)} onRun={onRun} />
        )}

        {err && <div className="banner err" role="alert"><span>{err}</span></div>}

        <div className="toolbar compact-toolbar" role="search">
          <label className="search-inline">
            <Search className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />
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
              <X className="icon" style={{ width: 12, height: 12 }} />Cola: {filter}
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
                { key: 'pending', title: 'Pendiente', accent: '#BBB3A8', items: kanbanCols.pending, dropQueue: agents[0]?.name || 'person' },
                { key: 'moving', title: 'En curso', accent: '#7FA6D6', items: kanbanCols.moving, dropQueue: null },
                { key: 'review', title: 'A revisar', accent: '#EB9D44', items: kanbanCols.review, dropQueue: null },
                { key: 'person', title: 'Persona', accent: 'rgba(235,211,187,.55)', items: kanbanCols.person, dropQueue: 'person' },
              ].map((col) => (
                <section
                  key={col.key}
                  className="kanban-col card"
                  style={{ borderTop: `4px solid ${col.accent}` }}
                  onDragOver={(e) => { if (col.dropQueue && dragId != null) e.preventDefault() }}
                  onDrop={() => { if (col.dropQueue && dragId != null) void moveToQueue(dragId, col.dropQueue) }}
                >
                  <div className="kanban-head">
                    <b>{col.title}</b>
                    <span className="mono muted">{col.items.length}</span>
                  </div>
                  <div className="kanban-cards">
                    {col.items.map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        draggable={t.state === 'pending' || t.state === 'person'}
                        onDragStart={() => setDragId(t.id)}
                        className={`kanban-card ${t.id === selectedId ? 'selected' : ''}`}
                        onClick={() => onSelect(t.id === selectedId ? null : t.id)}
                      >
                        <div className="kanban-card-top">
                          <span className="mono muted">#{pad(t.id)}</span>
                          <span className="mono muted">{queueName(t.queue)}</span>
                        </div>
                        <p>{t.text}</p>
                      </button>
                    ))}
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
                <span className="mono muted">{tasks.filter((t) => t.state === 'person').length} espera</span>
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
  )
}
