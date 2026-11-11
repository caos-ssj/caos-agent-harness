import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Cpu } from 'lucide-react'
import { Agent, ModelProfile, ProviderItem, RouterTier } from '../api'
import { baseName, clears, gb, isEmbedding, variantsOf } from '../models'

interface ModelPickerProps { provider?: ProviderItem; profiles: ModelProfile[]; tiers: RouterTier[]; agents: Agent[]; value: string; onChange: (m: string) => void }

/* Choosing a local model with what is known about it beside the name: its size, whether it was measured, how well,
   and which agents already run it. A model with no measurement is fine to talk to; the router will never pick it. */
export const ModelPicker: React.FC<ModelPickerProps> = ({ provider, profiles, tiers, agents, value, onChange }) => {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const click = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    window.addEventListener('keydown', key); window.addEventListener('mousedown', click)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('mousedown', click) }
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
      <button type="button" className="select mp-btn" aria-expanded={open} aria-haspopup="listbox" onClick={() => setOpen(!open)} title="Choose the local model">
        <Cpu className="icon" style={{ width: 15, height: 15 }} aria-hidden="true" />
        <span className="mp-name">{value}</span>
        {current?.best ? <span className="chip">{(current.best.precision * 100).toFixed(0)}% measured</span> : current ? <span className="chip dim">not measured</span> : <span className="chip dim">not installed</span>}
        <ChevronDown className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />
      </button>
      {open && (
        <div className="pop mp-pop" role="dialog" aria-label="Local models">
          <input className="field" autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a model" aria-label="Find a model" />
          <p className="hint" style={{ margin: '8px 2px 6px' }}>{rows.length} installed in Ollama · {rows.filter((r) => r.best).length} measured. Measured models are listed first.</p>
          <ul className="mp-list" role="listbox" aria-label="Installed models">
            {shown.map((r) => (
              <li key={r.name}>
                <button type="button" role="option" aria-selected={r.name === value} className="mp-item" onClick={() => { onChange(r.name); setOpen(false) }}>
                  <span className="mp-check">{r.name === value && <Check className="icon" aria-hidden="true" />}</span>
                  <span className="mp-text">
                    <b>{r.name}</b>
                    <small>{[r.d?.parameter_size, r.d?.quantization, gb(r.d?.size)].filter(Boolean).join(' · ') || 'installed'}</small>
                    {r.best ? <small className="ok">{(r.best.precision * 100).toFixed(1)}% precision · lower bound {(r.best.precision_lo * 100).toFixed(1)}%{clears(r.best, tiers).length ? ` · clears ${clears(r.best, tiers).join(', ')}` : ' · clears no tier'}</small> : <small className="dim">not measured: the router will not choose it</small>}
                    {r.runs.length > 0 && <small>runs agent{r.runs.length > 1 ? 's' : ''} {r.runs.join(', ')}</small>}
                  </span>
                </button>
              </li>
            ))}
            {shown.length === 0 && <li className="hint" style={{ padding: 12 }}>No model matches “{q}”.</li>}
          </ul>
        </div>
      )}
    </div>
  )
}
