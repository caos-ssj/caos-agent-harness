import React from 'react'
import { Play, Plus } from '../icons'
import { Agent, Task } from '../api'

interface FirstStepsProps {
  tasks: Task[]
  agents: Agent[]
  runnable: number
  running: boolean
  onAdd: () => void
  onRun: () => void
  onDismiss?: () => void
}

/* Clean 1-line empty state for the Board (no giant cover SVG or mixed English/Spanish blocks). */
export const FirstSteps: React.FC<FirstStepsProps> = ({ tasks, runnable, running, onAdd, onRun, onDismiss }) => {
  const hasTask = tasks.length > 0
  return (
    <section className="card board-empty-strip" aria-labelledby="steps-title">
      <div className="board-empty-copy">
        <b id="steps-title">{hasTask ? 'Tablero en marcha' : 'Tablero sin tareas'}</b>
        <span className="muted">
          {hasTask
            ? 'Revisa las entregas pendientes o ejecuta las tareas en cola.'
            : 'Crea una tarea para asignarla a un agente del proyecto o al router.'}
        </span>
      </div>
      <div className="board-empty-actions">
        {!hasTask && (
          <button type="button" className="btn btn-sm" onClick={onAdd}>
            <Plus className="icon icon-sm" aria-hidden="true" />Nueva tarea
          </button>
        )}
        {hasTask && runnable > 0 && (
          <button type="button" className="btn btn-amber btn-sm" onClick={onRun} disabled={running}>
            <Play className="icon icon-sm" aria-hidden="true" />{running ? 'Ejecutando…' : `Ejecutar ${runnable}`}
          </button>
        )}
        {onDismiss && <button type="button" className="btn btn-quiet btn-xs" onClick={onDismiss}>Ocultar</button>}
      </div>
    </section>
  )
}
