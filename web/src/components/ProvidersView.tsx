import React, { useEffect, useState } from 'react'
import { api, ProvidersResponse, ProviderItem } from '../api'
import {
  Server,
  Cpu,
  RefreshCw,
  ArrowRightLeft,
  PlusCircle,
  Globe,
  CheckCircle2,
} from 'lucide-react'

export const ProvidersView: React.FC = () => {
  const [data, setData] = useState<ProvidersResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedBackupModel, setSelectedBackupModel] = useState('qwen2.5:7b')
  const [saveMsg, setSaveMsg] = useState<string | null>(null)

  // Formulario de nuevo proveedor personalizado
  const [showAddForm, setShowAddForm] = useState(false)
  const [customName, setCustomName] = useState('')
  const [customBaseUrl, setCustomBaseUrl] = useState('')
  const [customApiKey, setCustomApiKey] = useState('')
  const [customModels, setCustomModels] = useState('')
  const [savingCustom, setSavingCustom] = useState(false)

  const fetchProviders = () => {
    setLoading(true)
    setError(null)
    api
      .getProviders()
      .then((res) => {
        setData(res)
        if (res.active_failover?.fallback_model) {
          setSelectedBackupModel(res.active_failover.fallback_model)
        }
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }

  useEffect(() => {
    fetchProviders()
  }, [])

  const handleSaveFailover = async (newModel: string) => {
    setSelectedBackupModel(newModel)
    try {
      await api.saveFailover({
        enabled: true,
        strategy: 'auto_fallback_to_local',
        fallback_target: 'ollama',
        fallback_model: newModel,
        description: 'Records the local model to fall back to. Automatic failover is not implemented.',
      })
      setSaveMsg(`Fallback model recorded: ${newModel}`)
      setTimeout(() => setSaveMsg(null), 3000)
    } catch (err: any) {
      console.error(err)
    }
  }

  const handleAddCustomProvider = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!customName.trim() || !customBaseUrl.trim()) return

    setSavingCustom(true)
    try {
      const modelsList = customModels
        .split(',')
        .map((m) => m.trim())
        .filter(Boolean)

      const payload: Partial<ProviderItem> = {
        id: `custom-${Date.now()}`,
        name: customName.trim(),
        type: 'custom',
        status: 'ready',
        quota: 'personal_endpoint',
        cost_per_m: 'Personalizado',
        base_url: customBaseUrl.trim(),
        api_key_env: customApiKey.trim() || undefined,
        models: modelsList.length > 0 ? modelsList : ['default-model'],
        default_model: modelsList[0] || 'default-model',
        description: `Endpoint compatible OpenAI en ${customBaseUrl.trim()}`,
        fallback_to: 'ollama',
      }

      await api.saveCustomProvider(payload)
      setCustomName('')
      setCustomBaseUrl('')
      setCustomApiKey('')
      setCustomModels('')
      setShowAddForm(false)
      setSaveMsg('Provider saved. It is listed here; the console still runs Ollama only.')
      fetchProviders()
      setTimeout(() => setSaveMsg(null), 4000)
    } catch (err: any) {
      setError(err.message || 'The provider was not saved')
    } finally {
      setSavingCustom(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* 1. Cabecera */}
      <div className="border border-caos-borde bg-caos-tinta p-6 shadow-xl">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-caos-borde pb-4">
          <div className="flex items-center gap-3">
            <Server className="w-8 h-8 text-caos-ambar" />
            <div>
              <h2 className="text-xl font-bold text-caos-hueso tracking-wide">
                Providers
              </h2>
              <p className="text-sm text-caos-gris mt-0.5">
                What can run here. The console and the board agents use the local Ollama service; other providers are listed with the state of their key and are not wired yet.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowAddForm(!showAddForm)}
              className="flex items-center gap-2 px-3.5 py-2 border border-caos-ambar bg-caos-ambar text-caos-negro text-xs uppercase font-bold tracking-wider hover:bg-caos-champan transition-all cursor-pointer shadow-md"
            >
              <PlusCircle className="w-4 h-4" />
              <span>{showAddForm ? 'Close' : 'Add a provider'}</span>
            </button>

            <button
              onClick={fetchProviders}
              disabled={loading}
              className="flex items-center gap-2 px-3.5 py-2 border border-caos-borde bg-caos-negro text-caos-gris hover:text-caos-hueso text-xs uppercase font-semibold transition-colors cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-caos-ambar' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Formulario para Agregar Proveedor / Endpoint Personalizado */}
        {showAddForm && (
          <form
            onSubmit={handleAddCustomProvider}
            className="mt-5 p-4 border border-caos-ambar bg-caos-negro space-y-4 animate-in fade-in duration-150"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-caos-ambar uppercase tracking-wider">
              <Globe className="w-4 h-4" />
              <span>Conectar Nuevo Proveedor o Endpoint Compatible con OpenAI</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-caos-gris mb-1">
                  Name:
                </label>
                <input
                  type="text"
                  required
                  placeholder="Ej: OpenRouter, vLLM Local, Groq, Together AI"
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  className="w-full p-2.5 bg-caos-tinta border border-caos-borde text-caos-hueso text-xs focus:border-caos-ambar focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-caos-gris mb-1">
                  URL Base del Endpoint:
                </label>
                <input
                  type="url"
                  required
                  placeholder="https://openrouter.ai/api/v1 o http://localhost:8000/v1"
                  value={customBaseUrl}
                  onChange={(e) => setCustomBaseUrl(e.target.value)}
                  className="w-full p-2.5 bg-caos-tinta border border-caos-borde text-caos-hueso text-xs font-mono focus:border-caos-ambar focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-caos-gris mb-1">
                  Environment variable that holds the key (the key itself is never stored; optional):
                </label>
                <input
                  type="text"
                  placeholder="OPENROUTER_API_KEY"
                  value={customApiKey}
                  onChange={(e) => setCustomApiKey(e.target.value)}
                  className="w-full p-2.5 bg-caos-tinta border border-caos-borde text-caos-hueso text-xs font-mono focus:border-caos-ambar focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-caos-gris mb-1">
                  Models (comma separated):
                </label>
                <input
                  type="text"
                  placeholder="deepseek/deepseek-r1, meta-llama/llama-3.3-70b-instruct"
                  value={customModels}
                  onChange={(e) => setCustomModels(e.target.value)}
                  className="w-full p-2.5 bg-caos-tinta border border-caos-borde text-caos-hueso text-xs font-mono focus:border-caos-ambar focus:outline-none"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowAddForm(false)}
                className="px-3.5 py-1.5 border border-caos-borde text-xs text-caos-tenue hover:text-caos-hueso cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={savingCustom}
                className="px-4 py-1.5 bg-caos-ambar text-caos-negro text-xs uppercase font-bold hover:bg-caos-champan transition-all cursor-pointer"
              >
                {savingCustom ? 'Saving…' : 'Save provider'}
              </button>
            </div>
          </form>
        )}

        {/* 2. Panel de Conmutación Automática por Cuota (Failover) */}
        <div className="mt-5 p-4 border border-caos-ambar bg-caos-negro">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div className="flex items-start gap-3">
              <ArrowRightLeft className="w-5 h-5 text-caos-ambar shrink-0 mt-0.5" />
              <div>
                <div className="text-sm font-bold text-caos-hueso flex items-center gap-2">
                  <span>Fallback model</span>
                  <span className="px-2 py-0.2 bg-caos-greenMuted border border-caos-greenText text-caos-greenText text-[10px] uppercase font-bold">
                    No implementado
                  </span>
                </div>
                <p className="text-xs text-caos-tenue mt-1 leading-relaxed max-w-2xl">
                  The console runs local Ollama models. Cloud connections and automatic failover are not implemented.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <span className="text-xs text-caos-gris font-medium">Preferencia guardada (sin efecto):</span>
              <select
                value={selectedBackupModel}
                onChange={(e) => handleSaveFailover(e.target.value)}
                className="p-2 bg-caos-tinta border border-caos-ambar text-caos-hueso text-xs font-mono focus:outline-none cursor-pointer"
              >
                <option value="qwen2.5:7b">Ollama: qwen2.5:7b (Recomendado)</option>
                <option value="llama3.2:3b">Ollama: llama3.2:3b</option>
                <option value="qwen3.5:4b">Ollama: qwen3.5:4b</option>
              </select>
            </div>
          </div>

          {saveMsg && (
            <div className="mt-2 text-xs text-caos-greenText font-mono flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>{saveMsg}</span>
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="p-4 border border-caos-redText bg-caos-redMuted text-caos-redText text-xs font-semibold">
          {error}
        </div>
      )}

      {/* 3. Grid de Proveedores */}
      {data && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {data.providers.map((prov) => {
            const isLocal = prov.type === 'local'
            const isOnline = prov.status === 'online' || prov.status === 'ready'

            return (
              <div
                key={prov.id}
                className="border border-caos-borde bg-caos-tinta p-5 flex flex-col justify-between shadow-md"
              >
                <div>
                  <div className="flex items-center justify-between border-b border-caos-borde pb-3 mb-3">
                    <div className="flex items-center gap-2.5">
                      {isLocal ? (
                        <Cpu className="w-5 h-5 text-caos-ambar" />
                      ) : (
                        <Server className="w-5 h-5 text-caos-champan" />
                      )}
                      <div>
                        <h3 className="text-sm font-bold text-caos-hueso">{prov.name}</h3>
                        <span className="text-[11px] text-caos-tenue font-mono">{prov.cost_per_m}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 text-xs font-medium">
                      <span
                        className={`w-2 h-2 rounded-full ${
                          isOnline ? 'bg-caos-greenText' : 'bg-caos-redText'
                        }`}
                      />
                      <span className={isOnline ? 'text-caos-greenText font-semibold' : 'text-caos-redText'}>
                        {prov.status === 'online'
                          ? 'Conectado (Local)'
                          : prov.status === 'ready'
                          ? 'Listo / Activo'
                          : 'Clave API Pendiente'}
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-caos-gris leading-relaxed mb-4">
                    {prov.description}
                  </p>

                  {/* Lista de Modelos Disponibles */}
                  <div className="space-y-1.5 mb-4">
                    <label className="block text-[11px] font-bold text-caos-tenue uppercase tracking-wider">
                      Models:
                    </label>
                    <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto">
                      {prov.models.map((m) => (
                        <span
                          key={m}
                          className="px-2 py-0.5 border border-caos-borde bg-caos-negro text-caos-hueso font-mono text-xs"
                        >
                          {m}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Pie de tarjeta */}
                <div className="pt-3 border-t border-caos-borde flex items-center justify-between text-xs font-mono">
                  <div className="text-caos-tenue">
                    Cuota: <strong className="text-caos-hueso">{prov.quota}</strong>
                  </div>
                  {prov.fallback_to && (
                    <div className="text-caos-champan flex items-center gap-1 text-[11px]">
                      <span>Respaldo en:</span>
                      <strong className="underline">@{prov.fallback_to}</strong>
                    </div>
                  )}
                  {isLocal && (
                    <span className="text-caos-greenText text-[11px] font-bold">
                      ✓ Respaldo de Emergencia CAOS
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
