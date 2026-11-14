import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, PreflightResponse, ProviderItem, RouterResponse, SessionItem, StateResponse, watchEvents, WorkspaceStatus } from './api'
import { isDesktop, notifyDesktop, onBackendExit, onDesktopNavigate, openExternalUrl, restartDesktopBackend, syncTrayState, waitForDesktopBackend } from './desktop'
import { useMedia } from './hooks'
import { ago, boardCounts, isSpecialKey, View } from './lib'
import { usePrefs } from './prefs'
import { useRunOverview } from './runData'
import { FamilyEmblem, HouseEmblem } from './emblems'
import { GitBranch, ShieldCheck } from './icons'
import { SubNav } from './components/SubNav'
import { Header } from './components/Header'
import { Sidebar } from './components/Sidebar'
import { Console } from './components/Console'
import { Board } from './components/Board'
import { ProvidersView } from './components/ProvidersView'
import { MetricsView } from './components/MetricsView'
import { SkillsView } from './components/SkillsView'
import { RunView } from './components/RunView'
import { RunDeck } from './components/RunDeck'
import { setTones } from './tones'
import { ShareView } from './components/ShareView'
import { Palette, PaletteItem } from './components/Palette'
import { Preferences } from './components/Preferences'
import { PreflightDrawer } from './components/Preflight'

const VIEW_FROM_URL: Record<string, View> = {
  run: 'run',
  console: 'console',
  board: 'board',
  desk: 'board',
  providers: 'providers',
  metrics: 'metrics',
  measured: 'metrics',
  skills: 'skills',
  share: 'share',
}

/* Console lives inside Run: every way of asking for the console lands in the room. */
const asRoom = (v: View): View => (v === 'console' ? 'run' : v)

function initialView(fallback: View): View {
  try {
    const q = new URLSearchParams(window.location.search).get('view')
    const h = window.location.hash.replace(/^#/, '')
    return VIEW_FROM_URL[(q || h).toLowerCase()] ?? fallback
  } catch {
    return fallback
  }
}

const BOOT_FAMILIES = ['claude', 'agy', 'codex', 'opencode', 'local'] as const

const fmtClock = () =>
  new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', hour12: false })

const BootCeremony: React.FC<{ motion: string }> = ({ motion }) => {
  const [open, setOpen] = useState<boolean>(() => {
    if (import.meta.env.MODE === 'test') return false
    if (typeof window === 'undefined') return false
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return false
    return motion !== 'focus'
  })

  useEffect(() => {
    if (!open) return
    if (motion === 'focus') {
      setOpen(false)
      return
    }
    const timer = window.setTimeout(() => setOpen(false), 1550)
    const onDismiss = () => setOpen(false)
    window.addEventListener('keydown', onDismiss, { once: true })
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('keydown', onDismiss)
    }
  }, [open, motion])

  if (!open) return null
  return (
    <div className="boot-ceremony" aria-hidden="true" onClick={() => setOpen(false)}>
      <HouseEmblem size={52} className="boot-emblem" />
      <div className="boot-title">caos</div>
      <div className="boot-stations">
        {BOOT_FAMILIES.map((f, i) => (
          <span key={f} className="boot-station" style={{ '--st-idx': i } as React.CSSProperties}>
            <FamilyEmblem family={f} size={16} />
          </span>
        ))}
      </div>
    </div>
  )
}

export const App: React.FC = () => {
  const [prefs, setPrefs, resetPrefs] = usePrefs()
  const { data: runOverview } = useRunOverview()
  const [clockText, setClockText] = useState<string>(() => fmtClock())
  useEffect(() => {
    const timer = window.setInterval(() => setClockText(fmtClock()), 30000)
    return () => window.clearInterval(timer)
  }, [])
  const [view, setView] = useState<View>(() => asRoom(initialView(prefs.start)))
  const [roomPane, setRoomPane] = useState<'talk' | 'checks'>('talk')
  useEffect(() => { setTones(prefs.sound) }, [prefs.sound])
  useEffect(() => {
    if (typeof document === 'undefined') return
    document.documentElement.dataset.glow = prefs.glow
    document.documentElement.dataset.density = prefs.density
    document.documentElement.dataset.text = prefs.text
  }, [prefs.glow, prefs.density, prefs.text])
  const [scope, setScope] = useState<'project' | 'global'>('project')
  const mobile = useMedia('(max-width: 720px)')
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      if (typeof window !== 'undefined' && window.innerWidth <= 720) return true
      const saved = localStorage.getItem('caos_sidebar_collapsed')
      if (saved === '1') return true
      if (saved === '0') return false
    } catch {
      /* ignore */
    }
    return true   // collapsed until the person opens it: the conversation and the stations get the width
  })

  useEffect(() => {
    if (mobile) setSidebarCollapsed(true)
  }, [mobile])

  const [wsKey, setWsKey] = useState(0)
  const [state, setState] = useState<StateResponse | null>(null)
  const [router, setRouter] = useState<RouterResponse | null>(null)
  const [providers, setProviders] = useState<ProviderItem[]>([])
  const [wsStatus, setWsStatus] = useState<WorkspaceStatus | null>(null)
  const [toolsCount, setToolsCount] = useState(0)
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)

  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null)
  const [boardFilter, setBoardFilter] = useState<string | null>(null)
  const [consoleSignal, setConsoleSignal] = useState(0)
  const [newTaskSignal, setNewTaskSignal] = useState(0)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [prefsOpen, setPrefsOpen] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [desktopMode] = useState<boolean>(() => isDesktop())
  const [backendReady, setBackendReady] = useState<boolean>(() => !isDesktop())
  const [backendErr, setBackendErr] = useState<string | null>(null)
  const [backendPort, setBackendPort] = useState<number | null>(null)
  const [bootAttempt, setBootAttempt] = useState(0)
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null)
  const [preflightLoading, setPreflightLoading] = useState(false)
  const [preflightOpen, setPreflightOpen] = useState(false)
  const [sessionsVersion, setSessionsVersion] = useState(0)
  const pendingTask = useRef<number | null>(null)

  useEffect(() => {   // the address is the view: editing the hash, or going back and forward, moves the page without a reload
    const onHash = () => { const next = VIEW_FROM_URL[window.location.hash.replace(/^#/, '').toLowerCase()]; if (next) setView(asRoom(next)) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const prevNeeds = useRef(0)

  const go = useCallback((to: View) => {
    const next = asRoom(to)
    if (to === 'console') setRoomPane('talk')
    setView(next)
    if (mobile) setSidebarCollapsed(true)
    try {
      window.history.replaceState(null, '', `#${next}`)
    } catch {
      /* ignore */
    }
  }, [mobile])

  const loadCore = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([api.getState(), api.getRouter()])
      setState(s)
      setRouter(r)
      setErr(null)
    } catch (e: any) {
      setErr(e.message || 'Sin conexión con el servidor CAOS')
    }
  }, [])

  const loadMeta = useCallback(async () => {
    const [pRes, wRes, tRes, sRes] = await Promise.allSettled([
      api.getProviders(),
      api.getWorkspaceStatus(),
      api.getTools(),
      api.getSessions(),
    ])
    if (pRes.status === 'fulfilled') setProviders(pRes.value.providers ?? [])
    if (wRes.status === 'fulfilled') setWsStatus(wRes.value)
    if (tRes.status === 'fulfilled') setToolsCount(tRes.value.tools?.length ?? 0)
    if (sRes.status === 'fulfilled') {
      const arr = Array.isArray(sRes.value) ? sRes.value : []
      setSessions(arr)
      setActiveSessionId((cur) => cur || arr[0]?.id || null)
    }
  }, [])

  const loadPreflight = useCallback(async (dry = false) => {
    setPreflightLoading(true)
    try {
      setPreflight(await api.getPreflight(dry))
    } catch {
      /* the card says it is unavailable */
    } finally {
      setPreflightLoading(false)
    }
  }, [])

  const loadAll = useCallback(async () => {
    await Promise.all([loadCore(), loadMeta()])
  }, [loadCore, loadMeta])

  useEffect(() => {
    if (!desktopMode) return
    let alive = true
    setBackendErr(null)
    // First boot waits for the engine the shell already started; a retry must start a new one (the failed one is final).
    const boot = bootAttempt === 0 ? waitForDesktopBackend() : restartDesktopBackend()
    boot
      .then((info) => {
        if (!alive) return
        setBackendPort(info?.port ?? null)
        setBackendReady(true)
      })
      .catch((e: any) => {
        if (!alive) return
        setBackendErr(e?.message || String(e) || 'No se pudo iniciar el motor local Python')
      })
    return () => {
      alive = false
    }
  }, [desktopMode, bootAttempt])

  useEffect(() => {
    if (!desktopMode) return
    let cleanup: () => void = () => undefined
    void onBackendExit((detail) => {
      setBackendReady(false)
      setBackendErr(`El motor Python se detuvo inesperadamente.${detail ? ` ${detail}` : ''}`)
    }).then((fn) => { cleanup = fn })
    return () => cleanup()
  }, [desktopMode])

  useEffect(() => {
    if (!backendReady) return
    void loadAll()
    void loadPreflight(false)
  }, [backendReady, loadAll, loadPreflight, wsKey])

  const counts = useMemo(() => boardCounts(state), [state])
  const running = !!state?.running

  // Live updates: the server says when the board, the runs or the sessions change, so the page reads them at that moment. While the stream
  // is up the poll is only a backup (15 s); without it (no EventSource, or the connection dropped) the old rhythm stays.
  const [live, setLive] = useState(false)
  useEffect(() => {
    if (!backendReady) return
    let last: Record<string, number> | null = null
    let wake = 0
    const handle = watchEvents((v) => {
      const moved = (k: string) => !last || last[k] !== v[k]
      const boardMoved = moved('board') || moved('runs')
      const sessionsMoved = last !== null && moved('sessions')
      last = v
      if (boardMoved) {
        window.clearTimeout(wake)
        wake = window.setTimeout(() => { void loadCore() }, 80)   // a burst of writes is one read
      }
      if (sessionsMoved) void api.getSessions().then((arr) => { if (Array.isArray(arr)) setSessions(arr) }).catch(() => undefined)
    }, setLive)
    return () => { window.clearTimeout(wake); handle?.close(); setLive(false) }
  }, [backendReady, loadCore, wsKey])

  useEffect(() => {
    if (!backendReady) return
    const ms = live ? 15000 : running || counts.moving > 0 ? 1800 : 12000
    const timer = window.setInterval(() => {
      void loadCore()
    }, ms)
    return () => window.clearInterval(timer)
  }, [backendReady, live, running, counts.moving, loadCore])

  useEffect(() => {
    if (!backendReady) return
    const onFocus = () => { void loadCore() }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [backendReady, loadCore])

  useEffect(() => {
    if (prefs.notify && counts.needs > prevNeeds.current) {
      void notifyDesktop('CAOS · Entrega lista', `${counts.needs} tarea(s) esperando veredicto.`)
    }
    prevNeeds.current = counts.needs
  }, [counts.needs, prefs.notify])

  useEffect(() => {
    const project = state?.project ?? ''
    if (typeof document !== 'undefined') {
      document.title = project ? `CAOS · ${project}` : 'CAOS Desktop'
    }
    if (desktopMode && backendReady) {
      void syncTrayState({ project, needsYou: counts.needs, running: running || counts.moving > 0 })
    }
  }, [desktopMode, backendReady, state?.project, counts.needs, counts.moving, running])

  useEffect(() => {
    if (!desktopMode) return
    let cleanup: () => void = () => undefined
    void onDesktopNavigate((target) => {
      if (target === 'orchestrate') {
        go('console')
        return
      }
      const next = VIEW_FROM_URL[target.toLowerCase()]
      if (next) go(next)
    }).then((fn) => { cleanup = fn })
    const onLinkClick = (e: MouseEvent) => {
      const a = (e.target as HTMLElement | null)?.closest('a')
      if (!a) return
      const href = a.getAttribute('href') || ''
      if (a.target === '_blank' || /^https?:\/\//i.test(href)) {
        if (href.startsWith('http://127.0.0.1:') && a.hasAttribute('download')) return
        e.preventDefault()
        void openExternalUrl(href)
      }
    }
    document.addEventListener('click', onLinkClick)
    return () => {
      cleanup()
      document.removeEventListener('click', onLinkClick)
    }
  }, [desktopMode, go])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPrefsOpen(false)
        setPaletteOpen((o) => !o)
        return
      }
      if (e.key === 'Escape') {
        setPaletteOpen(false)
        setPrefsOpen(false)
        return
      }
      if (isSpecialKey(e) || paletteOpen || prefsOpen || e.metaKey || e.ctrlKey || e.altKey) return
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [paletteOpen, prefsOpen])

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem('caos_sidebar_collapsed', next ? '1' : '0')
      } catch {
        /* ignore */
      }
      return next
    })
  }, [])

  const switchedWorkspace = useCallback((openSession?: string) => {
    setSelectedTaskId(pendingTask.current)
    pendingTask.current = null
    setBoardFilter(null)
    setActiveSessionId(openSession ?? null)
    setWsKey((k) => k + 1)
  }, [])

  const newSession = useCallback(async () => {
    const created = await api.createSession({ mode: 'plan', project: state?.project ?? '' }).catch(() => null)
    if (!created) return
    setSessions((prev) => [created, ...prev])
    setActiveSessionId(created.id)
    setSessionsVersion((n) => n + 1)
    go('console')
  }, [state?.project, go])

  const renameSession = useCallback(async (id: string, title: string) => {
    await api.renameSession(id, { title }).catch(() => undefined)
    setSessions((prev) => prev.map((x) => (x.id === id ? { ...x, title } : x)))
    setSessionsVersion((n) => n + 1)
  }, [])

  const deleteSession = useCallback(async (id: string) => {
    await api.deleteSession(id).catch(() => undefined)
    const remaining = sessions.filter((x) => x.id !== id)
    setSessions(remaining)
    if (activeSessionId === id) setActiveSessionId(remaining[0]?.id ?? null)
    setSessionsVersion((n) => n + 1)
  }, [sessions, activeSessionId])

  /** From the global board: change to that workspace and land on the task. */
  const openWorkspaceTask = useCallback(async (path: string, taskId: number) => {
    try {
      pendingTask.current = taskId
      await api.switchWorkspace(path)
      switchedWorkspace()
      go('board')
    } catch (e: any) {
      pendingTask.current = null
      setErr(e.message || 'No se pudo abrir ese proyecto')
    }
  }, [switchedWorkspace, go])

  const runPending = useCallback(async () => {
    await api.runPending().catch((e) => setErr(e.message || 'No se pudo iniciar la ejecución'))
    await loadCore()
  }, [loadCore])

  const useModelInConsole = useCallback((modelName: string, providerId?: string) => {
    try {
      localStorage.setItem('caos_model', modelName)
      if (providerId) localStorage.setItem('caos_provider', providerId)
      localStorage.setItem('caos_use_target', `${providerId || 'ollama'}::${modelName}`)
    } catch {
      /* ignore */
    }
    setConsoleSignal((n) => n + 1)
    go('console')
  }, [go])

  const useSkillInConsole = useCallback((skillName: string) => {
    setSelectedSkill(skillName)
    setConsoleSignal((n) => n + 1)
    go('console')
  }, [go])

  const paletteItems: PaletteItem[] = useMemo(() => [
    { id: 'v-console', group: 'Navegar', label: 'Console', hint: 'Plan / Act / Intent', run: () => go('console') },
    { id: 'v-run', group: 'Navegar', label: 'Run', hint: 'Ciclos, rama harness/landed, revisores y costes', run: () => go('run') },
    { id: 'v-board', group: 'Navegar', label: 'Board', hint: 'Lista / Kanban / Veredictos', run: () => go('board') },
    { id: 'v-providers', group: 'Navegar', label: 'Models & Providers', hint: 'Ollama / Cloud / Router', run: () => go('providers') },
    { id: 'v-metrics', group: 'Navegar', label: 'Metrics', hint: 'KPIs operativos y Smoke Test', run: () => go('metrics') },
    { id: 'v-skills', group: 'Navegar', label: 'Skills & Tools', hint: 'Categorías, SKILL.md y MCP', run: () => go('skills') },
    { id: 'v-share', group: 'Navegar', label: 'Share / Team', hint: 'Doctor pre-push y Share Pack', run: () => go('share') },
    { id: 'a-new-task', group: 'Acciones', label: 'Nueva tarea en Board', hint: 'Crear en cola', run: () => { go('board'); setNewTaskSignal((n) => n + 1) } },
    { id: 'a-run', group: 'Acciones', label: 'Ejecutar pendientes', hint: `${counts.runnable} listas`, run: () => void runPending() },
    { id: 'a-preflight', group: 'Acciones', label: 'Preflight del entorno', hint: preflight ? preflight.verdict : 'comprobando', run: () => setPreflightOpen(true) },
    { id: 'a-sidebar', group: 'Acciones', label: sidebarCollapsed ? 'Expandir barra lateral' : 'Colapsar barra lateral', run: toggleSidebar },
    { id: 'a-prefs', group: 'Acciones', label: 'Preferencias', run: () => setPrefsOpen((o) => !o) },
  ], [go, counts.runnable, runPending, sidebarCollapsed, toggleSidebar, preflight])

  const activeStations = useMemo(
    () => (runOverview?.stations ?? []).filter((s) => s.running),
    [runOverview?.stations],
  )
  const lastCycle = runOverview?.cycles?.[0] ?? null
  const dirtyCount = wsStatus?.dirty_files?.length ?? 0

  if (!backendReady) {
    return (
      <div className={`app desktop-boot density-${prefs.density} text-${prefs.text} motion-${prefs.motion} glow-${prefs.glow}`}>
        <div className="desktop-boot-card" role="status" aria-live="polite">
          <div className="desktop-boot-mark" aria-hidden="true">
            <HouseEmblem size={44} className="boot-emblem" />
            <span className="boot-title">caos</span>
          </div>
          <div className="boot-stations" aria-hidden="true">
            {BOOT_FAMILIES.map((f, i) => (
              <span key={f} className="boot-station" style={{ '--st-idx': i } as React.CSSProperties}>
                <FamilyEmblem family={f} size={15} />
              </span>
            ))}
          </div>
          <h1>{backendErr ? 'Error iniciando motor local' : 'Iniciando estación CAOS'}</h1>
          <p className="muted">
            {backendErr || 'Conectando con el servidor Python en loopback, cargando workspace y verificando agentes…'}
          </p>
          {backendErr ? (
            <button type="button" className="btn btn-primary btn-sm" onClick={() => setBootAttempt((n) => n + 1)}>
              Reintentar arranque
            </button>
          ) : (
            <div className="desktop-boot-bar" aria-hidden="true"><span /></div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className={`app density-${prefs.density} text-${prefs.text} motion-${prefs.motion} glow-${prefs.glow}`}>
      <BootCeremony motion={prefs.motion} />
      <a className="skip" href="#main">Saltar al contenido</a>

      <Header
        project={state?.project ?? ''}
        sample={!!state?.sample}
        view={view}
        onView={go}
        needsYou={counts.needs}
        runnable={counts.runnable}
        running={running}
        onRun={runPending}
        onOpenPalette={() => { setPrefsOpen(false); setPaletteOpen(true) }}
        onTogglePrefs={() => { setPaletteOpen(false); setPrefsOpen((o) => !o) }}
        prefsOpen={prefsOpen}
        onToggleSidebar={toggleSidebar}
        sidebarCollapsed={sidebarCollapsed}
        scope={scope}
        onScope={setScope}
      />

      {err && (
        <div className="banner err global-err" role="alert">
          <span>{err}</span>
          <button type="button" className="btn btn-quiet btn-xs" onClick={() => void loadAll()}>Reintentar</button>
        </div>
      )}

      <div className="shell">
        <Sidebar
          collapsed={sidebarCollapsed}
          onToggleCollapse={toggleSidebar}
          scope={scope}
          project={state?.project ?? ''}
          rootPath={state?.root}
          providers={providers}
          wsStatus={wsStatus}
          toolsCount={toolsCount}
          sessions={sessions}
          activeSessionId={activeSessionId}
          preflight={preflight}
          onSelectSession={(id) => { setActiveSessionId(id); go('console') }}
          onNewSession={() => void newSession()}
          onRenameSession={(id, title) => void renameSession(id, title)}
          onDeleteSession={(id) => void deleteSession(id)}
          onOpenPreflight={() => setPreflightOpen(true)}
          onGoProviders={() => go('providers')}
          onSwitchedWorkspace={switchedWorkspace}
        />

        <main id="main" className="main">
          <SubNav view={view} onView={go} />
          {view === 'run' && (
            <div className={`view room pane-${roomPane}`} key={`run-${wsKey}`}>
              <div className="seg room-switch" role="group" aria-label="Conversación o verificación">
                <button type="button" aria-pressed={roomPane === 'talk'} onClick={() => setRoomPane('talk')}>Console</button>
                <button type="button" aria-pressed={roomPane === 'checks'} onClick={() => setRoomPane('checks')}>Verificación</button>
              </div>
              <div className="room-main">
              <Console
                state={state}
                agents={state?.agents ?? []}
                profiles={router?.profiles ?? []}
                tiers={router?.tiers ?? []}
                project={state?.project ?? ''}
                skills={state?.skills ?? []}
                providers={providers}
                prefs={prefs}
                sessionsVersion={sessionsVersion}
                onProvidersChanged={() => void loadMeta()}
                onBoardChanged={() => void loadCore()}
                onNavigate={go}
                onOpenTask={(id) => { setSelectedTaskId(id); go('board') }}
                onSessionsChanged={(items, activeId) => { setSessions(items); if (activeId !== undefined) setActiveSessionId(activeId) }}
                externalSessionId={activeSessionId}
                initialSkill={selectedSkill}
                focusSignal={consoleSignal}
              />
              </div>
              <aside className="room-side" aria-label="Verificación"><RunDeck /><RunView /></aside>
            </div>
          )}

          {view === 'board' && (
            <div className="view" key={`board-${wsKey}`}>
              <Board
                router={router}
                state={state}
                selectedId={selectedTaskId}
                onSelect={setSelectedTaskId}
                onChanged={() => void loadCore()}
                onRun={() => void runPending()}
                runnable={counts.runnable}
                filter={boardFilter}
                onFilter={setBoardFilter}
                newTaskSignal={newTaskSignal}
                scope={scope}
                onOpenWorkspaceTask={(path, id) => void openWorkspaceTask(path, id)}
              />
            </div>
          )}

          {view === 'providers' && (
            <div className="view" key={`providers-${wsKey}`}>
              <ProvidersView
                agents={state?.agents ?? []}
                profiles={router?.profiles ?? []}
                tiers={router?.tiers ?? []}
                scope={scope}
                onAgentsChanged={() => void loadCore()}
                onProvidersChanged={() => void loadMeta()}
                onUseModel={useModelInConsole}
              />
            </div>
          )}

          {view === 'metrics' && (
            <div className="view" key={`metrics-${wsKey}`}>
              <MetricsView scope={scope} profiles={router?.profiles ?? []} tiers={router?.tiers ?? []} />
            </div>
          )}

          {view === 'skills' && (
            <div className="view" key={`skills-${wsKey}`}>
              <SkillsView
                skills={state?.skills ?? []}
                onSkillsChanged={() => void loadAll()}
                onUseSkill={useSkillInConsole}
              />
            </div>
          )}

          {view === 'share' && (
            <div className="view" key={`share-${wsKey}`}>
              <ShareView />
            </div>
          )}
        </main>
      </div>

      <footer className="foot" data-backend-port={desktopMode && backendPort ? backendPort : undefined}>
        <span className="foot-item">
          <GitBranch className="icon icon-xs" />
          <span className="mono">{wsStatus?.branch || runOverview?.landed?.branch || '—'}</span>
          {dirtyCount > 0 && <span className="muted">{`(${dirtyCount} pendiente${dirtyCount === 1 ? '' : 's'})`}</span>}
        </span>
        <span className="foot-sep" aria-hidden="true" />
        <span className="foot-item">
          {activeStations.length > 0 ? (
            activeStations.map((s) => (
              <span key={s.name} className={`foot-live fam-${s.family ?? 'tool'}`}>
                <span className="live-pulse" aria-hidden="true" />
                <FamilyEmblem family={s.family} size={13} />
                <span className="mono">{s.name}</span>
              </span>
            ))
          ) : running || counts.moving > 0 ? (
            <span className="foot-live">
              <span className="live-pulse" aria-hidden="true" />
              <span>{counts.moving > 0 ? `${counts.moving} en curso` : 'ejecutando'}</span>
            </span>
          ) : (
            <span className="muted">en reposo</span>
          )}
        </span>
        <span className="foot-sep" aria-hidden="true" />
        <span className="foot-item">
          {lastCycle ? (
            <>
              <span
                className={`pill-mini ${
                  lastCycle.status === 'landed'
                    ? 'sage'
                    : lastCycle.status === 'rejected' || lastCycle.status === 'verify_failed' || lastCycle.status === 'conflict'
                      ? 'coral'
                      : 'amber'
                }`}
              >
                {lastCycle.key} · {lastCycle.status}
              </span>
              <span className="muted">{ago(lastCycle.at)}</span>
            </>
          ) : preflight ? (
            <>
              <ShieldCheck className="icon icon-xs" />
              <span
                className={`pill-mini ${
                  preflight.verdict === 'ready' ? 'sage' : preflight.verdict === 'blocked' ? 'coral' : 'amber'
                }`}
              >
                {preflight.verdict}
              </span>
            </>
          ) : (
            <span className="muted">sin verificación</span>
          )}
        </span>
        <span className="mono foot-time">{clockText}</span>
      </footer>

      <Palette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        items={paletteItems}
        tasks={state?.tasks ?? []}
        onTask={(id) => { setSelectedTaskId(id); go('board') }}
      />

      <PreflightDrawer
        open={preflightOpen}
        data={preflight}
        loading={preflightLoading}
        onClose={() => setPreflightOpen(false)}
        onRecheck={() => void loadPreflight(false)}
        onGoProviders={() => go('providers')}
      />

      <Preferences
        open={prefsOpen}
        prefs={prefs}
        onChange={setPrefs}
        onReset={resetPrefs}
        onClose={() => setPrefsOpen(false)}
      />
    </div>
  )
}
