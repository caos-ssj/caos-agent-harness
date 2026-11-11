import React from 'react'
import { Command, Play, SlidersHorizontal } from 'lucide-react'
import { View } from '../lib'

interface HeaderProps {
  project: string
  sample: boolean
  view: View
  onView: (v: View) => void
  needsYou: number
  pending: number
  running: boolean
  onRun: () => void
  onOpenPalette: () => void
  onTogglePrefs: () => void
  prefsOpen: boolean
}

const VIEWS: Array<[View, string]> = [['desk', 'Desk'], ['console', 'Console'], ['library', 'Library']]

export const Header: React.FC<HeaderProps> = ({ project, sample, view, onView, needsYou, pending, running, onRun, onOpenPalette, onTogglePrefs, prefsOpen }) => (
  <header className="topbar">
    <div className="brand">
      <span className="brand-name">caos</span>
    </div>
    <div className="project" title="The project folder this server was started in">
      <b>{project || '…'}</b>
    </div>
    {sample && <span className="sample-tag" title="The tasks and answers on this board are made-up examples">Sample data</span>}
    <nav className="nav" aria-label="Views">
      {VIEWS.map(([id, label]) => (
        <button key={id} type="button" aria-current={view === id ? 'page' : undefined} onClick={() => onView(id)}>
          {label}
          {id === 'desk' && needsYou > 0 && <span className="count" aria-label={`${needsYou} need you`}>{needsYou}</span>}
        </button>
      ))}
    </nav>
    <div className="topbar-tools">
      <button type="button" className="search-btn" onClick={onOpenPalette} aria-label="Open the command palette">
        <Command size={15} aria-hidden="true" />
        <span className="grow">Search or run…</span>
        <span className="kbd" aria-hidden="true">⌘K</span>
      </button>
      <button type="button" className="btn btn-quiet btn-sm" aria-label="Preferences" aria-expanded={prefsOpen} aria-haspopup="dialog" onClick={onTogglePrefs} title="Preferences: density, start view">
        <SlidersHorizontal size={16} aria-hidden="true" />
      </button>
      <button type="button" className="btn btn-primary btn-run" onClick={onRun} disabled={running || pending === 0} title={pending === 0 ? 'Nothing is waiting for an agent' : `Send ${pending} pending to their agents (R)`}>
        <Play size={14} fill="currentColor" aria-hidden="true" />
        <span className="label">{running ? 'Running…' : `Run ${pending}`}</span>
      </button>
    </div>
  </header>
)
