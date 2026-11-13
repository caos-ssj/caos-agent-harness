import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Cpu, ExternalLink, KeyRound, Zap } from '../icons'
import { Agent, api, IntentResolution, ModelProfile, ProviderItem, RouterTier } from '../api'
import { baseName, clears, gb, isEmbedding, variantsOf } from '../models'
import { useDialog, usePresence } from '../hooks'
import { View } from '../lib'

export type IntentId = 'rapido' | 'codigo' | 'razonar' | 'local'
export type EngineChoice =
  | { kind: 'intent'; intent: IntentId }
  | { kind: 'model'; model: string }
  | { kind: 'provider'; provider: string; model?: string }
  | { kind: 'agent'; name: string }
  | { kind: 'tier'; tier: string }

export interface EngineSelection { kind: 'intent' | 'model' | 'provider' | 'agent' | 'tier'; intent: IntentId; model: string; provider: string; providerModel: string; name: string }

interface EnginePopoverProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  label: string
  online: boolean
  ollama?: ProviderItem
  cloud: ProviderItem[]
  intents: Array<{ id: IntentId; label: string }>
  resolved?: Record<string, IntentResolution>
  profile: string
  profiles: ModelProfile[]
  tiers: RouterTier[]
  agents: Agent[]
  selection: EngineSelection
  onPick: (c: EngineChoice) => void
  onProvidersChanged: () => void
  onNavigate?: (v: View) => void
}

const ready = (p: ProviderItem) => p.status === 'online' || p.status === 'key_present' || p.status === 'ready'

/* One place to choose what answers: the router's four intents, every model installed in Ollama (measured first), and the
   cloud providers with their free-tier models. A provider with no key opens its key form right here. */
export const EnginePopover: React.FC<EnginePopoverProps> = ({ open, onOpenChange, label, online, ollama, cloud, intents, resolved, profile, profiles, tiers, agents: allAgents, selection, onPick, onProvidersChanged, onNavigate }) => {
  const agents = allAgents.filter((a) => !a.test)   // a plain command (cat) is a test engine, not something to pick
  const box = useRef<HTMLDivElement>(null)
  const pres = usePresence(open, 150)
  const close = () => onOpenChange(false)
  const popRef = useDialog<HTMLDivElement>(open, close, { initial: 'input' })
  const [q, setQ] = useState('')
  const [keyFor, setKeyFor] = useState<string | null>(null)
  const [secret, setSecret] = useState('')
  const [keyMsg, setKeyMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState<'auto' | 'local' | 'cloud'>(selection.kind === 'model' ? 'local' : selection.kind === 'provider' ? 'cloud' : 'auto')
  const [allLocal, setAllLocal] = useState(false)

  useEffect(() => {
    if (!open) return
    const click = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) close() }
    window.addEventListener('mousedown', click)
    return () => window.removeEventListener('mousedown', click)
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const needle = q.trim().toLowerCase()
  const locals = useMemo(() => {
    const details = new Map((ollama?.model_details ?? []).map((d) => [d.name, d]))
    const rows = (ollama?.models ?? []).filter((m) => !isEmbedding(m)).map((m) => {
      const best = variantsOf(m, profiles).sort((a, b) => b.precision_lo - a.precision_lo)[0]
      return { name: m, d: details.get(m), best }
    })
    return rows.sort((a, b) => Number(!!b.best) - Number(!!a.best) || (b.best?.precision_lo ?? 0) - (a.best?.precision_lo ?? 0) || a.name.localeCompare(b.name))
  }, [ollama, profiles])
  const shownLocals = locals.filter((r) => !needle || r.name.toLowerCase().includes(needle))
  const shownCloud = cloud.filter((p) => !needle || p.name.toLowerCase().includes(needle) || p.id.includes(needle) || (p.free_models ?? []).some((m) => m.toLowerCase().includes(needle)))

  const measuredLocals = shownLocals.filter((r) => r.best)
  const restLocals = shownLocals.filter((r) => !r.best)
  const readyCloud = shownCloud.filter(ready)
  const idleCloud = shownCloud.filter((p) => !ready(p))

  const pick = (c: EngineChoice) => { onPick(c); close() }
  const saveKey = async (p: ProviderItem) => {
    if (!secret.trim()) return
    setBusy(true)
    setKeyMsg(null)
    try {
      await api.saveProviderKey(p.id, secret.trim(), 'auto')
      setSecret('')
      const t = await api.testProvider(p.id)
      setKeyMsg({ ok: !!t.ok, text: t.ok ? `Clave guardada y probada${t.latency_ms ? ` · ${t.latency_ms} ms` : ''}` : `Guardada, pero la prueba falló: ${t.message || t.error || 'sin respuesta'}` })
      onProvidersChanged()
    } catch (e: any) {
      setKeyMsg({ ok: false, text: e.message || 'No se pudo guardar la clave' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="engine" ref={box}>
      <button type="button" className="select engine-btn" aria-expanded={open} aria-haspopup="dialog" onClick={() => onOpenChange(!open)} title="Elegir motor (Ctrl+M)">
        <Cpu className="icon" style={{ width: 15, height: 15 }} aria-hidden="true" />
        <span className="engine-label">{label}</span>
        <span className={`pip ${online ? 'on' : ''}`} aria-hidden="true" />
        <ChevronDown className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />
      </button>
      {pres.mounted && (
        <div className="pop engine-pop" ref={popRef} data-leaving={pres.leaving ? '' : undefined} role="dialog" aria-label="Elegir motor">
          <div className="engine-top">
            <input className="field field-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search model or provider…" aria-label="Buscar motor" />
            <span className="kbd">Ctrl M</span>
          </div>
          <div className="engine-tabs" role="tablist" aria-label="Engine source">
            {([['auto', 'Auto & agents', intents.length + agents.length], ['local', 'Local', locals.length], ['cloud', 'Cloud', cloud.length]] as const).map(([id, name, n]) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{name}<span className="engine-count">{n}</span></button>
            ))}
          </div>
          <div className="engine-body">
            {tab === 'auto' && (
              <div className="engine-list">
                <h3>Router · <span className="chip">{profile}</span></h3>
                {intents.map((it) => {
                  const r = resolved?.[it.id]
                  const on = selection.kind === 'intent' && selection.intent === it.id
                  return (
                    <button key={it.id} type="button" className={`engine-line ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'intent', intent: it.id })}>
                      <span className="engine-check">{on && <Check className="icon" aria-hidden="true" />}</span>
                      <b>{it.label}</b>
                      <span className="engine-meta">{r ? `${r.provider} · ${r.model}` : 'resolving…'}{r?.pinned ? ' · pinned' : ''}</span>
                    </button>
                  )
                })}
                {agents.length > 0 && <h3>Board agents</h3>}
                {agents.map((a) => {
                  const on = selection.kind === 'agent' && selection.name === a.name
                  return (
                    <button key={a.name} type="button" className={`engine-line ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'agent', name: a.name })}>
                      <span className="engine-check">{on && <Check className="icon" aria-hidden="true" />}</span>
                      <b>{a.name}</b>
                      <span className="engine-meta">{a.system || a.model || 'command'}</span>
                    </button>
                  )
                })}
                {tiers.length > 0 && <h3>Tiers</h3>}
                {tiers.map((t) => {
                  const on = selection.kind === 'tier' && selection.name === t.tier
                  return (
                    <button key={t.tier} type="button" className={`engine-line ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'tier', tier: t.tier })}>
                      <span className="engine-check">{on && <Check className="icon" aria-hidden="true" />}</span>
                      <b>tier {t.tier}</b>
                      <span className="engine-meta">minimum precision {t.needs}</span>
                    </button>
                  )
                })}
              </div>
            )}

            {tab === 'local' && (
              <div className="engine-list">
                <div className="engine-head-row"><span>Model</span><span>Size</span><span>Measured</span></div>
                {measuredLocals.map((r) => {
                  const on = selection.kind === 'model' && selection.model === r.name
                  const cl = r.best ? clears(r.best, tiers) : []
                  return (
                    <button key={r.name} type="button" className={`engine-line engine-model ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'model', model: r.name })}>
                      <span className="engine-check">{on && <Check className="icon" aria-hidden="true" />}</span>
                      <b>{r.name}</b>
                      <span className="engine-meta">{[r.d?.parameter_size, gb(r.d?.size)].filter(Boolean).join(' · ') || 'installed'}</span>
                      <span className="engine-score ok">{r.best ? `${(r.best.precision * 100).toFixed(0)}%` : '—'}<small>{cl.length ? cl.join(' · ') : ''}</small></span>
                    </button>
                  )
                })}
                {restLocals.length > 0 && (
                  <button type="button" className="engine-more" onClick={() => setAllLocal((v) => !v)} aria-expanded={allLocal}>
                    {allLocal ? 'Hide' : `Show ${restLocals.length} not measured`}<small>the router does not pick them on its own</small>
                  </button>
                )}
                {allLocal && restLocals.map((r) => {
                  const on = selection.kind === 'model' && selection.model === r.name
                  return (
                    <button key={r.name} type="button" className={`engine-line engine-model dim ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'model', model: r.name })}>
                      <span className="engine-check">{on && <Check className="icon" aria-hidden="true" />}</span>
                      <b>{r.name}</b>
                      <span className="engine-meta">{[r.d?.parameter_size, gb(r.d?.size)].filter(Boolean).join(' · ') || 'installed'}</span>
                      <span className="engine-score">—</span>
                    </button>
                  )
                })}
                {shownLocals.length === 0 && <p className="hint">{locals.length ? `No model matches “${q}”.` : 'Ollama is not answering or has no models installed.'}</p>}
              </div>
            )}

            {tab === 'cloud' && (
              <div className="engine-list">
                {readyCloud.length > 0 && <h3>Connected</h3>}
                {readyCloud.map((p) => {
                  const on = selection.kind === 'provider' && selection.provider === p.id
                  return (
                    <div key={p.id} className={`engine-prov ${on ? 'on' : ''}`}>
                      <button type="button" className="engine-line" onClick={() => pick({ kind: 'provider', provider: p.id })}>
                        <span className="engine-check">{on && <Check className="icon" aria-hidden="true" />}</span>
                        <b>{p.name}</b>
                        <span className="engine-meta">{p.default_model.split('/').pop()}</span>
                      </button>
                      {(p.free_models ?? []).length > 0 && (
                        <div className="engine-chips" aria-label={`Free models from ${p.name}`}>
                          {(p.free_models ?? []).slice(0, 5).map((m) => (
                            <button key={m} type="button" className={`mini-chip ${on && selection.providerModel === m ? 'on' : ''}`} title={`Use ${m}`} onClick={() => pick({ kind: 'provider', provider: p.id, model: m })}>
                              <Zap className="icon" style={{ width: 10, height: 10 }} aria-hidden="true" />{m.replace(/^.*\//, '')}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
                {idleCloud.length > 0 && <h3>Not connected <span className="engine-count">{idleCloud.length}</span></h3>}
                {idleCloud.map((p) => (
                  <div key={p.id} className="engine-prov">
                    <div className="engine-line engine-idle">
                      <span className="engine-check" />
                      <b>{p.name}</b>
                      <button type="button" className="btn btn-quiet btn-xs" onClick={() => { setKeyFor(keyFor === p.id ? null : p.id); setKeyMsg(null) }}>
                        <KeyRound className="icon" style={{ width: 12, height: 12 }} aria-hidden="true" />{keyFor === p.id ? 'Cancel' : 'Add key'}
                      </button>
                    </div>
                    {keyFor === p.id && (
                      <form className="engine-key" onSubmit={(e) => { e.preventDefault(); void saveKey(p) }}>
                        <input className="field field-sm" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={`Paste ${p.api_key_env || 'API key'}`} aria-label={`${p.name} key`} autoFocus />
                        <button type="submit" className="btn btn-primary btn-xs" disabled={busy || !secret.trim()}>{busy ? 'Testing…' : 'Save and test'}</button>
                        {keyMsg && <small className={keyMsg.ok ? 'ok' : 'err-text'} role="status">{keyMsg.text}</small>}
                      </form>
                    )}
                  </div>
                ))}
                {shownCloud.length === 0 && <p className="hint">No provider matches.</p>}
              </div>
            )}
          </div>
          <button type="button" className="btn btn-quiet btn-xs engine-link" onClick={() => { close(); onNavigate?.('providers') }}><ExternalLink className="icon" style={{ width: 12, height: 12 }} aria-hidden="true" />Open Models &amp; Providers</button>
        </div>
      )}
    </div>
  )
}

export { baseName }
