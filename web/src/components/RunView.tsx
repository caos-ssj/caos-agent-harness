import React, { useState } from 'react'
import { ArrowRight, GitBranch, Play, RefreshCw, RotateCcw, ShieldCheck } from '../icons'
import { api, CycleRecord } from '../api'
import { FamilyEmblem } from '../emblems'
import { useFocusAgent, useRunOverview } from '../runData'
import { ago } from '../lib'
import '../run.css'

/* The cycle on one screen: author → another agent reviews → merge onto harness/landed → your tests → the branch moves.
   Every figure here is a count of recorded events; a value the tools did not report is shown as a dash, never estimated. */

type Tone = 'ok' | 'bad' | 'wait' | 'none'

/* Who an agent is, by the tool it runs on: the colour says at a glance that author and reviewer are not the same family. */
export const Fam: React.FC<{ name: string; families: Record<string, string> }> = ({ name, families }) => (
  <span className={`fam fam-${families[name] ?? 'tool'}`} title={families[name] ?? ''}><FamilyEmblem family={families[name]} size={14} />{name}</span>
)
const pct = (n: number) => `${Math.round(n * 100)}%`
const ci = (c: [number, number] | null) => (c ? `${pct(c[0])}–${pct(c[1])}` : '—')
const short = (sha?: string | null) => (sha ? sha.slice(0, 8) : '—')

const VERDICT: Record<string, string> = { approve: 'aprueba', reject: 'rechaza', invalid: 'sin veredicto válido', tampered: 'revisión anulada' }
const STATUS: Record<string, [string, string]> = {
  landed: ['en la rama', 'sage'], ready: ['lista: espera a una persona', 'amber'], rejected: ['rechazado', 'coral'], verify_failed: ['tests fallidos', 'coral'],
  conflict: ['conflicto', 'coral'], empty: ['sin cambios', ''], refused: ['no admitido', 'coral'], drifted: ['la rama se movió', 'amber'], rolled_back: ['revertido', 'amber'],
}

export function steps(c: CycleRecord): Array<{ label: string; value: string; tone: Tone; hint?: string }> {
  const l = c.landing, v = l.verify
  const merged: [string, Tone] = l.status === 'conflict' ? [`conflicto en ${l.conflicts?.length ?? 0}`, 'bad'] : l.status === 'empty' ? ['sin cambios', 'none'] : l.status === 'refused' ? ['no admitido', 'bad'] : [(l.files?.length ?? 0) === 1 ? '1 fichero' : `${l.files?.length ?? 0} ficheros`, 'ok']
  return [
    { label: 'Revisión', value: VERDICT[c.review.verdict] ?? c.review.verdict, tone: c.review.verdict === 'approve' ? 'ok' : 'bad' },
    { label: 'Fusión', value: merged[0], tone: merged[1] },
    { label: 'Tests', value: v ? (v.exit === 0 ? 'pasaron' : `fallaron (${v.exit})`) : 'sin correr', hint: v ? `${v.seconds} s · ${v.command.join(' ')}`.slice(0, 200) : undefined, tone: v ? (v.exit === 0 ? 'ok' : 'bad') : 'none' },
    { label: 'Rama', value: c.status === 'landed' ? short(l.commit ?? l.tree) : c.status === 'ready' ? 'espera tu sí' : 'sin mover', tone: c.status === 'landed' ? 'ok' : c.status === 'ready' ? 'wait' : 'none' },
  ]
}

const Cycle: React.FC<{ c: CycleRecord; families: Record<string, string> }> = ({ c, families }) => {
  const [expanded, setExpanded] = useState(false)
  const [label, tone] = STATUS[c.status] ?? [c.status, '']
  const stepItems = steps(c)
  const findingsCount = c.review.findings.length
  const conflictsCount = c.landing.conflicts?.length ?? 0
  return (
    <article className="cycle" aria-label={`Ciclo ${c.key}`}>
      <div className="cycle-head">
        <span className="cycle-who mono"><b>{c.key}</b><Fam name={c.author} families={families} /><ArrowRight className="icon icon-xs" aria-hidden="true" /><Fam name={c.review.verifier} families={families} /></span>
        <span className="run-actions"><span className="mono muted">{ago(c.at)}</span><span className={`pill-mini ${tone}`}>{label}</span></span>
      </div>
      <ol className="cycle-segbar">
        {stepItems.map((s) => (
          <li key={s.label}>
            <button type="button" className="seg-hit" title={s.hint ?? s.value} aria-expanded={expanded} onClick={() => setExpanded((e) => !e)}>
              <span className={`seg-fill ${s.tone}`} />
              <span className="seg-lbl">{s.label}</span>
            </button>
          </li>
        ))}
      </ol>
      <details className="cycle-details" open={expanded} onToggle={(e) => setExpanded(e.currentTarget.open)}>
        <summary className="cycle-summary mono muted">
          <span>Detalle de ronda</span>
          {findingsCount > 0 && <span className="pill-mini coral">{findingsCount} {findingsCount === 1 ? 'hallazgo' : 'hallazgos'}</span>}
          {conflictsCount > 0 && <span className="pill-mini coral">{conflictsCount} {conflictsCount === 1 ? 'conflicto' : 'conflictos'}</span>}
          {c.landing.verify && c.landing.verify.tail.trim() && <span>Salida del comando de tests</span>}
        </summary>
        <div className="cycle-details-body">
          <dl className="cycle-step-kv">
            {stepItems.map((s) => (
              <div key={s.label} className={`cycle-kv-cell ${s.tone}`}>
                <dt>{s.label}</dt>
                <dd title={s.hint ?? s.value}><b>{s.value}</b></dd>
              </div>
            ))}
          </dl>
          {findingsCount > 0 && <ul className="cycle-findings">{c.review.findings.map((f, i) => <li key={i}><span className="mono">{f.file}</span> · {f.problem}</li>)}</ul>}
          {c.landing.conflicts && conflictsCount > 0 && <p className="mono muted">{c.landing.conflicts.join(' · ')}</p>}
          {c.landing.verify && c.landing.verify.tail.trim() && <pre>{c.landing.verify.tail}</pre>}
        </div>
      </details>
    </article>
  )
}

type PanelTab = 'cycles' | 'branch' | 'reviewers' | 'costs'

export const RunView: React.FC = () => {
  const { data, error: loadErr, refresh: load } = useRunOverview()
  const [actErr, setErr] = useState<string | null>(null)
  const err = actErr ?? loadErr
  const [busy, setBusy] = useState<string | null>(null)
  const [diff, setDiff] = useState<string | null>(null)
  const [authors, setAuthors] = useState<Record<string, string>>({})
  const [panelTab, setPanelTab] = useState<PanelTab>('cycles')
  const [toast, setToast] = useState<string | null>(null)
  const [focus, setFocus] = useFocusAgent()

  const act = async (id: string, fn: () => Promise<unknown>, okMsg?: string) => {
    setBusy(id); setErr(null); setToast(null)
    try { await fn(); await load(); if (okMsg) setToast(okMsg) } catch (e: any) { setErr(e.message || 'No se pudo completar') } finally { setBusy(null) }
  }

  if (!data) return (
    <div className="page"><div className="page-inner run-page" aria-busy={!err}>
      {err ? <div className="run-empty"><b>{err}</b><button type="button" className="btn btn-sm" onClick={() => void load()}><RefreshCw className="icon icon-sm" />Reintentar</button></div>
        : <><div className="skel skel-bar" /><div className="skel skel-block" /><div className="skel skel-block" /></>}
    </div></div>
  )
  const { landed, ledger, verifiers, waiting, config } = data
  const cycles = focus ? data.cycles.filter((c) => c.author === focus || c.review.verifier === focus) : data.cycles
  const last = landed.entries[0]
  const maxAct = Math.max(1, ...data.activity.map((b) => b.calls))
  const tierTotal = Object.values(data.tiers).reduce((a, b) => a + b, 0)
  const failingReviewers = verifiers.filter((v) => v.failed > 0)

  return (
    <div className="page">
      <div className="page-inner run-page">
        <div className="page-bar">
          <h1>Verificación</h1>
          <div className="page-bar-right run-actions">
            <span className="chip dim">{config.target === 'branch' ? 'destino: harness/landed' : 'destino: carpeta del proyecto'}</span>
            <span className={`chip ${config.autonomous ? 'amber-chip' : 'dim'}`}>{config.autonomous ? 'aterriza solo' : 'aterriza con tu sí'}</span>
            <button type="button" className="btn btn-quiet btn-sm" onClick={() => void load()} title="Actualizar"><RefreshCw className="icon icon-sm" />Actualizar</button>
          </div>
        </div>
        {err && <p className="verdict-err" role="alert">{err}</p>}
        {toast && <div className="toast-strip" role="status">{toast}</div>}
        {!data.git_repo && <div className="card run-empty"><b>Esta carpeta no es un repositorio git con un commit.</b><span>El ciclo trabaja en worktrees y en la rama harness/landed: necesita git.</span></div>}
        {!config.verify && <div className="card run-empty"><b>Falta el comando de verificación.</b><span className="mono">harness.toml → [landing] verify = ["…"]</span></div>}

        <div className="run-tabs" role="tablist" aria-label="Secciones de verificación">
          <button type="button" role="tab" aria-selected={panelTab === 'cycles'} onClick={() => setPanelTab('cycles')}>
            Ciclos{cycles.length + waiting.length > 0 ? ` (${cycles.length + waiting.length})` : ''}
          </button>
          <button type="button" role="tab" aria-selected={panelTab === 'branch'} onClick={() => setPanelTab('branch')}>
            Rama{landed.tip ? ` (${landed.files.length})` : ''}
          </button>
          <button type="button" role="tab" aria-selected={panelTab === 'reviewers'} onClick={() => setPanelTab('reviewers')}>
            Revisores
          </button>
          <button type="button" role="tab" aria-selected={panelTab === 'costs'} onClick={() => setPanelTab('costs')}>
            Costes
          </button>
        </div>

        <div className="run-split">
          {panelTab === 'cycles' && (
            <div className="run-col">
              <section className="card" aria-label="Ciclos">
                <div className="card-head"><h2>Ciclos</h2>{focus ? <button type="button" className="chip chip-x" onClick={() => setFocus(null)} title="Ver las revisiones de todos"><Fam name={focus} families={data.families} /><span aria-hidden="true">×</span></button> : <span className="mono muted">autor → revisor → fusión → tests → {landed.branch}</span>}</div>
                {cycles.length === 0 && focus ? <div className="run-empty"><span>Este agente aún no ha escrito ni revisado ningún cambio.</span></div> : cycles.length === 0 ? <div className="run-empty"><span>Aún no ha corrido ninguna revisión en este proyecto.</span><span className="muted">{waiting.length > 0 ? 'Elige abajo quién hizo un cambio y envíalo a revisión.' : 'Pide un cambio en modo Act con «Worktree aislado»: aparecerá aquí para enviarlo a revisión.'}</span></div> : cycles.map((c) => <Cycle key={c.id} c={c} families={data.families} />)}
              </section>
              {waiting.length > 0 && (
                <section className="card" aria-label="Cambios por revisar">
                  <div className="card-head"><h2>Cambios por revisar</h2><span className="mono muted">{waiting.length}</span></div>
                  {waiting.map((w) => (
                    <div key={w.key} className="run-waiting">
                      <span className="mono cycle-who"><b>{w.key}</b>{w.last ? <span className={`pill-mini ${(STATUS[w.last] ?? ['', ''])[1]}`}>{(STATUS[w.last] ?? [w.last])[0]}</span> : <span className="pill-mini">sin ciclo</span>}</span>
                      <select className="select" aria-label="Agente autor" value={authors[w.key] ?? ''} onChange={(e) => setAuthors({ ...authors, [w.key]: e.target.value })}>
                        <option value="">Autor…</option>{data.agents.map((a) => <option key={a} value={a}>{a}</option>)}
                      </select>
                      <button type="button" className={`btn btn-sm ${busy === w.key ? 'is-live' : ''}`} disabled={!authors[w.key] || !!busy || !config.verify} onClick={() => void act(w.key, () => api.runCycle(w.key, authors[w.key]))}><Play className="icon icon-sm" />{busy === w.key ? 'Revisando…' : 'Enviar a revisión'}</button>
                    </div>
                  ))}
                </section>
              )}
            </div>
          )}

          {panelTab === 'branch' && (
            <div className="run-col">
              <section className="card" aria-label="harness/landed">
                <div className="card-head"><h2><GitBranch className="icon icon-sm" aria-hidden="true" />{landed.branch}</h2><span className="mono muted">{landed.tip ? `${landed.files.length} fichero(s) por delante de ${landed.base ?? 'HEAD'}` : 'vacía · tu rama intacta'}</span></div>
                {landed.entries.length === 0 ? <p className="muted">Aquí se acumula el trabajo verificado. Tu rama y tu carpeta no se tocan.</p> : (
                  <div className="tbl-scroll"><table className="tbl"><thead><tr><th>Commit</th><th>Worktree</th><th>Revisó</th><th>Cuándo</th><th>Intacto</th></tr></thead>
                    <tbody>{landed.entries.map((e) => <tr key={e.commit}><td className="mono">{short(e.commit)}</td><td className="mono">{e.worktree ?? '—'}</td><td className="mono">{e.reviewed_by ? <Fam name={e.reviewed_by} families={data.families} /> : '—'}</td><td className="mono muted">{e.at ? ago(e.at) : '—'}</td>
                      <td>{e.foreign ? <span className="pill-mini coral">ajeno</span> : e.intact ? <span className="pill-mini sage">sí</span> : <span className="pill-mini coral">no</span>}</td></tr>)}</tbody></table></div>
                )}
                {landed.tip && (
                  <div className="run-actions" style={{ marginTop: 8 }}>
                    <button type="button" className="btn btn-sm" onClick={() => (diff === null ? void act('diff', async () => setDiff((await api.getLandedDiff()).diff)) : setDiff(null))}>{diff === null ? 'Ver diff contra tu rama' : 'Ocultar diff'}</button>
                    <button type="button" className="btn btn-sm" disabled={!!busy || landed.checked_out || !last} title={landed.checked_out ? 'La rama está abierta en una carpeta de trabajo: cámbiala de rama para poder moverla' : 'Quita el último aterrizaje de harness/landed; el commit se conserva'} onClick={() => void act('undo', async () => { await api.undoLanded(last.commit); setDiff(null) }, `Revertido ${short(last?.commit)} de ${landed.branch}`)}><RotateCcw className="icon icon-sm" /><span>Quitar</span> <span className="mono">{last ? short(last.commit) : ''}</span></button>
                  </div>
                )}
                {diff !== null && <pre className="landed-diff">{diff || 'Sin diferencias.'}</pre>}
              </section>
            </div>
          )}

          {panelTab === 'reviewers' && (
            <div className="run-col">
              <section className="card inst-card" aria-label="Instrumentos de revisión">
                <div className="inst-grid">
                  <div className="inst-block">
                    <div className="card-head"><h2>Actividad</h2><span className="mono muted">llamadas cada 5 min · 2 h</span></div>
                    <div className="bars" role="img" aria-label="Llamadas por intervalo">
                      {data.activity.map((b) => (
                        <i key={b.t} className={b.failed ? 'has-fail' : ''} style={{ height: `${Math.max(3, (b.calls / maxAct) * 100)}%`, opacity: b.calls ? 1 : 0.28 }} title={`${b.calls} · ${new Date(b.t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`} />
                      ))}
                    </div>
                  </div>
                  <div className="inst-block">
                    <div className="card-head"><h2>Revisores</h2><span className="mono muted">fallos cazados</span></div>
                    {failingReviewers.length === 0 ? <p className="inst-empty">Sin cambios fallidos que medir todavía.</p> : failingReviewers.map((v) => (
                      <div key={v.verifier} className="gauge"><span className="mono">{v.verifier}</span>
                        <span className="gauge-track">{v.catch_rate_ci95 && <u style={{ left: pct(v.catch_rate_ci95[0]), width: pct(Math.max(0.02, v.catch_rate_ci95[1] - v.catch_rate_ci95[0])) }} />}<s style={{ left: pct(v.caught / v.failed) }} /></span>
                        <span className="mono">{v.caught}/{v.failed}</span></div>
                    ))}
                  </div>
                </div>
              </section>
              <section className="card" aria-label="Revisores">
                <div className="card-head"><h2><ShieldCheck className="icon icon-sm" aria-hidden="true" />Revisores</h2><span className="mono muted">medidos contra los tests</span></div>
                {verifiers.length === 0 ? <p className="muted">Sin ciclos con resultado de tests todavía.</p> : (
                  <div className="tbl-scroll"><table className="tbl"><thead><tr><th>Revisor</th><th className="num">Ciclos</th><th className="num">Fallos cazados</th><th className="num">Aprobados con pass</th></tr></thead>
                    <tbody>{verifiers.map((v) => <tr key={v.verifier}><td className="mono"><Fam name={v.verifier} families={data.families} /></td><td className="run-num mono">{v.cycles}</td>
                      <td className="run-num mono">{v.failed ? `${v.caught}/${v.failed} · ${ci(v.catch_rate_ci95)}` : '—'}</td>
                      <td className="run-num mono">{v.approved ? `${v.approved_passed}/${v.approved} · ${ci(v.approval_precision_ci95)}` : '—'}</td></tr>)}</tbody></table></div>
                )}
              </section>
            </div>
          )}

          {panelTab === 'costs' && (
            <div className="run-col">
              <section className="card inst-card" aria-label="Trabajo por nivel">
                <div className="card-head"><h2>Trabajo por nivel</h2><span className="mono muted">llamadas</span></div>
                {tierTotal === 0 ? <p className="inst-empty">Aún no se ha llamado a ningún agente.</p> : (
                  <div className="inst-block">
                    {(['free', 'cheap', 'paid'] as const).filter((t) => data.tiers[t]).map((t) => (
                      <div key={t} className={`gauge tier-${t}`}><span className="mono">{t}</span><span className="gauge-track"><u style={{ left: 0, width: pct(data.tiers[t] / tierTotal) }} /></span><span className="mono">{pct(data.tiers[t] / tierTotal)}</span></div>
                    ))}
                  </div>
                )}
              </section>
              <section className="card" aria-label="Costes medidos">
                <div className="card-head"><h2>Costes medidos</h2><span className="mono muted">llamadas, tiempos y tokens reportados</span></div>
                {ledger.agents.length === 0 ? <p className="muted">Aún no se ha llamado a ningún agente.</p> : (
                  <div className="tbl-scroll"><table className="tbl"><thead><tr><th>Agente</th><th>Nivel</th><th className="num">Llamadas</th><th className="num">Segundos</th><th className="num">Caracteres</th><th className="num">Tokens</th></tr></thead>
                    <tbody>{ledger.agents.map((a) => <tr key={a.agent}><td className="mono"><Fam name={a.agent} families={data.families} /></td><td><span className={`pill-mini ${a.tier === 'paid' ? 'amber' : a.tier === 'free' ? 'sage' : ''}`}>{a.tier || '—'}</span></td>
                      <td className="run-num mono">{a.calls}{a.failed ? ` (${a.failed} ✕)` : ''}</td><td className="run-num mono">{Math.round(a.seconds)}</td>
                      <td className="run-num mono">{a.chars_in.toLocaleString()} → {a.chars_out.toLocaleString()}</td>
                      <td className="run-num mono">{a.tokens_in === null ? '—' : `${a.tokens_in} → ${a.tokens_out ?? 0}`}</td></tr>)}</tbody></table></div>
                )}
              </section>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
