import React, { useEffect, useState } from 'react'
import { api, RouterResponse, StateResponse } from '../api'
import { BarChart3, TrendingUp, DollarSign, ShieldCheck, Cpu, CheckCircle2 } from 'lucide-react'

interface StatsViewProps {
  state: StateResponse | null
}

export const StatsView: React.FC<StatsViewProps> = ({ state }) => {
  const [routerData, setRouterData] = useState<RouterResponse | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    api
      .getRouter()
      .then((res) => {
        setRouterData(res)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const stats = state?.stats
  // Every figure here comes from the board or from a report a command wrote. No estimates.
  const total = stats?.tasks ?? 0
  const pending = stats?.by_status?.pending ?? 0
  const sending = stats?.by_status?.sending ?? 0
  const okCount = stats?.review?.ok ?? 0
  const returned = stats?.returned_at_least_once ?? 0
  const openReview = (stats?.review?.unreviewed ?? 0) + (stats?.review?.verify ?? 0)
  const closed = okCount + (stats?.review?.superseded ?? 0)
  const mutation = state?.quality?.mutation

  return (
    <div className="space-y-6">
      {/* Cabecera */}
      <div className="border border-caos-borde bg-caos-tinta p-6 shadow-xl">
        <div className="flex items-center gap-3 border-b border-caos-borde pb-4">
          <BarChart3 className="w-8 h-8 text-caos-ambar" />
          <div>
            <h2 className="text-xl font-bold text-caos-hueso tracking-wide">
              Measured
            </h2>
            <p className="text-sm text-caos-gris mt-0.5">
              What this project’s board says, and what the repository’s reports measured. Nothing here is an estimate.
            </p>
          </div>
        </div>

        {/* Tarjetas de Métricas Principales */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-5">
          {/* Total Encargos */}
          <div className="p-4 border border-caos-borde bg-caos-negro flex flex-col justify-between">
            <div className="flex items-center justify-between text-xs text-caos-tenue uppercase font-semibold">
              <span>Tasks</span>
              <Cpu className="w-4 h-4 text-caos-champan" />
            </div>
            <div className="text-3xl font-bold text-caos-hueso mt-2 font-mono">{total}</div>
            <div className="text-xs text-caos-gris mt-1">
              {pending} pending · {sending} sending
            </div>
          </div>

          {/* Tasa de Aprobación Humana */}
          <div className="p-4 border border-caos-borde bg-caos-negro flex flex-col justify-between">
            <div className="flex items-center justify-between text-xs text-caos-tenue uppercase font-semibold">
              <span>Closed with a verdict</span>
              <CheckCircle2 className="w-4 h-4 text-caos-greenText" />
            </div>
            <div className="text-3xl font-bold text-caos-greenText mt-2 font-mono">
              {closed}
            </div>
            <div className="text-xs text-caos-gris mt-1">
              {okCount} accepted · {returned} returned at least once
            </div>
          </div>

          {/* Ahorro Estimado */}
          <div className="p-4 border border-caos-borde bg-caos-negro flex flex-col justify-between">
            <div className="flex items-center justify-between text-xs text-caos-tenue uppercase font-semibold">
              <span>Waiting for review</span>
              <DollarSign className="w-4 h-4 text-caos-ambar hidden" />
            </div>
            <div className="text-3xl font-bold text-caos-ambar mt-2 font-mono">
              {openReview}
            </div>
            <div className="text-xs text-caos-tenue mt-1">
              sent or delivered, no closing verdict yet
            </div>
          </div>

          {/* Precisión de la Guarda */}
          <div className="p-4 border border-caos-borde bg-caos-negro flex flex-col justify-between">
            <div className="flex items-center justify-between text-xs text-caos-tenue uppercase font-semibold">
              <span>Mutation testing</span>
              <ShieldCheck className="w-4 h-4 text-caos-greenText" />
            </div>
            <div className="text-3xl font-bold text-caos-hueso mt-2 font-mono">
              {mutation ? `${mutation.caught} / ${mutation.total}` : '—'}
            </div>
            <div className="text-xs text-caos-gris mt-1">
              {mutation ? `injected faults caught · ${mutation.source}` : 'no report yet: run make mutation'}
            </div>
          </div>
        </div>
      </div>

      {/* Tabla Empírica de Modelos y Latencias */}
      <div className="border border-caos-borde bg-caos-tinta p-6 shadow-xl space-y-4">
        <div className="border-b border-caos-borde pb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-caos-champan" />
            <h3 className="text-base font-bold text-caos-hueso">
              Measured systems
            </h3>
          </div>
          <span className="text-xs text-caos-tenue font-mono">
            From <code className="text-caos-hueso">make benchmark</code>
          </span>
        </div>

        {loading && (
          <div className="py-8 text-center text-sm text-caos-tenue">
            Loading the benchmark…
          </div>
        )}

        {routerData && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs divide-y divide-caos-borde">
              <thead className="bg-caos-negro text-caos-tenue uppercase font-mono text-[11px]">
                <tr>
                  <th className="px-4 py-3">System</th>
                  <th className="px-4 py-3">Precision</th>
                  <th className="px-4 py-3">Lower bound (95 % CI)</th>
                  <th className="px-4 py-3">Coverage</th>
                  <th className="px-4 py-3">Seconds per 1,000</th>
                  <th className="px-4 py-3">Tokens per 1,000</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-caos-borde font-mono">
                {routerData.profiles.map((p) => (
                  <tr key={p.system} className="hover:bg-caos-tintaElevada transition-colors">
                    <td className="px-4 py-3 font-bold text-caos-ambar">
                      {p.system}
                    </td>
                    <td className="px-4 py-3 text-caos-hueso">
                      {(p.precision * 100).toFixed(1)}%
                    </td>
                    <td className="px-4 py-3 text-caos-greenText font-bold">
                      {(p.precision_lo * 100).toFixed(1)}%
                    </td>
                    <td className="px-4 py-3 text-caos-champan">
                      {(p.coverage * 100).toFixed(0)}%
                    </td>
                    <td className="px-4 py-3 text-caos-gris">
                      {p.seconds_per_1000.toLocaleString("en-US")} s
                    </td>
                    <td className="px-4 py-3 text-caos-tenue">
                      {p.tokens_per_1000 != null ? `${p.tokens_per_1000.toLocaleString("en-US")} tokens` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="p-3.5 bg-caos-negro border border-caos-borde text-xs text-caos-tenue leading-relaxed">
          <strong className="text-caos-hueso font-mono">How the router chooses:</strong> by the lower bound of the 95 % interval of precision, never by model name. It takes the cheapest measured system that reaches what the cost of an error requires; when none does, the task goes to a person.
        </div>
      </div>
    </div>
  )
}
