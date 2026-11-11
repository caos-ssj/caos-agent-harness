import React, { useEffect, useState } from 'react'
import { Gauge, Inbox, ListChecks, Scale, ShieldCheck } from 'lucide-react'
import { api, ModelProfile, RouterResponse, StateResponse } from '../api'
import { family } from '../models'
import { PageHead } from './PageHead'
import { NEEDS, CLOSED, fmt } from '../lib'

const pct = (n: number, d = 1) => `${(n * 100).toFixed(d)}%`
const LO = 0.6   // the chart starts at 60 %: below it no system is useful for any tier
const at = (x: number) => `${Math.max(0, Math.min(1, (x - LO) / (1 - LO))) * 100}%`

/* Measured: every figure is the board's own aggregate, the task list, or a report a command wrote; each tile names its source. */
const SHAPES: Record<string, string> = { llama: 'circle', qwen: 'square', gemma: 'diamond', phi: 'triangle', other: 'diamond' }

/* Reliability against time. Each point is one measured system: height is the lower bound of its precision (what the
   router decides on), distance to the right is the seconds it took per 1,000 items. The shape says which model family it
   is; a filled point is the same model behind the rule layer ("+rules"). The dashed lines are what each cost of error asks for. */
const Scatter: React.FC<{ profiles: ModelProfile[]; tiers: Array<{ tier: string; needs: number }> }> = ({ profiles, tiers }) => {
  const W = 900, H = 350, L = 58, R = 112, T = 14, B = 46
  const xs = profiles.map((p) => p.seconds_per_1000)
  const x0 = Math.max(0, Math.floor((Math.min(...xs) - 200) / 500) * 500), x1 = Math.ceil((Math.max(...xs) + 200) / 500) * 500
  const X = (v: number) => L + ((v - x0) / (x1 - x0)) * (W - L - R)
  const Y = (v: number) => T + (1 - (v - LO) / (1 - LO)) * (H - T - B)
  const marker = (shape: string, x: number, y: number, filled: boolean, key: string) => {
    const common = { fill: filled ? 'var(--ink)' : 'var(--ground)', stroke: 'var(--ink)', strokeWidth: 2 }
    if (shape === 'square') return <rect key={key} x={x - 6.5} y={y - 6.5} width={13} height={13} {...common} />
    if (shape === 'diamond') return <path key={key} d={`M${x} ${y - 8} L${x + 8} ${y} L${x} ${y + 8} L${x - 8} ${y} Z`} {...common} />
    if (shape === 'triangle') return <path key={key} d={`M${x} ${y - 8} L${x + 8} ${y + 6} L${x - 8} ${y + 6} Z`} {...common} />
    return <circle key={key} cx={x} cy={y} r={7} {...common} />
  }
  const fams = Array.from(new Set(profiles.map((p) => family(p.system))))
  return (
    <figure className="scatter">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Precision lower bound against seconds per 1,000 items, one point per measured system">
        {[0.6, 0.7, 0.8, 0.9, 1].map((v) => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} className="grid-line" /><text x={L - 10} y={Y(v) + 4} textAnchor="end" className="axis">{Math.round(v * 100)}%</text></g>)}
        {Array.from({ length: Math.round((x1 - x0) / 500) + 1 }, (_, i) => x0 + i * 500).map((v) => <text key={v} x={X(v)} y={H - 22} textAnchor="middle" className="axis">{fmt(v)}</text>)}
        <text x={(L + W - R) / 2} y={H - 4} textAnchor="middle" className="axis-title">seconds per 1,000 items: further left is faster</text>
        <text transform={`translate(14 ${(T + H - B) / 2}) rotate(-90)`} textAnchor="middle" className="axis-title">lower bound of precision</text>
        {tiers.map((t) => <g key={t.tier}><line x1={L} x2={W - R} y1={Y(t.needs)} y2={Y(t.needs)} className={`tier-line ${t.tier === 'critical' ? 'person' : ''}`} /><text x={W - R + 8} y={Y(t.needs) + 4} className={`tier-label ${t.tier === 'critical' ? 'person' : ''}`}>{t.tier} {Math.round(t.needs * 100)}%</text></g>)}
        {profiles.map((p) => { const f = family(p.system); const x = X(p.seconds_per_1000), y = Y(Math.max(LO, p.precision_lo)); return (
          <g key={p.system}><title>{`${p.system}: lower bound ${pct(p.precision_lo)}, precision ${pct(p.precision)}, ${fmt(p.seconds_per_1000)} s per 1,000`}</title>{marker(SHAPES[f], x, y, p.system.includes('+'), p.system)}<text x={x + 12} y={y - 8} className="pt-label">{p.system}</text></g>) })}
      </svg>
      <figcaption className="scatter-legend">
        {fams.map((f) => <span key={f}><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">{marker(SHAPES[f], 8, 8, false, f)}</svg>{f === 'other' ? 'other models' : f}</span>)}
        <span><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">{marker('circle', 8, 8, true, 'f')}</svg>filled: behind the rules</span>
        <span><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">{marker('circle', 8, 8, false, 'h')}</svg>hollow: the model alone</span>
      </figcaption>
    </figure>
  )
}

export const StatsView: React.FC<{ state: StateResponse | null }> = ({ state }) => {
  const [router, setRouter] = useState<RouterResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { api.getRouter().then(setRouter).catch((e) => setErr(e.message)) }, [])

  const tasks = state?.tasks ?? []
  const s = state?.stats
  const needs = tasks.filter((t) => NEEDS.has(t.state)).length
  const toReview = tasks.filter((t) => t.state === 'to_review' || t.state === 'verify').length
  const withPerson = tasks.filter((t) => t.state === 'person').length
  const moving = tasks.filter((t) => !NEEDS.has(t.state) && !CLOSED.has(t.state)).length
  const closed = tasks.filter((t) => CLOSED.has(t.state)).length
  const ok = s?.review?.ok ?? 0
  const sup = s?.review?.superseded ?? 0
  const ver = s?.review?.verify ?? 0
  const reviewed = ok + sup + ver
  const m = state?.quality?.mutation
  const seg = (parts: Array<[number, string]>) => (
    <div className="segbar" aria-hidden="true">{parts.filter(([n]) => n > 0).map(([n, c], i) => <i key={i} className={c} style={{ flex: n }} />)}</div>
  )
  const profiles = router?.profiles ?? []

  return (
    <div className="page"><div className="page-inner">
      <PageHead title="Measured" art="traces" lead="What this board says, and what the repository’s reports measured. Nothing here is an estimate; each figure names the command that produced it." />

      <div className="tiles">
        <div className={`card tile ${needs ? 'due' : ''}`}>
          <div className="tile-top"><span>Waiting for you</span><Inbox className="icon" aria-hidden="true" /></div>
          <div className="tile-value">{needs}</div>
          {seg([[toReview, 'c-warm'], [withPerson, 'c-ink2']])}
          <div className="legend"><span><i className="c-warm" />{toReview} to review or verify</span><span><i className="c-ink2" />{withPerson} with a person</span></div>
          <div className="tile-src">from the board</div>
        </div>
        <div className="card tile">
          <div className="tile-top"><span>Tasks on the board</span><ListChecks className="icon" aria-hidden="true" /></div>
          <div className="tile-value">{fmt(s?.tasks ?? 0)}</div>
          {seg([[needs, 'c-warm'], [moving, 'c-ink'], [closed, 'c-edge']])}
          <div className="legend"><span><i className="c-warm" />{needs} need you</span><span><i className="c-ink" />{moving} in motion</span><span><i className="c-edge" />{closed} closed</span></div>
          <div className="tile-src">caos-harness status</div>
        </div>
        <div className="card tile">
          <div className="tile-top"><span>Reviewed</span><Gauge className="icon" aria-hidden="true" /></div>
          <div className="tile-value">{reviewed}</div>
          {seg([[ok, 'c-ink'], [sup, 'c-ink3'], [ver, 'c-warm']])}
          <div className="legend"><span><i className="c-ink" />{ok} accepted</span><span><i className="c-ink3" />{sup} superseded</span><span><i className="c-warm" />{ver} to verify</span></div>
          <div className="tile-sub" style={{ marginTop: 6 }}>{s?.returned_at_least_once ?? 0} returned at least once</div>
          <div className="tile-src">caos-harness status</div>
        </div>
        <div className="card tile">
          <div className="tile-top"><span>Faults caught</span><ShieldCheck className="icon" aria-hidden="true" /></div>
          <div className="tile-value">{m ? `${m.caught}/${m.total}` : '—'}</div>
          {m ? seg([[m.caught, 'c-ink'], [m.total - m.caught, 'c-warm']]) : <div className="segbar" aria-hidden="true" />}
          <div className="tile-sub" style={{ marginTop: 8 }}>{m ? 'faults injected in the code, caught by the tests' : 'No report yet.'}</div>
          <div className="tile-src">{m ? m.source : 'run make mutation'}</div>
        </div>
      </div>

      <div className="section-title"><h2>What each system can take</h2><span className="src">from <code>make benchmark</code></span></div>
      <p className="lead">Each system was run over the same labelled set. The router decides on the <b style={{ color: 'var(--ink)' }}>lower end</b> of the 95 % interval of its precision: a system can take a cost of error when its point is above that tier’s line.</p>
      {err && <p className="verdict-err">{err}</p>}
      {profiles.length > 0 && <div className="card" style={{ padding: '14px 18px 8px' }}><Scatter profiles={profiles} tiers={router?.tiers ?? []} /></div>}
      <p className="lead" style={{ marginTop: 20 }}>The same data with its interval and numbers: the bar is the 95 % interval of precision, the dot is the measured precision.</p>
      <div className="card systems">
        {profiles.map((p) => (
          <div className="sys-row" key={p.system}>
            <div className="sys-name">{p.system}<small>measured {p.measured}</small></div>
            <div className="range-wrap">
              <div className="range" role="img" aria-label={`${p.system}: precision ${pct(p.precision)}, lower bound ${pct(p.precision_lo)}`}>
                <span className="span" style={{ left: at(p.precision_lo), width: `calc(${at(p.precision)} - ${at(p.precision_lo)})` }} />
                {(router?.tiers ?? []).map((t) => <span key={t.tier} className={`tick ${t.tier === 'critical' ? 'person' : ''}`} style={{ left: at(t.needs) }}><span>{t.tier}</span></span>)}
                <span className="dot" style={{ left: at(p.precision) }} />
              </div>
            </div>
            <div className="sys-nums"><b>{pct(p.precision)}</b> precision · <b>{pct(p.precision_lo)}</b> lower<br />{pct(p.coverage, 0)} coverage · {fmt(p.seconds_per_1000)} s per 1,000<br />{p.tokens_per_1000 != null ? `${fmt(p.tokens_per_1000)} tokens per 1,000` : 'tokens not measured'}</div>
          </div>
        ))}
        {router && profiles.length === 0 && <p style={{ color: 'var(--ink-2)', padding: '14px 0' }}>No benchmark report yet. Run <code>make benchmark</code> from a checkout.</p>}
      </div>

      <div className="section-title"><h2>Who takes which cost of error</h2><span className="src">from <code>make route</code></span></div>
      <div className="tiers">
        {router?.tiers.map((t) => (
          <div key={t.tier} className={`card tier ${t.action === 'route' ? '' : 'person'}`}>
            <div className="name"><span>{t.tier}</span><span className="need">needs ≥ {pct(t.needs, 0)}</span></div>
            <div className="goes">{t.action === 'route' ? t.system : 'a person'}</div>
            <p>{t.action === 'route' ? (t.agent ? `Runs as the agent “${t.agent}”.` : 'No agent in harness.toml runs it, so the task goes to a person.') : 'No measured system reaches the bar.'}</p>
            <p style={{ color: 'var(--ink-3)', fontSize: 13 }}>{t.reason}</p>
          </div>
        ))}
      </div>
      <div className="card how"><Scale className="icon" aria-hidden="true" /><div><b>How the router chooses:</b> by the lower bound of the 95 % interval of precision, never by model name. It takes the cheapest measured system that reaches what the cost of an error requires; when none does, the task goes to a person. That is a result, not a failure.</div></div>
    </div></div>
  )
}
