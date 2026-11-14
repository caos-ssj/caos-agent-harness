import React, { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, ExternalLink, FolderGit2, FolderOpen, GitBranch, MessageSquare, Pencil, Plus, Search, Terminal, Trash2, Wrench } from '../icons'
import { api, PreflightResponse, ProviderItem, SessionItem, Workspace, WorkspaceStatus } from '../api'
import { isDesktop, openInFileManager, openInTerminal, pickWorkspaceFolder } from '../desktop'
import { ago } from '../lib'
import { ConfirmButton } from './ConfirmButton'

type GlobalSession = { id: string; title: string; mode: string; target?: string; messages_count: number; updated_at: number; workspace: string; workspace_path: string; current: boolean }

interface SidebarProps {
  collapsed: boolean
  onToggleCollapse: () => void
  scope: 'project' | 'global'
  project: string
  rootPath?: string
  providers: ProviderItem[]
  wsStatus: WorkspaceStatus | null
  toolsCount: number
  sessions: SessionItem[]
  activeSessionId?: string | null
  preflight: PreflightResponse | null
  onSelectSession: (id: string) => void
  onNewSession: () => void
  onRenameSession: (id: string, title: string) => void
  onDeleteSession: (id: string) => void
  onOpenPreflight: () => void
  onGoProviders: () => void
  onSwitchedWorkspace: (openSession?: string) => void
}

const VERDICT_DOT: Record<PreflightResponse['verdict'], string> = { ready: 'sage', warning: 'amber', blocked: 'coral' }
const VERDICT_WORD: Record<PreflightResponse['verdict'], string> = { ready: 'Listo', warning: 'Con avisos', blocked: 'Bloqueado' }
const readyProv = (p: ProviderItem) => p.status === 'online' || p.status === 'key_present' || p.status === 'ready'

/* Context only: which project, its branch and worktrees, every session (searchable, renamable, deletable), and the live
   state of the engines and the preflight. Navigation lives in the header, never here. */
export const Sidebar: React.FC<SidebarProps> = ({
  collapsed, onToggleCollapse, scope, project, rootPath, providers, wsStatus, toolsCount, sessions, activeSessionId, preflight,
  onSelectSession, onNewSession, onRenameSession, onDeleteSession, onOpenPreflight, onGoProviders, onSwitchedWorkspace,
}) => {
  const [wsOpen, setWsOpen] = useState(false)
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [addingWs, setAddingWs] = useState(false)
  const [newPath, setNewPath] = useState('')
  const [wsErr, setWsErr] = useState<string | null>(null)
  const [detectInfo, setDetectInfo] = useState<{ stacks: string[]; verify: string[] | null; engines: { name: string }[] } | null>(null)
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [globalSessions, setGlobalSessions] = useState<GlobalSession[]>([])
  const [now, setNow] = useState(() => Date.now())

  const loadWorkspaces = () => { api.getWorkspaces().then((r) => setWorkspaces(r.items || [])).catch(() => undefined) }
  useEffect(() => { if (wsOpen) loadWorkspaces() }, [wsOpen, project])
  useEffect(() => {
    if (scope !== 'global') return
    api.getGlobalSessions().then((r) => setGlobalSessions(r.sessions)).catch(() => undefined)
  }, [scope, sessions.length, project])
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 30000)
    return () => window.clearInterval(t)
  }, [])

  const ollama = providers.find((p) => p.id === 'ollama')
  const cloud = providers.filter((p) => p.id !== 'ollama')
  const cloudReady = cloud.filter(readyProv).length
  const dirtyCount = wsStatus?.dirty_files?.length ?? 0
  const wtCount = wsStatus?.worktrees?.length ?? 0

  const list = useMemo(() => {
    const q = query.trim().toLowerCase()
    const base = scope === 'global' ? globalSessions : sessions.map((s) => ({ id: s.id, title: s.title, mode: s.mode, target: s.target, messages_count: s.messages_count, updated_at: s.updated_at, workspace: project, workspace_path: rootPath || '', current: true }))
    return base.filter((s) => !q || s.title.toLowerCase().includes(q) || s.workspace.toLowerCase().includes(q)).sort((a, b) => b.updated_at - a.updated_at)
  }, [scope, globalSessions, sessions, query, project, rootPath])

  const handleSwitch = async (path: string, openSession?: string) => {
    try {
      await api.switchWorkspace(path)
      setWsOpen(false)
      setWsErr(null)
      onSwitchedWorkspace(openSession)
    } catch (e: any) {
      setWsErr(e.message || 'No se pudo cambiar de proyecto')
    }
  }
  const handleAddWorkspace = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newPath.trim()) return
    try {
      await api.addWorkspace(newPath.trim(), true)
      setNewPath('')
      setAddingWs(false)
      setWsOpen(false)
      setWsErr(null)
      onSwitchedWorkspace()
    } catch (err: any) {
      setWsErr(err.message || 'Ruta inválida')
    }
  }
  const desktop = isDesktop()
  const handlePickFolder = async () => {
    try {
      const chosen = await pickWorkspaceFolder(rootPath)
      if (!chosen) return
      await api.addWorkspace(chosen, true)
      await api.switchWorkspace(chosen)
      setAddingWs(false)
      setWsOpen(false)
      setWsErr(null)
      onSwitchedWorkspace()
    } catch (err: any) {
      setWsErr(err.message || 'No se pudo abrir la carpeta')
    }
  }
  const openSession = (s: GlobalSession) => {
    if (s.current) onSelectSession(s.id)
    else void handleSwitch(s.workspace_path, s.id)
  }
  const saveRename = () => {
    if (editing && editText.trim()) onRenameSession(editing, editText.trim())
    setEditing(null)
  }

  if (collapsed) return null

  return (
    <aside className="sidebar is-expanded" aria-label="Contexto del proyecto">
      <div className="sb-top">
        <button type="button" className="sb-ws-btn" aria-expanded={wsOpen} onClick={() => setWsOpen((o) => !o)} title={rootPath || project}>
          <FolderOpen className="icon" style={{ width: 15, height: 15, color: 'var(--champan)' }} aria-hidden="true" />
          <span className="sb-ws-name">{project || 'workspace'}</span>
          <ChevronDown className="icon" style={{ width: 13, height: 13, marginLeft: 'auto' }} aria-hidden="true" />
        </button>
        <button type="button" className="sb-collapse-btn" onClick={onToggleCollapse} aria-label="Colapsar sidebar" title="Colapsar"><ChevronLeft className="icon icon-sm" aria-hidden="true" /></button>
      </div>

      {wsOpen && (
        <div className="sb-ws-pop">
          {wsErr && <p className="err-text">{wsErr}</p>}
          <ul className="sb-ws-list">
            {workspaces.map((w) => (
              <li key={w.path} className={w.current ? 'active' : ''}>
                <button type="button" className="sb-ws-item" onClick={() => handleSwitch(w.path)}>
                  <b>{w.name}</b>
                  <small>{w.ready ? 'harness' : 'nuevo'} · {w.path}</small>
                </button>
                {!w.current && (
                  <button type="button" className="sb-ws-del" aria-label={`Quitar ${w.name}`} onClick={async () => { await api.removeWorkspace(w.path); loadWorkspaces() }}>
                    <Trash2 className="icon icon-xs" aria-hidden="true" />
                  </button>
                )}
              </li>
            ))}
          </ul>
          {!addingWs ? (
            <div className="sb-ws-actions">
              {desktop && (
                <button type="button" className="btn btn-primary btn-sm" style={{ width: '100%' }} onClick={() => void handlePickFolder()}>
                  <FolderOpen className="icon icon-sm" aria-hidden="true" />Explorar carpeta…
                </button>
              )}
              <button type="button" className="btn btn-quiet btn-sm" style={{ width: '100%' }} onClick={() => setAddingWs(true)}>
                <Plus className="icon icon-sm" aria-hidden="true" />Registrar ruta manual
              </button>
            </div>
          ) : (
            <form className="sb-ws-add" onSubmit={handleAddWorkspace}>
              <input className="field field-sm" value={newPath} onChange={(e) => { setNewPath(e.target.value); setDetectInfo(null) }} placeholder="/ruta/absoluta/proyecto" required autoFocus />
              {detectInfo && (
                <div className="sb-ws-detect muted mono">
                  {`stack: ${detectInfo.stacks.join(', ') || 'generic'} · verify: ${detectInfo.verify ? detectInfo.verify.join(' ') : '—'} · ${detectInfo.engines.map((e) => e.name).join(', ')}`}
                </div>
              )}
              <div className="row">
                <button type="submit" className="btn btn-primary btn-sm">Abrir</button>
                <button type="button" className="btn btn-quiet btn-sm" onClick={() => { if (newPath.trim()) api.detectWorkspace(newPath.trim()).then(setDetectInfo).catch((err: any) => setWsErr(err.message || 'Ruta inválida')) }}>Detectar</button>
                <button type="button" className="btn btn-quiet btn-sm" onClick={() => { setAddingWs(false); setDetectInfo(null) }}>Cancelar</button>
              </div>
            </form>
          )}
        </div>
      )}

      <div className="sb-repo" aria-label="Estado del repositorio">
        <span className="sb-repo-row"><GitBranch className="icon icon-sm" aria-hidden="true" /><span className="mono">{wsStatus?.git_repo === false ? 'sin git' : wsStatus?.branch || '—'}</span></span>
        <span className="sb-repo-row">
          <i className={`dot ${dirtyCount > 0 ? 'amber' : 'sage'}`} />
          <span>{dirtyCount > 0 ? `${dirtyCount} cambio(s) sin confirmar` : 'árbol limpio'}</span>
        </span>
        <span className="sb-repo-row muted"><FolderGit2 className="icon icon-sm" aria-hidden="true" /><span>{wtCount > 0 ? `${wtCount} worktree(s) aislado(s)` : 'sin worktrees'}</span></span>
        {desktop && rootPath && (
          <div className="sb-repo-bar">
            <button type="button" className="btn btn-quiet btn-xs" onClick={() => void openInFileManager(rootPath)} title="Abrir carpeta en el gestor de archivos"><ExternalLink className="icon icon-xs" aria-hidden="true" />Carpeta</button>
            <button type="button" className="btn btn-quiet btn-xs" onClick={() => void openInTerminal(rootPath)} title="Abrir terminal en este proyecto"><Terminal className="icon icon-xs" aria-hidden="true" />Terminal</button>
          </div>
        )}
      </div>

      <div className="sb-sessions">
        <div className="sb-sess-head">
          <span className="sb-sec-title">Sesiones {scope === 'global' ? '· todos los proyectos' : ''}</span>
          <button type="button" className="btn btn-xs" onClick={onNewSession} title="Nueva sesión"><Plus className="icon icon-xs" aria-hidden="true" />Nueva</button>
        </div>
        <div className="search-inline sb-search">
          <Search className="icon icon-sm" aria-hidden="true" />
          <input className="field field-sm" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar sesión…" aria-label="Buscar sesión" />
        </div>
        <ul className="sb-sess-list">
          {list.map((s) => {
            const active = s.current && s.id === activeSessionId
            return (
              <li key={`${s.workspace_path}:${s.id}`} className={active ? 'active' : ''}>
                {editing === s.id && s.current ? (
                  <form className="sb-rename" onSubmit={(e) => { e.preventDefault(); saveRename() }}>
                    <input className="field field-sm" autoFocus value={editText} maxLength={120} onChange={(e) => setEditText(e.target.value)} onBlur={saveRename} onKeyDown={(e) => { if (e.key === 'Escape') setEditing(null) }} />
                  </form>
                ) : (
                  <>
                    <button type="button" className="sb-sess-main" onClick={() => openSession(s)} title={s.title} aria-current={active ? 'true' : undefined}>
                      <MessageSquare className="icon" style={{ width: 13, height: 13, flex: 'none' }} aria-hidden="true" />
                      <span className="sb-sess-text">
                        <b>{s.title}</b>
                        <small>{scope === 'global' && !s.current ? `${s.workspace} · ` : ''}{ago(s.updated_at, now)} · {s.target || s.mode} · {s.messages_count} msg</small>
                      </span>
                    </button>
                    {s.current && (
                      <span className="sb-sess-tools">
                        <button type="button" className="x" aria-label={`Renombrar ${s.title}`} onClick={() => { setEditing(s.id); setEditText(s.title) }}><Pencil className="icon icon-xs" aria-hidden="true" /></button>
                        <ConfirmButton className="x" ariaLabel={`Borrar ${s.title}`} question={`¿Borrar «${s.title}»?`} confirmLabel="Borrar" onConfirm={() => onDeleteSession(s.id)}><Trash2 className="icon icon-xs" aria-hidden="true" /></ConfirmButton>
                      </span>
                    )}
                  </>
                )}
              </li>
            )
          })}
          {list.length === 0 && <li className="muted sb-empty">{query ? `Nada coincide con «${query}».` : 'Aún no hay sesiones.'}</li>}
        </ul>
      </div>

      <div className="sb-foot">
        <button type="button" className="sb-foot-row" onClick={onGoProviders} title="Abrir Models & Providers">
          <i className={`dot ${(ollama?.status === 'online' || cloudReady > 0) ? 'sage' : 'coral'}`} />
          <span>Ollama <b className="mono">{ollama?.models.length ?? 0}</b> <span>modelos</span> · <span>Nube</span> <b className="mono">{cloudReady}/{cloud.length}</b> <span>listos</span></span>
        </button>
        <button type="button" className="sb-foot-row" onClick={onOpenPreflight} title="Ver el preflight completo">
          <i className={`dot ${preflight ? VERDICT_DOT[preflight.verdict] : ''}`} />
          <span>Preflight <b>{preflight ? VERDICT_WORD[preflight.verdict] : '…'}</b></span>
          <ChevronRight className="icon" style={{ width: 13, height: 13, marginLeft: 'auto' }} aria-hidden="true" />
        </button>
        <span className="sb-foot-row muted"><Wrench className="icon icon-sm" aria-hidden="true" /><span>Tools y MCP <b className="mono">{toolsCount}</b></span></span>
      </div>
    </aside>
  )
}
