import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Cpu, ExternalLink, KeyRound, Zap } from 'lucide-react'
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
export const EnginePopover: React.FC<EnginePopoverProps> = ({ open, onOpenChange, label, online, ollama, cloud, intents, resolved, profile, profiles, tiers, agents, selection, onPick, onProvidersChanged, onNavigate }) => {
  const box = useRef<HTMLDivElement>(null)
  const pres = usePresence(open, 150)
  const close = () => onOpenChange(false)
  const popRef = useDialog<HTMLDivElement>(open, close, { initial: 'input' })
  const [q, setQ] = useState('')
  const [keyFor, setKeyFor] = useState<string | null>(null)
  const [secret, setSecret] = useState('')
  const [keyMsg, setKeyMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

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
            <input className="field field-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar modelo o proveedor…" aria-label="Buscar motor" />
            <span className="kbd">Ctrl M</span>
          </div>
          <div className="engine-cols">
            <section className="engine-col" aria-label="Auto Intent y Router">
              <h3>Auto Intent · Router <span className="chip">{profile}</span></h3>
              {intents.map((it) => {
                const r = resolved?.[it.id]
                const on = selection.kind === 'intent' && selection.intent === it.id
                return (
                  <button key={it.id} type="button" className={`engine-row ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'intent', intent: it.id })}>
                    <span className="engine-check">{on && <Check className="icon" aria-hidden="true" />}</span>
                    <span className="engine-text"><b>{it.label}</b><small>{r ? `${r.provider} · ${r.model}` : 'resolviendo…'}{r?.pinned ? ' · fijado' : ''}</small></span>
                  </button>
                )
              })}
              {(agents.length > 0 || tiers.length > 0) && <h3 className="engine-sub">Agentes y tiers del Board</h3>}
              {agents.map((a) => {
                const on = selection.kind === 'agent' && selection.name === a.name
                return <button key={a.name} type="button" className={`engine-row ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'agent', name: a.name })}><span className="engine-check">{on && <Check className="icon" aria-hidden="true" />}</span><span className="engine-text"><b>{a.name}</b><small>agente · {a.system || a.model || 'comando'}</small></span></button>
              })}
              {tiers.map((t) => {
                const on = selection.kind === 'tier' && selection.name === t.tier
                return <button key={t.tier} type="button" className={`engine-row ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'tier', tier: t.tier })}><span className="engine-check">{on && <Check className="icon" aria-hidden="true" />}</span><span className="engine-text"><b>tier {t.tier}</b><small>precisión mínima {t.needs}</small></span></button>
              })}
            </section>

            <section className="engine-col" aria-label="Modelos locales de Ollama">
              <h3>Locales · Ollama <span className="chip sage-chip">sin coste de API</span></h3>
              <p className="hint engine-hint">{locals.length} instalados · {locals.filter((r) => r.best).length} medidos (primero)</p>
              {shownLocals.map((r) => {
                const on = selection.kind === 'model' && selection.model === r.name
                const cl = r.best ? clears(r.best, tiers) : []
                return (
                  <button key={r.name} type="button" className={`engine-row ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'model', model: r.name })}>
                    <span className="engine-check">{on && <Check className="icon" aria-hidden="true" />}</span>
                    <span className="engine-text">
                      <b>{r.name}</b>
                      <small>{[r.d?.parameter_size, r.d?.quantization, gb(r.d?.size)].filter(Boolean).join(' · ') || 'instalado'}</small>
                      {r.best ? <small className="ok">{(r.best.precision * 100).toFixed(0)}% medido · {cl.length ? `cubre ${cl.join(', ')}` : 'no cubre ningún tier'}</small> : <small className="dim">sin medir: el router no lo elige</small>}
                    </span>
                  </button>
                )
              })}
              {shownLocals.length === 0 && <p className="hint">{locals.length ? `Ningún modelo coincide con «${q}».` : 'Ollama no responde o no tiene modelos instalados.'}</p>}
            </section>

            <section className="engine-col" aria-label="Nube y free tiers">
              <h3>Nube · Free tiers</h3>
              {shownCloud.map((p) => {
                const ok = ready(p)
                const on = selection.kind === 'provider' && selection.provider === p.id
                const frees = p.free_models ?? []
                return (
                  <div key={p.id} className={`engine-prov ${on ? 'on' : ''}`}>
                    <div className="engine-prov-head">
                      <b>{p.name}</b>
                      {ok
                        ? <button type="button" className="chip sage-chip" onClick={() => pick({ kind: 'provider', provider: p.id })} title={`Usar ${p.default_model}`}>listo · {p.default_model.split('/').pop()}</button>
                        : <button type="button" className="chip amber-chip" onClick={() => { setKeyFor(keyFor === p.id ? null : p.id); setKeyMsg(null) }}><KeyRound className="icon" style={{ width: 11, height: 11 }} aria-hidden="true" />falta {p.api_key_env || 'KEY'} · configurar</button>}
                    </div>
                    {frees.length > 0 && (
                      <div className="engine-chips" aria-label={`Modelos gratuitos de ${p.name}`}>
                        {frees.slice(0, 5).map((m) => (
                          <button key={m} type="button" className={`mini-chip ${on && selection.providerModel === m ? 'on' : ''}`} disabled={!ok} title={ok ? `Usar ${m}` : 'Configura la clave primero'} onClick={() => pick({ kind: 'provider', provider: p.id, model: m })}>
                            <Zap className="icon" style={{ width: 10, height: 10 }} aria-hidden="true" />{m.replace(/^.*\//, '')}
                          </button>
                        ))}
                      </div>
                    )}
                    {p.tier_hint && <small className="engine-tier">{p.tier_hint}</small>}
                    {keyFor === p.id && (
                      <form className="engine-key" onSubmit={(e) => { e.preventDefault(); void saveKey(p) }}>
                        <input className="field field-sm" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={`Pegar ${p.api_key_env || 'API key'}`} aria-label={`Clave de ${p.name}`} autoFocus />
                        <button type="submit" className="btn btn-primary btn-xs" disabled={busy || !secret.trim()}>{busy ? 'Probando…' : 'Guardar y probar'}</button>
                        {keyMsg && <small className={keyMsg.ok ? 'ok' : 'err-text'} role="status">{keyMsg.text}</small>}
                      </form>
                    )}
                  </div>
                )
              })}
              {shownCloud.length === 0 && <p className="hint">Ningún proveedor coincide.</p>}
              <button type="button" className="btn btn-quiet btn-xs engine-link" onClick={() => { close(); onNavigate?.('providers') }}><ExternalLink className="icon" style={{ width: 12, height: 12 }} aria-hidden="true" />Abrir Models &amp; Providers</button>
            </section>
          </div>
        </div>
      )}
    </div>
  )
}

export { baseName }
