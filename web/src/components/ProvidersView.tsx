import React, { useEffect, useState } from 'react'
import { api, ProvidersResponse } from '../api'

const STATUS: Record<string, string> = { online: 'running', offline: 'not reachable', key_present: 'key in environment', missing_key: 'no key in environment', ready: 'recorded' }

/* Only Ollama runs work here; the rest are listed with whether their key is present in the environment. Keys are
   never typed, stored or shown: a provider takes the NAME of the variable that holds one. */
export const ProvidersView: React.FC = () => {
  const [data, setData] = useState<ProvidersResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ name: '', base_url: '', api_key_env: '', models: '' })
  const [msg, setMsg] = useState<string | null>(null)

  const load = () => api.getProviders().then((r) => { setData(r); setError(null) }).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

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
      <div className="prov-grid">
        {data?.providers.map((p) => (
          <article key={p.id} className="prov">
            <header>
              <h3>{p.name}</h3>
              <span className={`status ${p.status === 'online' ? 'on' : ''}`}><span className={`pip ${p.status === 'online' ? 'on' : ''}`} aria-hidden="true" />{STATUS[p.status] ?? p.status}</span>
            </header>
            <p>{p.description}</p>
            {p.models.length > 0 && <div className="chips" aria-label={`Models of ${p.name}`}>{p.models.slice(0, 14).map((m) => <span key={m} className="chip">{m}</span>)}{p.models.length > 14 && <span className="chip">+{p.models.length - 14}</span>}</div>}
            {p.api_key_env && <span className="mono" style={{ fontSize: 12, color: 'var(--ink-3)' }}>reads ${p.api_key_env}</span>}
          </article>
        ))}
      </div>
      {msg && <p className="muted" role="status" style={{ margin: '0 0 10px', color: 'var(--ink-2)' }}>{msg}</p>}
      {!adding ? (
        <button type="button" className="btn btn-sm" onClick={() => setAdding(true)}>Record a provider</button>
      ) : (
        <form onSubmit={save} aria-label="Record a provider">
          <div className="form-grid">
            <label>Name<input className="field" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Gateway" /></label>
            <label>Base URL<input className="field" required value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://gateway.example/v1" /></label>
            <label>Variable that holds the key<input className="field" value={form.api_key_env} onChange={(e) => setForm({ ...form, api_key_env: e.target.value.toUpperCase() })} placeholder="GATEWAY_API_KEY" /></label>
            <label>Models, comma separated<input className="field" value={form.models} onChange={(e) => setForm({ ...form, models: e.target.value })} placeholder="model-a, model-b" /></label>
          </div>
          <div className="verdict-row"><button type="submit" className="btn btn-primary btn-sm">Record</button><button type="button" className="btn btn-quiet btn-sm" onClick={() => setAdding(false)}>Cancel</button></div>
        </form>
      )}
    </>
  )
}
