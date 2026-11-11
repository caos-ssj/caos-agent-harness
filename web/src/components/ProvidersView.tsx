import React, { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Check, Plus, X } from 'lucide-react'
import { api, Agent, ModelProfile, ProvidersResponse, RouterTier } from '../api'
import { baseName, clears, gb, isEmbedding, variantsOf } from '../models'

const STATUS: Record<string, string> = { online: 'Running', offline: 'Not reachable', key_present: 'Key found', missing_key: 'No key', ready: 'Recorded' }
const pct = (n: number, d = 1) => `${(n * 100).toFixed(d)}%`
const LO = 0.6
const at = (x: number) => `${Math.max(0, Math.min(1, (x - LO) / (1 - LO))) * 100}%`

const Interval: React.FC<{ v: ModelProfile | undefined; label: string }> = ({ v, label }) => v ? (
  <div className="cell-int">
    <span className="mini-range" role="img" aria-label={`${label}: precision ${pct(v.precision)}, at least ${pct(v.precision_lo)}`}><i style={{ left: at(v.precision_lo), width: `calc(${at(v.precision)} - ${at(v.precision_lo)})` }} /><b style={{ left: at(v.precision) }} /></span>
    <span><b>{pct(v.precision)}</b> <span className="mute">≥ {pct(v.precision_lo)}</span></span>
  </div>
) : <div className="cell-int"><span className="mute" aria-label={`${label}: not measured`}>not measured</span></div>

interface ProvidersViewProps { agents: Agent[]; profiles: ModelProfile[]; tiers: RouterTier[]; onUseModel: (model: string) => void }

/* Providers: where models come from, in the order a person decides. First the verdict (is Ollama up, how many models,
   which costs of error have a model that clears them); then the models that were measured, with what was measured and
   who runs them; then the ones that were not; then the providers that only say whether a key exists. A key is never
   typed, stored or shown: a provider takes the NAME of the variable that holds one. */
export const ProvidersView: React.FC<ProvidersViewProps> = ({ agents, profiles, tiers, onUseModel }) => {
  const [data, setData] = useState<ProvidersResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ name: '', base_url: '', api_key_env: '', models: '' })
  const [msg, setMsg] = useState<string | null>(null)

  const load = () => api.getProviders().then((r) => { setData(r); setError(null) }).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const ollama = data?.providers.find((p) => p.id === 'ollama')
  const others = data?.providers.filter((p) => p.id !== 'ollama') ?? []
  const rows = useMemo(() => {
    const details = new Map((ollama?.model_details ?? []).map((d) => [d.name, d]))
    return (ollama?.models ?? []).filter((m) => !isEmbedding(m)).map((m) => {
      const variants = variantsOf(m, profiles)
      const best = [...variants].sort((a, b) => b.precision_lo - a.precision_lo)[0]
      return { name: m, d: details.get(m), plain: variants.find((v) => !v.system.includes('+')), rules: variants.find((v) => v.system.includes('+')), best, runs: agents.filter((a) => a.system && baseName(a.system) === baseName(m)) }
    })
  }, [ollama, profiles, agents])
  const measured = rows.filter((r) => r.best).sort((a, b) => b.best!.precision_lo - a.best!.precision_lo)
  const unmeasured = rows.filter((r) => !r.best).sort((a, b) => a.name.localeCompare(b.name))
  const covered = tiers.map((t) => ({ tier: t.tier, needs: t.needs, by: measured.filter((r) => clears(r.best!, [t]).length).length }))

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.name.trim() || !form.base_url.trim()) return
    try {
      const models = form.models.split(',').map((m) => m.trim()).filter(Boolean)
      await api.saveCustomProvider({ id: `custom-${Date.now()}`, name: form.name.trim(), base_url: form.base_url.trim(), api_key_env: form.api_key_env.trim() || undefined, models } as any)
      setForm({ name: '', base_url: '', api_key_env: '', models: '' })
      setAdding(false)
      setMsg('Recorded. It is listed here; the console and the agents still run on Ollama.')
      load()
    } catch (err: any) { setError(err.message || 'The provider was not saved.') }
  }

  return (
    <>
      {error && <p className="verdict-err" role="alert">{error}</p>}

      <div className="tiles">
        <div className="card tile">
          <div className="tile-top"><span>Ollama, on this machine</span></div>
          <div className="tile-value" style={{ fontSize: 30 }}>{ollama ? STATUS[ollama.status] ?? ollama.status : '…'}</div>
          <div className="tile-sub">The only provider that runs work here: the Console and every agent use it.</div>
          <img className="tile-plate" src="/art/local.svg" alt="" aria-hidden="true" />
        </div>
        <div className="card tile">
          <div className="tile-top"><span>Installed models</span></div>
          <div className="tile-value">{rows.length}</div>
          <div className="segbar" aria-hidden="true">{measured.length > 0 && <i className="c-ink" style={{ flex: measured.length }} />}{unmeasured.length > 0 && <i className="c-edge" style={{ flex: unmeasured.length }} />}</div>
          <div className="legend"><span><i className="c-ink" />{measured.length} measured</span><span><i className="c-edge" />{unmeasured.length} not measured</span><span>{rows.filter((r) => r.runs.length).length} run by an agent</span></div>
        </div>
        <div className="card tile">
          <div className="tile-top"><span>Costs of error covered</span></div>
          <div className="cover">
            {covered.map((c) => <div key={c.tier} className={c.by ? 'yes' : 'no'}><span className="cv-name">{c.tier}</span><span className="cv-state">{c.by ? <><Check className="icon" style={{ width: 15, height: 15 }} aria-hidden="true" />{c.by} model{c.by > 1 ? 's' : ''}</> : <><X className="icon" style={{ width: 15, height: 15 }} aria-hidden="true" />a person</>}</span></div>)}
          </div>
          <div className="tile-src">an installed, measured model clears the bar</div>
        </div>
      </div>

      <div className="section-title"><h2>Measured models</h2><span className="src">from <code>make benchmark</code></span></div>
      <p className="lead">These were run over the same labelled set. “Precise” is what they got right; “at least” is the lower end of the 95 % interval, which is what the router decides on. The <b style={{ color: 'var(--ink)' }}>bar</b> is the interval.</p>
      <div className="card" style={{ padding: '4px 22px 10px', overflowX: 'auto' }}>
        <table className="tbl">
          <thead><tr><th>Model</th><th>Alone</th><th>Behind the rules</th><th>Clears the bar for</th><th>Run by</th><th /></tr></thead>
          <tbody>
            {measured.map((r) => (
              <tr key={r.name}>
                <td className="m">{r.name}<small>{[r.d?.parameter_size, r.d?.quantization, gb(r.d?.size)].filter(Boolean).join(' · ')}</small></td>
                <td><Interval v={r.plain} label="alone" /></td>
                <td><Interval v={r.rules} label="with rules" /></td>
                <td>{clears(r.best!, tiers).length ? <div className="chips">{clears(r.best!, tiers).map((t) => <span key={t} className="chip">{t}</span>)}</div> : <span className="mute">no tier</span>}</td>
                <td>{r.runs.length ? <div className="chips">{r.runs.map((a) => <span key={a.name} className="chip">{a.name}</span>)}</div> : <span className="mute">no agent</span>}</td>
                <td style={{ textAlign: 'right' }}><button type="button" className="btn btn-sm" onClick={() => onUseModel(r.name)}>Use in Console<ArrowRight className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" /></button></td>
              </tr>
            ))}
            {measured.length === 0 && <tr><td colSpan={6} className="mute" style={{ padding: '16px 0' }}>None of the installed models has a benchmark yet.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="section-title"><h2>Installed, not measured</h2></div>
      <p className="lead">Fine to talk to in the Console. The router will never choose them, because nothing says how often they are right. To measure one, run <code className="mono" style={{ color: 'var(--ink)' }}>make benchmark MODELS="name"</code> from a checkout.</p>
      <div className="plain-list">
        {unmeasured.map((r) => (
          <div key={r.name} className="plain-row"><b className="mono">{r.name}</b><span className="mute">{[r.d?.parameter_size, gb(r.d?.size)].filter(Boolean).join(' · ')}</span><button type="button" className="btn btn-quiet btn-sm" onClick={() => onUseModel(r.name)}>Use in Console</button></div>
        ))}
        {unmeasured.length === 0 && <p className="mute">Every installed model has been measured.</p>}
      </div>

      <div className="section-title"><h2>Other providers</h2><img className="inline-plate" src="/art/cloud.svg" alt="" aria-hidden="true" /></div>
      <p className="lead">Listed only to say whether their key is in the environment. They are not wired to the Console or the agents.</p>
      <div className="card" style={{ padding: '4px 22px 6px', overflowX: 'auto' }}>
        <table className="tbl">
          <thead><tr><th>Provider</th><th>Key</th><th>Reads the key from</th></tr></thead>
          <tbody>
            {others.map((p) => <tr key={p.id}><td className="m" style={{ fontFamily: 'var(--serif)', fontSize: 18 }}>{p.name}{p.models.length > 0 && <small>{p.models.join(', ')}</small>}</td><td><span className="status"><span className="pip" aria-hidden="true" />{STATUS[p.status] ?? p.status}</span></td><td className="m">{p.api_key_env ? `$${p.api_key_env}` : '—'}</td></tr>)}
          </tbody>
        </table>
      </div>
      {msg && <p role="status" style={{ margin: '12px 0 0', color: 'var(--ink-2)' }}>{msg}</p>}
      {!adding ? (
        <button type="button" className="btn" onClick={() => setAdding(true)} style={{ marginTop: 14 }}><Plus className="icon" aria-hidden="true" />Record a provider</button>
      ) : (
        <form onSubmit={save} aria-label="Record a provider" className="card form-card">
          <div className="form-grid">
            <label>Name<input className="field" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Gateway" /></label>
            <label>Base URL<input className="field" required value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://gateway.example/v1" /></label>
            <label>Variable that holds the key<input className="field" value={form.api_key_env} onChange={(e) => setForm({ ...form, api_key_env: e.target.value.toUpperCase() })} placeholder="GATEWAY_API_KEY" /></label>
            <label>Models, comma separated<input className="field" value={form.models} onChange={(e) => setForm({ ...form, models: e.target.value })} placeholder="model-a, model-b" /></label>
          </div>
          <div className="verdict-row"><button type="submit" className="btn btn-primary">Record</button><button type="button" className="btn btn-quiet" onClick={() => setAdding(false)}>Cancel</button></div>
        </form>
      )}
    </>
  )
}
