import React, { useEffect, useRef, useState } from 'react'
import { RunOverview, Station } from '../api'
import { FamilyEmblem } from '../emblems'
import { ago, pad } from '../lib'
import { lastVisit, useFocusAgent, useRunOverview } from '../runData'
import '../stations.css'

/* Compact 2-column live agent deck + real-time activity strip.
   Leaves 65% of the right pane open for live activity and Verification without vertical overflow. */

const ROLE: Record<string, string> = { scout: 'Lector', author: 'Autor', reviewer: 'Revisor' }
const still = () => typeof window !== 'undefined' && (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || !!document.querySelector('.app.motion-focus'))

type Sig = 'live' | 'pass' | 'fail' | 'idle'
const sigOf = (s: Station): Sig => (s.running ? 'live' : !s.last ? 'idle' : s.last.status === 'ok' ? 'pass' : 'fail')

const Signal: React.FC<{ kind: Sig; seed: number }> = ({ kind, seed }) => {
  const trailRef = useRef<SVGPathElement>(null)
  const ref = useRef<SVGPathElement>(null)
  useEffect(() => {
    const el = ref.current
    const trail = trailRef.current
    if (!el) return
    const wave = (t: number, amp = 1) => {
      let d = ''
      for (let x = 0; x <= 88; x += 2) {
        const y =
          9 +
          (Math.sin(x / 6 + t / 160) * 4.5 * Math.sin(x / 28 + t / 750 + seed) +
            Math.sin(x / 2.6 + t / 65) * 1.8) *
            amp
        d += `${x ? 'L' : 'M'}${x} ${y.toFixed(1)}`
      }
      return d
    }
    const calm = () => {
      let d = ''
      for (let x = 0; x <= 88; x += 2) {
        let y = 9
        if (kind === 'pass' && x > 50 && x < 72) y -= Math.sin(((x - 50) / 22) * Math.PI) * 4.5
        else if (kind === 'fail' && x > 50 && x < 72) y += x % 8 < 4 ? -4.5 : 4.5
        d += `${x ? 'L' : 'M'}${x} ${y.toFixed(1)}`
      }
      return d
    }
    if (kind !== 'live' || still()) {
      trail?.setAttribute('d', '')
      el.setAttribute('d', kind === 'live' ? wave(600) : calm())
      return
    }
    let raf = 0
    const loop = (t: number) => {
      trail?.setAttribute('d', wave(t - 80, 0.85))
      el.setAttribute('d', wave(t, 1))
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [kind, seed])
  return (
    <svg className="stn-signal" viewBox="0 0 88 18" preserveAspectRatio="none" aria-hidden="true">
      <path ref={trailRef} className="stn-trail" />
      <path ref={ref} className="stn-trace" />
    </svg>
  )
}

const StationCard: React.FC<{ s: Station; i: number; now: number; focused: boolean; onFocus: () => void }> = ({ s, i, now, focused, onFocus }) => {
  const sig = sigOf(s)
  const state = s.running ? 'trabajando' : !s.last ? 'sin llamadas' : s.last.status === 'ok' ? 'listo' : 'falló'
  const liveSec = s.running && s.live?.started_at ? Math.max(1, Math.round(now / 1000 - s.live.started_at)) : null
  const liveDur = liveSec == null ? null : liveSec >= 3600 ? `${Math.floor(liveSec / 3600)}h` : liveSec >= 120 ? `${Math.floor(liveSec / 60)}m` : `${liveSec}s`
  return (
    <button
      type="button"
      className={`stn sig-${sig} fam-${s.family ?? 'tool'} ${s.running ? 'is-live' : ''} ${focused ? 'is-focus' : ''}`}
      aria-label={`Estación ${s.name}`}
      aria-pressed={focused}
      onClick={onFocus}
      title={focused ? 'Ver las revisiones de todos' : `Filtrar actividad y ciclos de ${s.name}`}
    >
      <span className="stn-top">
        <FamilyEmblem family={s.family ?? s.name} size={15} className="stn-emblem" />
        <b className="stn-name">{s.name}</b>
        {s.roles.length > 0 && <span className="stn-role">{ROLE[s.roles[0]] ?? s.roles[0]}</span>}
        <Signal kind={sig} seed={i} />
      </span>

      {s.running ? (
        <span className="stn-live-line" role="status">
          <i className="live-pulse" aria-hidden="true" />
          <span className="stn-live-what">
            {s.live?.task_id != null && <b className="mono">#{pad(s.live.task_id)} </b>}
            {s.live?.step || s.live?.text || 'ejecutando en vivo…'}
          </span>
          {liveDur && <em className="mono">{liveDur}</em>}
        </span>
      ) : (
        <span className="stn-foot">
          <span className="stn-state">
            <i aria-hidden="true" />
            <span>{state}</span>
            {s.last && <em className="mono">{ago(s.last.ts)}</em>}
          </span>
          <span className="stn-meta mono">
            <span>{s.calls} ll</span>
            {s.reviewed_failing ? <span>{s.caught}/{s.reviewed_failing} caz</span> : <span className={`tier-${s.tier}`}>{s.tier}</span>}
          </span>
        </span>
      )}
      <i className="stn-sweep" aria-hidden="true" />
    </button>
  )
}

const Shift: React.FC<{ d: RunOverview }> = ({ d }) => {
  const s = d.shift
  const since = lastVisit()
  return (
    <section className="shift glass" aria-label="Desde tu última visita">
      <h2><span>{since ? 'Desde tu última visita' : 'Hasta ahora'}</span>{since ? <small className="mono">{ago(since)}</small> : null}</h2>
      <div className="tone-pass"><b>{s.landed}</b><span>en la rama</span></div>
      <div className={s.failed ? 'tone-fail' : ''}><b>{s.failed}</b><span>{s.failed === 1 ? 'test fallido' : 'tests fallidos'}</span></div>
      <div className={s.needs_you ? 'tone-wait' : ''}><b>{s.needs_you}</b><span>esperan por ti</span></div>
      <div><b>{s.paid_calls}<i>/{s.calls}</i></b><span>{s.calls === 1 ? 'llamada de pago' : 'llamadas de pago'}</span></div>
    </section>
  )
}

const LivePulseStrip: React.FC<{ d: RunOverview }> = ({ d }) => {
  const maxAct = Math.max(1, ...d.activity.map((b) => b.calls))
  const totalCalls = d.activity.reduce((acc, b) => acc + b.calls, 0)
  return (
    <section className="live-strip glass" aria-label="Pulso de actividad en vivo">
      <div className="live-strip-head">
        <span className="mono muted">ACTIVIDAD EN VIVO · 2 H</span>
        <span className="mono">{totalCalls} llamadas · {Math.round(d.ledger.seconds)}s acumulados</span>
      </div>
      <div className="act-bars compact" role="img" aria-label="Llamadas a agentes en las últimas dos horas">
        {d.activity.map((b) => (
          <span key={b.t} className={`act-bar ${b.failed ? 'has-fail' : ''} ${b.calls ? 'has-call' : ''}`}
            style={{ ['--h' as string]: `${b.calls ? Math.max(18, Math.round((b.calls / maxAct) * 100)) : 8}%` }}
            title={`${new Date(b.t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · ${b.calls} llamada(s)`} />
        ))}
      </div>
    </section>
  )
}

export const RunDeck: React.FC = () => {
  const { data } = useRunOverview()
  const [focus, setFocus] = useFocusAgent()
  const [now, setNow] = useState(() => Date.now())
  const working = data?.stations.find((s) => s.running)

  useEffect(() => {
    if (!working) return
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [working])

  useEffect(() => {
    const room = document.querySelector<HTMLElement>('.view.room')
    if (!room) return
    if (working) {
      room.dataset.stationWorking = working.family ?? 'tool'
      room.dataset.working = working.family ?? 'tool'
    } else {
      delete room.dataset.stationWorking
      room.dataset.working = room.dataset.consoleWorking || ''
    }
  }, [working])

  if (!data) return null
  return (
    <div className="run-deck" aria-label="Estaciones de agentes">
      <Shift d={data} />
      { data.stations.length > 0 && (
        <section className="stations" aria-label="Agentes del proyecto">
          {data.stations.map((s, i) => (
            <StationCard key={s.name} s={s} i={i} now={now} focused={focus === s.name} onFocus={() => setFocus(focus === s.name ? null : s.name)} />
          ))}
        </section>
      )}
      <LivePulseStrip d={data} />
    </div>
  )
}
