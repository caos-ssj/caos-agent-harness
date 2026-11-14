import React, { useEffect, useMemo, useState } from 'react'
import { Copy, Eye, Pencil, Plus, Search, Sparkles, Wrench } from '../icons'
import { api, SkillInfo, SkillOverview, ToolInfo } from '../api'
import { CAT_ACCENT, catOf, groupSkillsByWorkflow } from '../skillCats'
import { Markdown } from './Markdown'
import { SkillLoop } from './SkillLoop'

interface Props {
  skills: SkillInfo[]
  onSkillsChanged?: () => void
  onUseSkill?: (name: string) => void
}

const SLUG = /^[a-z0-9][a-z0-9-]{1,48}$/
const NEW = '__new__'

const WORKFLOW_DESC: Record<string, string> = {
  'Planificar e Investigar': 'contexto, investigación y documentación',
  'Escribir Código': 'implementación, interfaz y arquitectura',
  'Auditar / QA': 'pruebas, verificación y cobertura',
  'Automatización y MCP': 'modelos, router y servidores MCP',
}

export const SkillsView: React.FC<Props> = ({ skills, onSkillsChanged, onUseSkill }) => {
  const [tab, setTab] = useState<'skills' | 'tools'>('skills')
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<'all' | 'local' | 'bundle'>('all')
  const [sel, setSel] = useState<string | null>(null)
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [draft, setDraft] = useState({ name: '', description: '', category: 'Proyecto', body: '' })
  const [mode, setMode] = useState<'edit' | 'preview'>('preview')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [err, setErr] = useState(null as string | null)

  useEffect(() => { api.getTools().then((r) => setTools(r.tools || [])).catch(() => undefined) }, [])
  const [loop, setLoop] = useState<{ rows: SkillOverview[]; min: number }>({ rows: [], min: 20 })
  const loadLoop = () => { api.getSkillEvidence().then((r) => setLoop({ rows: r.skills || [], min: r.min_decided })).catch(() => undefined) }
  useEffect(loadLoop, [skills.length])
  const loopOf = (name: string) => loop.rows.find((r) => r.skill === name)

  const visible = useMemo(() => skills.filter((s) => filter === 'all' || (filter === 'local' ? !!s.local : !s.local)), [skills, filter])
  const groups = useMemo(() => groupSkillsByWorkflow(visible, q), [visible, q])
  const current = sel && sel !== NEW ? skills.find((s) => s.name === sel) ?? null : null
  const creating = sel === NEW

  useEffect(() => {
    if (current) { setDraft({ name: current.name, description: current.description, category: catOf(current), body: current.body ?? '' }); setMode('preview'); setErr(null) }
  }, [current?.name, current?.body, current?.description]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!sel && skills.length) setSel(skills.find((s) => s.local)?.name ?? skills[0].name)
  }, [skills, sel])

  const editable = creating || !!current?.local
  const save = async () => {
    setBusy(true); setErr(null)
    try {
      const slug = draft.name.trim().toLowerCase()
      if (!SLUG.test(slug)) throw new Error('El nombre usa minúsculas, números y guiones (2–49 caracteres).')
      await api.saveSkill({ name: slug, description: draft.description.trim(), body: draft.body, category: draft.category })
      setNote(`«${slug}» guardado en .harness/skills`)
      onSkillsChanged?.(); setSel(slug); setMode('preview')
    } catch (e: any) { setErr(e.message || 'No se pudo guardar') } finally { setBusy(false) }
  }
  const clone = async () => {
    if (!current) return
    setBusy(true); setErr(null)
    try {
      const cloned = await api.cloneSkill(current.name)
      const slug = cloned?.name || current.name
      setNote(`«${slug}» clonado al proyecto: ya puedes editarlo`)
      onSkillsChanged?.(); setSel(slug); setMode('edit')
    } catch (e: any) { setErr(e.message || 'No se pudo clonar') } finally { setBusy(false) }
  }

  const byKind = (k: string) => tools.filter((t) => t.kind === k)
  const mcp = byKind('mcp')
  const harness = tools.filter((t) => t.kind !== 'mcp')

  return (
    <div className="page">
      <div className="page-inner skills-page">
        <div className="page-bar">
          <h1>Skills &amp; Tools</h1>
          <div className="page-bar-right">
            <div className="seg" role="tablist" aria-label="Skills o herramientas">
              <button type="button" role="tab" aria-selected={tab === 'skills'} aria-pressed={tab === 'skills'} onClick={() => setTab('skills')}>Skills ({skills.length})</button>
              <button type="button" role="tab" aria-selected={tab === 'tools'} aria-pressed={tab === 'tools'} onClick={() => setTab('tools')}>MCP &amp; Tools ({tools.length})</button>
            </div>
            {tab === 'skills' && (
              <button type="button" className="btn btn-sm" onClick={() => { setSel(NEW); setDraft({ name: '', description: '', category: 'Proyecto', body: '# Instrucciones\n\n- ' }); setMode('edit'); setErr(null) }}>
                <Plus className="icon icon-sm" />Nuevo Skill
              </button>
            )}
          </div>
        </div>
        {note && <div className="toast-strip" role="status">{note}</div>}

        {tab === 'tools' ? (
          <div className="tools-split">
            <section className="card prov-section"><div className="card-head"><h2>Servidores MCP ({mcp.length})</h2><span className="mono muted">de .mcp.json y del harness</span></div>
              <div className="tools-mcp-grid">{mcp.map((t) => <ToolRow key={t.id} t={t} />)}{mcp.length === 0 && <p className="muted mono">Ningún servidor MCP configurado.</p>}</div></section>
            <section className="card prov-section"><div className="card-head"><h2>Herramientas del harness ({harness.length})</h2><span className="mono muted">lo que un agente puede hacer aquí</span></div>
              <div className="tools-mcp-grid">{harness.map((t) => <ToolRow key={t.id} t={t} />)}</div></section>
          </div>
        ) : (
          <div className="skills-split">
            <aside className="skills-list card" aria-label="Lista de skills">
              <div className="skills-list-top">
                <label className="search-inline"><Search className="icon icon-sm" aria-hidden="true" /><input className="field field-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filtrar por flujo o nombre…" aria-label="Filtrar skills" /></label>
                <div className="seg" role="group" aria-label="Origen">
                  {(['all', 'local', 'bundle'] as const).map((f) => <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>{f === 'all' ? 'Todas' : f === 'local' ? 'Del Proyecto' : 'Incluidas'}</button>)}
                </div>
              </div>
              <div className="skills-scroll">
                {groups.map(({ cat, items }) => (
                  <section key={cat} className="skill-group" style={{ ['--cat' as string]: CAT_ACCENT[cat] || 'var(--ink-3)' }}>
                    <div className="skill-group-head">
                      <h3>{cat} <span className="pill-mini">{items.length}</span></h3>
                      {WORKFLOW_DESC[cat] && <small className="muted">{WORKFLOW_DESC[cat]}</small>}
                    </div>
                    {items.map((s) => {
                      const ev = loopOf(s.name)?.evidence
                      return (
                        <div key={s.name} className={`skill-item ${sel === s.name ? 'on' : ''}`}>
                          <button type="button" className="skill-item-main" aria-current={sel === s.name ? 'true' : undefined} onClick={() => { setSel(s.name); setErr(null) }}>
                            <span className="skill-item-head">
                              <span className="with-icon" style={{ minWidth: 0 }}>
                                <Sparkles className="icon icon-xs" />
                                <b className="mono">{s.name}</b>
                              </span>
                              <span className="skill-tags" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, flexShrink: 0 }}>
                                {ev && ev.decided > 0 ? (
                                  <span className="skill-rate" title="Aceptadas a la primera / decididas">{ev.first_pass}/{ev.decided}</span>
                                ) : (
                                  <span className={`pill-mini ${s.local ? 'steel' : ''}`}>{s.local ? 'proyecto' : 'incluida'}</span>
                                )}
                              </span>
                            </span>
                            <small className="skill-item-desc">{s.description}</small>
                          </button>
                          {onUseSkill && (
                            <button type="button" className="btn btn-quiet btn-xs skill-item-use" onClick={() => onUseSkill(s.name)} title={`Usar ${s.name} en Console`}>
                              Usar
                            </button>
                          )}
                        </div>
                      )
                    })}
                  </section>
                ))}
                {groups.length === 0 && <p className="muted mono" style={{ padding: 12 }}>Ningún skill coincide.</p>}
              </div>
            </aside>

            <section className="skill-detail card" aria-label="Detalle del skill">
              {!current && !creating ? <p className="muted mono">Elige un skill de la lista.</p> : (
                <>
                  <div className="skill-detail-head">
                    <div className="skill-detail-title">
                      <span className="skill-glyph-mini"><Sparkles className="icon" /></span>
                      <div>
                        <h2 className="mono">{creating ? 'Nuevo skill' : current!.name}</h2>
                        <div className="skill-tags">
                          {creating || current?.local ? <span className="pill-mini steel">local del proyecto</span> : <span className="pill-mini">bundle · solo lectura</span>}
                          {current?.team_shareable === false && <span className="pill-mini amber">solo local</span>}
                        </div>
                      </div>
                    </div>
                    <div className="skill-actions">
                      {editable && !creating && (
                        <div className="seg" role="group" aria-label="Modo">
                          <button type="button" aria-pressed={mode === 'edit'} onClick={() => setMode('edit')}><Pencil className="icon icon-xs" />Editar</button>
                          <button type="button" aria-pressed={mode === 'preview'} onClick={() => setMode('preview')}><Eye className="icon icon-xs" />Vista previa</button>
                        </div>
                      )}
                      {current && <button type="button" className={`btn ${mode !== 'edit' && current.local ? 'btn-primary ' : ''}btn-sm`} onClick={() => onUseSkill?.(current.name)}><Wrench className="icon icon-sm" />Usar en Console</button>}
                      {current && !current.local && <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void clone()}><Copy className="icon icon-sm" />Clonar a Proyecto</button>}
                      {editable && mode === 'edit' && <button type="button" className="btn btn-primary btn-sm" disabled={busy || !draft.name.trim() || !draft.body.trim()} onClick={() => void save()}>{busy ? 'Guardando…' : 'Guardar'}</button>}
                    </div>
                  </div>
                  {err && <div className="banner err" role="alert"><span>{err}</span></div>}

                  {editable && mode === 'edit' ? (
                    <div className="skill-editor">
                      <div className="form-2col">
                        <label>Nombre (slug)<input className="field field-sm mono" value={draft.name} disabled={!creating} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="mi-skill" /></label>
                        <label>Flujo / Categoría
                          <select className="select select-sm" value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })}>
                            {['Planificar e Investigar', 'Escribir Código', 'Auditar / QA', 'Automatización y MCP', 'Proyecto'].map((c) => <option key={c} value={c}>{c}</option>)}
                          </select>
                        </label>
                      </div>
                      <label>Descripción (1 línea)<input className="field field-sm" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} placeholder="Cuándo debe usarla el agente y qué resuelve" /></label>
                      <label className="skill-body-label">SKILL.md<textarea className="field mono skill-textarea" rows={16} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} /></label>
                    </div>
                  ) : (
                    <div className="skill-preview">
                      {current?.description && <p className="skill-lead">{current.description}</p>}
                      {current && loopOf(current.name) && (
                        <SkillLoop row={loopOf(current.name)!} minDecided={loop.min} onChanged={() => { loadLoop(); onSkillsChanged?.() }} />
                      )}
                      <Markdown text={current?.body || '(vacío)'} />
                    </div>
                  )}
                </>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  )
}

const ToolRow: React.FC<{ t: ToolInfo }> = ({ t }) => (
  <article className="tool-row">
    <div className="tool-row-top"><b>{t.name}</b><span className={`pill-mini ${t.status === 'ready' || t.status === 'online' ? 'sage' : ''}`}>{t.status}</span></div>
    <small className="mono muted">{t.summary}</small>
  </article>
)
