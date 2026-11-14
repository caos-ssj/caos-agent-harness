import React from 'react'
import { Gauge } from '../icons'
import { Effort, EffortSupport } from '../api'

/* How hard an agent is asked to think. The choice exists only where the agent's tool documents one (the server checks the command);
   anywhere else the control is shown switched off with the reason, so it never looks like a setting that does something. */

const LEVELS: Array<{ value: Effort | ''; label: string }> = [
  { value: '', label: 'Por defecto' },
  { value: 'low', label: 'low' },
  { value: 'medium', label: 'medium' },
  { value: 'high', label: 'high' },
]

interface EffortPickerProps {
  value: Effort | ''
  onChange: (e: Effort | '') => void
  support?: EffortSupport
  /** What this effort applies to, for the screen reader: "claude", "OpenAI Codex"… */
  label: string
  busy?: boolean
  /** Hide the reason line (the caller prints it somewhere else). */
  quiet?: boolean
}

export const EffortPicker: React.FC<EffortPickerProps> = ({ value, onChange, support, label, busy, quiet }) => {
  const off = !support?.supported
  const why = support?.reason ?? 'Sin datos de este agente'
  return (
    <div className="effort-row">
      <span className="effort-label"><Gauge className="icon icon-sm" /><span>Esfuerzo</span></span>
      <div className="seg" role="group" aria-label={`Esfuerzo de ${label}`}>
        {LEVELS.map((l) => (
          <button key={l.value || 'default'} type="button" aria-pressed={!off && value === l.value} disabled={off || busy} title={off ? why : undefined} onClick={() => onChange(l.value)}>
            {l.label}
          </button>
        ))}
      </div>
      {!quiet && <p className="effort-why">{off ? <><span>No disponible:</span> <span>{why}</span></> : <span>{why}</span>}</p>}
    </div>
  )
}
