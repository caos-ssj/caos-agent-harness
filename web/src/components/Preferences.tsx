import React, { useEffect, useRef } from 'react'
import { Prefs } from '../prefs'
import { View } from '../lib'

interface PreferencesProps { prefs: Prefs; onChange: (p: Partial<Prefs>) => void; onReset: () => void; onClose: () => void }
const STARTS: Array<[View, string]> = [['board', 'Board'], ['console', 'Console'], ['measured', 'Measured']]

/* Three choices that change how the work feels, nothing else: how many tasks fit, how large the text is, and where
   the page opens. Stored in this browser only. */
export const Preferences: React.FC<PreferencesProps> = ({ prefs, onChange, onReset, onClose }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('button[aria-pressed="true"]')?.focus()
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const click = (e: MouseEvent) => { const t = e.target as HTMLElement; if (ref.current && !ref.current.contains(t) && !t.closest('[aria-haspopup="dialog"]')) onClose() }
    window.addEventListener('keydown', key); window.addEventListener('mousedown', click)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('mousedown', click) }
  }, [onClose])
  return (
    <div className="pop" role="dialog" aria-label="Preferences" ref={ref}>
      <h2>Preferences</h2>
      <fieldset>
        <legend>Density</legend>
        <div className="seg">
          <button type="button" aria-pressed={prefs.density === 'comfortable'} onClick={() => onChange({ density: 'comfortable' })}>Comfortable</button>
          <button type="button" aria-pressed={prefs.density === 'compact'} onClick={() => onChange({ density: 'compact' })}>Compact</button>
        </div>
        <p className="hint">Compact fits about a third more tasks on a laptop screen.</p>
      </fieldset>
      <fieldset>
        <legend>Text size</legend>
        <div className="seg">
          <button type="button" aria-pressed={prefs.text === 'standard'} onClick={() => onChange({ text: 'standard' })}>Standard</button>
          <button type="button" aria-pressed={prefs.text === 'large'} onClick={() => onChange({ text: 'large' })}>Large</button>
        </div>
      </fieldset>
      <fieldset>
        <legend>Open on</legend>
        <div className="seg">
          {STARTS.map(([v, label]) => <button key={v} type="button" aria-pressed={prefs.start === v} onClick={() => onChange({ start: v })}>{label}</button>)}
        </div>
      </fieldset>
      <div className="pop-foot"><span>kept in this browser</span><button type="button" className="btn btn-quiet btn-sm" onClick={onReset}>Reset</button></div>
    </div>
  )
}
