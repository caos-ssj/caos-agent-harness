import React, { useEffect, useRef, useState } from 'react'
import { api, RouterResponse, StateResponse } from '../api'
import { fmt } from '../lib'
import { ProvidersView } from './ProvidersView'

const SECTIONS = [['measured', 'Measured systems'], ['router', 'The router'], ['agents', 'Agents'], ['skills', 'Skills'], ['providers', 'Providers']] as const
const pct = (n: number, d = 1) => `${(n * 100).toFixed(d)}%`

/* Reference: everything the desk's numbers rest on. Read it once, come back when a figure needs its source. */
export const Library: React.FC<{ state: StateResponse | null }> = ({ state }) => {
  const [router, setRouter] = useState<RouterResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [current, setCurrent] = useState<string>('measured')
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => { api.getRouter().then(setRouter).catch((e) => setErr(e.message)) }, [])
  useEffect(() => {
    const root = scroller.current
    if (!root) return
    const io = new IntersectionObserver((entries) => { const hit = entries.find((e) => e.isIntersecting); if (hit) setCurrent(hit.target.id) }, { root, rootMargin: '0px 0px -70% 0px' })
    SECTIONS.forEach(([id]) => { const el = root.querySelector(`#${id}`); if (el) io.observe(el) })
    return () => io.disconnect()
  }, [router])
  const go = (id: string) => { scroller.current?.querySelector(`#${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); setCurrent(id) }

  const profiles = router?.profiles ?? []
  return (
    <div className="library">
      <nav className="toc" aria-label="Sections">
        {SECTIONS.map(([id, label]) => <button key={id} type="button" aria-current={current === id} onClick={() => go(id)}>{label}</button>)}
      </nav>
      <div className="lib-scroll" ref={scroller}>
        <section className="lib-section" id="measured" aria-labelledby="h-measured">
          <img className="lib-plate" src="/art/traces.svg" alt="" aria-hidden="true" />
          <header><h2 id="h-measured">Measured systems</h2><span className="src">from <code>make benchmark</code></span></header>
          <p className="lead">Each system was run over the same labelled set. The router never reads a model’s name, only the lower bound of the 95 % interval of its precision.</p>
          {err && <p className="verdict-err">{err}</p>}
          <div style={{ overflowX: 'auto' }}>
            <table className="tbl">
              <thead><tr><th>System</th><th>Precision, with its 95 % interval</th><th className="num">Lower bound</th><th className="num">Coverage</th><th className="num">Seconds per 1,000</th><th className="num">Tokens per 1,000</th></tr></thead>
              <tbody>
                {profiles.map((p) => (
                  <tr key={p.system}>
                    <td className="name">{p.system}</td>
                    <td><span className="interval-wrap"><span className="interval" role="img" aria-label={`Precision ${pct(p.precision)}, lower bound ${pct(p.precision_lo)}`}><i style={{ left: `${p.precision_lo * 100}%`, width: `${(p.precision - p.precision_lo) * 100}%` }} /><b style={{ left: `calc(${p.precision * 100}% - 1px)` }} /></span>{pct(p.precision)}</span></td>
                    <td className="num">{pct(p.precision_lo)}</td>
                    <td className="num dim">{pct(p.coverage, 0)}</td>
                    <td className="num dim">{fmt(p.seconds_per_1000)}</td>
                    <td className="num dim">{p.tokens_per_1000 != null ? fmt(p.tokens_per_1000) : '—'}</td>
                  </tr>
                ))}
                {router && profiles.length === 0 && <tr><td colSpan={6} className="dim">No benchmark report yet. Run <code>make benchmark</code> from a checkout.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>

        <section className="lib-section" id="router" aria-labelledby="h-router">
          <img className="lib-plate" src="/art/router.svg" alt="" aria-hidden="true" />
          <header><h2 id="h-router">The router</h2><span className="src">from <code>make route</code></span></header>
          <p className="lead">Each cost of error asks for a minimum lower bound. The cheapest measured system that reaches it takes the task; when none does, a person does. That is a result, not a failure.</p>
          <div style={{ overflowX: 'auto' }}>
            <table className="tbl">
              <thead><tr><th>Cost of an error</th><th className="num">Needs at least</th><th>Goes to</th><th>Runs as agent</th><th>Why</th></tr></thead>
              <tbody>
                {router?.tiers.map((t) => (
                  <tr key={t.tier}>
                    <td className="name">{t.tier}</td>
                    <td className="num">{pct(t.needs, 0)}</td>
                    <td className={t.action === 'route' ? '' : 'person'}>{t.action === 'route' ? t.system : 'a person'}</td>
                    <td className="dim">{t.agent ?? (t.action === 'route' ? 'none in harness.toml' : '—')}</td>
                    <td className="dim" style={{ fontFamily: 'var(--serif)', fontSize: 15.5 }}>{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="lib-section" id="agents" aria-labelledby="h-agents">
          <img className="lib-plate" src="/art/board.svg" alt="" aria-hidden="true" />
          <header><h2 id="h-agents">Agents</h2><span className="src">from <code>harness.toml</code></span></header>
          <p className="lead">An agent is a command: the task arrives on its standard input and whatever it prints is the delivery.</p>
          <div className="agent-grid">
            {state?.agents.map((a) => (
              <div className="agent-card" key={a.name}><b>{a.name}</b><span className="sys">{a.system ? `runs ${a.system}` : 'no measured system'}</span><span title={a.command}>{a.command}</span><span>timeout {a.timeout}s · {a.pending} pending</span></div>
            ))}
            {state && state.agents.length === 0 && <div className="agent-card"><b>None yet</b><span>Add an [agents.name] table to harness.toml</span></div>}
          </div>
        </section>

        <section className="lib-section" id="skills" aria-labelledby="h-skills">
          <img className="lib-plate" src="/art/policy.svg" alt="" aria-hidden="true" />
          <header><h2 id="h-skills">Skills</h2><span className="src">from <code>caos-harness skills</code></span></header>
          <p className="lead">A skill is a short instruction file. Naming one on a task makes the agent read it first, so the same rules travel with the work.</p>
          <dl style={{ margin: 0 }}>
            {state?.skills.map((s) => (
              <div className="skill" key={s.name}><dt>{s.name}</dt><dd>{s.description}<small>skills/{s.name}/SKILL.md{s.local ? ' · local to this project' : ''}</small></dd></div>
            ))}
          </dl>
        </section>

        <section className="lib-section" id="providers" aria-labelledby="h-providers">
          <img className="lib-plate" src="/art/memory.svg" alt="" aria-hidden="true" />
          <header><h2 id="h-providers">Providers</h2></header>
          <p className="lead">The console and the agents run on local Ollama. The others are listed only to say whether their key is present in the environment.</p>
          <ProvidersView />
        </section>
      </div>
    </div>
  )
}
