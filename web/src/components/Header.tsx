import React, { useEffect, useRef } from 'react'
import { FolderGit2, Gear, Globe, LayoutGrid, PanelLeft, Play, Search, SlidersHorizontal, Users, Workflow } from '../icons'
import { HouseEmblem } from '../emblems'
import { View, onTabKeys } from '../lib'

interface HeaderProps {
  project: string
  sample?: boolean
  view: View
  onView: (v: View) => void
  needsYou: number
  runnable: number
  running: boolean
  onRun: () => void
  onOpenPalette: () => void
  onTogglePrefs: () => void
  prefsOpen: boolean
  onToggleSidebar: () => void
  sidebarCollapsed: boolean
  scope: 'project' | 'global'
  onScope: (s: 'project' | 'global') => void
}

/* Six views in four places: the two you work in, and one for each kind of setup. The views of a group share a second row (see SubNav). */
export const GROUPS: Array<{ id: string; label: string; views: View[]; Icon: React.ElementType }> = [
  { id: 'run', label: 'Run', views: ['run'], Icon: Workflow },
  { id: 'board', label: 'Board', views: ['board'], Icon: LayoutGrid },
  { id: 'team', label: 'Team', views: ['skills', 'share'], Icon: Users },
  { id: 'system', label: 'System', views: ['providers', 'metrics'], Icon: Gear },
]

export const Header: React.FC<HeaderProps> = ({
  project,
  sample,
  view,
  onView,
  needsYou,
  runnable,
  running,
  onRun,
  onOpenPalette,
  onTogglePrefs,
  prefsOpen,
  onToggleSidebar,
  sidebarCollapsed,
  scope,
  onScope,
}) => {
  const barRef = useRef<HTMLElement>(null)
  useEffect(() => {
    const setH = () => {
      const h = barRef.current?.offsetHeight
      if (h) document.documentElement.style.setProperty('--topbar-h', `${h}px`)
    }
    setH()
    window.addEventListener('resize', setH)
    return () => window.removeEventListener('resize', setH)
  }, [])

  return (
    <header className="topbar" ref={barRef}>
      <div className="top-left">
        <button
          type="button"
          className="btn btn-quiet btn-icon btn-sm"
          onClick={onToggleSidebar}
          aria-label={sidebarCollapsed ? 'Expandir barra lateral' : 'Colapsar barra lateral'}
          title={sidebarCollapsed ? 'Expandir panel' : 'Colapsar panel'}
        >
          <PanelLeft className="icon" aria-hidden="true" />
        </button>
        <span className="brand-mark" aria-hidden="true"><HouseEmblem size={28} /></span>
        <span className="brand-name">caos</span>
        {project && <span className="repo-pill" title={project}>{project}</span>}
        {sample && <span className="pill-mini amber-chip">demo</span>}
      </div>

      <nav className="tabs" role="tablist" aria-label="Vistas principales" onKeyDown={onTabKeys}>
        {GROUPS.map(({ id, label, views, Icon }) => {
          const active = views.includes(view)
          return (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={active}
              tabIndex={active ? 0 : -1}
              data-tab={id}
              onClick={() => !active && onView(views[0])}
              title={label}
            >
              <Icon className="icon" aria-hidden="true" />
              <span className="label">{label}</span>
              <span className="short-label">{label}</span>
              {id === 'board' && needsYou > 0 && (
                <span className="tab-count" title={`${needsYou} esperando veredicto`}>
                  {needsYou}
                </span>
              )}
            </button>
          )
        })}
      </nav>

      <div className="top-actions">
        <div className="seg scope-seg" role="group" aria-label="Alcance: este proyecto o todos">
          <button type="button" aria-pressed={scope === 'project'} onClick={() => onScope('project')} title="Solo este proyecto"><FolderGit2 className="icon icon-sm" aria-hidden="true" />Proyecto</button>
          <button type="button" aria-pressed={scope === 'global'} onClick={() => onScope('global')} title="Todos los proyectos registrados"><Globe className="icon icon-sm" aria-hidden="true" />Global</button>
        </div>
        {runnable > 0 && (
          <button
            type="button"
            className="btn btn-amber btn-sm btn-run" data-count={runnable}
            disabled={running}
            onClick={onRun}
            title="Ejecutar tareas pendientes en sus agentes (r)"
          >
            <Play className="icon icon-sm" weight="fill" />
            <span className="label">{running ? 'Corriendo…' : `Ejecutar ${runnable}`}</span>
          </button>
        )}
        <button type="button" className="search-btn" onClick={onOpenPalette} title="Paleta de comandos (Ctrl/⌘ K)">
          <Search className="icon icon-sm" aria-hidden="true" />
          <span className="kbd">⌘K</span>
        </button>
        <button
          type="button"
          className="btn btn-quiet btn-icon btn-sm"
          aria-haspopup="dialog"
          aria-expanded={prefsOpen}
          aria-label="Preferencias"
          onClick={onTogglePrefs}
          title="Preferencias"
        >
          <SlidersHorizontal className="icon" aria-hidden="true" />
        </button>
      </div>
    </header>
  )
}
