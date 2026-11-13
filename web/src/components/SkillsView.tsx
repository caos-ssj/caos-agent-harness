import React, { useEffect, useMemo, useState } from 'react'
import { Copy, Eye, Pencil, Plus, Search, Wrench } from '../icons'
import { api, SkillInfo, ToolInfo } from '../api'
import { CAT_ACCENT, CAT_ORDER, catOf, groupSkills } from '../skillCats'
import { Markdown } from './Markdown'

interface Props {
  skills: SkillInfo[]
  onSkillsChanged?: () => void
  onUseSkill?: (name: string) => void
}

const SLUG = /^[a-z0-9][a-z0-9-]{1,48}$/
const NEW = '__new__'

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
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => { api.getTools().then((r) => setTools(r.tools || [])).catch(() => undefined) }, [])

  const visible = useMemo(() => skills.filter((s) => filter === 'all' || (filter === 'local' ? !!s.local : !s.local)), [skills, filter])
  const groups = useMemo(() => groupSkills(visible, q), [visible, q])
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
      await api.cloneSkill(current.name)
      setNote(`«${current.name}» clonado al proyecto: ya puedes editarlo`)
      onSkillsChanged?.(); setMode('edit')
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
            {tab === 'skills' && <button type="button" className="btn btn-primary btn-sm" onClick={() => { setSel(NEW); setDraft({ name: '', description: '', category: 'Proyecto', body: '# Instrucciones\n\n- ' }); setMode('edit'); setErr(null) }}><Plus className="icon" style={{ width: 14, height: 14 }} />Nuevo Skill</button>}
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
                <label className="search-inline"><Search className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" /><input className="field field-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filtrar skills…" aria-label="Filtrar skills" /></label>
                <div className="seg" role="group" aria-label="Origen">
                  {(['all', 'local', 'bundle'] as const).map((f) => <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>{f === 'all' ? 'Todos' : f === 'local' ? 'Locales' : 'Bundle'}</button>)}
                </div>
              </div>
              <div className="skills-scroll">
                {groups.map(({ cat, items }) => (
                  <section key={cat} className="skill-group" style={{ ['--cat' as string]: CAT_ACCENT[cat] || 'var(--ink-3)' }}>
                    <h3>{cat} <span className="chip">{items.length}</span></h3>
                    {items.map((s) => (
                      <button key={s.name} type="button" className={`skill-item ${sel === s.name ? 'on' : ''}`} aria-current={sel === s.name ? 'true' : undefined} onClick={() => { setSel(s.name); setErr(null) }}>
                        <span className="skill-item-head"><b className="mono">{s.name}</b>
                          <span className="skill-tags">{s.local ? <span className="chip steel-chip">local</span> : <span className="chip dim">bundle</span>}</span></span>
                        <small>{s.description}</small>
                      </button>
                    ))}
                  </section>
                ))}
                {groups.length === 0 && <p className="muted mono" style={{ padding: 12 }}>Ningún skill coincide.</p>}
              </div>
            </aside>

            <section className="skill-detail card" aria-label="Detalle del skill">
              {!current && !creating ? <p className="muted mono">Elige un skill de la lista.</p> : (
                <>
                  <div className="skill-detail-head">
                    <div>
                      <h2 className="mono">{creating ? 'Nuevo skill' : current!.name}</h2>
                      <div className="skill-tags">{creating || current?.local ? <span className="chip steel-chip">local del proyecto</span> : <span className="chip dim">bundle · solo lectura</span>}{current?.team_shareable === false && <span className="chip amber-chip">solo local</span>}</div>
                    </div>
                    <div className="skill-actions">
                      {editable && !creating && <div className="seg" role="group" aria-label="Modo"><button type="button" aria-pressed={mode === 'edit'} onClick={() => setMode('edit')}><Pencil className="icon" style={{ width: 12, height: 12 }} />Editar</button><button type="button" aria-pressed={mode === 'preview'} onClick={() => setMode('preview')}><Eye className="icon" style={{ width: 12, height: 12 }} />Vista previa</button></div>}
                      {current && <button type="button" className="btn btn-sm" onClick={() => onUseSkill?.(current.name)}><Wrench className="icon" style={{ width: 13, height: 13 }} />Usar en Console</button>}
                      {current && !current.local && <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void clone()}><Copy className="icon" style={{ width: 13, height: 13 }} />Clonar a Proyecto</button>}
                      {editable && <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void save()}>Guardar</button>}
                    </div>
                  </div>
                  {err && <p className="verdict-err" role="alert">{err}</p>}
                  {editable && mode === 'edit' ? (
                    <div className="skill-form">
                      <div className="form-2col">
                        <label>Nombre (slug)<input className="field field-sm" value={draft.name} disabled={!creating} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="mi-skill" /></label>
                        <label>Categoría<select className="select" value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })}>{[...new Set([...CAT_ORDER, draft.category])].map((c) => <option key={c} value={c}>{c}</option>)}</select></label>
                      </div>
                      <label>Descripción<input className="field field-sm" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} placeholder="Cuándo debe usar un agente este skill (mín. 8 caracteres)" /></label>
                      <label>SKILL.md<textarea className="field skill-body" value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} rows={16} spellCheck={false} /></label>
                    </div>
                  ) : (
                    <div className="skill-read">
                      <p className="skill-desc">{current?.description ?? draft.description}</p>
                      <Markdown text={current?.body ?? draft.body} />
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
  <div className="tool-mcp-row"><span className="mono bone">{t.name}</span><span className="muted mono" title={t.summary}>{t.summary}</span>
    <span className={`pill-mini ${t.status === 'online' || t.status === 'ready' ? 'sage' : t.status === 'offline' ? 'coral' : ''}`}>{t.status}</span></div>
)
