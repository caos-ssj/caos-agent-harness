import React from 'react'
import { SessionItem, RepositoryItem } from '../api'
import {
  FolderGit2,
  Plus,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Zap,
} from 'lucide-react'

interface SidebarProps {
  isCollapsed: boolean
  onToggleCollapse: () => void
  sessions: SessionItem[]
  currentSessionId: string | null
  onSelectSession: (id: string) => void
  onCreateSession: () => void
  onDeleteSession: (id: string) => void
  repositories: RepositoryItem[]
  activeRepo: string
  onSelectRepo: (repo: string) => void
}

export const Sidebar: React.FC<SidebarProps> = ({
  isCollapsed,
  onToggleCollapse,
  sessions,
  currentSessionId,
  onSelectSession,
  onCreateSession,
  onDeleteSession,
  repositories,
  activeRepo,
  onSelectRepo,
}) => {
  if (isCollapsed) {
    return (
      <div className="app-sidebar w-12 border-r border-caos-borde bg-caos-tinta flex flex-col items-center py-4 space-y-4 h-full min-h-0 shrink-0">
        <button
          onClick={onToggleCollapse}
          aria-label="Expand sidebar"
          title="Expand sidebar"
          className="p-2 border border-caos-borde bg-caos-negro text-caos-gris hover:text-caos-hueso transition-colors cursor-pointer"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
        <button
          onClick={onCreateSession}
          aria-label="New session"
          title="New session"
          className="p-2 border border-caos-ambar bg-caos-ambarMuted text-caos-ambar hover:bg-caos-ambar hover:text-caos-negro transition-colors cursor-pointer"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>
    )
  }

  return (
    <div className="app-sidebar w-72 border-r border-caos-borde bg-caos-tinta flex flex-col h-full min-h-0 shrink-0">
      {/* 1. Selector de Repositorio Activo */}
      <div className="p-3.5 border-b border-caos-borde bg-caos-negro space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold text-caos-tenue uppercase tracking-wider flex items-center gap-1.5 font-mono">
            <FolderGit2 className="w-3.5 h-3.5 text-caos-ambar" />
            <span>Workspace</span>
          </span>
          <button
            onClick={onToggleCollapse}
            aria-label="Colapsar barra lateral"
            title="Colapsar barra lateral"
            className="p-1 text-caos-tenue hover:text-caos-hueso cursor-pointer"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        </div>

        <select
          aria-label="Workspace"
          value={activeRepo}
          onChange={(e) => onSelectRepo(e.target.value)}
          className="w-full p-2 bg-caos-tinta border border-caos-borde text-caos-hueso text-xs font-mono focus:border-caos-ambar focus:outline-none cursor-pointer"
        >
          {repositories.map((repo) => (
            <option key={repo.name} value={repo.name}>
              {repo.name}
            </option>
          ))}
        </select>
      </div>

      {/* 2. Botón Nueva Sesión */}
      <div className="p-3 border-b border-caos-borde">
        <button
          onClick={onCreateSession}
          className="w-full py-2 px-3 border border-caos-borde bg-caos-negro hover:border-caos-ambar text-caos-hueso text-xs font-bold uppercase tracking-wider flex items-center justify-center gap-2 transition-all cursor-pointer shadow-sm"
        >
          <Plus className="w-3.5 h-3.5 text-caos-ambar" />
          <span>New session</span>
        </button>
      </div>

      {/* 3. Lista de Sesiones Guardadas */}
      <div className="flex-1 overflow-y-auto divide-y divide-caos-borde">
        <div className="px-3.5 py-2 text-[10px] font-bold text-caos-tenue uppercase tracking-wider font-mono">
          Sessions ({sessions.length})
        </div>

        {sessions.map((sess) => {
          const isActive = currentSessionId === sess.id

          return (
            <div
              key={sess.id}
              onClick={() => onSelectSession(sess.id)}
              className={`p-3 cursor-pointer transition-all border-l-2 flex items-start justify-between gap-2 ${
                isActive
                  ? 'border-l-caos-ambar bg-caos-tintaElevada'
                  : 'border-l-transparent hover:bg-caos-negro'
              }`}
            >
              <div className="flex-1 min-w-0 space-y-1">
                <div className="flex items-center gap-1.5">
                  {sess.mode === 'plan' ? (
                    <Sparkles className="w-3 h-3 text-caos-ambar shrink-0" />
                  ) : (
                    <Zap className="w-3 h-3 text-caos-greenText shrink-0" />
                  )}
                  <span className="text-xs font-semibold text-caos-hueso truncate">
                    {sess.title}
                  </span>
                </div>

                <div className="flex items-center gap-2 text-[10px] text-caos-tenue font-mono">
                  <span>{sess.messages_count} msgs</span>
                  <span>•</span>
                  <span>{new Date(sess.updated_at * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' })}</span>
                </div>
              </div>

              {sessions.length > 1 && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    if (window.confirm(`Delete the session "${sess.title}"?`)) {
                      onDeleteSession(sess.id)
                    }
                  }}
                  title="Delete session"
                  className="p-1 text-caos-tenue hover:text-caos-redText transition-colors cursor-pointer"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
