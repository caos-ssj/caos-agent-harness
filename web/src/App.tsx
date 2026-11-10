import React, { useEffect, useState, useCallback } from 'react'
import {
  api,
  StateResponse,
  SessionItem,
  SessionDetail,
  RepositoryItem,
  ProviderItem,
} from './api'
import { Header } from './components/Header'
import { Sidebar } from './components/Sidebar'
import { HackerConsole } from './components/HackerConsole'
import { CommandBar } from './components/CommandBar'
import { Board } from './components/Board'
import { ProvidersView } from './components/ProvidersView'
import { StatsView } from './components/StatsView'
import { SkillsView } from './components/SkillsView'
import { CommandPaletteModal } from './components/CommandPaletteModal'
import { EnvironmentModal, EnvironmentSettings } from './components/EnvironmentModal'
import { AlertCircle } from 'lucide-react'

export const App: React.FC = () => {
  const [state, setState] = useState<StateResponse | null>(null)
  // Deep links: /?tab=board&task=12 opens the board with that task expanded.
  const query = new URLSearchParams(window.location.search)
  const tabFromUrl = ({ board: 'workstation', console: 'console', providers: 'providers', measured: 'stats', skills: 'skills' } as const)[query.get('tab') || ''] as
    | 'console' | 'workstation' | 'providers' | 'stats' | 'skills' | undefined
  const [activeTab, setActiveTab] = useState<'console' | 'workstation' | 'providers' | 'stats' | 'skills'>(tabFromUrl || 'console')
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(() => Number(query.get('task')) || null)
  const [showCreateTask, setShowCreateTask] = useState(false)

  // Sesiones de la Consola Hacker
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [currentSession, setCurrentSession] = useState<SessionDetail | null>(null)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => window.matchMedia('(max-width: 767px)').matches)

  // Repositorios y Proveedores
  const [repositories, setRepositories] = useState<RepositoryItem[]>([])
  const [activeRepo, setActiveRepo] = useState('')
  const [providers, setProviders] = useState<ProviderItem[]>([])

  // Modal de Paleta de Comandos (Ctrl+K)
  const [isPaletteOpen, setIsPaletteOpen] = useState(false)

  // Configuración de Personalización de Entorno CAOS
  const [isEnvModalOpen, setIsEnvModalOpen] = useState(false)
  const [envSettings, setEnvSettings] = useState<EnvironmentSettings>(() => {
    try {
      const saved = localStorage.getItem('caos_env_settings')
      if (saved) return JSON.parse(saved)
    } catch (e) {}
    return { accent: 'ambar', pattern: 'vignette', density: 'comfortable' }
  })

  const updateEnvSettings = (partial: Partial<EnvironmentSettings>) => {
    setEnvSettings((prev) => {
      const next = { ...prev, ...partial }
      try {
        localStorage.setItem('caos_env_settings', JSON.stringify(next))
      } catch (e) {}
      return next
    })
  }

  const loadState = useCallback(async (quiet = false) => {
    if (!quiet) setIsRefreshing(true)
    setError(null)
    try {
      const data = await api.getState()
      setState(data)
    } catch (err: any) {
      setError(err.message || 'Cannot reach the harness API on this machine. Is `caos-harness serve` still running?')
    } finally {
      if (!quiet) setIsRefreshing(false)
    }
  }, [])

  const loadSessions = useCallback(async () => {
    try {
      const list = await api.getSessions()
      setSessions(list)
      if (list.length > 0 && !currentSessionId) {
        setCurrentSessionId(list[0].id)
      }
    } catch (err) {
      console.error('Could not load sessions:', err)
    }
  }, [currentSessionId])

  const loadCurrentSession = useCallback(async (sid: string) => {
    try {
      const detail = await api.getSession(sid)
      setCurrentSession(detail)
    } catch (err) {
      console.error('Could not load the session:', err)
    }
  }, [])

  const loadProvidersAndRepos = useCallback(async () => {
    try {
      const [pRes, rRes] = await Promise.all([api.getProviders(), api.getRepositories()])
      setProviders(pRes.providers)
      setRepositories(rRes.filter((repo) => repo.current))
      if (rRes.length > 0 && !activeRepo) {
        setActiveRepo(rRes[0].name)
      }
    } catch (err) {
      console.error(err)
    }
  }, [activeRepo])

  // Carga inicial
  useEffect(() => {
    loadState()
    loadSessions()
    loadProvidersAndRepos()
  }, [loadState, loadSessions, loadProvidersAndRepos])

  // Cargar sesión cuando cambie el ID seleccionado
  useEffect(() => {
    if (currentSessionId) {
      loadCurrentSession(currentSessionId)
    }
  }, [currentSessionId, loadCurrentSession])

  // Atajo global Ctrl+K / ⌘K
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setIsPaletteOpen((prev) => !prev)
      }
    }
    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => window.removeEventListener('keydown', handleGlobalKeyDown)
  }, [])

  const handleCreateSession = async () => {
    try {
      const created = await api.createSession({
        project: activeRepo,
        mode: 'plan',
      })
      await loadSessions()
      setCurrentSessionId(created.id)
    } catch (err) {
      console.error('Could not create the session:', err)
    }
  }

  const handleDeleteSession = async (sid: string) => {
    try {
      await api.deleteSession(sid)
      await loadSessions()
      if (currentSessionId === sid) {
        setCurrentSessionId(null)
        setCurrentSession(null)
      }
    } catch (err) {
      console.error('Could not delete the session:', err)
    }
  }

  const handleRunPending = async () => {
    try {
      await api.runPending()
      loadState(true)
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div
      data-accent={envSettings.accent}
      data-density={envSettings.density}
      className={`h-[100dvh] w-full overflow-hidden flex flex-col font-sans bg-caos-negro text-caos-hueso ${
        envSettings.pattern === 'grid'
          ? 'bg-pattern-grid'
          : envSettings.pattern === 'vignette'
          ? 'bg-pattern-vignette'
          : ''
      }`}
    >
      {/* Cabecera Unificada Compacta */}
      <Header
        state={state}
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        onRunPending={handleRunPending}
        isRefreshing={isRefreshing}
        onRefresh={() => {
          loadState()
          loadSessions()
        }}
        onOpenPalette={() => setIsPaletteOpen(true)}
        onOpenEnvironment={() => setIsEnvModalOpen(true)}
        activeRepo={activeRepo}
      />

      {/* Espacio de Trabajo Principal (Llena el 100% de la ventana sin scroll externo) */}
      <main className="flex-1 min-h-0 w-full overflow-hidden flex flex-col">
        {error && (
          <div className="shrink-0 p-3 border-b border-caos-redText bg-caos-redMuted text-caos-redText text-xs font-semibold flex items-center justify-between px-4">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
            <button
              onClick={() => setError(null)}
              className="text-xs uppercase font-mono hover:underline cursor-pointer"
            >
              Close
            </button>
          </div>
        )}

        {/* Pestaña 1: Consola Hacker (Dominante) */}
        {activeTab === 'console' && (
          <div className="work-surface h-full w-full flex overflow-hidden relative">
            <div className={`${isSidebarCollapsed ? 'shrink-0' : 'absolute inset-y-0 left-0 z-20 shadow-2xl md:static md:shadow-none'} h-full`}>
            <Sidebar
              isCollapsed={isSidebarCollapsed}
              onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
              sessions={sessions}
              currentSessionId={currentSessionId}
              onSelectSession={(sid) => setCurrentSessionId(sid)}
              onCreateSession={handleCreateSession}
              onDeleteSession={handleDeleteSession}
              repositories={repositories}
              activeRepo={activeRepo}
              onSelectRepo={(repo) => setActiveRepo(repo)}
            />
            </div>

            <HackerConsole
              currentSession={currentSession}
              providers={providers}
              activeRepo={activeRepo}
              onMessageSent={() => {
                if (currentSessionId) loadCurrentSession(currentSessionId)
                loadSessions()
              }}
              onOpenPalette={() => setIsPaletteOpen(true)}
              onCreateSession={handleCreateSession}
            />
          </div>
        )}

        {/* Pestaña 2: Mesa de Encargos y Aprobaciones (Workstation) */}
        {activeTab === 'workstation' && (
          <div className="work-surface h-full w-full overflow-y-auto flex flex-col p-3 sm:p-4 max-w-[1700px] mx-auto">
            <div className="board-toolbar">
              <div>
                <h1>Board</h1>
                <p>Who holds what, what was delivered, and what is waiting for your verdict.</p>
              </div>
              <button type="button" className="board-create" aria-expanded={showCreateTask} aria-controls="new-task-form" onClick={() => setShowCreateTask(!showCreateTask)}>
                {showCreateTask ? 'Close' : 'New task'}
              </button>
            </div>
            <div id="new-task-form" className="shrink-0 mb-3" hidden={!showCreateTask}>
              <CommandBar
                agents={state?.agents || []}
                skills={state?.skills || []}
                tiers={state?.tiers || ['low', 'medium', 'high', 'critical']}
                onTaskCreated={() => loadState()}
              />
            </div>

            <div className="flex-1 min-h-[420px] overflow-hidden">
              <Board
                tasks={state?.tasks || []}
                agents={state?.agents || []}
                running={state?.running ?? false}
                selectedTaskId={selectedTaskId}
                onSelectTask={setSelectedTaskId}
                onChanged={() => loadState(true)}
              />
            </div>
          </div>
        )}

        {/* Pestaña 3: Proveedores, Modelos y Failover de Cuota */}
        {activeTab === 'providers' && (
          <div className="h-full w-full overflow-y-auto p-5 max-w-[1500px] mx-auto">
            <ProvidersView />
          </div>
        )}

        {/* Pestaña 4: Estadísticas y Costos */}
        {activeTab === 'stats' && (
          <div className="h-full w-full overflow-y-auto p-5 max-w-[1500px] mx-auto">
            <StatsView state={state} />
          </div>
        )}

        {/* Pestaña 5: Habilidades de Rol & MCP */}
        {activeTab === 'skills' && (
          <div className="h-full w-full overflow-y-auto p-5 max-w-[1500px] mx-auto">
            <SkillsView
              skills={state?.skills || []}
              agents={state?.agents || []}
            />
          </div>
        )}
      </main>

      {/* Paleta de Comandos Flotante (Ctrl+K) */}
      <CommandPaletteModal
        isOpen={isPaletteOpen}
        onClose={() => setIsPaletteOpen(false)}
        onSelectTab={setActiveTab}
        onSelectRepo={(repo) => setActiveRepo(repo)}
        repositories={repositories}
        activeRepo={activeRepo}
      />

      {/* Modal de Personalización de Entorno CAOS */}
      <EnvironmentModal
        isOpen={isEnvModalOpen}
        onClose={() => setIsEnvModalOpen(false)}
        settings={envSettings}
        onUpdateSettings={updateEnvSettings}
      />

      {/* Barra de Estado Inferior Firme: Firma CAOS 'BRAYNER JAIME · caos' */}
      <footer className="h-7 shrink-0 border-t border-caos-borde bg-caos-tinta flex items-center justify-between gap-3 px-3 text-[11px] font-mono text-caos-tenue z-20 overflow-hidden">
        <div className="flex items-center gap-2 shrink-0 whitespace-nowrap">
          <span className="font-serif tracking-widest text-caos-hueso font-bold">
            BRAYNER JAIME
          </span>
          <span className="text-caos-borde">·</span>
          <span className="font-brand text-caos-champan text-sm leading-none">
            caos
          </span>
          <span className="text-caos-borde">·</span>
          <span className="text-caos-champan font-mono">{window.location.host}</span>
        </div>
        <div className="hidden sm:flex items-center gap-3 text-[11px] font-mono whitespace-nowrap">
          <span>Runs on this machine · commands need your approval</span>
          <span className="text-caos-borde">•</span>
          <span>Ctrl/⌘ K for commands</span>
        </div>
      </footer>
    </div>
  )
}
