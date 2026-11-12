import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Wrench } from 'lucide-react'
import { SkillInfo } from '../api'
import { useDialog, usePresence } from '../hooks'
import { CAT_ACCENT, groupSkills } from '../skillCats'

interface SkillPopoverProps {
  skills: SkillInfo[]
  value: string
  onPick: (name: string) => void
  open: boolean
  onOpenChange: (o: boolean) => void
  /** Open already narrowed to one category (the chips above the composer do this). */
  category?: string | null
}

/* The skill an agent reads first, grouped by category with a colour stripe, a search box, and the local/team marks. */
export const SkillPopover: React.FC<SkillPopoverProps> = ({ skills, value, onPick, open, onOpenChange, category }) => {
  const box = useRef<HTMLDivElement>(null)
  const pres = usePresence(open, 150)
  const close = () => onOpenChange(false)
  const popRef = useDialog<HTMLDivElement>(open, close, { initial: 'input' })
  const [q, setQ] = useState('')
  useEffect(() => { if (open) setQ(category ? category : '') }, [open, category])
  useEffect(() => {
    if (!open) return
    const click = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) close() }
    window.addEventListener('mousedown', click)
    return () => window.removeEventListener('mousedown', click)
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const groups = useMemo(() => groupSkills(skills, q), [skills, q])
  const pick = (n: string) => { onPick(n); close() }

  return (
    <div className="skillpop" ref={box}>
      <button type="button" className="select skill-btn" aria-expanded={open} aria-haspopup="dialog" onClick={() => onOpenChange(!open)} title="Skill activo">
        <Wrench className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />
        <span className="engine-label">{value === 'auto' ? 'Sin skill' : value}</span>
        <ChevronDown className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />
      </button>
      {pres.mounted && (
        <div className="pop skill-pop" ref={popRef} data-leaving={pres.leaving ? '' : undefined} role="dialog" aria-label="Elegir skill">
          <input className="field field-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar skill o categoría…" aria-label="Buscar skill" />
          <div className="skill-groups">
            <button type="button" className={`skill-row ${value === 'auto' ? 'on' : ''}`} onClick={() => pick('auto')}>
              <span className="engine-check">{value === 'auto' && <Check className="icon" aria-hidden="true" />}</span>
              <span className="engine-text"><b>Sin skill</b><small>el agente decide con su propio criterio</small></span>
            </button>
            {groups.map(({ cat, items }) => (
              <section key={cat} className="skill-group" style={{ ['--cat' as string]: CAT_ACCENT[cat] || 'var(--ink-3)' }}>
                <h3>{cat} <span className="chip">{items.length}</span></h3>
                {items.map((s) => (
                  <button key={s.name} type="button" className={`skill-row ${value === s.name ? 'on' : ''}`} onClick={() => pick(s.name)}>
                    <span className="engine-check">{value === s.name && <Check className="icon" aria-hidden="true" />}</span>
                    <span className="engine-text">
                      <b>{s.name} {s.local ? <span className="chip">local</span> : <span className="chip dim">equipo</span>}</b>
                      <small>{s.description}</small>
                    </span>
                  </button>
                ))}
              </section>
            ))}
            {groups.length === 0 && <p className="hint">Ningún skill coincide con «{q}».</p>}
          </div>
        </div>
      )}
    </div>
  )
}
