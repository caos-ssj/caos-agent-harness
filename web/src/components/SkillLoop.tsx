import React, { useState } from 'react'
import { ArrowRight, Check, RotateCcw, Sparkles } from '../icons'
import { api, SkillChange, SkillEvidence, SkillOverview, SkillProposeResult } from '../api'
import '../skillloop.css'

/* Evidence for one skill, straight from the board: how often work done with it passes review at the first attempt, why it was
   returned, and the one-change trial a cheap reader may propose. Every number is a count; nothing here is estimated. */

const pct = (n: number) => `${Math.round(n * 100)}%`

export const Meter: React.FC<{ e: SkillEvidence }> = ({ e }) => (
  <>
    <div className="skill-meter" role="img" aria-label="Tasa a la primera con su intervalo">
      <i style={{ left: pct(e.lower), width: pct(Math.max(0.01, e.upper - e.lower)) }} />
      <u style={{ left: pct(e.rate) }} />
    </div>
    <div className="wilson-legend" aria-hidden="true">
      <span>punto: tasa observada</span>
      <span>barra: intervalo Wilson 95%</span>
    </div>
  </>
)

const Figure: React.FC<{ e: SkillEvidence; label?: string }> = ({ e, label }) => (
  <div>
    {label && <span className="mono muted">{label}</span>}
    <div className="skill-loop-figure">
      <b>{e.first_pass}/{e.decided}</b>
      <span className="muted">aceptadas a la primera</span>
      {e.decided > 0 && <><span className="muted">intervalo 95 %</span><span className="mono muted">{pct(e.lower)}–{pct(e.upper)}</span></>}
    </div>
    {e.decided > 0 && <Meter e={e} />}
  </div>
)

const Change: React.FC<{ c: SkillChange }> = ({ c }) => (
  <div className="skill-change">
    {c.anchor && <span className="del">− {c.anchor}</span>}
    {c.text && <span className="add">+ {c.text}</span>}
  </div>
)

const DECISION: Record<string, string> = { promote: 'mantener el cambio', reject: 'restaurar el texto anterior', insufficient: 'faltan datos' }

interface Props { row: SkillOverview; minDecided: number; onChanged: () => void }

export const SkillLoop: React.FC<Props> = ({ row, minDecided, onChanged }) => {
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<SkillProposeResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null)
    try { await fn(); onChanged() } catch (e: any) { setErr(e.message || 'No se pudo completar') } finally { setBusy(false) }
  }
  const e = row.evidence
  const t = row.trial

  return (
    <section className="skill-loop" aria-label="Evidencia del skill">
      <div className="skill-loop-head">
        <h3>Evidencia del tablero</h3>
        {t ? <span className="chip amber-chip">en prueba</span> : e && e.decided < minDecided ? <span className="chip dim">pocas tareas: intervalo ancho</span> : null}
      </div>

      {t ? (
        <>
          <div className="skill-vs">
            <Figure e={t.gate.baseline} label="antes del cambio" />
            <Figure e={t.gate.candidate} label="con el cambio" />
          </div>
          <p className="muted"><b>Problema</b> · {t.problem}</p>
          <Change c={t.change} />
          <p className="mono muted"><span>La puerta dice</span> → <b>{DECISION[t.gate.decision]}</b> · <span>{t.gate.reason}</span></p>
          <div className="skill-loop-actions">
            <button type="button" className="btn btn-primary btn-sm" disabled={busy || t.gate.decision === 'insufficient'} onClick={() => void run(() => api.closeSkillTrial(row.skill))}><Check className="icon icon-sm" />Cerrar según la puerta</button>
            <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void run(() => api.closeSkillTrial(row.skill, 'reject'))}><RotateCcw className="icon icon-sm" />Restaurar ahora</button>
            <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void run(() => api.closeSkillTrial(row.skill, 'promote'))}>Mantener ahora</button>
          </div>
        </>
      ) : (
        <>
          {e ? <Figure e={e} /> : <p className="muted mono">Aún no hay tareas decididas con este skill.</p>}
          {row.notes.length > 0 && (
            <>
              <span className="mono muted"><span>Por qué se devolvió</span> <span>({row.notes.length})</span></span>
              <ul className="skill-notes">{row.notes.map((n, i) => <li key={`${n.task}-${i}`}><span className="mono">#{String(n.task).padStart(2, '0')}</span><span>{n.note}</span></li>)}</ul>
            </>
          )}
          {res?.proposal && res.problems.length === 0 ? (
            <>
              <p className="muted"><b><span>Propuesta de</span> {res.reader}</b> · {res.proposal.problem}</p>
              <Change c={res.proposal.change} />
              <span className="mono muted"><span>Citas comprobadas</span> <span>{res.proposal.evidence.map((x) => `#${x.task} «${x.quote}»`).join('  ')}</span></span>
              <div className="skill-loop-actions">
                <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void run(async () => { await api.startSkillTrial(res.proposal!); setRes(null) })}><ArrowRight className="icon icon-sm" />Iniciar prueba</button>
                <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setRes(null)}>Descartar</button>
              </div>
            </>
          ) : (
            <div className="skill-loop-actions">
              <button type="button" className="btn btn-sm" disabled={busy || !row.can_propose} title={row.can_propose ? 'Un agente gratis o barato lee las devoluciones y propone un cambio' : 'Hacen falta devoluciones con nota en al menos 2 tareas'}
                onClick={() => void run(async () => setRes(await api.proposeSkillChange(row.skill)))}><Sparkles className="icon icon-sm" />{busy ? 'Leyendo devoluciones…' : 'Proponer mejora'}</button>
              {res && res.problems.length > 0 && <span className="verdict-err" role="alert"><span>Propuesta descartada</span> · <span>{res.problems.join('; ')}</span></span>}
            </div>
          )}
        </>
      )}
      {err && <p className="verdict-err" role="alert">{err}</p>}
    </section>
  )
}
