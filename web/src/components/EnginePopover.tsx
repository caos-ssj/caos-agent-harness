import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Cpu, ExternalLink, KeyRound, Plus } from '../icons'
import { Agent, api, IntentResolution, ModelProfile, OrchestratorInfo, ProviderItem, RouterTier } from '../api'
import { baseName, clears, gb, isEmbedding, variantsOf } from '../models'
import { useDialog, usePresence } from '../hooks'
import { View } from '../lib'
import { FamilyEmblem } from '../emblems'

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
  orchestrate?: {
    orchestrator: string
    model: string
    orchestrators: OrchestratorInfo[]
    installable?: Array<{ id: string; label: string }>
    adding?: string | null
    onPick: (orchestrator: string, model?: string) => void
    onAddCli?: (id: string) => void
    onAddLocal?: (model: string) => void
  }
}

const ready = (p: ProviderItem) => p.status === 'online' || p.status === 'key_present' || p.status === 'ready'

const familyFor = (name: string): string => {
  const s = name.toLowerCase()
  if (s.includes('claude') || s.includes('anthropic')) return 'claude'
  if (s.includes('gemini') || s.includes('agy')) return 'agy'
  if (s.includes('codex') || s.includes('openai')) return 'codex'
  if (s.includes('opencode')) return 'opencode'
  if (s.includes('ollama') || s.includes('qwen') || s.includes('llama') || s.includes('local')) return 'local'
  if (s.includes('review')) return 'reviewer'
  return 'api'
}

/* Compact 2-column engine selector:
   Left column: origin (Auto Router · Suscripciones CLI · Local Ollama · Cloud API · + Conectar)
   Right column: 1-line clean rows (only ready engines, no overflowing free-model chip clouds) + inline API key / CLI setup. */
export const EnginePopover: React.FC<EnginePopoverProps> = ({
  open,
  onOpenChange,
  label,
  online,
  ollama,
  cloud,
  intents,
  resolved,
  profile,
  profiles,
  tiers,
  agents: allAgents,
  selection,
  onPick,
  onProvidersChanged,
  onNavigate,
  orchestrate,
}) => {
  const agents = allAgents.filter((a) => !a.test)
  const box = useRef<HTMLDivElement>(null)
  const pres = usePresence(open, 150)
  const close = () => onOpenChange(false)
  const popRef = useDialog<HTMLDivElement>(open, close, { initial: 'input' })
  const [q, setQ] = useState('')
  const [keyFor, setKeyFor] = useState<string | null>(null)
  const [secret, setSecret] = useState('')
  const [keyMsg, setKeyMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const defaultTab = orchestrate
    ? 'orch'
    : selection.kind === 'model' ? 'local' : selection.kind === 'provider' ? 'cloud' : selection.kind === 'agent' ? 'cli' : 'auto'
  const [tab, setTab] = useState<'orch' | 'auto' | 'cli' | 'local' | 'cloud' | 'connect'>(defaultTab)
  const [allLocal, setAllLocal] = useState(false)

  useEffect(() => {
    if (open) setTab(defaultTab)
  }, [open, defaultTab])

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
  const shownAgents = agents.filter((a) => !needle || a.name.toLowerCase().includes(needle) || (a.model || a.system || '').toLowerCase().includes(needle))

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
      setKeyMsg({
        ok: !!t.ok,
        text: t.ok ? `Conectado${t.latency_ms ? ` · ${t.latency_ms} ms` : ''}` : `Clave guardada, prueba falló: ${t.message || t.error || 'sin respuesta'}`,
      })
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
        <Cpu className="icon icon-sm" aria-hidden="true" />
        <span className="engine-label">{label}</span>
        <span className={`pip ${online ? 'on' : ''}`} aria-hidden="true" />
        <ChevronDown className="icon icon-sm" aria-hidden="true" />
      </button>
      {pres.mounted && (
        <div className="pop engine-pop" ref={popRef} data-leaving={pres.leaving ? '' : undefined} role="dialog" aria-label="Elegir motor">
          <div className="engine-top">
            <input className="field field-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar modelo, agente o proveedor…" aria-label="Buscar motor" />
            <span className="kbd">Ctrl M</span>
          </div>

          <div className="engine-split">
            <nav className="engine-nav" role="tablist" aria-label="Origen del motor">
              {(orchestrate
                ? ([['orch', 'Orquestador', orchestrate.orchestrators.length]] as const)
                : ([
                    ['auto', 'Auto Router', intents.length + tiers.length],
                    ['cli', 'Suscripciones CLI', agents.length],
                    ['local', 'Local Ollama', locals.length],
                    ['cloud', 'Cloud API', readyCloud.length],
                  ] as const)
              ).map(([id, name, n]) => (
                <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
                  <span>{name}</span>
                  <span className="engine-count">{n}</span>
                </button>
              ))}
              <div className="engine-nav-foot">
                <button
                  type="button"
                  role="tab"
                  aria-selected={tab === 'connect'}
                  className="engine-connect-tab"
                  onClick={() => setTab('connect')}
                >
                  <Plus className="icon icon-xs" aria-hidden="true" />
                  <span>Conectar</span>
                  {idleCloud.length > 0 && <span className="engine-count">{idleCloud.length}</span>}
                </button>
                <button type="button" className="btn btn-quiet btn-xs engine-link" onClick={() => { close(); onNavigate?.('providers') }}>
                  <ExternalLink className="icon icon-xs" aria-hidden="true" />Proveedores
                </button>
              </div>
            </nav>

            <div className="engine-body">
              {tab === 'orch' && orchestrate && (
                <div className="engine-list">
                  <h3>Orquestador y modelo activos</h3>
                  {orchestrate.orchestrators.length === 0 && (
                    <p className="hint">Este proyecto aún no tiene agentes IA en harness.toml. Añade uno abajo para activar Orquestar:</p>
                  )}
                  {orchestrate.orchestrators
                    .filter((o) => !needle || o.name.toLowerCase().includes(needle) || (o.model || '').toLowerCase().includes(needle) || (o.models ?? []).some((m) => m.toLowerCase().includes(needle)))
                    .map((o) => {
                      const isSel = o.name === orchestrate.orchestrator
                      const activeModel = isSel ? orchestrate.model : o.model || ''
                      const modelsList = o.family === 'local'
                        ? Array.from(new Set([...(o.models ?? []), ...locals.map((l) => l.name)]))
                        : (o.models ?? [])
                      const filteredModels = modelsList.filter((m) => !needle || m.toLowerCase().includes(needle) || o.name.toLowerCase().includes(needle))
                      return (
                        <React.Fragment key={o.name}>
                          <button type="button" className={`engine-line ${isSel ? 'on' : ''}`} onClick={() => { orchestrate.onPick(o.name, o.model || undefined); close() }}>
                            <span className="engine-check">{isSel ? <Check className="icon icon-sm" aria-hidden="true" /> : <FamilyEmblem family={o.family || familyFor(o.name)} size={14} />}</span>
                            <b>{o.name}</b>
                            <span className="engine-meta">{activeModel || o.family || o.kind}</span>
                            <span className={`pill-mini ${o.installed ? 'sage' : 'amber'}`}>{o.installed ? 'listo' : 'sin instalar'}</span>
                          </button>
                          {filteredModels.map((m) => {
                            const mOn = isSel && activeModel === m
                            return (
                              <button key={`${o.name}:${m}`} type="button" className={`engine-line engine-subline ${mOn ? 'on' : ''}`} onClick={() => { orchestrate.onPick(o.name, m); close() }}>
                                <span className="engine-check">{mOn && <Check className="icon icon-sm" aria-hidden="true" />}</span>
                                <b>{m.replace(/^.*\//, '')}</b>
                                <span className="engine-meta">{o.name}</span>
                                <span className="pill-mini">{m === o.model ? 'base' : 'opción'}</span>
                              </button>
                            )
                          })}
                        </React.Fragment>
                      )
                    })}
                  {(orchestrate.installable?.length ?? 0) > 0 && orchestrate.onAddCli && (
                    <>
                      <h3>CLIs instalados listos para añadir</h3>
                      {orchestrate.installable!.map((c) => (
                        <button key={c.id} type="button" className="engine-line" disabled={orchestrate.adding === c.id} onClick={() => orchestrate.onAddCli!(c.id)}>
                          <span className="engine-check"><FamilyEmblem family={c.id} size={14} /></span>
                          <b>{c.label}</b>
                          <span className="engine-meta">{c.id}</span>
                          <span className="pill-mini sage">{orchestrate.adding === c.id ? 'añadiendo…' : '+ Añadir'}</span>
                        </button>
                      ))}
                    </>
                  )}
                  {orchestrate.orchestrators.length === 0 && locals.length > 0 && orchestrate.onAddLocal && (
                    <>
                      <h3>Modelos locales en Ollama</h3>
                      {locals.slice(0, 4).map((r) => (
                        <button key={r.name} type="button" className="engine-line" disabled={!!orchestrate.adding} onClick={() => orchestrate.onAddLocal!(r.name)}>
                          <span className="engine-check"><FamilyEmblem family="local" size={14} /></span>
                          <b>{r.name}</b>
                          <span className="engine-meta">Ollama local</span>
                          <span className="pill-mini sage">+ Añadir</span>
                        </button>
                      ))}
                    </>
                  )}
                </div>
              )}

              {tab === 'auto' && (
                <div className="engine-list">
                  <h3>Router por intención · <span className="pill-mini">{profile}</span></h3>
                  {intents.map((it) => {
                    const r = resolved?.[it.id]
                    const on = selection.kind === 'intent' && selection.intent === it.id
                    return (
                      <button key={it.id} type="button" className={`engine-line ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'intent', intent: it.id })}>
                        <span className="engine-check">{on ? <Check className="icon icon-sm" aria-hidden="true" /> : <FamilyEmblem family={r ? familyFor(r.provider) : 'api'} size={14} />}</span>
                        <b>{it.label}</b>
                        <span className="engine-meta">{r ? `${r.provider} · ${r.model}` : 'auto'}</span>
                        <span className={`pill-mini ${r?.pinned ? 'amber' : 'sage'}`}>{r?.pinned ? 'fijado' : 'auto'}</span>
                      </button>
                    )
                  })}
                  {shownAgents.length > 0 && <h3>Agentes activos del proyecto</h3>}
                  {shownAgents.map((a) => {
                    const on = selection.kind === 'agent' && selection.name === a.name
                    return (
                      <button key={a.name} type="button" className={`engine-line ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'agent', name: a.name })}>
                        <span className="engine-check">{on ? <Check className="icon icon-sm" aria-hidden="true" /> : <FamilyEmblem family={familyFor(a.name)} size={14} />}</span>
                        <b>{a.name}</b>
                        <span className="engine-meta">{a.system || a.model || 'CLI'}</span>
                        <span className="pill-mini sage">listo</span>
                      </button>
                    )
                  })}
                  {tiers.length > 0 && <h3>Tiers de precisión</h3>}
                  {tiers.map((t) => {
                    const on = selection.kind === 'tier' && selection.name === t.tier
                    return (
                      <button key={t.tier} type="button" className={`engine-line ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'tier', tier: t.tier })}>
                        <span className="engine-check">{on && <Check className="icon icon-sm" aria-hidden="true" />}</span>
                        <b>tier {t.tier}</b>
                        <span className="engine-meta">{t.system || 'router'}</span>
                        <span className="pill-mini">≥ {t.needs}</span>
                      </button>
                    )
                  })}
                </div>
              )}

              {tab === 'cli' && (
                <div className="engine-list">
                  <h3>Suscripciones y agentes CLI activos</h3>
                  {shownAgents.map((a) => {
                    const on = selection.kind === 'agent' && selection.name === a.name
                    return (
                      <button key={a.name} type="button" className={`engine-line ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'agent', name: a.name })}>
                        <span className="engine-check">{on ? <Check className="icon icon-sm" aria-hidden="true" /> : <FamilyEmblem family={familyFor(a.name)} size={14} />}</span>
                        <b>{a.name}</b>
                        <span className="engine-meta">{a.system || a.model || 'suscripción CLI'}</span>
                        <span className="pill-mini sage">conectado</span>
                      </button>
                    )
                  })}
                  {shownAgents.length === 0 && (
                    <p className="hint">Ningún agente CLI coincide. Pulsa «+ Conectar» o abre Proveedores para añadir Claude Code, Codex, Gemini o OpenCode.</p>
                  )}
                </div>
              )}

              {tab === 'local' && (
                <div className="engine-list">
                  <h3>Modelos locales en Ollama</h3>
                  {measuredLocals.map((r) => {
                    const on = selection.kind === 'model' && selection.model === r.name
                    const cl = r.best ? clears(r.best, tiers) : []
                    return (
                      <button key={r.name} type="button" className={`engine-line ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'model', model: r.name })}>
                        <span className="engine-check">{on ? <Check className="icon icon-sm" aria-hidden="true" /> : <FamilyEmblem family="local" size={14} />}</span>
                        <b>{r.name}</b>
                        <span className="engine-meta">{[r.d?.parameter_size, gb(r.d?.size)].filter(Boolean).join(' · ') || 'local'}{cl.length ? ` · ${cl.join('/')}` : ''}</span>
                        <span className="pill-mini sage">{r.best ? `${(r.best.precision * 100).toFixed(0)}%` : 'local'}</span>
                      </button>
                    )
                  })}
                  {restLocals.length > 0 && (
                    <button type="button" className="engine-more" onClick={() => setAllLocal((v) => !v)} aria-expanded={allLocal}>
                      <span>{allLocal ? 'Ocultar no medidos' : `Ver ${restLocals.length} modelos instalados sin medir`}</span>
                      <small>uso directo en consola</small>
                    </button>
                  )}
                  {allLocal && restLocals.map((r) => {
                    const on = selection.kind === 'model' && selection.model === r.name
                    return (
                      <button key={r.name} type="button" className={`engine-line dim ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'model', model: r.name })}>
                        <span className="engine-check">{on ? <Check className="icon icon-sm" aria-hidden="true" /> : <FamilyEmblem family="local" size={14} />}</span>
                        <b>{r.name}</b>
                        <span className="engine-meta">{[r.d?.parameter_size, gb(r.d?.size)].filter(Boolean).join(' · ') || 'instalado'}</span>
                        <span className="pill-mini">local</span>
                      </button>
                    )
                  })}
                  {shownLocals.length === 0 && <p className="hint">{locals.length ? `Ningún modelo coincide con «${q}».` : 'Ollama no responde o no tiene modelos instalados.'}</p>}
                </div>
              )}

              {tab === 'cloud' && (
                <div className="engine-list">
                  <h3>Proveedores conectados</h3>
                  {readyCloud.map((p) => {
                    const on = selection.kind === 'provider' && selection.provider === p.id && !selection.providerModel
                    const shortModel = (p.default_model || '').split('/').pop() || p.default_model
                    return (
                      <React.Fragment key={p.id}>
                        <button type="button" className={`engine-line ${on ? 'on' : ''}`} onClick={() => pick({ kind: 'provider', provider: p.id })}>
                          <span className="engine-check">{on ? <Check className="icon icon-sm" aria-hidden="true" /> : <FamilyEmblem family={familyFor(p.id)} size={14} />}</span>
                          <b>{p.name}</b>
                          <span className="engine-meta">{shortModel}</span>
                          <span className="pill-mini sage">conectado</span>
                        </button>
                        {(p.free_models ?? []).slice(0, 2).map((m) => {
                          const mOn = selection.kind === 'provider' && selection.provider === p.id && selection.providerModel === m
                          return (
                            <button key={m} type="button" className={`engine-line engine-subline ${mOn ? 'on' : ''}`} onClick={() => pick({ kind: 'provider', provider: p.id, model: m })}>
                              <span className="engine-check">{mOn && <Check className="icon icon-sm" aria-hidden="true" />}</span>
                              <b>{m.replace(/^.*\//, '')}</b>
                              <span className="engine-meta">{p.name}</span>
                              <span className="pill-mini">gratis</span>
                            </button>
                          )
                        })}
                      </React.Fragment>
                    )
                  })}
                  {readyCloud.length === 0 && (
                    <div className="engine-empty-connect">
                      <p className="hint">No hay proveedores Cloud con clave activa todavía.</p>
                      <button type="button" className="btn btn-xs" onClick={() => setTab('connect')}>
                        <KeyRound className="icon icon-xs" aria-hidden="true" />+ Conectar proveedor o suscripción
                      </button>
                    </div>
                  )}
                  {idleCloud.length > 0 && readyCloud.length > 0 && (
                    <button type="button" className="engine-more" onClick={() => setTab('connect')}>
                      <span>+ Conectar otro proveedor ({idleCloud.length} disponibles)</span>
                      <small>pegar API key sin salir</small>
                    </button>
                  )}
                </div>
              )}

              {tab === 'connect' && (
                <div className="engine-list">
                  <h3>Conectar API Key sin salir de Console</h3>
                  {idleCloud.map((p) => (
                    <div key={p.id} className="engine-prov">
                      <div className="engine-line engine-idle">
                        <span className="engine-check"><FamilyEmblem family={familyFor(p.id)} size={14} /></span>
                        <b>{p.name}</b>
                        <span className="engine-meta">{p.api_key_env || 'API_KEY'}</span>
                        <button type="button" className="btn btn-xs" onClick={() => { setKeyFor(keyFor === p.id ? null : p.id); setSecret(''); setKeyMsg(null) }}>
                          <KeyRound className="icon icon-xs" aria-hidden="true" />{keyFor === p.id ? 'Cancelar' : 'Conectar Key'}
                        </button>
                      </div>
                      {keyFor === p.id && (
                        <form className="engine-key" onSubmit={(e) => { e.preventDefault(); void saveKey(p) }}>
                          <input className="field field-sm" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={`Pegar ${p.api_key_env || 'API key'}`} aria-label={`${p.name} key`} autoFocus />
                          <button type="submit" className="btn btn-primary btn-xs" disabled={busy || !secret.trim()}>{busy ? 'Probando…' : 'Guardar y probar'}</button>
                          {keyMsg && <small className={keyMsg.ok ? 'ok' : 'err-text'} role="status">{keyMsg.text}</small>}
                        </form>
                      )}
                    </div>
                  ))}
                  {idleCloud.length === 0 && <p className="hint">Todos los proveedores Cloud están conectados.</p>}
                  <h3>Suscripciones CLI y Gateways</h3>
                  <button type="button" className="engine-more" onClick={() => { close(); onNavigate?.('providers') }}>
                    <span>Gestionar suscripciones CLI, Ollama y Gateways</span>
                    <small>abrir Modelos y Proveedores →</small>
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export { baseName }
