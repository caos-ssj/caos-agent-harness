import React from 'react'
import { BarChart3, BookOpen, Command, LayoutGrid, Play, Server, SlidersHorizontal, Terminal } from 'lucide-react'
import { View } from '../lib'
import { WorkspaceMenu } from './WorkspaceMenu'

interface HeaderProps {
  project: string
  root?: string
  onSwitched: () => void
  sample: boolean
  view: View
  onView: (v: View) => void
  needsYou: number
  runnable: number
  running: boolean
  onRun: () => void
  onOpenPalette: () => void
  onTogglePrefs: () => void
  prefsOpen: boolean
}

const TABS: Array<[View, string, React.ElementType]> = [
  ['console', 'Console', Terminal],
  ['board', 'Board', LayoutGrid],
  ['providers', 'Providers', Server],
  ['measured', 'Measured', BarChart3],
  ['skills', 'Skills', BookOpen],
]

export const Header: React.FC<HeaderProps> = ({ project, root, onSwitched, sample, view, onView, needsYou, runnable, running, onRun, onOpenPalette, onTogglePrefs, prefsOpen }) => (
  <header className="topbar">
    <div className="brand">
      <span className="brand-name">caos</span>
      <span className="brand-sub">harness</span>
    </div>
    <WorkspaceMenu project={project} root={root} onSwitched={onSwitched} />
    {sample && <span className="sample-tag" title="The tasks and answers on this board are made-up examples">Sample data</span>}
    <nav className="tabs" aria-label="Views">
      {TABS.map(([id, label, Icon]) => (
        <button key={id} type="button" aria-current={view === id ? 'page' : undefined} onClick={() => onView(id)} title={label} aria-label={label}>
          <Icon className="icon" aria-hidden="true" />
          <span className="label">{label}</span>
          {id === 'board' && needsYou > 0 && <span className="count" role="img" aria-label={`${needsYou} need you`}>{needsYou}</span>}
        </button>
      ))}
    </nav>
    <div className="topbar-tools">
      <button type="button" className="search-btn" onClick={onOpenPalette} aria-label="Open the command palette">
        <Command className="icon" style={{ width: 16, height: 16 }} aria-hidden="true" />
        <span className="grow">Search or run…</span>
        <span className="kbd" aria-hidden="true">⌘K</span>
      </button>
      <button type="button" className="btn btn-quiet btn-icon" aria-label="Preferences" aria-expanded={prefsOpen} aria-haspopup="dialog" onClick={onTogglePrefs} title="Preferences: density, text size, start view">
        <SlidersHorizontal className="icon" aria-hidden="true" />
      </button>
      <button type="button" className="btn btn-primary btn-run" onClick={onRun} disabled={running || runnable === 0} aria-label={running ? 'Running' : `Run ${runnable} pending`} title={runnable === 0 ? 'Nothing is waiting for an agent' : `Send ${runnable} pending to their agents (R)`}>
        <Play className="icon" style={{ width: 15, height: 15 }} fill="currentColor" aria-hidden="true" />
        <span className="label">{running ? 'Running…' : `Run ${runnable}`}</span>
        <span className="run-n" aria-hidden="true">{runnable}</span>
      </button>
    </div>
  </header>
)
