import React, { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, ArrowRightLeft, CheckCircle2, CircleDot, RotateCcw, Send } from 'lucide-react'
import { ActivityEvent, ActivityResponse, api, Task } from '../api'
import { ago, NEEDS, pad, stateLabel } from '../lib'

const KIND: Record<ActivityEvent['kind'], { label: string; Icon: React.ElementType; cls: string }> = {
  intent: { label: 'nueva', Icon: CircleDot, cls: 'steel' },
  delegated: { label: 'delegada', Icon: Send, cls: 'steel' },
  done: { label: 'hecha', Icon: CheckCircle2, cls: 'pass' },
  blocked: { label: 'bloqueada', Icon: AlertTriangle, cls: 'act' },
  returned: { label: 'devuelta', Icon: RotateCcw, cls: 'fail' },
}

interface Props {
  tasks: Task[]
  root: string
  onSelect: (id: number) => void
}

/* What the board looks like when nothing is selected: what is waiting for you, and what happened since you last looked.
   The feed is computed by the server from the board's own rows; "last visit" is a line this browser remembers per project. */
export const BoardOverview: React.FC<Props> = ({ tasks, root, onSelect }) => {
  const key = `caos_board_seen:${root}`
  const [feed, setFeed] = useState<ActivityResponse | null>(null)
  const [only, setOnly] = useState(false)
  const lastSeen = useRef<number>(0)
  if (lastSeen.current === 0) {
    try { lastSeen.current = Number(localStorage.getItem(key)) || 0 } catch { /* ignore */ }
  }
  const signature = tasks.map((t) => `${t.id}:${t.state}`).join(',')

  useEffect(() => {
    let alive = true
    api.getActivity().then((r) => { if (alive) setFeed(r) }).catch(() => undefined)
    return () => { alive = false }
  }, [signature])
  // Leaving the board is "looking": the next visit draws its divider from here.
  useEffect(() => () => { try { localStorage.setItem(key, String(Date.now() / 1000)) } catch { /* ignore */ } }, [key])

  const needs = useMemo(() => tasks.filter((t) => NEEDS.has(t.state)).sort((a, b) => b.id - a.id), [tasks])
  const sum = feed?.summary
  const events = (feed?.events ?? []).filter((e) => !only || e.kind === 'blocked' || e.kind === 'returned')
  const known = new Set(tasks.map((t) => t.id))
  const dividerAt = lastSeen.current > 0 ? events.findIndex((e) => e.ts <= lastSeen.current) : -1
  const fresh = lastSeen.current > 0 ? events.filter((e) => e.ts > lastSeen.current).length : 0

  const tiles: Array<[string, number | undefined, string]> = [
    ['Esperando por ti', sum?.needs_you, 'act'],
    ['En ejecución', sum?.running, 'steel'],
    ['Pendientes', sum?.pending, 'steel'],
    ['Con una persona', sum?.with_person, 'act'],
  ]

  return (
    <section className="board-overview card" aria-label="Resumen del Board">
      <div className="ov-tiles">
        {tiles.map(([label, n, cls]) => (
          <div key={label} className={`ov-tile ${cls} ${n ? 'has' : ''}`}><b className="mono">{n ?? '—'}</b><span>{label}</span></div>
        ))}
      </div>

      <div className="ov-block">
        <h3>Necesita de ti {needs.length > 0 && <span className="chip amber-chip">{needs.length}</span>}</h3>
        {needs.length === 0 ? (
          <p className="muted ov-empty">Nada espera tu veredicto. Cuando un agente entregue algo, aparece aquí y en la lista.</p>
        ) : (
          <ul className="ov-needs">
            {needs.slice(0, 5).map((t) => (
              <li key={t.id}>
                <button type="button" onClick={() => onSelect(t.id)}>
                  <span className="mono muted">#{pad(t.id)}</span>
                  <span className="pill-mini amber">{stateLabel(t)}</span>
                  <span className="ov-need-text">{t.text}</span>
                  <ArrowRightLeft className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <p className="ov-checklist"><b>Antes de aceptar:</b> lee la entrega, mira el Diff, y escribe el motivo. Devolver exige decir qué corregir.</p>
      </div>

      <div className="ov-block ov-feed">
        <div className="ov-feed-head">
          <h3>Actividad {fresh > 0 && <span className="chip amber-chip">{fresh} nueva(s)</span>}</h3>
          <div className="seg" role="group" aria-label="Filtro de actividad">
            <button type="button" aria-pressed={!only} onClick={() => setOnly(false)}>Todo</button>
            <button type="button" aria-pressed={only} onClick={() => setOnly(true)}>Bloqueados · necesita de ti</button>
          </div>
        </div>
        {events.length === 0 ? (
          <p className="muted ov-empty">{feed ? 'Todavía no ha pasado nada en este proyecto.' : 'Cargando actividad…'}</p>
        ) : (
          <ol className="ov-events">
            {events.slice(0, 40).map((e, i) => {
              const K = KIND[e.kind]
              return (
                <React.Fragment key={`${e.task_id}-${e.kind}-${e.ts}`}>
                  {i === dividerAt && <li className="ov-divider" role="separator"><span>última visita · {ago(lastSeen.current)}</span></li>}
                  <li className={`ov-event ${e.ts > lastSeen.current && lastSeen.current > 0 ? 'is-new' : ''}`}>
                    <K.Icon className={`icon ${K.cls}`} style={{ width: 14, height: 14 }} aria-hidden="true" />
                    <button type="button" className="ov-event-main" disabled={!known.has(e.task_id)} onClick={() => onSelect(e.task_id)} title={known.has(e.task_id) ? 'Abrir la tarea' : 'La tarea ya no está en el Board'}>
                      <span><b>{K.label}</b> <span className="mono muted">#{pad(e.task_id)}</span> {e.text}</span>
                      {e.note && <small>{e.note}</small>}
                    </button>
                    <span className="mono muted ov-ago">{ago(e.ts)}</span>
                  </li>
                </React.Fragment>
              )
            })}
          </ol>
        )}
      </div>
    </section>
  )
}
