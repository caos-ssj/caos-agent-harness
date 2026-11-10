import React, { useEffect, useState } from 'react'
import { api, RouterResponse } from '../api'
import { Cpu, Terminal, CheckCircle2, User, RefreshCw } from 'lucide-react'

export const RouterView: React.FC = () => {
  const [data, setData] = useState<RouterResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchRouter = () => {
    setLoading(true)
    setError(null)
    api
      .getRouter()
      .then((res) => {
        setData(res)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }

  useEffect(() => {
    fetchRouter()
  }, [])

  return (
    <div className="space-y-8">
      {/* Overview Card */}
      <div className="border border-caos-borde bg-caos-tinta p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-caos-borde pb-4">
          <div className="flex items-center gap-3">
            <img src="/art/router.svg" alt="Router" className="w-10 h-10 opacity-80" />
            <div>
              <h2 className="font-brand text-2xl text-caos-hueso tracking-wide">
                Router by Cost of Error
              </h2>
              <p className="font-serif text-sm text-caos-champan">
                Routing agents by lower bound of 95% confidence interval (IC95) vs. measured inference cost.
              </p>
            </div>
          </div>
          <button
            onClick={fetchRouter}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 border border-caos-borde bg-caos-negro text-caos-gris hover:text-caos-hueso font-mono text-xs uppercase tracking-wider transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-caos-ambar' : ''}`} />
            <span>Reload Profiles</span>
          </button>
        </div>

        {/* Command origin rule */}
        <div className="mt-4 flex items-center gap-2 font-mono text-xs text-caos-tenue bg-caos-negro p-3 border border-caos-borde">
          <Terminal className="w-4 h-4 text-caos-ambar shrink-0" />
          <span>
            Numbers verified via:{' '}
            <code className="text-caos-hueso font-bold">make route</code> and{' '}
            <code className="text-caos-hueso font-bold">make benchmark</code> (reports under <code className="text-caos-champan">reports/validation/</code>)
          </span>
        </div>
      </div>

      {error && (
        <div className="p-4 border border-caos-redText bg-caos-redMuted text-caos-redText font-mono text-xs">
          {error}
        </div>
      )}

      {loading && !data && (
        <div className="py-12 text-center font-mono text-xs text-caos-tenue">
          Loading router tiers and model profiles...
        </div>
      )}

      {data && (
        <>
          {/* Tiers Table */}
          <div className="border border-caos-borde bg-caos-tinta">
            <div className="px-6 py-4 border-b border-caos-borde bg-caos-negro flex items-center justify-between">
              <div className="font-mono text-xs uppercase tracking-wider text-caos-ambar font-semibold flex items-center gap-2">
                <Cpu className="w-4 h-4" />
                <span>Error-Cost Risk Tiers (`router.json`)</span>
              </div>
              <span className="font-mono text-[11px] text-caos-tenue">
                Threshold: precision_lo &ge; needs
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono text-xs divide-y divide-caos-borde">
                <thead className="bg-caos-negro text-caos-tenue uppercase text-[10px]">
                  <tr>
                    <th className="px-6 py-3">Tier</th>
                    <th className="px-6 py-3">Required Precision</th>
                    <th className="px-6 py-3">Router Action</th>
                    <th className="px-6 py-3">Assigned System</th>
                    <th className="px-6 py-3">Target Agent</th>
                    <th className="px-6 py-3">Policy Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-caos-borde">
                  {data.tiers.map((t) => {
                    const isHuman = t.action === 'human_review'
                    return (
                      <tr key={t.tier} className="hover:bg-caos-tintaElevada transition-colors">
                        <td className="px-6 py-3 font-bold text-caos-hueso uppercase">
                          {t.tier}
                        </td>
                        <td className="px-6 py-3 text-caos-champan tabular-nums">
                          {(t.needs * 100).toFixed(0)}%
                        </td>
                        <td className="px-6 py-3">
                          {isHuman ? (
                            <span className="inline-flex items-center gap-1 text-caos-ambar bg-caos-ambarMuted border border-caos-ambar px-2 py-0.5 text-[10px] uppercase font-bold">
                              <User className="w-3 h-3" />
                              human_review
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-caos-greenText bg-caos-greenMuted border border-caos-greenText px-2 py-0.5 text-[10px] uppercase">
                              <CheckCircle2 className="w-3 h-3" />
                              route
                            </span>
                          )}
                        </td>
                        <td className="px-6 py-3 text-caos-hueso font-semibold">
                          {t.system || <span className="text-caos-tenue">—</span>}
                        </td>
                        <td className="px-6 py-3 text-caos-champan">
                          {t.agent ? `@${t.agent}` : <span className="text-caos-tenue">—</span>}
                        </td>
                        <td className="px-6 py-3 font-serif italic text-caos-gris text-[11px]">
                          {t.reason}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Model Profiles Table */}
          <div className="border border-caos-borde bg-caos-tinta">
            <div className="px-6 py-4 border-b border-caos-borde bg-caos-negro flex items-center justify-between">
              <div className="font-mono text-xs uppercase tracking-wider text-caos-hueso font-semibold flex items-center gap-2">
                <Terminal className="w-4 h-4 text-caos-ambar" />
                <span>Empirical Model Profiles (Benchmark Evidence)</span>
              </div>
              <span className="font-mono text-[11px] text-caos-tenue">
                Conservative evaluation: Lower 95% bound decides eligibility
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono text-xs divide-y divide-caos-borde">
                <thead className="bg-caos-negro text-caos-tenue uppercase text-[10px]">
                  <tr>
                    <th className="px-6 py-3">System / Model</th>
                    <th className="px-6 py-3">Point Precision</th>
                    <th className="px-6 py-3">Precision LO (IC95)</th>
                    <th className="px-6 py-3">Coverage</th>
                    <th className="px-6 py-3">Latency / 1k Tasks</th>
                    <th className="px-6 py-3">Tokens / 1k Tasks</th>
                    <th className="px-6 py-3">Benchmark Snapshot</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-caos-borde">
                  {data.profiles.map((p) => (
                    <tr key={p.system} className="hover:bg-caos-tintaElevada transition-colors">
                      <td className="px-6 py-3 font-bold text-caos-ambar">
                        {p.system}
                      </td>
                      <td className="px-6 py-3 text-caos-hueso tabular-nums">
                        {(p.precision * 100).toFixed(1)}%
                      </td>
                      <td className="px-6 py-3 text-caos-greenText font-bold tabular-nums">
                        {(p.precision_lo * 100).toFixed(1)}%
                      </td>
                      <td className="px-6 py-3 text-caos-champan tabular-nums">
                        {(p.coverage * 100).toFixed(0)}%
                      </td>
                      <td className="px-6 py-3 text-caos-gris tabular-nums">
                        {p.seconds_per_1000.toLocaleString()} s
                      </td>
                      <td className="px-6 py-3 text-caos-gris tabular-nums">
                        {p.tokens_per_1000 != null ? p.tokens_per_1000.toLocaleString() : '—'}
                      </td>
                      <td className="px-6 py-3 text-caos-tenue text-[11px]">
                        {p.measured}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="p-4 bg-caos-negro border-t border-caos-borde font-serif text-xs text-caos-tenue leading-relaxed">
              <strong className="text-caos-hueso font-mono uppercase text-[10px]">Note on Safety:</strong>{' '}
              Point estimates can fluctuate by luck on small test sets. The harness strictly uses the lower bound
              of the Wilson score interval (<code className="font-mono text-caos-champan">precision_lo</code>).
              If no model's lower bound meets the tier requirement, the task is safely routed to the human reviewer
              queue (<code className="font-mono text-caos-ambar">queue: person</code>).
            </div>
          </div>
        </>
      )}
    </div>
  )
}
