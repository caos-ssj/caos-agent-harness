import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowRight, Check, GitCompareArrows, KeyRound, Pin, Plus, RefreshCw, Terminal, Trash2, Zap } from '../icons'
import { Agent, api, FailoverPolicy, IntentResolution, ModelProfile, OllamaHost, ProviderItem, ProvidersResponse, RouterTier } from '../api'
import { Accordion } from './Accordion'
import { baseName, clears, gb, isEmbedding, variantsOf } from '../models'

const pct = (n: number, d = 0) => `${(n * 100).toFixed(d)}%`
const isReady = (p: ProviderItem) => p.status === 'online' || p.status === 'key_present' || p.status === 'ready'
const PRESET_ORDER = ['anthropic', 'openai', 'openrouter', 'gemini', 'deepseek', 'groq', 'nvidia']
const INTENT_IDS = ['rapido', 'codigo', 'razonar', 'local'] as const
const isLocalUrl = (u?: string) => !!u && /^https?:\/\/(127\.|localhost|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(u)

interface Props {
  agents: Agent[]
  profiles: ModelProfile[]
  tiers: RouterTier[]
  scope: 'project' | 'global'
  onAgentsChanged: () => void
  onProvidersChanged?: () => void
  onUseModel: (m: string, provider?: string) => void
}

interface Engine { value: string; label: string; provider: string; model: string; cloud: boolean }
interface CompareResult { provider: string; model: string; ok: boolean; latency_ms: number; json_ok: boolean; tool_calls: number; answer: string; prompt_tokens: number; completion_tokens: number; error: string }

export const ProvidersView: React.FC<Props> = ({ agents, profiles, tiers, scope, onAgentsChanged, onProvidersChanged, onUseModel }) => {
  const [data, setData] = useState<ProvidersResponse | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [smoke, setSmoke] = useState<Record<string, { ok: boolean; latency_ms?: number; json_ok?: boolean; tools_ok?: boolean; error?: string }>>({})
  const [ping, setPing] = useState<Record<string, { ok: boolean; message: string; latency_ms?: number }>>({})
  const [keyFor, setKeyFor] = useState<string | null>(null)
  const [secret, setSecret] = useState('')
  const [storage, setStorage] = useState<'auto' | 'env_local' | 'keyring'>(scope === 'global' ? 'auto' : 'env_local')
  const [addingHost, setAddingHost] = useState(false)
  const [hostForm, setHostForm] = useState({ label: '', url: '' })
  const [addingCustom, setAddingCustom] = useState(false)
  const [customForm, setCustomForm] = useState({ name: '', base_url: '', api_key_env: '', kind: 'openai' as 'openai' | 'anthropic', models: '' })
  const [failover, setFailover] = useState<FailoverPolicy>({ enabled: false, strategy: 'sequential', fallback_target: 'ollama', fallback_model: '', description: '' })
  const [cliModel, setCliModel] = useState<Record<string, string>>({})
  const [pinFor, setPinFor] = useState<string | null>(null)
  // comparator
  const [cmpPrompt, setCmpPrompt] = useState('Resume en una frase qué hace un harness de agentes.')
  const [cmpA, setCmpA] = useState('')
  const [cmpB, setCmpB] = useState('')
  const [cmpResults, setCmpResults] = useState<CompareResult[] | null>(null)
  const [cmpConfirm, setCmpConfirm] = useState(false)

  useEffect(() => { setStorage(scope === 'global' ? 'auto' : 'env_local') }, [scope])

  const load = useCallback(async () => {
    try {
      const r = await api.getProviders()
      setData(r)
      if (r.active_failover) setFailover(r.active_failover)
      setErr(null)
    } catch (e: any) {
      setErr(e.message || 'No se pudieron consultar los proveedores')
    }
  }, [])
  useEffect(() => { void load() }, [load])
  const changed = () => { onProvidersChanged?.() }

  const ollama = useMemo(() => (data?.providers ?? []).find((p) => p.id === 'ollama'), [data])
  const cloud = useMemo(() => (data?.providers ?? []).filter((p) => p.id !== 'ollama' && p.type === 'cloud').sort((a, b) => (PRESET_ORDER.indexOf(a.id) + 1 || 99) - (PRESET_ORDER.indexOf(b.id) + 1 || 99)), [data])
  const gateways = useMemo(() => (data?.providers ?? []).filter((p) => p.type === 'custom'), [data])
  const localGateways = gateways.filter((g) => isLocalUrl(g.base_url))
  const remoteGateways = gateways.filter((g) => !isLocalUrl(g.base_url))
  const hosts: OllamaHost[] = data?.ollama_hosts ?? []

  const modelRows = useMemo(() => {
    const details = new Map((ollama?.model_details ?? []).map((d) => [d.name, d]))
    return (ollama?.models ?? []).filter((m) => !isEmbedding(m)).map((m) => {
      const best = [...variantsOf(m, profiles)].sort((a, b) => b.precision_lo - a.precision_lo)[0]
      return { name: m, d: details.get(m), best, runs: agents.filter((a) => a.system && baseName(a.system) === baseName(m)).map((a) => a.name) }
    }).sort((a, b) => Number(!!b.best) - Number(!!a.best) || (b.best?.precision_lo ?? 0) - (a.best?.precision_lo ?? 0) || a.name.localeCompare(b.name))
  }, [ollama, profiles, agents])
  const measuredCount = modelRows.filter((r) => r.best).length
  const [showUnmeasured, setShowUnmeasured] = useState(false)
  const restRows = modelRows.filter((r) => !r.best)
  const visibleRows = showUnmeasured ? modelRows : modelRows.filter((r) => r.best)

  const engines: Engine[] = useMemo(() => {
    const out: Engine[] = modelRows.map((r) => ({ value: `ollama::${r.name}`, label: `Local · ${r.name}`, provider: 'ollama', model: r.name, cloud: false }))
    for (const p of [...cloud, ...gateways].filter(isReady)) {
      const models = Array.from(new Set([p.default_model, ...(p.free_models ?? [])].filter(Boolean)))
      for (const m of models.slice(0, 6)) out.push({ value: `${p.id}::${m}`, label: `${p.name} · ${m}${(p.free_models ?? []).includes(m) ? ' (free)' : ''}`, provider: p.id, model: m, cloud: true })
    }
    return out
  }, [modelRows, cloud, gateways])
  useEffect(() => {
    if (!engines.length) return
    setCmpA((cur) => (engines.some((e) => e.value === cur) ? cur : engines[0].value))
    setCmpB((cur) => (engines.some((e) => e.value === cur) ? cur : (engines.find((e) => !e.cloud && e.value !== engines[0].value) ?? engines[Math.min(1, engines.length - 1)]).value))
  }, [engines])

  const doPing = async (pid: string, baseUrl?: string) => {
    setBusyId(`ping:${pid}`)
    try { const r = await api.testProvider(pid, baseUrl); setPing((c) => ({ ...c, [pid]: r })) } catch (e: any) { setPing((c) => ({ ...c, [pid]: { ok: false, message: e.message } })) } finally { setBusyId(null) }
  }
  const doSmoke = async (pid: string, model?: string) => {
    setBusyId(`smoke:${pid}:${model ?? ''}`)
    try { const r = await api.smokeProvider(pid, model); setSmoke((c) => ({ ...c, [pid]: r })); changed() } catch (e: any) { setSmoke((c) => ({ ...c, [pid]: { ok: false, error: e.message } })) } finally { setBusyId(null) }
  }
  const saveKey = async (e: React.FormEvent, pid: string) => {
    e.preventDefault()
    if (!secret.trim()) return
    setBusyId(`key:${pid}`)
    try {
      const r = await api.saveProviderKey(pid, secret.trim(), storage)
      setNote(`Clave guardada en ${r.storage} (${r.masked})`)
      setSecret(''); setKeyFor(null); await load(); changed()
    } catch (ex: any) { setErr(ex.message || 'No se pudo guardar la clave') } finally { setBusyId(null) }
  }
  const addHost = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!hostForm.url.trim()) return
    try { await api.saveOllamaHost({ url: hostForm.url.trim(), label: hostForm.label.trim() }); setHostForm({ label: '', url: '' }); setAddingHost(false); await load(); changed() } catch (ex: any) { setErr(ex.message || 'Host inválido') }
  }
  const addCustom = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.saveCustomProvider({ name: customForm.name.trim(), base_url: customForm.base_url.trim(), kind: customForm.kind, api_key_env: customForm.api_key_env.trim() || undefined, models: customForm.models.split(',').map((m) => m.trim()).filter(Boolean) } as any)
      setCustomForm({ name: '', base_url: '', api_key_env: '', kind: 'openai', models: '' }); setAddingCustom(false); await load(); changed()
    } catch (ex: any) { setErr(ex.message || 'Gateway inválido') }
  }
  const saveFailover = async (next: FailoverPolicy) => {
    setFailover(next)
    try { const saved = await api.saveFailover(next); setFailover(saved); setNote(`Failover ${saved.enabled ? 'activado' : 'apagado'} (${saved.strategy} → ${saved.fallback_target})`) } catch (ex: any) { setErr(ex.message || 'No se pudo guardar el failover') }
  }
  const pinIntent = async (intent: string, val: string) => {
    if (!val.includes('::')) return
    const [prov, mod] = val.split('::', 2)
    try { await api.saveIntentOverride(intent, prov, mod); setNote(`Intent «${intent}» fijado a ${prov} · ${mod}`); setPinFor(null); await load(); changed() } catch (ex: any) { setErr(ex.message || 'Error fijando intent') }
  }

  const sideOf = (v: string) => engines.find((e) => e.value === v)
  const runCompare = async (confirmed: boolean) => {
    const a = sideOf(cmpA), b = sideOf(cmpB)
    if (!a || !b) return
    if ((a.cloud || b.cloud) && !confirmed) { setCmpConfirm(true); return }
    setCmpConfirm(false); setBusyId('compare'); setCmpResults(null)
    try {
      const r = await api.compareProviders({ prompt: cmpPrompt, sides: [{ provider: a.provider, model: a.model }, { provider: b.provider, model: b.model }], confirm_cloud: confirmed ? true : undefined })
      setCmpResults(r.results)
    } catch (ex: any) { setErr(ex.message || 'No se pudo comparar') } finally { setBusyId(null) }
  }
  const cmpCloudNames = [sideOf(cmpA), sideOf(cmpB)].filter((e) => e?.cloud).map((e) => `${e!.provider} · ${e!.model}`)

  const intents: Record<string, IntentResolution> = data?.intents ?? {}
  const choices = engines.map((e) => ({ value: e.value, label: e.label }))

  return (
    <div className="page">
      <div className="page-inner prov-page">
        <div className="page-bar">
          <h1>Models &amp; Providers</h1>
          <div className="page-bar-right">
            <span className="chip">{scope === 'global' ? 'Global · hosts, claves y catálogo' : 'Proyecto · agentes, router y respaldo'}</span>
            <button type="button" className="btn btn-quiet btn-icon btn-sm" onClick={() => void load()} title="Actualizar" aria-label="Actualizar proveedores"><RefreshCw className="icon" style={{ width: 14, height: 14 }} /></button>
          </div>
        </div>
        {note && <div className="toast-strip" role="status">{note}</div>}
        {err && <div className="banner err" role="alert"><span>{err}</span><button type="button" className="btn btn-quiet btn-xs" onClick={() => setErr(null)}>Cerrar</button></div>}

        {/* ── Local ─────────────────────────────────────────────── */}
        <section className="card prov-section" aria-label="Modelos locales">
          <div className="card-head">
            <h2>Local · Ollama ({modelRows.length} modelos · {measuredCount} medidos)</h2>
            <span className="chip sage-chip">sin coste de API</span>
          </div>
          <h3 className="prov-sub">Ollama Multi-Host ({hosts.filter((h) => h.online).length}/{hosts.length} online)</h3>
          <div className="hosts-row">
            {hosts.map((h) => (
              <span key={h.id} className="host-chip">
                <i className={`dot ${h.online ? 'sage' : 'coral'}`} />
                <b>{h.label}</b><span className="mono muted">{h.url}</span><span className="chip">{h.models?.length ?? 0} mod</span>
                {scope === 'global' && h.id !== 'local' && <button type="button" className="btn btn-quiet btn-icon btn-xs" aria-label={`Quitar host ${h.label}`} onClick={async () => { await api.saveOllamaHost({ id: h.id, remove: true }); await load() }}><Trash2 className="icon" style={{ width: 12, height: 12 }} /></button>}
              </span>
            ))}
            <button type="button" className="btn btn-quiet btn-xs" onClick={() => setAddingHost((v) => !v)}><Plus className="icon" style={{ width: 13, height: 13 }} />Host LAN / Remoto</button>
          </div>
          {addingHost && (
            <form className="inline-form prov-form" onSubmit={addHost}>
              <input className="field field-sm" value={hostForm.label} onChange={(e) => setHostForm({ ...hostForm, label: e.target.value })} placeholder="Etiqueta (opcional)" />
              <input className="field field-sm" required value={hostForm.url} onChange={(e) => setHostForm({ ...hostForm, url: e.target.value })} placeholder="http://192.168.1.50:11434" />
              <button type="submit" className="btn btn-primary btn-sm">Guardar Host</button>
            </form>
          )}

          <div className="tbl-scroll">
            <table className="tbl prov-models">
              <thead><tr><th>Modelo</th><th className="col-fam">Familia · tamaño</th><th className="col-quant">Cuantización</th><th className="num">Peso</th><th className="num">Precisión</th><th>Cubre</th><th className="actions-col">Acciones</th></tr></thead>
              <tbody>
                {visibleRows.map((r) => {
                  const cl = r.best ? clears(r.best, tiers) : []
                  return (
                    <tr key={r.name}>
                      <td><b className="mono">{r.name}</b>{r.runs.length > 0 && <small className="muted"> · agente {r.runs.join(', ')}</small>}</td>
                      <td className="mono muted col-fam">{[r.d?.family, r.d?.parameter_size].filter(Boolean).join(' · ') || '—'}</td>
                      <td className="mono muted col-quant">{r.d?.quantization || '—'}</td>
                      <td className="num mono">{gb(r.d?.size) || '—'}</td>
                      <td className="num mono">{r.best ? <span title={`n=${r.best.n ?? '?'}`}><b className="sage">{pct(r.best.precision)}</b> <span className="muted">≥{pct(r.best.precision_lo, 1)}</span></span> : <span className="muted">sin medir</span>}</td>
                      <td>{cl.length ? cl.map((t) => <span key={t} className="chip">{t}</span>) : <span className="muted mono">{r.best ? 'ningún tier' : 'el router no lo elige'}</span>}</td>
                      <td className="actions-col">
                        <button type="button" className="btn btn-xs" disabled={busyId === `smoke:ollama:${r.name}`} onClick={() => void doSmoke('ollama', r.name)}>Smoke</button>
                        <button type="button" className="btn btn-xs" onClick={() => onUseModel(r.name, 'ollama')}>Usar en Console</button>
                        {pinFor === r.name ? (
                          <select className="select select-sm" aria-label={`Fijar ${r.name} en una intención`} defaultValue="" onChange={(e) => e.target.value && void pinIntent(e.target.value, `ollama::${r.name}`)} autoFocus onBlur={() => setPinFor(null)}>
                            <option value="" disabled>Intención…</option>
                            {INTENT_IDS.map((i) => <option key={i} value={i}>{i}</option>)}
                          </select>
                        ) : <button type="button" className="btn btn-quiet btn-xs" onClick={() => setPinFor(r.name)} title="Fijar este modelo como el motor de una intención"><Pin className="icon" style={{ width: 12, height: 12 }} />Promover</button>}
                      </td>
                    </tr>
                  )
                })}
                {modelRows.length === 0 && <tr><td colSpan={7} className="muted">Ollama no responde o no tiene modelos instalados.</td></tr>}
              </tbody>
            </table>
          </div>
          {restRows.length > 0 && (
            <button type="button" className="engine-more" onClick={() => setShowUnmeasured((v) => !v)} aria-expanded={showUnmeasured}>
              {showUnmeasured ? 'Hide models not measured' : `Show ${restRows.length} models not measured`}<small>the router does not pick them on its own</small>
            </button>
          )}
          {Object.entries(smoke).filter(([k]) => k === 'ollama').map(([k, r]) => <div key={k} className="probe-strip"><b className={r.ok ? 'sage' : 'coral'}>{r.ok ? 'Smoke OK' : 'Smoke falló'}</b><span>{r.latency_ms ?? 0} ms</span><span>JSON {r.json_ok ? 'ok' : 'no'}</span><span>Tools {r.tools_ok ? 'ok' : 'no'}</span>{r.error && <span className="coral">{r.error}</span>}</div>)}

          {(localGateways.length > 0 || scope === 'global') && (
            <>
              <h3 className="prov-sub">Gateways locales (127.0.0.1 / LAN)</h3>
              <div className="prov-grid">{localGateways.map((g) => <GatewayCard key={g.id} p={g} onUse={onUseModel} onSmoke={() => void doSmoke(g.id, g.default_model)} onPing={() => void doPing(g.id, g.base_url)} probe={smoke[g.id]} />)}
                {localGateways.length === 0 && <p className="muted mono">Sin gateways locales. Añade uno con «+ Custom» más abajo.</p>}</div>
            </>
          )}
        </section>

        {/* ── Nube ──────────────────────────────────────────────── */}
        <section className="card prov-section" aria-label="Nube y free tiers">
          <div className="card-head"><h2>Nube &amp; Free tiers</h2><span className="chip">{cloud.filter(isReady).length}/{cloud.length} con clave</span></div>
          <div className="prov-grid cloud">
            {cloud.map((p) => {
              const ok = isReady(p)
              const pg = ping[p.id], sm = smoke[p.id]
              return (
                <article key={p.id} className={`prov-card ${ok ? 'ready' : ''}`}>
                  <div className="prov-top">
                    <div><b>{p.name}</b><small className="mono muted">{p.kind ?? 'openai'} · {p.default_model}</small></div>
                    <span className={`pill-mini ${ok ? 'sage' : 'amber'}`}>{ok ? `listo (${p.key_source || 'env'})` : `falta ${p.api_key_env || 'KEY'}`}</span>
                  </div>
                  {(p.free_models ?? []).length > 0 && (
                    <div className="engine-chips" aria-label={`Modelos gratuitos de ${p.name}`}>
                      {(p.free_models ?? []).map((m) => (
                        <button key={m} type="button" className="mini-chip wrap" title={ok ? `Usar ${m} en Console` : 'Configura la clave para usarlo'} disabled={!ok} onClick={() => onUseModel(m, p.id)}><Zap className="icon" style={{ width: 10, height: 10 }} />{m}</button>
                      ))}
                    </div>
                  )}
                  {p.tier_hint && <small className="engine-tier">{p.tier_hint}</small>}
                  <div className="prov-actions">
                    <button type="button" className="btn btn-xs" onClick={() => { setKeyFor(keyFor === p.id ? null : p.id); setSecret('') }}><KeyRound className="icon" style={{ width: 12, height: 12 }} />Key</button>
                    <button type="button" className="btn btn-xs" disabled={busyId === `ping:${p.id}`} onClick={() => void doPing(p.id)}>Test</button>
                    <button type="button" className="btn btn-xs" disabled={!ok || busyId?.startsWith(`smoke:${p.id}`)} onClick={() => void doSmoke(p.id, p.default_model)}>Smoke</button>
                    {ok && <button type="button" className="btn btn-xs" onClick={() => onUseModel(p.default_model, p.id)}>Usar <ArrowRight className="icon" style={{ width: 12, height: 12 }} /></button>}
                  </div>
                  {keyFor === p.id && (
                    <form className="key-form" onSubmit={(e) => void saveKey(e, p.id)}>
                      <input className="field field-sm" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={`Pegar clave ${p.api_key_env || p.id.toUpperCase() + '_API_KEY'}`} aria-label={`Clave de ${p.name}`} />
                      <div className="inline-form">
                        <select className="select select-sm" value={storage} onChange={(e) => setStorage(e.target.value as typeof storage)} aria-label="Dónde guardar la clave">
                          <option value="env_local">.env.local del proyecto</option><option value="keyring">Keyring del sistema</option><option value="auto">Automático (keyring o global)</option>
                        </select>
                        <button type="submit" className="btn btn-primary btn-xs" disabled={busyId === `key:${p.id}` || !secret.trim()}>Guardar</button>
                      </div>
                    </form>
                  )}
                  {(pg || sm) && <div className="probe-strip">{pg && <span className={pg.ok ? 'sage' : 'coral'}>Test: {pg.message}{pg.latency_ms ? ` · ${pg.latency_ms} ms` : ''}</span>}{sm && <span className={sm.ok ? 'sage' : 'coral'}>Smoke: {sm.ok ? `OK · ${sm.latency_ms} ms · JSON ${sm.json_ok ? 'ok' : 'no'}` : sm.error || 'falló'}</span>}</div>}
                </article>
              )
            })}
            {remoteGateways.map((g) => <GatewayCard key={g.id} p={g} onUse={onUseModel} onSmoke={() => void doSmoke(g.id, g.default_model)} onPing={() => void doPing(g.id, g.base_url)} probe={smoke[g.id]} />)}
            <button type="button" className="prov-card prov-add" onClick={() => setAddingCustom((v) => !v)} aria-expanded={addingCustom}><Plus className="icon" style={{ width: 18, height: 18 }} /><b>+ Custom</b><small>Gateway compatible con OpenAI o Anthropic</small></button>
          </div>
          {addingCustom && (
            <form className="prov-form custom-form" onSubmit={addCustom}>
              <input className="field field-sm" required value={customForm.name} onChange={(e) => setCustomForm({ ...customForm, name: e.target.value })} placeholder="Nombre" />
              <input className="field field-sm" required value={customForm.base_url} onChange={(e) => setCustomForm({ ...customForm, base_url: e.target.value })} placeholder="https://gateway.ejemplo/v1" />
              <input className="field field-sm" value={customForm.api_key_env} onChange={(e) => setCustomForm({ ...customForm, api_key_env: e.target.value.toUpperCase() })} placeholder="GATEWAY_API_KEY" />
              <input className="field field-sm" value={customForm.models} onChange={(e) => setCustomForm({ ...customForm, models: e.target.value })} placeholder="modelos separados por coma" />
              <select className="select select-sm" value={customForm.kind} onChange={(e) => setCustomForm({ ...customForm, kind: e.target.value as 'openai' | 'anthropic' })}><option value="openai">OpenAI-compatible</option><option value="anthropic">Anthropic</option></select>
              <button type="submit" className="btn btn-primary btn-sm">Guardar gateway</button>
            </form>
          )}
        </section>

        {/* ── Agentes CLI ───────────────────────────────────────── */}
        {scope === 'project' && (
          <section className="card prov-section" aria-label="Agentes CLI">
            <div className="card-head"><h2>Agentes CLI locales</h2><span className="mono muted">se añaden al Board de este proyecto</span></div>
            <div className="prov-grid cloud">
              {(data?.clis ?? []).map((c) => {
                const free = c.free_models ?? []
                const sel = cliModel[c.id] ?? free[0] ?? ''
                return (
                  <article key={c.id} className={`prov-card ${c.installed ? 'ready' : ''}`}>
                    <div className="prov-top"><div><b><Terminal className="icon" style={{ width: 13, height: 13, marginRight: 6 }} />{c.label}</b><small className="mono muted">{c.command}</small></div>
                      <span className={`pill-mini ${c.installed ? 'sage' : ''}`}>{c.installed ? 'instalado' : 'no instalado'}</span></div>
                    {free.length > 0 && (
                      <label className="cli-model">Modelo gratuito
                        <select className="select select-sm" aria-label={`Modelo de ${c.label}`} value={sel} onChange={(e) => setCliModel((m) => ({ ...m, [c.id]: e.target.value }))}>{free.map((m) => <option key={m} value={m}>{m}</option>)}</select>
                      </label>
                    )}
                    <div className="prov-actions">
                      {c.added && <span className="pill-mini sage"><Check className="icon" style={{ width: 12, height: 12 }} />en Board</span>}
                      <button type="button" className="btn btn-xs" disabled={!c.installed} onClick={async () => { try { await api.addAgent({ kind: 'cli', id: c.id, model: free.length ? sel : undefined, name: c.added ? `${c.id}-${(sel || 'x').replace(/^.*\//, '').replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`.slice(0, 32) : undefined }); setNote(`${c.label} agregado al Board`); await load(); onAgentsChanged() } catch (ex: any) { setErr(ex.message) } }}>{c.added ? 'Agregar otro modelo' : 'Agregar al Board'}</button>
                    </div>
                  </article>
                )
              })}
              {(data?.api_agents ?? []).map((a) => <article key={a.name} className="prov-card ready"><div className="prov-top"><div><b>{a.name}</b><small className="mono muted">API · {a.provider} · {a.model}</small></div><span className="pill-mini sage">agente</span></div></article>)}
            </div>
          </section>
        )}

        {/* ── Router, failover ──────────────────────────────────── */}
        {scope === 'project' && (
          <section className="card prov-section" aria-label="Router y failover">
            <div className="card-head"><h2>Router por intención</h2><span className="mono muted">Auto Intent en Console y CLI; la respuesta fijada gana siempre</span></div>
            <div className="intents-grid">
              {INTENT_IDS.map((ik) => {
                const cur = intents[ik]
                const curVal = cur ? `${cur.provider}::${cur.model}` : ''
                return (
                  <div key={ik} className="intent-box">
                    <div className="intent-head"><span className="chip-steel">{ik}</span><span className="mono muted">{cur?.pinned ? 'manual' : 'auto'}</span></div>
                    <select className="select select-sm" aria-label={`Motor para ${ik}`} value={curVal} onChange={(e) => void pinIntent(ik, e.target.value)}>
                      {!choices.some((o) => o.value === curVal) && cur && <option value={curVal}>{cur.provider} · {cur.model}</option>}
                      {choices.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                    <small className="muted">{cur?.pinned ? 'fijado manualmente' : cur?.label || cur?.source || 'automático'}</small>
                  </div>
                )
              })}
            </div>
            <h3 className="prov-sub">Auto-Failover</h3>
            <div className="inline-form">
              <label className="check-inline"><input type="checkbox" checked={failover.enabled} onChange={(e) => void saveFailover({ ...failover, enabled: e.target.checked })} />Activar failover automático</label>
              <select className="select select-sm" aria-label="Estrategia de failover" value={failover.strategy} onChange={(e) => void saveFailover({ ...failover, strategy: e.target.value })}><option value="sequential">Secuencial (en orden)</option><option value="local_fallback">Local como respaldo</option></select>
              <select className="select select-sm" aria-label="Proveedor de respaldo" value={failover.fallback_target} onChange={(e) => void saveFailover({ ...failover, fallback_target: e.target.value })}>
                <option value="ollama">ollama</option>{cloud.filter(isReady).map((p) => <option key={p.id} value={p.id}>{p.id}</option>)}
              </select>
              <input className="field field-sm" style={{ width: 230 }} value={failover.fallback_model} onChange={(e) => setFailover({ ...failover, fallback_model: e.target.value })} onBlur={() => void saveFailover(failover)} placeholder="modelo de respaldo" aria-label="Modelo de respaldo" />
            </div>
          </section>
        )}

        {/* ── Comparador ────────────────────────────────────────── */}
        <section className="card prov-section" aria-label="Comparador lado a lado">
          <div className="card-head"><h2><GitCompareArrows className="icon" style={{ width: 17, height: 17 }} />Comparador lado a lado</h2><span className="mono muted">mismo prompt, dos motores; no cuenta como trabajo real</span></div>
          <textarea className="field" rows={2} value={cmpPrompt} onChange={(e) => setCmpPrompt(e.target.value)} maxLength={4000} aria-label="Prompt a comparar" />
          <div className="cmp-pick">
            <select className="select" value={cmpA} onChange={(e) => setCmpA(e.target.value)} aria-label="Motor A">{engines.map((e) => <option key={e.value} value={e.value}>{e.label}</option>)}</select>
            <span className="mono muted">vs</span>
            <select className="select" value={cmpB} onChange={(e) => setCmpB(e.target.value)} aria-label="Motor B">{engines.map((e) => <option key={e.value} value={e.value}>{e.label}</option>)}</select>
            <button type="button" className="btn btn-primary btn-sm" disabled={busyId === 'compare' || !cmpPrompt.trim() || engines.length < 2} onClick={() => void runCompare(false)}>{busyId === 'compare' ? 'Comparando…' : 'Comparar'}</button>
          </div>
          {cmpConfirm && (
            <div className="cmp-confirm" role="alertdialog" aria-label="Confirmar uso de la nube">
              <b>Esta comparación gasta cuota de nube</b>
              <span>Se enviará el prompt a {cmpCloudNames.join(' y ')}. Se registra en tu uso del proveedor y puede consumir su límite gratuito.</span>
              <div className="verdict-row"><button type="button" className="btn btn-amber btn-sm" onClick={() => void runCompare(true)}>Confirmar y comparar</button><button type="button" className="btn btn-quiet btn-sm" onClick={() => setCmpConfirm(false)}>Cancelar</button></div>
            </div>
          )}
          {cmpResults && (
            <div className="cmp-results">
              {cmpResults.map((r, i) => (
                <article key={i} className={`cmp-col ${r.ok ? '' : 'failed'}`}>
                  <header><b className="mono">{r.provider} · {r.model}</b><span className={`pill-mini ${r.ok ? 'sage' : 'coral'}`}>{r.ok ? 'respondió' : 'falló'}</span></header>
                  <div className="cmp-stats mono"><span>{r.latency_ms} ms</span><span>JSON {r.json_ok ? 'válido' : 'no'}</span><span>{r.tool_calls} tool calls</span><span>{r.prompt_tokens}↑ {r.completion_tokens}↓ tokens</span></div>
                  <pre className="delivered">{r.answer || r.error || '(sin respuesta)'}</pre>
                </article>
              ))}
            </div>
          )}
        </section>

        <Accordion id="providers-bench" title="Benchmarks medidos y reglas por tier" count={profiles.length} defaultOpen={false}>
          <div className="tbl-scroll"><table className="tbl compact"><thead><tr><th>Sistema</th><th className="num">Precisión</th><th className="num">Límite 95%</th><th className="num">Cobertura</th><th className="num">s/1000</th></tr></thead>
            <tbody>{profiles.map((p) => <tr key={p.system}><td className="mono">{p.system}</td><td className="num mono">{pct(p.precision, 1)}</td><td className="num mono">{pct(p.precision_lo, 1)}</td><td className="num mono">{pct(p.coverage, 0)}</td><td className="num mono">{p.seconds_per_1000}</td></tr>)}</tbody></table></div>
          <div className="tiers-compact">{tiers.map((t) => <span key={t.tier} className="tier-mini"><b>{t.tier}</b><span className="mono muted">≥ {t.needs}</span><span className="mono steel">{t.action === 'route' ? t.system : 'persona'}</span></span>)}</div>
        </Accordion>
      </div>
    </div>
  )
}

const GatewayCard: React.FC<{ p: ProviderItem; probe?: { ok: boolean; latency_ms?: number; error?: string }; onUse: (m: string, p?: string) => void; onSmoke: () => void; onPing: () => void }> = ({ p, probe, onUse, onSmoke, onPing }) => (
  <article className={`prov-card ${isReady(p) ? 'ready' : ''}`}>
    <div className="prov-top"><div><b>{p.name}</b><small className="mono muted">{p.base_url}</small></div><span className={`pill-mini ${isReady(p) ? 'sage' : 'amber'}`}>{isReady(p) ? 'listo' : `falta ${p.api_key_env || 'KEY'}`}</span></div>
    <small className="mono muted">{p.default_model || (p.models ?? [])[0] || 'sin modelo'}</small>
    <div className="prov-actions"><button type="button" className="btn btn-xs" onClick={onPing}>Test</button><button type="button" className="btn btn-xs" onClick={onSmoke}>Smoke</button>{isReady(p) && p.default_model && <button type="button" className="btn btn-xs" onClick={() => onUse(p.default_model, p.id)}>Usar</button>}</div>
    {probe && <div className="probe-strip"><span className={probe.ok ? 'sage' : 'coral'}>{probe.ok ? `Smoke OK · ${probe.latency_ms} ms` : probe.error || 'falló'}</span></div>}
  </article>
)
