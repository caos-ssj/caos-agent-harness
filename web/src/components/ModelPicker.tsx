import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Cpu } from '../icons'
import { Agent, ModelProfile, ProviderItem, RouterTier } from '../api'
import { baseName, clears, gb, isEmbedding, variantsOf } from '../models'
import { useDialog, usePresence } from '../hooks'

interface ModelPickerProps { provider?: ProviderItem; profiles: ModelProfile[]; tiers: RouterTier[]; agents: Agent[]; value: string; onChange: (m: string) => void }

/* Compact single-line local model picker without overflowing subtitles. */
export const ModelPicker: React.FC<ModelPickerProps> = ({ provider, profiles, tiers, agents, value, onChange }) => {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const box = useRef<HTMLDivElement>(null)
  const pres = usePresence(open, 150)
  const popRef = useDialog<HTMLDivElement>(open, () => setOpen(false), { initial: 'input' })
  useEffect(() => {
    if (!open) return
    const click = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    window.addEventListener('mousedown', click)
    return () => window.removeEventListener('mousedown', click)
  }, [open])

  const rows = useMemo(() => {
    const details = new Map((provider?.model_details ?? []).map((d) => [d.name, d]))
    const names = (provider?.models ?? []).filter((m) => !isEmbedding(m))
    const out = names.map((m) => {
      const best = variantsOf(m, profiles).sort((a, b) => b.precision_lo - a.precision_lo)[0]
      return { name: m, d: details.get(m), best, runs: agents.filter((a) => a.system && baseName(a.system) === baseName(m)).map((a) => a.name) }
    })
    return out.sort((a, b) => Number(!!b.best) - Number(!!a.best) || (b.best?.precision_lo ?? 0) - (a.best?.precision_lo ?? 0) || a.name.localeCompare(b.name))
  }, [provider, profiles, agents])
  const shown = rows.filter((r) => r.name.toLowerCase().includes(q.toLowerCase()))
  const current = rows.find((r) => r.name === value)

  return (
    <div className="mp" ref={box}>
      <button type="button" className="select mp-btn" aria-expanded={open} aria-haspopup="listbox" onClick={() => setOpen(!open)} title="Elegir modelo local">
        <Cpu className="icon icon-sm" aria-hidden="true" />
        <span className="mp-name">{value}</span>
        {current?.best ? <span className="pill-mini sage">{(current.best.precision * 100).toFixed(0)}%</span> : <span className="pill-mini">local</span>}
        <ChevronDown className="icon icon-sm" aria-hidden="true" />
      </button>
      {pres.mounted && (
        <div className="pop mp-pop" ref={popRef} data-leaving={pres.leaving ? '' : undefined} role="dialog" aria-label="Local models">
          <input className="field field-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar modelo local…" aria-label="Find a model" />
          <ul className="mp-list" role="listbox" aria-label="Installed models">
            {shown.map((r) => {
              const cl = r.best ? clears(r.best, tiers) : []
              return (
                <li key={r.name}>
                  <button type="button" role="option" aria-selected={r.name === value} className={`engine-line ${r.name === value ? 'on' : ''}`} onClick={() => { onChange(r.name); setOpen(false) }}>
                    <span className="engine-check">{r.name === value && <Check className="icon icon-sm" aria-hidden="true" />}</span>
                    <b>{r.name}</b>
                    <span className="engine-meta">{[r.d?.parameter_size, gb(r.d?.size), cl.join('/')].filter(Boolean).join(' · ') || 'local'}</span>
                    <span className={`pill-mini ${r.best ? 'sage' : ''}`}>{r.best ? `${(r.best.precision * 100).toFixed(0)}%` : 'sin medir'}</span>
                  </button>
                </li>
              )
            })}
            {shown.length === 0 && <li className="hint" style={{ padding: 10 }}>Ningún modelo coincide con «{q}».</li>}
          </ul>
        </div>
      )}
    </div>
  )
}
