import React, { useEffect, useMemo, useState } from 'react'
import { Eye, GitBranch, Loader2, Play, Plus, RefreshCw, Square, Trash2, Workflow } from '../icons'
import { OrchestrateOptions, OrchestrationPlan, OrchestrationState, OrchestrationSubtask, SkillInfo, SubtaskRun } from '../api'
import { pad } from '../lib'
import { FamilyEmblem } from '../emblems'
import { DiffViewer } from './DiffViewer'

const shortModel = (m?: string | null): string => {
  if (!m) return ''
  const parts = m.split('/')
  return parts.length > 1 ? parts[parts.length - 1] : m
}

const familyFor = (name: string): string => {
  const s = name.toLowerCase()
  if (s.includes('claude') || s.includes('haiku')) return 'claude'
  if (s.includes('gemini') || s.includes('agy')) return 'agy'
  if (s.includes('codex')) return 'codex'
  if (s.includes('opencode') || s.includes('pickle')) return 'opencode'
  if (s.includes('ollama') || s.includes('qwen') || s.includes('llama') || s.includes('local')) return 'local'
  return 'api'
}

const modelsFor = (
  info?: { family?: string | null; model?: string | null; models?: string[] } | null,
  current?: string | null,
  localModels: string[] = [],
): string[] => {
  const base = info?.family === 'local' ? [...(info.models ?? []), ...localModels] : (info?.models ?? [])
  return Array.from(new Set([current || '', info?.model || '', ...base].filter(Boolean)))
}

const REASON: Record<string, string> = {
  local: 'trabaja 100 % local, sin red',
  fast: 'iteración rápida sin gastar cuota',
  architecture: 'coordina varios módulos y planes largos',
  default: 'el orquestador de siempre',
}

const STATE_LABEL: Record<SubtaskRun['state'], string> = {
  queued: 'en cola',
  running: 'trabajando',
  delivered: 'entregó',
  failed: 'falló',
  cancelled: 'detenido',
}

const STATE_TONE: Record<SubtaskRun['state'], string> = { queued: 'steel', running: 'amber', delivered: 'sage', failed: 'coral', cancelled: 'steel' }

export const fmtElapsed = (ms: number): string => {
  const s = Math.max(0, Math.round(ms / 1000))
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`
}

/* ── The bar above the composer: who orchestrates, who works, and what is installed but not added yet. ── */

interface BarProps {
  options: OrchestrateOptions
  orchestrator: string
  orchestratorModel: string
  pool: string[]
  agentModels: Record<string, string>
  onOrchestrator: (name: string) => void
  onOrchestratorModel: (model: string) => void
  onPool: (pool: string[]) => void
  onAgentModel: (agent: string, model: string) => void
  scout: string
  onScout: (scout: string) => void
  onAdd: (id: string) => void
  onAddLocal?: (model: string) => void
  adding: string | null
  localModels?: string[]
}

export const OrchestrateBar: React.FC<BarProps> = ({
  options,
  orchestrator,
  orchestratorModel,
  pool,
  agentModels,
  onOrchestrator,
  onOrchestratorModel,
  onPool,
  onAgentModel,
  scout,
  onScout,
  onAdd,
  onAddLocal,
  adding,
  localModels = [],
}) => {
  const sug = options.suggested
  const hasOrch = options.orchestrators.length > 0
  const showSug = !!sug.name && sug.name !== orchestrator
  const orchObj = options.orchestrators.find((o) => o.name === orchestrator)
  const activeOrchModel = orchestratorModel || orchObj?.model || ''
  const orchModels = modelsFor(orchObj, activeOrchModel, localModels)
  const workers = options.pool.filter((a) => a.kind !== 'command' || pool.includes(a.name))
  const lanes = Math.min(4, new Set(pool).size)
  const toggle = (name: string) => onPool(pool.includes(name) ? pool.filter((n) => n !== name) : [...pool, name])
  return (
    <div className="orch-bar" role="group" aria-label="Orquestación">
      <label className="orch-pick">
        <span className="mono muted">Orquestador</span>
        <select className="field field-sm" value={orchestrator} disabled={!hasOrch} onChange={(e) => onOrchestrator(e.target.value)} aria-label="Orquestador">
          {hasOrch ? (
            options.orchestrators.map((o) => (
              <option key={o.name} value={o.name}>{o.name}</option>
            ))
          ) : (
            <option value="">Sin agente IA (añade uno →)</option>
          )}
        </select>
      </label>
      <label className="orch-pick orch-model-pick">
        <span className="mono muted">Modelo</span>
        {!hasOrch ? (
          <select className="field field-sm" value="" disabled aria-label="Modelo del orquestador">
            <option value="">—</option>
          </select>
        ) : orchModels.length > 0 ? (
          <select className="field field-sm" value={activeOrchModel} onChange={(e) => onOrchestratorModel(e.target.value)} aria-label="Modelo del orquestador">
            {orchModels.map((m) => <option key={m} value={m}>{shortModel(m)}</option>)}
          </select>
        ) : (
          <input className="field field-sm" value={activeOrchModel} placeholder="por defecto" onChange={(e) => onOrchestratorModel(e.target.value)} aria-label="Modelo del orquestador" />
        )}
      </label>
      {showSug && (
        <button type="button" className="orch-suggest" onClick={() => onOrchestrator(sug.name!)} title={`Para este objetivo encaja mejor ${sug.name}: ${REASON[sug.reason] ?? sug.reason}`}>
          <span className="dot" aria-hidden="true" />Sugerido: <b>{sug.name}</b> · {REASON[sug.reason] ?? sug.reason}
        </button>
      )}
      {options.scouts.length > 0 && (
        <label className="orch-pick" title="Un modelo gratis o barato lee el repositorio antes y entrega un resumen al agente de pago: el de pago va directo a la tarea y no gasta cuota explorando">
          <span className="mono muted">Lectura previa</span>
          <select className="field field-sm" value={scout} onChange={(e) => onScout(e.target.value)} aria-label="Lectura previa gratis">
            <option value="auto">Automática{options.suggested_scout ? ` · ${options.suggested_scout}` : ''}</option>
            {options.scouts.map((c) => <option key={c.name} value={c.name}>{c.name} · {c.tier === 'free' ? 'gratis' : 'barato'}</option>)}
            <option value="off">Sin lectura previa</option>
          </select>
        </label>
      )}
      <div className="orch-pool" role="group" aria-label="Subagentes disponibles">
        <span className="mono muted">Subagentes</span>
        {workers.map((a) => {
          const selected = pool.includes(a.name)
          const wCur = agentModels[a.name] || a.model || ''
          const wModels = modelsFor(a, wCur, localModels)
          return (
            <div key={a.name} className={`orch-worker ${selected ? 'on' : ''}`}>
              <button
                type="button"
                className="skill-chip orch-pill"
                aria-pressed={selected}
                disabled={!a.installed}
                onClick={() => toggle(a.name)}
                title={a.installed ? `${a.name}${wCur ? ` · ${wCur}` : ''}` : `${a.name} no está instalado aquí`}
              >
                {a.name}
              </button>
              {a.installed && wModels.length > 0 && (
                <select
                  className="field field-xs orch-worker-model"
                  value={wCur}
                  disabled={!selected}
                  aria-label={`Modelo de ${a.name}`}
                  onChange={(e) => onAgentModel(a.name, e.target.value)}
                >
                  {wModels.map((m) => <option key={m} value={m}>{shortModel(m)}</option>)}
                </select>
              )}
            </div>
          )
        })}
        {lanes > 0 && <span className="mono muted orch-lanes" title="Carriles paralelos simultáneos (máx. 4)">{`${lanes} carriles`}</span>}
        {workers.length === 0 && (options.installable.length > 0 || (onAddLocal && localModels.length > 0)) && (
          <span className="mono muted">· añade uno:</span>
        )}
        {options.installable.map((c) => (
          <button key={c.id} type="button" className="btn btn-quiet btn-xs orch-add" disabled={adding === c.id} onClick={() => onAdd(c.id)} title={`${c.label} está instalado pero no está en harness.toml`}>
            <Plus className="icon icon-xs" aria-hidden="true" />Añadir {c.id}
          </button>
        ))}
        {!hasOrch && onAddLocal && localModels.length > 0 && (
          <button
            type="button"
            className="btn btn-quiet btn-xs orch-add"
            disabled={adding === `local:${localModels[0]}`}
            onClick={() => onAddLocal(localModels[0])}
            title="Añadir este modelo local de Ollama como agente a harness.toml"
          >
            <Plus className="icon icon-xs" aria-hidden="true" />Añadir {shortModel(localModels[0])}
          </button>
        )}
      </div>
    </div>
  )
}

/* ── The critical desk: the plan, editable, before anything runs. ── */

interface DeskProps {
  plan: OrchestrationPlan
  options: OrchestrateOptions
  skills: SkillInfo[]
  canIsolate: boolean
  blocked: boolean
  busy: boolean
  localModels?: string[]
  onChange: (plan: OrchestrationPlan) => void
  onReplan: () => void
  onLaunch: () => void
  onDiscard: () => void
}

export const CriticalDesk: React.FC<DeskProps> = ({ plan, options, skills, canIsolate, blocked, busy, localModels = [], onChange, onReplan, onLaunch, onDiscard }) => {
  const edit = (i: number, patch: Partial<OrchestrationSubtask>) =>
    onChange({ ...plan, source: 'edited', subtasks: plan.subtasks.map((s, k) => (k === i ? { ...s, ...patch } : s)) })
  const remove = (i: number) => onChange({ ...plan, source: 'edited', subtasks: plan.subtasks.filter((_, k) => k !== i) })
  const add = () => {
    const used = new Set(plan.subtasks.map((s) => s.id))
    let n = plan.subtasks.length + 1
    while (used.has(`s${n}`)) n += 1
    const agent = plan.pool.find((a) => options.pool.some((p) => p.name === a)) ?? options.pool[0]?.name ?? plan.orchestrator
    const agentObj = options.pool.find((p) => p.name === agent)
    onChange({
      ...plan,
      source: 'edited',
      subtasks: [
        ...plan.subtasks,
        { id: `s${n}`, title: 'Nueva subtarea', agent, model: agentObj?.model ?? null, mode: 'readonly', skill: null, depends_on: [], scout: !!plan.scout && options.tiers[agent] === 'paid', task: '', criteria: '' },
      ],
    })
  }
  const n = plan.subtasks.length
  const incomplete = plan.subtasks.some((s) => !s.task.trim())
  const edits = plan.subtasks.filter((s) => s.mode === 'isolated').length
  const planOrchObj = options.orchestrators.find((o) => o.name === plan.orchestrator)
  const planOrchModel = plan.orchestrator_model ?? planOrchObj?.model ?? ''
  const planOrchModels = modelsFor(planOrchObj, planOrchModel, localModels)
  return (
    <section className="orch-root orch-desk stagger-in" aria-label="Mesa crítica de delegación">
      <header className="orch-head">
        <Workflow className="icon" aria-hidden="true" />
        <b>Mesa crítica de delegación</b>
        <span className="mono muted">orquesta {plan.orchestrator}{planOrchModel ? ` · ${shortModel(planOrchModel)}` : ''}</span>
        <span className="grow" />
        <button type="button" className="btn btn-quiet btn-xs" onClick={onDiscard}>Descartar</button>
      </header>
      <p className="orch-goal"><span className="mono muted">Objetivo</span> {plan.goal}</p>
      {plan.summary && <p className="orch-summary">{plan.summary}</p>}
      {plan.source === 'fallback' && <div className="banner warn orch-banner" role="status"><span>{plan.note || 'Propuesta del harness: edítala antes de lanzar.'}</span></div>}

      <ol className="orch-list">
        {plan.subtasks.map((s, i) => {
          const workerObj = options.pool.find((a) => a.name === s.agent)
          const subModel = s.model ?? workerObj?.model ?? ''
          const subModels = modelsFor(workerObj, subModel, localModels)
          return (
            <li key={s.id} className="orch-card stagger-in" style={{ ['--i' as string]: Math.min(i, 7) }}>
              <div className="orch-card-head">
                <span className="orch-num mono">{i + 1}</span>
                <input className="field field-sm orch-title" value={s.title} maxLength={80} aria-label={`Título de la subtarea ${i + 1}`} onChange={(e) => edit(i, { title: e.target.value })} />
                {s.depends_on?.length > 0 && <span className="chip mono">depende de {s.depends_on.join(', ')}</span>}
                <button type="button" className="btn btn-quiet btn-icon btn-xs" onClick={() => remove(i)} aria-label={`Quitar la subtarea ${i + 1}`} disabled={n <= 1}>
                  <Trash2 className="icon icon-sm" />
                </button>
              </div>
              <div className="orch-controls">
                <label className="orch-field">
                  <span className="mono muted">Agente</span>
                  <select
                    className="field field-sm"
                    value={s.agent}
                    aria-label={`Agente de la subtarea ${i + 1}`}
                    onChange={(e) => {
                      const next = e.target.value
                      const nextObj = options.pool.find((a) => a.name === next)
                      edit(i, { agent: next, model: nextObj?.model ?? null })
                    }}
                  >
                    {options.pool.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
                  </select>
                </label>
                <label className="orch-field">
                  <span className="mono muted">Modelo</span>
                  {subModels.length > 0 ? (
                    <select className="field field-sm" value={subModel} aria-label={`Modelo de la subtarea ${i + 1}`} onChange={(e) => edit(i, { model: e.target.value || null })}>
                      {subModels.map((m) => <option key={m} value={m}>{shortModel(m)}</option>)}
                    </select>
                  ) : (
                    <input className="field field-sm" value={subModel} placeholder="por defecto" aria-label={`Modelo de la subtarea ${i + 1}`} onChange={(e) => edit(i, { model: e.target.value || null })} />
                  )}
                </label>
                <div className="seg orch-mode" role="group" aria-label={`Modo de la subtarea ${i + 1}`}>
                  <button type="button" aria-pressed={s.mode === 'readonly'} onClick={() => edit(i, { mode: 'readonly' })}><Eye className="icon icon-xs" aria-hidden="true" />Lectura (paralelo)</button>
                  <button type="button" aria-pressed={s.mode === 'isolated'} disabled={!canIsolate && s.mode !== 'isolated'} title={canIsolate ? 'Edita en su propio git worktree' : 'Necesita un repo git con al menos un commit: sin él correría en solo lectura'} onClick={() => edit(i, { mode: 'isolated' })}>
                    <GitBranch className="icon icon-xs" aria-hidden="true" />Edición (worktree)
                  </button>
                </div>
                <label className="orch-field">
                  <span className="mono muted">Skill</span>
                  <select className="field field-sm" value={s.skill ?? ''} aria-label={`Skill de la subtarea ${i + 1}`} onChange={(e) => edit(i, { skill: e.target.value || null })}>
                    <option value="">sin skill</option>
                    {skills.map((sk) => <option key={sk.name} value={sk.name}>{sk.name}</option>)}
                  </select>
                </label>
              </div>
              {plan.scout && (
                <label className="orch-field wide orch-scout" title={`${plan.scout} lee el repositorio antes y le pasa un resumen a ${s.agent}`}>
                  <input type="checkbox" checked={s.scout} aria-label={`Lectura previa de la subtarea ${i + 1}`} onChange={(e) => edit(i, { scout: e.target.checked })} />
                  <span className="mono muted">Lectura previa por {plan.scout}: {s.agent} va directo a la tarea</span>
                </label>
              )}
              <label className="orch-field wide">
                <span className="mono muted">Tarea</span>
                <textarea className="field orch-task" rows={2} value={s.task} aria-label={`Tarea de la subtarea ${i + 1}`} placeholder="Qué debe hacer este agente, acotado y preciso" onChange={(e) => edit(i, { task: e.target.value })} />
              </label>
              <label className="orch-field wide orch-crit-field">
                <span className="mono">Criterio crítico de aceptación</span>
                <textarea className="field orch-crit" rows={2} value={s.criteria} aria-label={`Criterio de la subtarea ${i + 1}`} placeholder="Qué debe demostrar su entrega para que la aceptes" onChange={(e) => edit(i, { criteria: e.target.value })} />
              </label>
            </li>
          )
        })}
      </ol>

      <footer className="orch-foot">
        <button type="button" className="btn btn-quiet btn-xs" onClick={add} disabled={n >= 8}><Plus className="icon icon-sm" aria-hidden="true" />Subtarea</button>
        <label className="orch-pick">
          <span className="mono muted">Orquestador</span>
          <select
            className="field field-sm"
            value={plan.orchestrator}
            aria-label="Orquestador del plan"
            onChange={(e) => {
              const next = e.target.value
              const nextObj = options.orchestrators.find((o) => o.name === next)
              onChange({ ...plan, orchestrator: next, orchestrator_model: nextObj?.model ?? null, source: 'edited' })
            }}
          >
            {options.orchestrators.map((o) => <option key={o.name} value={o.name}>{o.name}</option>)}
          </select>
        </label>
        <label className="orch-pick">
          <span className="mono muted">Modelo</span>
          {planOrchModels.length > 0 ? (
            <select
              className="field field-sm"
              value={planOrchModel}
              aria-label="Modelo del orquestador del plan"
              onChange={(e) => onChange({ ...plan, orchestrator_model: e.target.value || null, source: 'edited' })}
            >
              {planOrchModels.map((m) => <option key={m} value={m}>{shortModel(m)}</option>)}
            </select>
          ) : (
            <input
              className="field field-sm"
              value={planOrchModel}
              placeholder="por defecto"
              aria-label="Modelo del orquestador del plan"
              onChange={(e) => onChange({ ...plan, orchestrator_model: e.target.value || null, source: 'edited' })}
            />
          )}
        </label>
        <button type="button" className="btn btn-quiet btn-xs" onClick={onReplan} disabled={busy} title="Pide un plan nuevo al orquestador elegido: reemplaza lo que editaste">
          <RefreshCw className="icon icon-sm" aria-hidden="true" />Re-planificar con {plan.orchestrator}
        </button>
        <span className="grow" />
        {edits > 0 && !canIsolate && <span className="mono muted">sin repo git: correrán en solo lectura</span>}
        <button type="button" className="btn btn-primary btn-sm orch-launch" onClick={onLaunch} disabled={busy || blocked || n === 0 || incomplete}>
          <Play className="icon icon-sm" aria-hidden="true" />
          {n === 1 ? 'Lanzar 1 subagente' : `Lanzar ${n} subagentes en paralelo`}
        </button>
      </footer>
      {blocked && <p className="mono muted orch-blocked">Hay una ejecución en curso en esta sesión: espera a que termine para lanzar.</p>}
    </section>
  )
}

/* ── What happens after launch (and what stays in the conversation): every subagent side by side, then the synthesis. ── */

interface LiveProps {
  orch: OrchestrationState
  live: boolean
  onOpenTask?: (id: number) => void
  onStop?: () => void
}

const Elapsed: React.FC<{ s: SubtaskRun; at: number; now: number }> = ({ s, at, now }) => {
  const ms = s.state === 'running' ? s.elapsed_ms + Math.max(0, now - at) : s.duration_ms ?? s.elapsed_ms
  return <span className="mono muted orch-time">{s.state === 'queued' ? '—' : fmtElapsed(ms)}</span>
}

export const OrchestrationLive: React.FC<LiveProps> = ({ orch, live, onOpenTask, onStop }) => {
  const [now, setNow] = useState(() => Date.now())
  const at = useMemo(() => Date.now(), [orch])
  const running = orch.subtasks.some((s) => s.state === 'running')
  useEffect(() => {
    if (!live || !running) return
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [live, running])
  const done = orch.subtasks.filter((s) => s.state === 'delivered').length
  const failed = orch.subtasks.filter((s) => s.state === 'failed').length
  const stopped = orch.subtasks.filter((s) => s.state === 'cancelled').length
  const statusSummary = [
    `${done}/${orch.subtasks.length} listos`,
    failed ? `${failed} fallaron` : '',
    stopped ? `${stopped} detenidos` : '',
    `orquesta ${orch.orchestrator}${orch.orchestrator_model ? ` · ${shortModel(orch.orchestrator_model)}` : ''}`,
  ].filter(Boolean).join(' · ')
  return (
    <section className="orch-root orch-live" aria-label="Subagentes en paralelo">
      <header className="orch-head">
        <Workflow className="icon" aria-hidden="true" />
        <b>Subagentes en paralelo</b>
        <span className="mono muted">{statusSummary}</span>
        <span className="grow" />
        {live && onStop && <button type="button" className="btn btn-xs" onClick={onStop}><Square className="icon icon-xs" aria-hidden="true" />Detener</button>}
      </header>
      <ol className="orch-grid">
        {orch.subtasks.map((s, i) => (
          <li key={s.id} className={`orch-card stagger-in state-${s.state}`} style={{ ['--i' as string]: Math.min(i, 7) }}>
            <div className="orch-card-head">
              <span className="orch-agent">
                <FamilyEmblem family={s.family || familyFor(s.agent)} size={14} />
                <b>{s.agent}</b>
                {s.model && <small className="mono muted orch-sub-model">{shortModel(s.model)}</small>}
                {s.state === 'running' && <span className="live-pulse" aria-hidden="true" />}
              </span>
              <span className={`pill-mini ${STATE_TONE[s.state]}`}>{STATE_LABEL[s.state]}</span>
              <span className="grow" />
              <Elapsed s={s} at={at} now={now} />
            </div>
            <h4 className="orch-card-title">{s.title}</h4>
            <div className="orch-meta">
              <span className="chip">{s.mode === 'isolated' ? 'edición · worktree' : 'lectura'}</span>
              {s.skill && <span className="chip">{s.skill}</span>}
              {s.task_id != null && <button type="button" className="task-badge-btn" onClick={() => onOpenTask?.(s.task_id!)}>Board #{pad(s.task_id)} →</button>}
            </div>
            <p className="orch-crit-line"><span className="mono">Criterio</span> {s.criteria || 'sin criterio'}</p>
            {s.note && <p className="orch-note mono">{s.note}</p>}
            {s.error && <p className="verdict-err" role="alert">{s.error}</p>}
            {s.brief && <details className="orch-more"><summary>Lectura previa{s.scout_cached ? ' (reutilizada)' : s.scout_ms != null ? ` · ${(s.scout_ms / 1000).toFixed(1)} s` : ''}</summary><pre className="delivered">{s.brief}</pre></details>}
            {s.result && <details className="orch-more"><summary>Entrega</summary><pre className="delivered">{s.result}</pre></details>}
            {s.diff && <details className="orch-more"><summary>Diff · worktree {s.worktree?.key}</summary><DiffViewer diffText={s.diff} /></details>}
          </li>
        ))}
      </ol>
      {orch.phase === 'synthesizing' && (
        <div className="orch-synth pending" role="status"><Loader2 className="icon spin icon-sm" aria-hidden="true" /><span>{orch.orchestrator} está sintetizando las entregas…</span></div>
      )}
      {orch.synthesis && (orch.phase === 'done' || orch.phase === 'stopped') && (
        <section className="orch-synth" aria-label="Síntesis final" aria-live="polite">
          <h4>Síntesis final · {orch.orchestrator}{orch.orchestrator_model ? ` · ${shortModel(orch.orchestrator_model)}` : ''}</h4>
          <div className="turn-body">{orch.synthesis}</div>
        </section>
      )}
    </section>
  )
}
