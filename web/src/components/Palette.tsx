import React, { useEffect, useMemo, useState } from 'react'
import { Task } from '../api'
import { pad, stateLabel } from '../lib'
import { useDialog, usePresence } from '../hooks'

export interface PaletteItem { id: string; group: string; label: string; hint?: string; run: () => void }
interface PaletteProps { open: boolean; onClose: () => void; items: PaletteItem[]; tasks: Task[]; onTask: (id: number) => void }

/* ⌘K: go anywhere, run anything, jump to a task by its number or its words. */
export const Palette: React.FC<PaletteProps> = ({ open, onClose, items, tasks, onTask }) => {
  const [q, setQ] = useState('')
  const [i, setI] = useState(0)
  const pres = usePresence(open, 140)
  const box = useDialog<HTMLDivElement>(open, onClose, { modal: true, initial: 'input' })   // focus in, Tab kept inside, Escape closes, focus returns to the opener
  useEffect(() => { if (open) { setQ(''); setI(0) } }, [open])

  const all = useMemo<PaletteItem[]>(() => [
    ...items,
    ...tasks.slice(0, 80).map((t) => ({ id: `task-${t.id}`, group: 'Tasks', label: `${pad(t.id)}  ${t.text}`, hint: stateLabel(t), run: () => onTask(t.id) })),
  ], [items, tasks, onTask])

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    return s ? all.filter((x) => x.label.toLowerCase().includes(s) || (x.hint ?? '').toLowerCase().includes(s)) : all.filter((x) => x.group !== 'Tasks').concat(all.filter((x) => x.group === 'Tasks').slice(0, 5))
  }, [q, all])
  useEffect(() => { setI(0) }, [q])
  useEffect(() => { document.getElementById(`pal-${i}`)?.scrollIntoView({ block: 'nearest' }) }, [i])
  if (!pres.mounted) return null

  const go = (x?: PaletteItem) => { if (!x) return; onClose(); x.run() }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose() }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setI((i + 1) % Math.max(1, shown.length)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setI((i - 1 + shown.length) % Math.max(1, shown.length)) }
    else if (e.key === 'Enter') { e.preventDefault(); go(shown[i]) }
    else if (e.key === 'Tab') e.preventDefault()
  }
  let last = ''
  return (
    <div className="scrim" data-leaving={pres.leaving ? '' : undefined} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="palette" ref={box} role="dialog" aria-modal="true" aria-label="Command palette">
        <input
          value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
          role="combobox" aria-expanded="true" aria-controls="pal-list" aria-activedescendant={shown[i] ? `pal-${i}` : undefined} aria-label="Search commands and tasks"
          placeholder="Go to a view, run something, or find a task"
        />
        <div className="palette-list" id="pal-list" role="listbox">
          {shown.length === 0 && <p className="palette-none">Nothing matches “{q}”. Try a task number, or a word from its text.</p>}
          {shown.map((x, n) => {
            const head = x.group !== last ? <div className="palette-group" role="presentation">{x.group}</div> : null
            last = x.group
            return (
              <React.Fragment key={x.id}>
                {head}
                <button type="button" id={`pal-${n}`} role="option" tabIndex={-1} aria-selected={n === i} className="palette-item" onMouseMove={() => setI(n)} onClick={() => go(x)}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{x.label}</span>
                  {x.hint && <small>{x.hint}</small>}
                </button>
              </React.Fragment>
            )
          })}
        </div>
        <div className="palette-foot"><span>↑ ↓ move</span><span>↵ open</span><span>esc close</span></div>
      </div>
    </div>
  )
}
