import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, GitCompareArrows, RefreshCw } from 'lucide-react'
import { api, MetricsResponse, MetricsSeries, ModelProfile, RouterTier } from '../api'

interface Props {
  scope: 'project' | 'global'
  profiles: ModelProfile[]
  tiers: RouterTier[]
}

const pct = (n: number | null | undefined, d = 0) => (n == null ? '—' : `${(n * 100).toFixed(d)}%`)

/** What the repository's own gates say, without claiming more than was checked. */
export function gatesReading(g: { mutation: { caught: number; total: number } | null; regress_status: string | null } | undefined): { value: string; tone: 'pass' | 'fail' | 'idle'; sub: string } {
  const mut = g?.mutation ?? null
  const reg = g?.regress_status ?? null
  const mutOk = mut ? mut.caught === mut.total : null
  const sub = [mut ? `mut ${mut.caught}/${mut.total}` : 'mut sin medir', `regress ${reg === 'pass' ? 'pass' : reg === 'check' ? 'revisar' : 'sin verificar'}`].join(' · ')
  if (reg === 'check' || mutOk === false) return { value: 'REVISAR', tone: 'fail', sub }
  if (reg === 'pass') return { value: 'PASS', tone: 'pass', sub }
  if (mutOk === true) return { value: 'PARCIAL', tone: 'idle', sub }
  return { value: 'SIN VERIFICAR', tone: 'idle', sub }
}

const fmtT = (t: number, bucket: 'hour' | 'day') => {
  const d = new Date(t * 1000)
  return bucket === 'hour' ? `${String(d.getHours()).padStart(2, '0')}:00` : `${d.getDate()}/${d.getMonth() + 1}`
}

/* A trend drawn from the runs the telemetry actually holds: success rate (area) and median latency (line). */
export const TrendChart: React.FC<{ series: MetricsSeries | null }> = ({ series }) => {
  const [hover, setHover] = useState<number | null>(null)
  const ref = useRef<SVGSVGElement>(null)
  if (!series) return <p className="muted mono">Leyendo la telemetría…</p>
  if (!series.enough) {
    return (
      <div className="trend-empty" role="status">
        <b>Aún no hay tendencia que mostrar</b>
        <span>Hay {series.total_runs} run(s) registrados; la gráfica aparece desde {series.min_runs}. Ejecuta un prompt en Console o un Smoke Test.</span>
      </div>
    )
  }
  const W = 640, H = 200, L = 36, R = 44, T = 12, B = 26
  const pts = series.points
  const maxMs = Math.max(1, ...pts.map((p) => p.p50_ms ?? 0))
  const x = (i: number) => L + (pts.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (pts.length - 1))
  const ySucc = (v: number) => T + (1 - v) * (H - T - B)
  const yMs = (v: number) => T + (1 - v / maxMs) * (H - T - B)
  const succLine = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${ySucc(p.success_rate).toFixed(1)}`).join(' ')
  const area = `${succLine} L${x(pts.length - 1).toFixed(1)} ${H - B} L${x(0).toFixed(1)} ${H - B} Z`
  const msPts = pts.filter((p) => p.p50_ms != null)
  const msLine = msPts.map((p, i) => `${i ? 'L' : 'M'}${x(pts.indexOf(p)).toFixed(1)} ${yMs(p.p50_ms!).toFixed(1)}`).join(' ')
  const onMove = (e: React.MouseEvent) => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    const rel = ((e.clientX - r.left) / r.width) * W
    let best = 0
    pts.forEach((_, i) => { if (Math.abs(x(i) - rel) < Math.abs(x(best) - rel)) best = i })
    setHover(best)
  }
  const h = hover != null ? pts[hover] : null
  return (
    <div className="trend">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="trend-svg" role="img" aria-label="Tendencia de éxito y latencia p50" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <defs><linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--pass)" stopOpacity=".28" /><stop offset="1" stopColor="var(--pass)" stopOpacity="0" /></linearGradient></defs>
        {[0, 0.25, 0.5, 0.75, 1].map((g) => <g key={g}><line x1={L} x2={W - R} y1={ySucc(g)} y2={ySucc(g)} className="trend-grid" /><text x={L - 6} y={ySucc(g) + 3} textAnchor="end" className="trend-axis">{Math.round(g * 100)}%</text></g>)}
        {[0, 0.5, 1].map((g) => <text key={g} x={W - R + 6} y={yMs(g * maxMs) + 3} className="trend-axis ms">{Math.round(g * maxMs)}ms</text>)}
        <path d={area} fill="url(#trend-fill)" />
        <path d={succLine} className="trend-line pass" />
        {msLine && <path d={msLine} className="trend-line steel" />}
        {pts.map((p, i) => (i === 0 || i === pts.length - 1 || pts.length <= 8 || i % Math.ceil(pts.length / 6) === 0) && <text key={p.t} x={x(i)} y={H - 8} textAnchor="middle" className="trend-axis">{fmtT(p.t, series.bucket)}</text>)}
        {pts.map((p, i) => <circle key={p.t} cx={x(i)} cy={ySucc(p.success_rate)} r={hover === i ? 4.5 : 2.5} className="trend-dot" />)}
        {h && <line x1={x(hover!)} x2={x(hover!)} y1={T} y2={H - B} className="trend-cursor" />}
      </svg>
      <div className="trend-legend"><span><i className="sw pass" />éxito de runs</span><span><i className="sw steel" />latencia p50</span>
        {pts.length < 3 && <span className="muted mono trend-note">solo {pts.length} intervalo(s) con datos: la línea se completa con el paso del tiempo</span>}
        {h ? <b className="mono trend-tip">{fmtT(h.t, series.bucket)} · {h.runs} runs · éxito {pct(h.success_rate)} · p50 {h.p50_ms ?? '—'} ms</b> : <span className="muted mono">{series.total_runs} runs · pasa el ratón por un punto</span>}</div>
    </div>
  )
}

export const MetricsView: React.FC<Props> = ({ scope, profiles, tiers }) => {
  const [data, setData] = useState<MetricsResponse | null>(null)
  const [series, setSeries] = useState<MetricsSeries | null>(null)
  const [bucket, setBucket] = useState<'hour' | 'day'>('day')
  const picked = useRef(false)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [m, s] = await Promise.all([api.getMetrics(scope), api.getMetricsSeries(scope, bucket)])
      setData(m); setSeries(s); setErr(null)
      if (!picked.current && bucket === 'day' && s.enough && s.points.length < 3) setBucket('hour')   // a day holds too little: show the hours instead
    } catch (e: any) { setErr(e.message || 'No se pudieron leer las métricas') }
  }, [scope, bucket])
  useEffect(() => { void load() }, [load])

  const smoke = async (provider: string, model: string) => {
    const key = `smoke:${provider}:${model}`
    setBusyKey(key)
    try { const r = await api.smokeProvider(provider, model); setNote(`${model}: ${r.ok ? `Smoke OK · ${r.latency_ms} ms` : r.error || 'falló'}`); await load() } catch (e: any) { setErr(e.message) } finally { setBusyKey(null) }
  }
  const toggleDemote = async (provider: string, model: string, currently: boolean) => {
    const key = `demote:${provider}:${model}`
    setBusyKey(key)
    try {
      await api.demoteMetric(provider, model, !currently, !currently ? 'degradado desde Metrics' : 'restaurado')
      setNote(`${provider} · ${model}: ${!currently ? 'degradado en el Router' : 'restaurado en el Router'}`)
      await load()
    } catch (e: any) { setErr(e.message || 'No se pudo cambiar el estado') } finally { setBusyKey(null) }
  }

  const exportMarkdown = () => {
    if (!data) return
    const k = data.kpis
    const g = gatesReading(k.gates)
    const lines = [
      `# CAOS Métricas Operativas (${data.project} · ${data.scope})`, '',
      `- Éxito de runs: ${k.run_success_rate != null ? `${(k.run_success_rate * 100).toFixed(1)}%` : 'n/d'} (${k.runs_total} runs)`,
      `- Retorno humano: ${k.human_redo_rate != null ? `${(k.human_redo_rate * 100).toFixed(1)}%` : 'n/d'} (${k.returned}/${k.reviewed_total})`,
      `- Latencia p50: ${k.p50_latency_ms != null ? `${k.p50_latency_ms} ms` : 'n/d'}`,
      `- Tokens: ${k.tokens.total}`, `- Gates del repo: ${g.value} (${g.sub})`, '',
      '| Proveedor | Modelo | Runs | Éxito | p50 ms | Errores | Degradado |', '|---|---|---:|---:|---:|---:|---|',
      ...data.models.map((m) => `| ${m.provider} | ${m.model} | ${m.runs} | ${(m.success_rate * 100).toFixed(0)}% | ${m.p50_ms} | ${m.errors} | ${m.demoted ? 'sí' : 'no'} |`),
    ]
    const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown' }))
    const a = document.createElement('a')
    a.href = url; a.download = `caos-metrics-${data.scope}.md`; a.click(); URL.revokeObjectURL(url)
    setNote(`Exportado a caos-metrics-${data.scope}.md`)
  }

  const k = data?.kpis
  const gates = gatesReading(k?.gates)
  const kpis: Array<{ label: string; value: string; sub: string; tone?: string }> = [
    { label: 'Éxito de runs', value: pct(k?.run_success_rate), sub: `${k?.runs_total ?? 0} ejecutados`, tone: (k?.run_success_rate ?? 1) >= 0.8 ? 'pass' : 'act' },
    { label: 'Retorno humano', value: pct(k?.human_redo_rate), sub: `${k?.returned ?? 0}/${k?.reviewed_total ?? 0} devueltas`, tone: (k?.human_redo_rate ?? 0) > 0 ? 'act' : '' },
    { label: 'Latencia p50', value: k?.p50_latency_ms != null ? `${k.p50_latency_ms} ms` : '—', sub: 'mediana en caliente' },
    { label: 'Tokens', value: (k?.tokens.total ?? 0).toLocaleString('en-US'), sub: `${k?.tokens.prompt ?? 0} in · ${k?.tokens.completion ?? 0} out` },
    { label: 'Gates repo', value: gates.value, sub: gates.sub, tone: gates.tone },
  ]

  const measured = useMemo(() => [...profiles].sort((a, b) => b.precision_lo - a.precision_lo), [profiles])

  return (
    <div className="page">
      <div className="page-inner metrics-page">
        <div className="page-bar">
          <h1>Metrics</h1>
          <div className="page-bar-right">
            <span className="chip">{scope === 'global' ? 'Global · todos los proyectos' : 'Proyecto'}</span>
            <button type="button" className="btn btn-sm" onClick={exportMarkdown} disabled={!data}><Download className="icon" style={{ width: 14, height: 14 }} />Exportar Markdown</button>
            <button type="button" className="btn btn-quiet btn-icon btn-sm" onClick={() => void load()} title="Actualizar" aria-label="Actualizar métricas"><RefreshCw className="icon" style={{ width: 14, height: 14 }} /></button>
          </div>
        </div>
        {note && <div className="toast-strip" role="status">{note}</div>}
        {err && <div className="banner err" role="alert"><span>{err}</span></div>}

        <div className="kpi-grid-5">
          {kpis.map((c) => (
            <div key={c.label} className="kpi-card"><span className="kpi-label">{c.label}</span><span className={`kpi-val ${c.tone ?? ''}`}>{c.value}</span><span className="kpi-sub" title={c.sub}>{c.sub}</span></div>
          ))}
        </div>

        <div className="metrics-split">
          <section className="card chart-card" aria-label="Tendencia">
            <div className="card-head"><h2>Tendencia</h2>
              <div className="seg" role="group" aria-label="Agrupar por"><button type="button" aria-pressed={bucket === 'day'} onClick={() => { picked.current = true; setBucket('day') }}>Día</button><button type="button" aria-pressed={bucket === 'hour'} onClick={() => { picked.current = true; setBucket('hour') }}>Hora</button></div></div>
            <TrendChart series={series} />
          </section>
          <section className="card tbl-card" aria-label="Matriz de tiers">
            <div className="card-head"><h2>Tier × Modelo</h2><span className="mono muted">límite inferior 95% ≥ exigido</span></div>
            {measured.length === 0 ? <p className="muted mono">Sin modelos medidos.</p> : (
              <div className="tbl-scroll"><table className="tbl matrix"><thead><tr><th>Tier</th>{measured.slice(0, 3).map((p) => <th key={p.system} className="mono mx-head" title={p.system}>{p.system.replace(/^.*\//, '').replace('+rules', '+r')}</th>)}<th>Hoy responde</th></tr></thead>
                <tbody>{tiers.map((t) => (
                  <tr key={t.tier}><td><b>{t.tier}</b> <span className="muted mono">≥{t.needs}</span></td>
                    {measured.slice(0, 3).map((p) => { const cov = p.precision_lo >= t.needs; const chosen = t.system === p.system; return <td key={p.system} className={`mx ${cov ? 'cov' : ''} ${chosen ? 'chosen' : ''}`} title={`${p.system}: límite ${pct(p.precision_lo, 1)}`}>{chosen ? '★' : cov ? '✓' : '—'}</td> })}
                    <td className="mono">{t.action === 'route' ? t.system : <span className="amber">persona</span>}</td></tr>))}</tbody></table></div>
            )}
          </section>
        </div>

        <section className="card tbl-card" aria-label="Rendimiento por modelo">
          <div className="card-head"><h2>Rendimiento operativo por modelo ({data?.models.length ?? 0})</h2><span className="mono muted">alcance: {scope}</span></div>
          <div className="tbl-scroll"><table className="tbl"><thead><tr><th>Modelo</th><th className="num">Runs</th><th className="num">Éxito</th><th className="num">p50</th><th className="num">Errores</th><th>Smoke</th><th className="actions-col">Acciones</th></tr></thead>
            <tbody>
              {(data?.models ?? []).map((m) => (
                <tr key={`${m.provider}:${m.model}`} className={m.demoted ? 'is-demoted' : ''}>
                  <td><b className="mono">{m.model}</b> <span className="muted mono">{m.provider}</span>{m.demoted && <span className="chip coral-chip"> degradado</span>}</td>
                  <td className="num mono">{m.runs}</td><td className="num mono">{pct(m.success_rate)}</td><td className="num mono">{m.p50_ms} ms</td><td className="num mono">{m.errors}</td>
                  <td>{m.last_smoke ? <span className={`pill-mini ${m.last_smoke.ok ? 'sage' : 'coral'}`}>{m.last_smoke.ok ? `OK · ${m.last_smoke.ms} ms` : 'falló'}</span> : <span className="muted mono">—</span>}</td>
                  <td className="actions-col">
                    <button type="button" className="btn btn-xs" disabled={busyKey === `smoke:${m.provider}:${m.model}`} onClick={() => void smoke(m.provider, m.model)}>Smoke</button>
                    <button type="button" className="btn btn-xs" disabled={busyKey === `demote:${m.provider}:${m.model}`} onClick={() => void toggleDemote(m.provider, m.model, m.demoted)}>{m.demoted ? 'Restaurar' : 'Degradar'}</button>
                  </td>
                </tr>
              ))}
              {data && data.models.length === 0 && <tr><td colSpan={7} className="muted">Aún no hay runs registrados en este alcance. Ejecuta un prompt en Console o un Smoke Test.</td></tr>}
            </tbody></table></div>
        </section>

        {!!data?.compare?.runs && (
          <section className="card tbl-card" aria-label="Comparaciones">
            <div className="card-head"><h2><GitCompareArrows className="icon" style={{ width: 16, height: 16 }} />Comparaciones lado a lado ({data.compare.runs})</h2><span className="mono muted">no cuentan en los KPIs de trabajo real</span></div>
            <div className="tiers-compact">{data.compare.models.map((m) => <span key={`${m.provider}:${m.model}`} className="tier-mini"><b>{m.model}</b><span className="mono muted">{m.provider} · {m.runs} corridas · {pct(m.ok_rate)} ok · p50 {m.p50_ms ?? '—'} ms</span></span>)}</div>
          </section>
        )}
      </div>
    </div>
  )
}
