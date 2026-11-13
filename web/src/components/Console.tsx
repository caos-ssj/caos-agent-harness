import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowRight,
  Check,
  CheckCircle2,
  Copy,
  FilePlus2,
  FolderGit2,
  GitBranch,
  ListPlus,
  Repeat2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
  X,
  Zap,
} from '../icons'
import {
  Agent,
  api,
  ExecutionRun,
  ModelProfile,
  OrchestrateOptions,
  OrchestrationPlan,
  watchRun,
  ProvidersResponse,
  ProviderItem,
  RouterTier,
  SessionDetail,
  SessionItem,
  SkillInfo,
  StateResponse,
  WorkspaceStatus,
} from '../api'
import { boardCounts, pad, View } from '../lib'
import { Prefs } from '../prefs'
import { catOf, CAT_ACCENT, CAT_ORDER } from '../skillCats'
import { WorkspaceDrawer } from './WorkspaceDrawer'
import { ToolStepsView } from './ToolStepsView'
import { CoreData, CoreStage, StageRow, SystemFlowDiagram } from './CaosArt'
import { DiffViewer } from './DiffViewer'
import { EngineChoice, EnginePopover, IntentId } from './EnginePopover'
import { SkillPopover } from './SkillPopover'
import { CriticalDesk, OrchestrateBar, OrchestrationLive } from './OrchestratePanel'
import { useDialog, useFresh, useMedia, usePresence } from '../hooks'

interface ConsoleProps {
  state?: StateResponse | null
  agents: Agent[]
  profiles: ModelProfile[]
  tiers: RouterTier[]
  project: string
  skills: SkillInfo[]
  providers: ProviderItem[]
  prefs: Prefs
  sessionsVersion: number
  onProvidersChanged: () => void
  onBoardChanged: () => void
  onNavigate?: (view: View) => void
  onOpenTask?: (id: number) => void
  onSessionsChanged?: (items: SessionItem[], activeId: string | null) => void
  externalSessionId?: string | null
  initialSkill?: string | null
  focusSignal: number
}

const isFinal = (status?: string) => status === 'completed' || status === 'failed' || status === 'stopped'
const MAX_POLL_FAILS = 8
const SAFETY_POLL_MS = 5000   // with the live stream the poll is only a safety net; without it (no EventSource) the run is polled fast
const FAST_POLL_MS = 600
const LOST_RUN = 'Se perdió conexión con el servidor mientras corría. Recarga para ver lo guardado.'

const INTENTS: Array<{ id: 'rapido' | 'codigo' | 'razonar' | 'local'; label: string }> = [
  { id: 'rapido', label: 'Rápido' },
  { id: 'codigo', label: 'Código' },
  { id: 'razonar', label: 'Razonamiento' },
  { id: 'local', label: 'Barato / Local' },
]

const STARTERS = [
  { title: 'Revisar repo y tests', prompt: 'Inspecciona el estado actual del repositorio, archivos modificados y qué pruebas correr primero.' },
  { title: 'Planear cambio seguro', prompt: 'Analiza la arquitectura y dame un plan por pasos con preguntas de alineación antes de editar archivos.' },
  { title: 'Estado de motores', prompt: 'Resume qué agentes, modelos locales y tareas pendientes hay ahora mismo en el proyecto.' },
]

export const Console: React.FC<ConsoleProps> = ({
  state = null,
  agents,
  profiles,
  tiers,
  project,
  skills,
  providers,
  prefs,
  sessionsVersion,
  onProvidersChanged,
  onBoardChanged,
  onNavigate,
  onOpenTask,
  onSessionsChanged,
  externalSessionId,
  initialSkill,
  focusSignal,
}) => {
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [sid, setSid] = useState<string | null>(null)
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [provMeta, setProvMeta] = useState<ProvidersResponse | null>(null)
  const [activeRun, setActiveRun] = useState<ExecutionRun | null>(null)
  const wide = useMedia('(min-width: 1180px)')
  const [drawerOpen, setDrawerOpen] = useState(() => prefs.inspector && typeof window !== 'undefined' && window.innerWidth >= 1500)
  const [engineOpen, setEngineOpen] = useState(false)
  const [skillOpen, setSkillOpen] = useState(false)
  const [skillCat, setSkillCat] = useState<string | null>(null)
  const [providerModel, setProviderModel] = useState('')
  const [slashIdx, setSlashIdx] = useState(0)
  const [gates, setGates] = useState<{ mutation: { caught: number; total: number } | null; regress: string | null; metrics: { success: number | null; redo: number | null; p50: number | null; runs: number } | null }>({ mutation: null, regress: null, metrics: null })
  const currentRunId = useRef<string | null>(null)
  const [drawerTab] = useState<'files' | 'diff' | 'preview'>('files')
  const [drawerRefresh, setDrawerRefresh] = useState(0)
  const [showPipeline, setShowPipeline] = useState(false)
  const ctxPresence = usePresence(drawerOpen, 190)
  const phone = useMedia('(max-width: 900px)')

  const [wsStatus, setWsStatus] = useState<WorkspaceStatus | null>(null)
  const [wsFiles, setWsFiles] = useState<string[]>([])
  const [attachMenu, setAttachMenu] = useState(false)
  const [attachFilter, setAttachFilter] = useState('')

  const ollama = useMemo(() => providers.find((p) => p.id === 'ollama'), [providers])
  const onlineCloud = useMemo(
    () => providers.filter((p) => p.id !== 'ollama' && (p.status === 'online' || p.status === 'key_present' || p.status === 'ready')),
    [providers]
  )
  const models = useMemo(() => ollama?.models ?? [], [ollama])
  const online = ollama?.status === 'online' || onlineCloud.length > 0

  const [selectionKind, setSelectionKind] = useState<'intent' | 'model' | 'provider' | 'agent' | 'tier'>('intent')
  const [intent, setIntent] = useState<'rapido' | 'codigo' | 'razonar' | 'local'>('codigo')
  const [providerPick, setProviderPick] = useState<string>(() => {
    try { return localStorage.getItem('caos_provider') || 'ollama' } catch { return 'ollama' }
  })
  const [model, setModel] = useState<string>(() => {
    try { return localStorage.getItem('caos_model') || '' } catch { return '' }
  })
  const [agentOrTier, setAgentOrTier] = useState<string>('')
  const [mode, setMode] = useState<'plan' | 'act' | 'orchestrate'>('plan')
  const [orchOptions, setOrchOptions] = useState<OrchestrateOptions | null>(null)
  const [orchSel, setOrchSel] = useState<string | null>(null)
  const [orchPool, setOrchPool] = useState<string[] | null>(null)
  const [orchScout, setOrchScout] = useState<string>('auto')   // auto | off | the name of a free or cheap agent
  const [orchPlan, setOrchPlan] = useState<OrchestrationPlan | null>(null)
  const [orchPlanning, setOrchPlanning] = useState(false)
  const [orchAdding, setOrchAdding] = useState<string | null>(null)
  const modeRef = useRef(mode)
  modeRef.current = mode
  const sidRef = useRef(sid)
  sidRef.current = sid
  const [isolated, setIsolated] = useState(false)
  const [skill, setSkill] = useState<string>(initialSkill || 'auto')
  const [prompt, setPrompt] = useState('')
  const [queue, setQueue] = useState<string[]>([])
  const [planAnswers, setPlanAnswers] = useState<Record<string, string>>({})
  const dispatching = useRef(false)
  const pollFails = useRef(0)

  const [sending, setSending] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [promotedId, setPromotedId] = useState<string | null>(null)
  const [quickReviewed, setQuickReviewed] = useState<Record<number, string>>({})
  const [renaming, setRenaming] = useState(false)
  const [renameText, setRenameText] = useState('')

  const feedRef = useRef<HTMLDivElement>(null)
  const fieldRef = useRef<HTMLTextAreaElement>(null)
  const routerSummary = useMemo(() => ({ tiers, profiles }), [tiers, profiles])

  useEffect(() => {
    if (initialSkill) setSkill(initialSkill)
  }, [initialSkill])

  useEffect(() => {
    api.getProviders(prefs.profile).then(setProvMeta).catch(() => undefined)
  }, [providers.length, prefs.profile])

  const loadGates = useCallback(() => {
    api.getMetrics('project').then((m) => setGates({
      mutation: m.kpis.gates?.mutation ?? null,
      regress: m.kpis.gates?.regress_status ?? null,
      metrics: { success: m.kpis.run_success_rate ?? null, redo: m.kpis.human_redo_rate ?? null, p50: m.kpis.p50_latency_ms ?? null, runs: m.kpis.runs_total ?? 0 },
    })).catch(() => undefined)
  }, [])
  useEffect(() => { loadGates() }, [loadGates])

  // Ctrl/⌘ M opens the engine chooser from anywhere in Console.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'm') { e.preventDefault(); setEngineOpen((o) => !o) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (externalSessionId && externalSessionId !== sid) setSid(externalSessionId)
  }, [externalSessionId])

  useEffect(() => {
    if (!models.length) return
    setModel((cur) => (cur && models.includes(cur) ? cur : (ollama?.default_model && models.includes(ollama.default_model) ? ollama.default_model : models[0])))
  }, [models, ollama?.default_model])

  const loadWorkspaceMeta = useCallback(() => {
    api.getWorkspaceStatus().then(setWsStatus).catch(() => undefined)
    api.getWorkspaceFiles().then((r) => setWsFiles(r.files || [])).catch(() => undefined)
  }, [])

  const loadSessions = useCallback(async () => {
    try {
      const list = await api.getSessions()
      const items = Array.isArray(list) ? list : []
      setSessions(items)
      onSessionsChanged?.(items, sid)
      if (!sid && items.length > 0) setSid(items[0].id)
      else if (items.length === 0) {
        const created = await api.createSession({ mode: 'plan', project })
        setSessions([created])
        setSid(created.id)
        setSession({ ...created, messages: [], commands_enabled: false })
        onSessionsChanged?.([created], created.id)
      }
    } catch {
      /* ignore */
    }
  }, [sid, project])

  const loadSession = useCallback(async (id: string) => {
    try {
      const s = await api.getSession(id)
      setSession(s)
      // Reloading the session you are in never pulls you out of Orquestar: the server only knows Plan or Act until a plan is launched.
      if ((s.mode === 'plan' || s.mode === 'act') && !(modeRef.current === 'orchestrate' && id === sidRef.current)) setMode(s.mode)
      if (s.target_kind === 'model' && s.target) setModel(s.target)
      if (s.target_kind === 'provider' && s.target) setProviderPick(s.target)
      onSessionsChanged?.(sessions, id)
    } catch {
      /* ignore */
    }
  }, [sessions])

  useEffect(() => {
    loadSessions()
    loadWorkspaceMeta()
  }, [])

  // The sidebar renamed or deleted a session: if the one open is gone, move to the first left (or start a fresh one).
  useEffect(() => {
    if (sessionsVersion === 0) return
    void (async () => {
      const list = await api.getSessions().catch(() => null)
      if (!Array.isArray(list)) return
      setSessions(list)
      if (sid && !list.some((x) => x.id === sid)) {
        setSession(null)
        setActiveRun(null)
        if (list[0]) setSid(list[0].id)
        else { setSid(null); void loadSessions() }
      } else if (sid) void loadSession(sid)
    })()
  }, [sessionsVersion]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (sid) loadSession(sid)
  }, [sid])

  useEffect(() => {
    if (focusSignal > 0) {
      try {
        const rawTarget = localStorage.getItem('caos_use_target')
        if (rawTarget && rawTarget.includes('::')) {
          localStorage.removeItem('caos_use_target')
          const [prov, mod] = rawTarget.split('::', 2)
          if (prov && prov !== 'ollama') {
            setSelectionKind('provider')
            setProviderPick(prov)
          } else {
            setSelectionKind('model')
            if (mod) setModel(mod)
          }
        }
      } catch {
        /* ignore */
      }
      fieldRef.current?.focus()
    }
  }, [focusSignal])

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight
  }, [session?.messages?.length, activeRun?.steps?.length, activeRun?.status])

  const resolvedIntent = provMeta?.intents?.[intent]
  const effectiveTarget = useMemo(() => {
    if (selectionKind === 'intent') {
      return {
        target_kind: 'intent' as const,
        target: intent,
        provider: resolvedIntent?.provider || providerPick || 'ollama',
        model: resolvedIntent?.model || model || 'qwen2.5:7b',
        intent,
        label: `${intent} · ${resolvedIntent?.model || model || 'auto'}`,
      }
    }
    if (selectionKind === 'provider') {
      const pItem = providers.find((p) => p.id === providerPick)
      const mod = providerModel || pItem?.default_model || pItem?.models?.[0] || model
      return { target_kind: 'provider' as const, target: mod, provider: providerPick, model: mod, intent: '', label: `${providerPick} · ${mod}` }
    }
    if (selectionKind === 'agent' || selectionKind === 'tier') {
      return { target_kind: selectionKind, target: agentOrTier, provider: 'ollama', model, intent: '', label: `${selectionKind} · ${agentOrTier}` }
    }
    return { target_kind: 'model' as const, target: model || 'qwen2.5:7b', provider: 'ollama', model: model || 'qwen2.5:7b', intent: '', label: `ollama · ${model || 'auto'}` }
  }, [selectionKind, intent, resolvedIntent, providerPick, providerModel, model, agentOrTier, providers])

  /** Follows a run until it ends: the live stream when the browser has one, with a slow poll as a safety net; the fast poll when it does not. */
  const pollRun = useCallback((runId: string, curSid: string) => {
    pollFails.current = 0
    let timer = 0
    let live: { close: () => void } | null = null
    let ended = false
    const finish = async (r: ExecutionRun) => {
      if (ended) return
      ended = true
      window.clearInterval(timer)
      live?.close()
      if (currentRunId.current !== runId) return   // a newer run took over (Stop and send now): its own tracker owns the state
      setSending(false)
      dispatching.current = false
      await loadSession(curSid)
      loadGates()
      loadWorkspaceMeta()
      setDrawerRefresh((n) => n + 1)
      if (r.task_id != null) onBoardChanged()
      if (r.status === 'failed' && r.error) setErr(r.error)
    }
    const apply = (r: ExecutionRun) => {
      pollFails.current = 0
      if (currentRunId.current === runId) setActiveRun(r)
      if (isFinal(r.status)) void finish(r)
    }
    live = watchRun(runId, apply)
    timer = window.setInterval(async () => {
      if (ended) return
      try {
        apply(await api.getRun(runId))
      } catch {
        pollFails.current += 1
        if (pollFails.current >= MAX_POLL_FAILS) {
          ended = true
          window.clearInterval(timer)
          live?.close()
          setSending(false)
          dispatching.current = false
          setErr(LOST_RUN)
        }
      }
    }, live ? SAFETY_POLL_MS : FAST_POLL_MS)
  }, [loadSession, loadWorkspaceMeta, loadGates, onBoardChanged])

  // ── Orchestrate: plan, edit, launch ──
  const orchestrator = orchSel && orchOptions?.orchestrators.some((o) => o.name === orchSel) ? orchSel : orchOptions?.default_orchestrator ?? orchOptions?.orchestrators[0]?.name ?? ''
  const poolNames = useMemo(() => {
    if (!orchOptions) return [] as string[]
    const valid = (orchPool ?? []).filter((n) => orchOptions.pool.some((a) => a.name === n))
    if (orchPool && valid.length) return valid
    const rest = orchOptions.pool.filter((a) => a.capable && a.name !== orchestrator).map((a) => a.name)
    return rest.length ? rest : orchOptions.pool.filter((a) => a.capable).map((a) => a.name)
  }, [orchOptions, orchPool, orchestrator])

  const loadOrchOptions = useCallback((goal = '') => api.getOrchestrateOptions(goal).then(setOrchOptions).catch(() => undefined), [])
  useEffect(() => {
    if (mode !== 'orchestrate') return
    const t = window.setTimeout(() => void loadOrchOptions(prompt), prompt ? 450 : 0)   // the suggestion follows what is being written
    return () => window.clearTimeout(t)
  }, [mode, prompt, loadOrchOptions])

  const planGoal = useCallback(async (goal: string, orch = orchestrator) => {
    setOrchPlanning(true)
    setErr(null)
    try {
      const plan = await api.planOrchestration({ goal, orchestrator: orch || undefined, pool: poolNames.length ? poolNames : undefined, scout: orchScout })
      setOrchPlan(plan)
      setPrompt('')
    } catch (e: any) {
      setErr(e.message || 'No se pudo planificar')
    } finally {
      setOrchPlanning(false)
    }
  }, [orchestrator, poolNames, orchScout])

  const launchOrchestration = async () => {
    if (!orchPlan) return
    let curSid = sid
    try {
      if (!curSid) {
        const s = await api.createSession({ mode: 'orchestrate', project })
        curSid = s.id
        setSid(s.id)
        setSession({ ...s, messages: [], commands_enabled: false })
        setSessions((prev) => [s, ...prev])
      }
      dispatching.current = true
      setSending(true)
      setErr(null)
      const resp = await api.launchOrchestration(curSid, orchPlan)
      setOrchPlan(null)
      await loadSession(curSid)
      currentRunId.current = resp.run_id
      setActiveRun(await api.getRun(resp.run_id))
      pollRun(resp.run_id, curSid)
    } catch (e: any) {
      dispatching.current = false
      setSending(false)
      setErr(e.message || 'No se pudo lanzar la orquestación')
    }
  }

  const addOrchAgent = async (id: string) => {
    setOrchAdding(id)
    try {
      await api.addAgent({ kind: 'cli', id })
      onBoardChanged()
      await loadOrchOptions(prompt)
    } catch (e: any) {
      setErr(e.message || 'No se pudo añadir el agente')
    } finally {
      setOrchAdding(null)
    }
  }

  const sendText = useCallback(async (rawText: string, overrideMode?: 'plan' | 'act' | 'orchestrate', force = false) => {
    const text = rawText.trim()
    if (!text) return
    if ((overrideMode || mode) === 'orchestrate') {   // the goal is planned, not sent: the person reviews the plan first
      void planGoal(text)
      return
    }
    if (!force && (dispatching.current || sending)) {
      setQueue((q) => [...q, text])
      setPrompt('')
      return
    }
    let curSid = sid
    if (!curSid) {
      const s = await api.createSession({ mode: overrideMode || mode, project })
      curSid = s.id
      setSid(s.id)
      setSession({ ...s, messages: [], commands_enabled: false })
      setSessions((prev) => [s, ...prev])
    }
    dispatching.current = true
    setSending(true)
    setErr(null)
    setPrompt('')
    const useMode = overrideMode || mode
    try {
      const resp = await api.addMessage(curSid, {
        content: text,
        mode: useMode,
        model: effectiveTarget.model,
        provider: effectiveTarget.provider,
        agent: skill !== 'auto' ? skill : undefined,
        tier: selectionKind === 'tier' ? agentOrTier : undefined,
        target_kind: effectiveTarget.target_kind,
        target: effectiveTarget.target,
        intent: effectiveTarget.intent || undefined,
        profile: effectiveTarget.target_kind === 'intent' ? prefs.profile : undefined,
        isolated,
      })
      await loadSession(curSid)
      if (resp.run_id) {
        currentRunId.current = resp.run_id
        const firstRun = await api.getRun(resp.run_id)
        setActiveRun(firstRun)
        pollRun(resp.run_id, curSid)
      } else {
        dispatching.current = false
        setSending(false)
      }
    } catch (e: any) {
      dispatching.current = false
      setSending(false)
      setErr(e.message || 'No se pudo enviar el mensaje')
    }
  }, [sid, sending, mode, effectiveTarget, skill, selectionKind, agentOrTier, isolated, prefs.profile, loadSession, pollRun, planGoal])

  useEffect(() => {
    if (!sending && !dispatching.current && queue.length > 0 && activeRun?.status !== 'awaiting_approval') {
      const [nextMsg, ...rest] = queue
      setQueue(rest)
      void sendText(nextMsg)
    }
  }, [sending, queue, activeRun?.status, sendText])

  const switchMode = async (next: 'plan' | 'act' | 'orchestrate') => {
    setMode(next)
    if (sid && next === 'act' && !session?.commands_enabled) {
      await api.setSessionCommands(sid, true).catch(() => undefined)
      await loadSession(sid)
    }
  }

  const toggleCommands = async (on: boolean) => {
    if (!sid) return
    await api.setSessionCommands(sid, on).catch(() => undefined)
    if (!on && mode === 'act') setMode('plan')
    await loadSession(sid)
  }

  const decide = async (stepIndex: number, approve: boolean, trustSession = false) => {
    if (!activeRun) return
    try {
      await api.decideRun(activeRun.id, stepIndex, approve, trustSession)
      const r = await api.getRun(activeRun.id)
      setActiveRun(r)
    } catch (e: any) {
      setErr(e.message || 'Error al decidir acción')
    }
  }

  const stopRun = async () => {
    if (!activeRun) return
    await api.cancelRun(activeRun.id).catch(() => undefined)
    dispatching.current = false
    setSending(false)
  }

  /** The queued message that should not wait: stop what is running, then send it now. */
  const stopAndSendNow = async (index: number) => {
    const text = queue[index]
    if (text === undefined) return
    setQueue((q) => q.filter((_, k) => k !== index))
    if (activeRun && !isFinal(activeRun.status)) await api.cancelRun(activeRun.id).catch(() => undefined)
    dispatching.current = false
    setSending(false)
    await sendText(text, undefined, true)
  }

  const pickEngine = (c: EngineChoice) => {
    if (c.kind === 'intent') { setSelectionKind('intent'); setIntent(c.intent as IntentId) }
    else if (c.kind === 'model') {
      setSelectionKind('model'); setModel(c.model)
      try { localStorage.setItem('caos_model', c.model) } catch { /* ignore */ }
    } else if (c.kind === 'provider') {
      setSelectionKind('provider'); setProviderPick(c.provider); setProviderModel(c.model || '')
      try { localStorage.setItem('caos_provider', c.provider) } catch { /* ignore */ }
    } else if (c.kind === 'agent') { setSelectionKind('agent'); setAgentOrTier(c.name) }
    else { setSelectionKind('tier'); setAgentOrTier(c.tier) }
  }

  const submitRename = async () => {
    if (!sid || !renameText.trim()) return
    await api.renameSession(sid, { title: renameText.trim() }).catch(() => undefined)
    setRenaming(false)
    loadSession(sid)
    loadSessions()
  }

  const quickVerdict = async (taskId: number, v: 'ok' | 'redo') => {
    const reason = v === 'ok' ? 'Verificado en Console' : 'Revisar en Console'
    await api.reviewTask(taskId, v, reason)
    setQuickReviewed((cur) => ({ ...cur, [taskId]: v }))
    onBoardChanged()
  }

  const toTask = async (msgId: string, content: string) => {
    const queuePick = agents[0]?.name || 'person'
    await api.addTask({ text: content.slice(0, 260), queue: queuePick })
    setPromotedId(msgId)
    onBoardChanged()
  }

  const attachIntoComposer = (relPath: string) => {
    const token = `@${relPath}`
    setPrompt((cur) => (cur.includes(token) ? cur : (cur ? `${cur.trimEnd()} ${token} ` : `${token} `)))
    setAttachMenu(false)
    fieldRef.current?.focus()
  }

  const passToActWithAnswers = async (qs: Array<{ question: string; chips: string[] }>) => {
    const lines = qs.map((q) => `- ${q.question}: ${planAnswers[q.question] || q.chips?.[0] || 'Confirmado'}`)
    await toggleCommands(true)
    setMode('act')
    await sendText(`Respuestas de alineación:\n${lines.join('\n')}\nEjecuta ahora en modo Act.`, 'act')
  }

  const busy = sending || (!!activeRun && !isFinal(activeRun.status))
  const commandsOn = !!session?.commands_enabled
  const messages = session?.messages ?? []
  const awaiting = activeRun?.status === 'awaiting_approval'
    ? activeRun.steps.map((s, i) => ({ s, i })).filter(({ s }) => s.status === 'awaiting_approval')
    : []
  const dirtyCount = wsStatus?.dirty_files?.length ?? 0
  const freshTurns = useFresh(messages.map((m) => m.id))
  const attachRef = useDialog<HTMLDivElement>(attachMenu, () => setAttachMenu(false), { initial: 'input' })
  const approvalRef = useDialog<HTMLDivElement>(awaiting.length > 0, () => { if (awaiting[0]) void decide(awaiting[0].i, false) }, { initial: '[data-safe]' })
  const filteredAttach = wsFiles.filter((f) => !/^(build|dist|node_modules|\.venv|.*\.egg-info)\//.test(f)).filter((f) => !attachFilter.trim() || f.toLowerCase().includes(attachFilter.trim().toLowerCase())).slice(0, 36)
  const canIsolate = !!wsStatus?.git_repo && !!wsStatus?.has_head

  // The core's four stages, each read from something real: the plan's open questions, the run in progress, the repository gates, the tasks waiting for you.
  const needsCount = boardCounts(state).needs
  const openQuestions = [...messages].reverse().find((m) => m.role === 'assistant' && m.questions && m.questions.length)?.questions?.length ?? 0
  const mutOk = gates.mutation ? gates.mutation.caught === gates.mutation.total : null
  const verifyTone: 'ok' | 'fail' | 'idle' = gates.regress === 'check' || mutOk === false ? 'fail' : gates.regress === 'pass' || mutOk === true ? 'ok' : 'idle'
  const verifyDetail = [gates.mutation ? `mut ${gates.mutation.caught}/${gates.mutation.total}` : null, `regress ${gates.regress === 'pass' ? 'pass' : gates.regress === 'check' ? 'revisar' : 'sin verificar'}`].filter(Boolean).join(' · ')
  const coreData: CoreData = {
    nodes: [
      { id: 'plan', label: 'Plan', detail: openQuestions > 0 ? `${openQuestions} pregunta(s)` : busy && mode === 'plan' ? 'leyendo…' : 'solo lectura', tone: busy && mode === 'plan' ? 'active' : openQuestions > 0 ? 'wait' : 'idle' },
      { id: 'act', label: 'Act', detail: awaiting.length > 0 ? 'esperando OK' : busy && mode === 'act' ? `${activeRun?.steps.length ?? 0} pasos` : commandsOn ? 'permiso activo' : 'pide aprobación', tone: awaiting.length > 0 ? 'wait' : busy && mode === 'act' ? 'active' : 'idle' },
      { id: 'verify', label: 'Verify', detail: gates.mutation ? `mut ${gates.mutation.caught}/${gates.mutation.total}` : gates.regress === 'pass' ? 'regress pass' : gates.regress === 'check' ? 'regress: revisar' : 'sin verificar', full: verifyDetail, tone: verifyTone },
      { id: 'review', label: 'Review', detail: needsCount > 0 ? `${needsCount} esperando` : 'al día', tone: needsCount > 0 ? 'wait' : 'idle' },
    ],
    running: busy,
    mode: mode === 'act' ? 'act' : 'plan',
    engine: effectiveTarget.model || effectiveTarget.label,
    engineOnline: online,
    routerNote: `${effectiveTarget.label} · perfil ${prefs.profile}`,
    profile: prefs.profile,
    metrics: gates.metrics,
  }
  const onCoreNode = (id: CoreStage) => {
    if (id === 'plan') { void switchMode('plan'); fieldRef.current?.focus() }
    else if (id === 'act') { void switchMode('act'); fieldRef.current?.focus() }
    else if (id === 'verify') onNavigate?.('metrics')
    else onNavigate?.('board')
  }
  const starters: Array<{ title: string; run: () => void }> = [
    dirtyCount > 0
      ? { title: `Revisar ${dirtyCount} cambio${dirtyCount === 1 ? '' : 's'}`, run: () => void sendText('Revisa los cambios sin confirmar (git diff): riesgos, pruebas que faltan y si algo no debería commitearse.') }
      : { title: 'Revisar repo y tests', run: () => void sendText(STARTERS[0].prompt) },
    needsCount > 0
      ? { title: `${needsCount} entrega${needsCount === 1 ? '' : 's'} en Board`, run: () => onNavigate?.('board') }
      : { title: 'Planear cambio seguro', run: () => void sendText(STARTERS[1].prompt) },
    { title: 'Estado de motores y Board', run: () => void sendText(STARTERS[2].prompt) },
  ]
  const slashMatch = /^\/([\w-]*)$/.exec(prompt)
  const slashSkills = slashMatch ? skills.filter((sk) => sk.name.toLowerCase().includes(slashMatch[1].toLowerCase())).slice(0, 8) : []
  const slashOpen = slashSkills.length > 0
  const pickSlash = (name: string) => { setSkill(name); setPrompt(''); setSlashIdx(0); fieldRef.current?.focus() }
  const skillCats = CAT_ORDER.map((c) => [c, skills.filter((sk) => catOf(sk) === c).length] as const).filter(([, n]) => n > 0)
  useEffect(() => { document.documentElement.dataset.mode = mode === 'act' ? 'act' : 'plan' }, [mode])
  const lastAssistantRun = [...messages].reverse().find((m) => m.role === 'assistant')?.run_id

  return (
    <div className={`console no-rail ${ctxPresence.mounted ? 'has-ctx' : ''}`}>
      <section className={`talk ${busy || orchPlanning ? 'is-live' : ''}`} aria-label="Conversación" inert={phone && drawerOpen ? true : undefined}>
        <div className="talk-bar compact one-line">
          {session && !renaming && (
            <button type="button" className="sess-title-btn" onClick={() => { setRenameText(session.title); setRenaming(true) }} title="Renombrar sesión">
              <b>{session.title}</b>
            </button>
          )}
          {session && renaming && (
            <form className="rename-form" onSubmit={(e) => { e.preventDefault(); submitRename() }}>
              <input className="field field-sm" autoFocus value={renameText} maxLength={120} onChange={(e) => setRenameText(e.target.value)} />
              <button type="submit" className="btn btn-primary btn-xs">OK</button>
            </form>
          )}

          <div className="seg mode-seg" role="group" aria-label="Modo de ejecución">
            <button type="button" className="plan-btn" aria-pressed={mode === 'plan'} onClick={() => switchMode('plan')}>Plan</button>
            <button type="button" className="act-btn" aria-pressed={mode === 'act'} onClick={() => void switchMode('act')}>Act</button>
            <button type="button" className="orch-btn" aria-pressed={mode === 'orchestrate'} onClick={() => void switchMode('orchestrate')} title="Un orquestador reparte el objetivo entre varios agentes que trabajan en paralelo">Orquestar</button>
          </div>

          <EnginePopover
            open={engineOpen}
            onOpenChange={setEngineOpen}
            label={effectiveTarget.label}
            online={online}
            ollama={ollama}
            cloud={providers.filter((p) => p.id !== 'ollama')}
            intents={INTENTS}
            resolved={provMeta?.intents}
            profile={prefs.profile}
            profiles={profiles}
            tiers={tiers}
            agents={agents}
            selection={{ kind: selectionKind, intent, model, provider: providerPick, providerModel, name: agentOrTier }}
            onPick={pickEngine}
            onProvidersChanged={onProvidersChanged}
            onNavigate={onNavigate}
          />

          <SkillPopover skills={skills} value={skill} onPick={setSkill} open={skillOpen} onOpenChange={(o) => { setSkillOpen(o); if (!o) setSkillCat(null) }} category={skillCat} />

          <div className="push">
            <button type="button" className={`btn btn-quiet btn-xs tb-toggle wt-btn ${isolated ? 'on' : ''}`} disabled={!canIsolate} aria-pressed={isolated} aria-label="Worktree aislado"
              onClick={() => setIsolated((v) => !v)} title={canIsolate ? 'Worktree: aislar los cambios en una rama git aparte' : 'Worktree necesita un repo git con al menos un commit'}>
              <GitBranch className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" /><span className="tb-label">Worktree</span>
            </button>
            <button type="button" className={`btn btn-quiet btn-xs tb-toggle ${showPipeline ? 'is-on' : ''}`} aria-pressed={showPipeline} aria-label="Pipeline" onClick={() => setShowPipeline((p) => !p)} title="Pipeline: cómo fluye el trabajo ahora mismo">
              <Zap className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" /><span className="tb-label">Pipeline</span>
            </button>
            <button type="button" className={`btn btn-xs tb-toggle ${drawerOpen ? 'is-on' : ''}`} aria-pressed={drawerOpen} aria-label="Inspector" onClick={() => setDrawerOpen((d) => !d)} title={`Inspector: archivos, diff, pasos y worktrees${dirtyCount > 0 ? ` (${dirtyCount} cambios)` : ''}`}>
              <FolderGit2 className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" /><span className="tb-label">Inspector{dirtyCount > 0 ? ` (${dirtyCount})` : ''}</span>
              {!wide && dirtyCount > 0 && <span className="tb-dot" aria-hidden="true" />}
            </button>
          </div>
        </div>

        <div className={`safety slim ${mode === 'act' ? 'armed' : ''}`}>
          {mode === 'orchestrate' ? (
            <span className="orch-safety">Modo ORQUESTAR: un orquestador reparte el objetivo, tú editas el plan y varios subagentes trabajan en paralelo. Los que editan lo hacen cada uno en su worktree.</span>
          ) : (
            <label>
              <input type="checkbox" checked={commandsOn} disabled={!sid} onChange={(e) => toggleCommands(e.target.checked)} />
              {mode === 'act' ? 'Permiso ACT activo: lectura automática, escritura/shell pide confirmación.' : 'Modo PLAN (Acero): solo análisis y preguntas de alineación sin modificar archivos.'}
            </label>
          )}
          <span className="mono muted">{mode === 'orchestrate' ? `orquesta ${orchestrator || '—'}` : effectiveTarget.label}</span>
        </div>

        {showPipeline && (
          <div className="pipeline-drawer">
            <SystemFlowDiagram state={state} router={routerSummary} providers={providers} workspace={wsStatus} onNavigate={onNavigate} compact />
          </div>
        )}

        <div className="feed" ref={feedRef}>
          {err && <div className="banner err" role="alert"><span>{err}</span><button type="button" className="btn btn-quiet btn-xs" onClick={() => setErr(null)}>Cerrar</button></div>}

          {messages.length === 0 && !busy && (
            <div className="talk-empty hero">
              <StageRow data={coreData} onNode={onCoreNode} onRouter={() => setEngineOpen(true)} />
              <p className="hero-caption"><b>{project || 'CAOS Workstation'}</b> · {mode === 'plan' ? 'Plan lee y pregunta, no toca archivos' : mode === 'act' ? 'Act cambia archivos y pide tu aprobación en cada escritura' : 'Orquestar reparte un objetivo entre varios agentes y tú revisas el plan'}</p>
              <ol className="hero-steps" aria-label="How it works">
                <li><b>1 · Pick a mode</b><span>Plan reads and asks · Act edits with your approval · Orchestrate splits the goal among a team</span></li>
                <li><b>2 · Pick the engines</b><span>Free and local models cost nothing; a paid agent starts only after a free scout has read the code for it</span></li>
                <li><b>3 · Give the verdict</b><span>Nothing closes until you review the delivery on the Board</span></li>
              </ol>
              <div className="starter-row" role="group" aria-label="Arranques rápidos">
                {starters.map((st) => (
                  <button key={st.title} type="button" className="starter-chip" onClick={st.run}>
                    <Sparkles className="icon" style={{ width: 13, height: 13, color: 'var(--champan)' }} />
                    <span>{st.title}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, mi) => {
            const prevAssistant = m.role === 'assistant' ? [...messages.slice(0, mi)].reverse().find((x) => x.role === 'assistant') : undefined
            const changed = !!prevAssistant && (prevAssistant.provider !== m.provider || prevAssistant.model !== m.model)
            return (
            <React.Fragment key={m.id}>
            {changed && prevAssistant && (
              <div className="engine-divider" role="separator" aria-label="Cambio de motor">
                <Repeat2 className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />
                <span>Motor: {prevAssistant.provider || 'ollama'} · {prevAssistant.model || 'auto'} → <b>{m.provider || 'ollama'} · {m.model || 'auto'}</b></span>
              </div>
            )}
            <article className={`turn ${m.role === 'user' ? 'me' : ''} ${freshTurns.has(m.id) ? 'fresh' : ''}`}>
              <div className="turn-head">
                <b>{m.role === 'user' ? 'Tú' : `${m.provider || 'ollama'}${m.model ? ` · ${m.model}` : ''}`}</b>
                <span>
                  {m.task_id != null && (
                    <button type="button" className="task-badge-btn" onClick={() => onOpenTask?.(m.task_id!)}>
                      Task #{pad(m.task_id)} →
                    </button>
                  )}
                  {m.attached && m.attached.length > 0 && ` · @${m.attached.length}`}
                  {m.agent && m.agent !== 'auto' ? ` · ${m.agent}` : ''}
                </span>
              </div>
              {m.tool_steps && m.tool_steps.length > 0 && !m.orchestration && <ToolStepsView steps={m.tool_steps} />}
              {m.orchestration ? <OrchestrationLive orch={m.orchestration} live={false} onOpenTask={onOpenTask} /> : <div className="turn-body">{m.content}</div>}

              {m.questions && m.questions.length > 0 && (
                <div className="plan-qa-card">
                  <div className="plan-qa-head">Preguntas de alineación (Plan)</div>
                  {m.questions.map((q, qi) => (
                    <div key={qi} className="plan-q-item">
                      <span className="plan-q-text">{qi + 1}. {q.question}</span>
                      <div className="plan-q-chips">
                        {(q.chips || []).map((ch) => (
                          <button
                            key={ch}
                            type="button"
                            className={`qa-chip ${planAnswers[q.question] === ch ? 'selected' : ''}`}
                            onClick={() => setPlanAnswers((cur) => ({ ...cur, [q.question]: ch }))}
                          >
                            {ch}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                  <div className="plan-qa-foot">
                    <button type="button" className="btn btn-primary btn-xs" onClick={() => passToActWithAnswers(m.questions!)}>
                      Pasar a Act con respuestas
                    </button>
                  </div>
                </div>
              )}

              {m.diff && <DiffViewer diffText={m.diff} onSendDrafts={(txt) => setPrompt((cur) => (cur ? `${cur}\n${txt}` : txt))} annotateLabel="Citar en seguimiento" />}

              {m.role === 'assistant' && (
                <div className="turn-act">
                  {m.task_id != null && !quickReviewed[m.task_id] && (
                    <>
                      <button type="button" onClick={() => quickVerdict(m.task_id!, 'ok')}><CheckCircle2 className="icon" style={{ width: 13, height: 13 }} />Aceptar #{pad(m.task_id)}</button>
                      <button type="button" onClick={() => quickVerdict(m.task_id!, 'redo')}><ShieldAlert className="icon" style={{ width: 13, height: 13 }} />Devolver</button>
                    </>
                  )}
                  <button type="button" onClick={() => { navigator.clipboard.writeText(m.content); setCopiedId(m.id); setTimeout(() => setCopiedId(null), 1200) }}>
                    {copiedId === m.id ? <Check className="icon" style={{ width: 13, height: 13 }} /> : <Copy className="icon" style={{ width: 13, height: 13 }} />}
                    {copiedId === m.id ? 'Copiado' : 'Copiar'}
                  </button>
                  {m.task_id == null && (
                    <button type="button" onClick={() => toTask(m.id, m.content)}>
                      <ListPlus className="icon" style={{ width: 13, height: 13 }} />
                      {promotedId === m.id ? 'En Board' : 'Crear tarea'}
                    </button>
                  )}
                </div>
              )}
            </article>
            </React.Fragment>
            )
          })}

          {activeRun?.failover_used && (busy || activeRun.id === lastAssistantRun) && (
            <div className="engine-divider failover" role="separator" aria-label="Auto-Failover">
              <Repeat2 className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />
              <span>Auto-Failover: el motor falló y la respuesta siguió en <b>{activeRun.failover_used}</b></span>
            </div>
          )}

          {activeRun && awaiting.map(({ s, i }) => (
            <div key={i} ref={i === awaiting[0].i ? approvalRef : undefined} className="run-card amber-card" role="alertdialog" aria-modal="false">
              <div className="run-card-head">
                <ShieldAlert className="icon amber" style={{ width: 16, height: 16 }} aria-hidden="true" />
                <b>Aprobación requerida en Act</b>
              </div>
              <dl className="act-summary-dl">
                {s.summary_what && <><dt>Qué</dt><dd>{s.summary_what}</dd></>}
                {s.summary_why && <><dt>Para qué</dt><dd>{s.summary_why}</dd></>}
                {s.summary_goal && <><dt>Objetivo</dt><dd>{s.summary_goal}</dd></>}
              </dl>
              {s.preview && !s.preview.error ? <WritePreviewBlock p={s.preview} /> : <pre className="act-cmd-pre">{s.input}</pre>}
              {s.preview?.error && <p className="verdict-err" role="alert">{s.preview.error}</p>}
              <div className="verdict-row">
                <button type="button" className="btn btn-primary btn-sm" onClick={() => decide(i, true, false)}>Aprobar</button>
                <button type="button" className="btn btn-amber btn-sm" onClick={() => decide(i, true, true)}>Confiar en esta sesión</button>
                <button type="button" className="btn btn-sm" data-safe onClick={() => decide(i, false, false)}>Rechazar</button>
                <button type="button" className="btn btn-quiet btn-sm" onClick={stopRun}><Square className="icon" style={{ width: 12, height: 12 }} />Detener</button>
              </div>
            </div>
          ))}

          {orchPlanning && (
            <div className="thinking" role="status">
              <span className="think-dots" aria-hidden="true"><i /><i /><i /></span>
              <span>{orchestrator || 'El orquestador'} está repartiendo el objetivo…</span>
            </div>
          )}

          {orchPlan && orchOptions && (
            <CriticalDesk
              plan={orchPlan}
              options={orchOptions}
              skills={skills}
              canIsolate={canIsolate}
              blocked={busy}
              busy={orchPlanning}
              onChange={setOrchPlan}
              onReplan={() => void planGoal(orchPlan.goal, orchPlan.orchestrator)}
              onLaunch={() => void launchOrchestration()}
              onDiscard={() => setOrchPlan(null)}
            />
          )}

          {busy && activeRun?.orchestration && activeRun.status !== 'awaiting_approval' && (
            <OrchestrationLive orch={activeRun.orchestration} live onOpenTask={onOpenTask} onStop={stopRun} />
          )}

          {busy && activeRun && !activeRun.orchestration && activeRun.status !== 'awaiting_approval' && (
            <div className="thinking" role="status">
              <span className="think-dots" aria-hidden="true"><i /><i /><i /></span>
              <div style={{ flex: 1 }}>
                <span>{activeRun.status === 'finishing' ? 'Guardando respuesta…' : `Ejecutando con ${effectiveTarget.label}…`}</span>
                {activeRun.steps.length > 0 && <ToolStepsView steps={activeRun.steps} />}
              </div>
              <button type="button" className="btn btn-xs" onClick={stopRun}><Square className="icon" style={{ width: 12, height: 12 }} />Detener</button>
            </div>
          )}
        </div>

        <div className="talk-compose">
          {queue.length > 0 && (
            <div className="queue-tray">
              <span className="mono muted">En cola ({queue.length})</span>
              {queue.map((qt, qi) => (
                <span key={qi} className="queue-item">
                  <button type="button" className="view-chip" title="Volver al compositor" onClick={() => { setQueue((q) => q.filter((_, k) => k !== qi)); setPrompt(qt) }}>
                    {qt.slice(0, 32)}
                  </button>
                  {busy && <button type="button" className="btn btn-amber btn-xs" onClick={() => void stopAndSendNow(qi)} title="Detiene el turno actual y envía este mensaje ahora"><Square className="icon" style={{ width: 11, height: 11 }} aria-hidden="true" />Detener y enviar ya</button>}
                </span>
              ))}
            </div>
          )}

          {attachMenu && (
            <div className="attach-pop card" role="dialog" aria-label="Adjuntar archivo" ref={attachRef}>
              <div className="attach-pop-head">
                <input className="field field-sm" value={attachFilter} onChange={(e) => setAttachFilter(e.target.value)} placeholder="Filtrar archivo…" />
                <button type="button" className="btn btn-quiet btn-xs" onClick={() => setAttachMenu(false)}><X className="icon" style={{ width: 13, height: 13 }} /></button>
              </div>
              <ul className="attach-pop-list">
                {filteredAttach.map((f) => (
                  <li key={f}><button type="button" className="mono" onClick={() => attachIntoComposer(f)}>@{f}</button></li>
                ))}
              </ul>
            </div>
          )}

          {skillCats.length > 0 && !slashOpen && (
            <div className="skill-chips" role="group" aria-label="Skills por categoría">
              {skillCats.map(([cat, n]) => (
                <button key={cat} type="button" className="skill-chip" style={{ ['--cat' as string]: CAT_ACCENT[cat] }} onClick={() => { setSkillCat(cat); setSkillOpen(true) }} title={`${n} skill(s) de ${cat}`}>{cat} <span className="muted">{n}</span></button>
              ))}
              {skill !== 'auto' && <button type="button" className="skill-chip on" onClick={() => setSkill('auto')} title="Quitar el skill">{skill} <X className="icon" style={{ width: 11, height: 11 }} aria-hidden="true" /></button>}
              <span className="mono muted skill-hint">escribe <kbd className="kbd">/</kbd> para elegir uno</span>
            </div>
          )}
          {mode === 'orchestrate' && orchOptions && orchestrator && (
            <OrchestrateBar options={orchOptions} orchestrator={orchestrator} pool={poolNames} onOrchestrator={setOrchSel} onPool={setOrchPool} scout={orchScout} onScout={setOrchScout} onAdd={(id) => void addOrchAgent(id)} adding={orchAdding} />
          )}
          <div className="composer">
            {slashOpen && (
              <div className="slash-menu" role="listbox" aria-label="Skills">
                {slashSkills.map((sk, i) => (
                  <button key={sk.name} type="button" role="option" aria-selected={i === slashIdx} className={i === slashIdx ? 'on' : ''} onMouseDown={(e) => { e.preventDefault(); pickSlash(sk.name) }}>
                    <span>/{sk.name}</span><small>{sk.description}</small>
                  </button>
                ))}
              </div>
            )}
            <textarea
              ref={fieldRef}
              className="composer-field"
              value={prompt}
              aria-label="Prompt"
              placeholder={mode === 'orchestrate' ? 'Describe el objetivo que se repartirá entre los subagentes…' : `Escribe tu tarea en modo ${mode.toUpperCase()} (@archivo para adjuntar)…`}
              onChange={(e) => { setPrompt(e.target.value); setSlashIdx(0) }}
              onKeyDown={(e) => {
                if (slashOpen) {
                  if (e.key === 'ArrowDown') { e.preventDefault(); setSlashIdx((i) => (i + 1) % slashSkills.length); return }
                  if (e.key === 'ArrowUp') { e.preventDefault(); setSlashIdx((i) => (i - 1 + slashSkills.length) % slashSkills.length); return }
                  if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickSlash(slashSkills[Math.min(slashIdx, slashSkills.length - 1)].name); return }
                  if (e.key === 'Escape') { setPrompt(''); return }
                }
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  void sendText(prompt)
                }
              }}
            />
            <div className="composer-bar">
              <button type="button" className="btn btn-quiet btn-xs" onClick={() => { loadWorkspaceMeta(); setAttachMenu((m) => !m) }}>
                <FilePlus2 className="icon" style={{ width: 13, height: 13 }} />@ Archivo
              </button>
              <span className={`chip-inline ${mode === 'act' ? 'amber' : mode === 'orchestrate' ? 'copper' : 'steel'}`}>{mode === 'orchestrate' ? 'ORQUESTAR' : mode.toUpperCase()}</span>
              <span className="chip-inline">{mode === 'orchestrate' ? `orquesta ${orchestrator || '—'}` : effectiveTarget.label}</span>
              <span className="grow" />
              <button type="button" className="btn btn-primary btn-sm" disabled={mode === 'orchestrate' ? !prompt.trim() || orchPlanning : !prompt.trim() && !busy} onClick={() => sendText(prompt)}>
                <ShieldCheck className="icon" style={{ width: 13, height: 13 }} />
                {mode === 'orchestrate' ? 'Planificar' : busy ? 'Encolar' : 'Enviar'}
                <ArrowRight className="icon" style={{ width: 14, height: 14 }} />
              </button>
            </div>
          </div>
        </div>
      </section>

      <WorkspaceDrawer
        isOpen={ctxPresence.mounted}
        leaving={ctxPresence.leaving}
        modal={phone}
        onClose={() => setDrawerOpen(false)}
        activeRepo={project}
        worktreeKey={isolated && sid ? sid : null}
        initialTab={drawerTab}
        refreshKey={drawerRefresh}
        onAttachFile={attachIntoComposer}
        onCiteDiff={(sn) => setPrompt((cur) => `${cur}\n${sn}`)}
        onSendDrafts={(txt) => setPrompt((cur) => (cur ? `${cur}\n${txt}` : txt))}
        steps={activeRun?.steps ?? []}
        onWorktreeDiscarded={() => { setIsolated(false); loadWorkspaceMeta(); if (sid) void loadSession(sid) }}
        onTaskCreated={onBoardChanged}
      />
    </div>
  )
}

/* What an approval is asking to write: the file, whether it is new, how big, and the change itself as a coloured diff. */
const WritePreviewBlock: React.FC<{ p: NonNullable<import('../api').ToolStep['preview']> }> = ({ p }) => (
  <div className="write-preview">
    <div className="write-preview-head">
      <b className="mono">{p.path}</b>
      <span className="chip">{p.new_file ? 'archivo nuevo' : 'cambio'}</span>
      <span className="mono"><b className="plus">+{p.added ?? 0}</b> <b className="minus">-{p.removed ?? 0}</b></span>
      <span className="mono muted">{p.bytes ?? 0} B · {p.lines ?? 0} líneas</span>
    </div>
    <pre className="write-preview-diff">{(p.diff || '').split('\n').filter((ln) => !ln.startsWith('--- ') && !ln.startsWith('+++ ')).map((ln, i) => (
      <span key={i} className={ln.startsWith('+') ? 'd-add' : ln.startsWith('-') ? 'd-del' : ln.startsWith('@@') ? 'd-hunk' : 'd-ctx'}>{ln || ' '}{'\n'}</span>
    ))}</pre>
    {p.diff_truncated && <small className="muted">La vista previa se corta aquí; el cambio continúa.</small>}
  </div>
)
