export interface Agent {
  name: string
  system: string | null
  provider?: string | null
  model?: string | null
  command: string
  timeout: number
  pending: number
  working: number
}

export interface TaskRouterInfo {
  tier: string
  system: string | null
  action: string
  reason?: string
}

export interface Task {
  id: number
  text: string
  state: "pending" | "person" | "sending" | "sent" | "to_review" | "ok" | "redo" | "verify" | "superseded" | "discarded"
  status: "pending" | "sending" | "sent" | "discarded"
  queue: string
  agent: string | null
  skill: string | null
  created: number
  sent_at: number | null
  review: "ok" | "redo" | "verify" | "superseded" | null
  review_note: string | null
  reviewed_at: number | null
  delivered: boolean
  router?: TaskRouterInfo
  /** The task that split this one into subtasks (orchestration), or null. */
  parent_id: number | null
  /** What the delivery must demonstrate to be accepted, or null. */
  criteria: string | null
  /** The isolated git worktree this subtask worked in, or null. */
  worktree_key: string | null
}

export interface TraceEvent {
  seq: number
  ts: number
  source: string
  kind: string
  name: string | null
  status: string
  reason: string | null
}

export interface TaskDetail extends Task {
  result: string | null
  timeline: TraceEvent[]
}

// Mirrors Board.stats() in caos_harness/board/core.py: aggregates only, no task text.
export interface BoardStats {
  tasks: number
  by_status: Record<string, number>
  review: Record<string, number>
  returned_at_least_once: number
  by_agent: Record<string, number>
}

/** Mirrors app.summary(): counts over every task, the same figures the terminal shows. `to_review` already includes `verify`. */
export interface BoardSummary {
  tasks: number
  needs_you: number
  to_review: number
  with_person: number
  runnable: number
  agents: number
}

export interface Quality {
  mutation?: { caught: number; total: number; source: string }
}

export interface SkillInfo {
  name: string
  description: string
  local?: boolean
  category?: string
  team_shareable?: boolean
  body?: string
}

export interface StateResponse {
  project: string
  root?: string
  now: number
  agents: Agent[]
  tasks: Task[]
  stats: BoardStats
  /** Counts over every task (not only the 400 listed in `tasks`); `needs_you` is the figure the TUI shows as "waiting for you". */
  summary?: BoardSummary
  quality?: Quality
  running: boolean
  sample?: boolean
  last_run: Array<{ id: number; ok: boolean; reason: string }>
  skills: SkillInfo[]
  tiers: string[]
}

export interface RouterTier {
  tier: string
  needs: number
  action: string
  system: string | null
  agent: string | null
  reason: string
}

export interface ModelProfile {
  system: string
  measured: string
  precision: number
  precision_lo: number
  precision_hi?: number | null
  n?: number
  coverage: number
  seconds_per_1000: number
  tokens_per_1000: number | null
  demoted?: boolean
}

export interface RouterResponse {
  tiers: RouterTier[]
  profiles: ModelProfile[]
}

export interface ModelDetail {
  name: string
  size: number | null
  parameter_size: string | null
  quantization: string | null
  family: string | null
}

export interface Workspace {
  name: string
  path: string
  current: boolean
  ready: boolean
}

export interface WorkspacesResponse {
  current: string
  items: Workspace[]
}

export interface ProviderItem {
  id: string
  name: string
  type: "local" | "cloud" | "custom"
  status: "online" | "ready" | "missing_key" | "invalid_key" | "offline" | "key_present"
  quota: string
  cost_per_m: string
  models: string[]
  model_details?: ModelDetail[]
  default_model: string
  description: string
  is_fallback?: boolean
  fallback_to?: string
  base_url?: string
  api_key_env?: string
  key_source?: string
  key_masked?: string
  key_error?: string
  kind?: string
  enabled?: boolean
  wired?: boolean
  free_models?: string[]
  tier_hint?: string
}

export interface OllamaHost {
  id: string
  label: string
  url: string
  online?: boolean
  latency_ms?: number
  models?: string[]
  error?: string
}

export interface IntentResolution {
  intent: string
  label?: string
  provider: string
  model: string
  base_url?: string
  source?: string
  pinned?: boolean
  fallback_used?: boolean
  healthy?: boolean
}

export interface FailoverPolicy {
  enabled: boolean
  strategy: string
  fallback_target: string
  fallback_provider?: string
  fallback_model: string
  description: string
}

export interface CliAgent {
  id: string
  label: string
  account: string
  installed: boolean
  command: string
  added: boolean
  free_models?: string[]
  models?: string[]
  orchestrator_capable?: boolean
}

export interface ProvidersResponse {
  providers: ProviderItem[]
  ollama_hosts?: OllamaHost[]
  intents?: Record<string, IntentResolution>
  active_failover: FailoverPolicy
  clis?: CliAgent[]
  api_agents?: Array<{ name: string; provider: string; model: string }>
}

export interface ProviderTest {
  ok: boolean
  message: string
  models?: string[]
  source?: string
  latency_ms?: number
  json_ok?: boolean
  tools_ok?: boolean
  error?: string
  answer?: string
  usage?: { prompt_tokens: number; completion_tokens: number }
}

export interface ToolStep {
  name: string
  kind: 'read' | 'write' | 'bash' | 'skill' | 'memory'
  status: 'awaiting_approval' | 'running' | 'completed' | 'failed' | 'denied' | 'expired'
  input?: string
  output?: string
  duration_ms?: number
  exit_code?: number
  summary_what?: string
  summary_why?: string
  summary_goal?: string
  preview?: WritePreview
}

export interface WritePreview {
  path?: string
  error?: string
  new_file?: boolean
  bytes?: number
  lines?: number
  added?: number
  removed?: number
  diff?: string
  diff_truncated?: boolean
  content?: string
  content_truncated?: boolean
}

export interface WorktreeInfo {
  key: string
  path: string
  branch: string
  was_branch_pre_existing: boolean
  included_files?: string[]
  created_at?: number
}

export interface ExecutionRun {
  id: string
  status: "queued" | "running" | "awaiting_approval" | "finishing" | "completed" | "failed" | "stopped"
  model: string
  provider?: string
  target_kind?: "model" | "agent" | "tier" | "provider" | "intent" | "orchestrate"
  target?: string
  task_id?: number
  queue?: string
  cancelled?: boolean
  orchestration?: OrchestrationState
  workspace: string
  worktree?: WorktreeInfo | null
  diff?: string | null
  steps: ToolStep[]
  questions?: AlignmentQuestion[]
  usage?: { prompt_tokens: number; completion_tokens: number }
  failover_used?: string | null
  answer: string
  error: string
}

export interface WorkspaceStatus {
  repo: string
  path: string
  git_repo?: boolean
  has_head?: boolean
  branch: string | null
  dirty_files: string[]
  worktrees?: WorktreeInfo[]
  integrated_worktrees?: string[]
  skills: string[]
  agents: string[]
  stats: BoardStats
  quality?: Quality
}

export interface PreflightCheck {
  id: string
  label: string
  level: 'ok' | 'info' | 'warning' | 'blocked'
  detail: string
  action: string
}

export interface PreflightResponse {
  ok: boolean
  verdict: 'ready' | 'warning' | 'blocked'
  dry_run: boolean
  tokens_spent: number
  project: string | null
  summary: Record<string, number>
  checks: PreflightCheck[]
  next_actions: string[]
}

export interface ActivityEvent {
  ts: number
  kind: 'intent' | 'delegated' | 'done' | 'blocked' | 'returned'
  task_id: number
  text: string
  agent: string
  note: string
}

export interface ActivityResponse {
  events: ActivityEvent[]
  summary: { needs_you: number; running: number; pending: number; to_review: number; with_person: number; closed: number }
}

export interface GlobalTask {
  id: number
  state: string
  queue: string
  text: string
  created: number
  needs_you: boolean
}

export interface GlobalWorkspace {
  name: string
  path: string
  current: boolean
  tasks: GlobalTask[]
  counts: { needs_you: number; open: number }
  error: string
}

export interface GlobalBoardResponse {
  workspaces: GlobalWorkspace[]
  readonly: boolean
}

export interface WorktreeInspect {
  key: string
  branch: string
  base: string
  ahead: number
  behind: number
  dirty: number
  integrated: boolean
  files: Array<{ path: string; added: number; removed: number; committed: boolean }>
}

export interface PatchExport {
  ok: boolean
  filename: string
  relative_path: string
  size_bytes: number
  files: number
}

export interface MetricsSeries {
  scope: string
  bucket: 'hour' | 'day'
  min_runs: number
  total_runs: number
  enough: boolean
  points: Array<{ t: number; runs: number; ok: number; success_rate: number; p50_ms: number | null }>
}

export interface SharePreview {
  ok: boolean
  dry_run: boolean
  format: string
  included: Array<{ path: string; size: number; redacted_lines: number; sanitized?: boolean }>
  generated: Array<{ path: string; size: number }>
  excluded: Array<{ path: string; reason: string }>
  redactions: Array<{ path: string; lines: number[]; kinds: string[] }>
  redacted_paths: string[]
  unscanned: string[]
  files_count: number
  total_bytes: number
  skills_included: string[]
  sanitization: Array<{ id: string; label: string; ok: boolean }>
  onboarding: string[]
}

export interface ChangedFile {
  path: string
  status: "added" | "modified" | "deleted"
  additions: number
  deletions: number
}

export interface WorkspaceDiffResponse {
  git_repo: boolean
  branch: string | null
  dirty_files: string[]
  files: ChangedFile[]
  diff: string
  preview: { path: string; kind: "html" | "svg"; content: string } | null
  path: string
  worktree?: WorktreeInfo | null
}

export type OrchestrationMode = "readonly" | "isolated"
export type SubtaskState = "queued" | "running" | "delivered" | "failed" | "cancelled"

/** One subtask of a plan, as the orchestrator proposes it and as the person edits it. */
export interface OrchestrationSubtask {
  id: string
  title: string
  agent: string
  mode: OrchestrationMode
  skill: string | null
  task: string
  criteria: string
}

export interface OrchestrationPlan {
  goal: string
  orchestrator: string
  pool: string[]
  summary: string
  recommended_orchestrator: string
  subtasks: OrchestrationSubtask[]
  /** `orchestrator` when the agent answered with a plan, `fallback` when this is a proposal the harness made, `edited` after the person changed it. */
  source: "orchestrator" | "fallback" | "edited"
  note: string
  suggested?: OrchestratorSuggestion
}

export interface OrchestratorInfo {
  name: string
  family: string | null
  kind: "cli" | "local" | "api" | "command"
  model: string | null
  installed: boolean
  capable: boolean
}

export interface OrchestratorSuggestion {
  name: string | null
  reason: "local" | "fast" | "architecture" | "default"
  alternatives: string[]
}

export interface OrchestrateOptions {
  orchestrators: OrchestratorInfo[]
  pool: OrchestratorInfo[]
  suggested: OrchestratorSuggestion
  default_orchestrator: string | null
  installable: Array<{ id: string; label: string }>
}

/** A subtask while it runs and after: the plan's fields plus what the board and the agent produced. */
export interface SubtaskRun extends OrchestrationSubtask {
  state: SubtaskState
  task_id: number | null
  worktree: { key: string; path: string; branch: string } | null
  duration_ms: number | null
  elapsed_ms: number
  result: string
  diff: string
  error: string
  note: string
}

export interface OrchestrationState {
  goal: string
  orchestrator: string
  summary: string
  phase: "queued" | "delegating" | "synthesizing" | "done" | "stopped"
  parent_id: number | null
  subtasks: SubtaskRun[]
  synthesis: string
}

export interface AlignmentQuestion {
  question: string
  chips: string[]
}

export interface MessageItem {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: number
  model?: string
  provider?: string
  target_kind?: "model" | "agent" | "tier" | "provider" | "intent" | "orchestrate"
  target?: string
  task_id?: number
  orchestration?: OrchestrationState
  orchestrate?: boolean
  agent?: string
  tier?: string
  tokens?: number
  cost_saved?: number
  attached?: string[]
  tool_steps?: ToolStep[]
  questions?: AlignmentQuestion[]
  diff?: string | null
  run_id?: string
  bash_logs?: string | null
}

export interface SessionItem {
  id: string
  title: string
  project: string
  /** Resolved path of the project the session belongs to; absent in sessions made before it was recorded. */
  root?: string
  created_at: number
  updated_at: number
  mode: "plan" | "act" | "orchestrate"
  target_kind?: "model" | "agent" | "tier" | "provider" | "intent" | "orchestrate"
  target?: string
  messages_count: number
}

export interface SessionDetail extends SessionItem {
  active_run?: string | null
  commands_enabled?: boolean
  active_worktree?: WorktreeInfo | null
  messages: MessageItem[]
}

export interface RepositoryItem {
  name: string
  path: string
  current: boolean
}

/** Live updates. `EventSource` exists in every browser but not in jsdom (the tests): without it these return null and the caller keeps polling. */
export const liveSupported = (): boolean => typeof EventSource !== 'undefined'

export interface LiveHandle {
  close: () => void
}

/** Board, run and session changes as they happen. `onChange` gets the version of each channel; `onState` tells whether the stream is up. */
export function watchEvents(onChange: (v: Record<string, number>) => void, onState?: (connected: boolean) => void): LiveHandle | null {
  if (!liveSupported()) return null
  const es = new EventSource('/api/events')
  es.addEventListener('change', (e) => {
    try {
      onChange(JSON.parse((e as MessageEvent).data))
    } catch {
      /* a malformed event is ignored: the next one or the backup poll catches up */
    }
  })
  es.onopen = () => onState?.(true)
  es.onerror = () => onState?.(false)   // EventSource reconnects by itself; the backup poll covers the gap
  return { close: () => es.close() }
}

/** One run as it changes, until it ends. Returns null when the browser has no EventSource. */
export function watchRun(id: string, onRun: (run: ExecutionRun) => void, onState?: (connected: boolean) => void): LiveHandle | null {
  if (!liveSupported()) return null
  const es = new EventSource(`/api/runs/${id}/events`)
  const terminal = ['completed', 'failed', 'stopped']
  es.addEventListener('run', (e) => {
    try {
      const run = JSON.parse((e as MessageEvent).data) as ExecutionRun
      onRun(run)
      if (terminal.includes(run.status)) es.close()   // the server ends the stream; closing here stops EventSource from reconnecting to it
    } catch {
      /* ignored: see above */
    }
  })
  es.onopen = () => onState?.(true)
  es.onerror = () => onState?.(false)
  return { close: () => es.close() }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (options.method && options.method !== 'GET') {
    headers.set('X-Harness', '1')
    if (!headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }
  }

  const res = await fetch(path, {
    ...options,
    headers,
  })

  if (!res.ok) {
    let errMessage = `Error ${res.status}`
    try {
      const data = await res.json()
      if (data.error) errMessage = data.error
    } catch {
      // ignore json parse error
    }
    throw new Error(errMessage)
  }

  return res.json()
}

export interface MetricsModelRow {
  provider: string
  model: string
  runs: number
  ok: number
  errors: number
  success_rate: number
  p50_ms: number
  tokens: number
  last_smoke: { ok: boolean; ms: number; json_ok: boolean; ts: number } | null
  demoted: boolean
}

export interface MetricsResponse {
  scope: "project" | "global"
  project: string
  kpis: {
    runs_total: number
    run_success_rate: number | null
    human_redo_rate: number | null
    returned: number
    reviewed_total: number
    p50_latency_ms: number | null
    tokens: { prompt: number; completion: number; total: number }
    gates: {
      mutation: { caught: number; total: number } | null
      eval_precision: number | null
      regress_status: string | null
    }
  }
  models: MetricsModelRow[]
  compare?: { runs: number; models: Array<{ provider: string; model: string; runs: number; ok_rate: number; p50_ms: number | null }> }
}

export interface ToolInfo {
  id: string
  name: string
  kind: string
  status: string
  summary: string
  shareable: boolean
}

export interface ShareDoctorIssue {
  path: string
  line: number
  kind: "secret_file" | "secret_token" | "private_path"
  message: string
}

export interface ShareDoctorResponse {
  clean: boolean
  scanned: number
  total_issues?: number
  issues: ShareDoctorIssue[]
}

export interface SharePackResponse {
  ok: boolean
  format: "zip" | "dir" | "tar.gz"
  verified?: boolean
  redacted_paths?: string[]
  excluded?: Array<{ path: string; reason: string }>
  path: string
  relative_path: string
  filename: string
  size_bytes: number
  files_count: number
  skills_included: string[]
  doctor: ShareDoctorResponse
}

export interface ShareUploadResponse {
  ok: boolean
  provider?: string
  file_id?: string
  url?: string
  filename?: string
  message?: string
}

export interface ShareExportsResponse {
  exports: Array<{ filename: string; relative_path: string; is_dir: boolean; size_bytes: number; mtime: number }>
  gdrive_connected: boolean
}

export const api = {
  getState: () => request<StateResponse>('/api/state'),
  getRouter: () => request<RouterResponse>('/api/router'),
  getProviders: (profile?: string) => request<ProvidersResponse>(`/api/providers${profile ? `?profile=${encodeURIComponent(profile)}` : ''}`),
  getWorkspaces: () => request<WorkspacesResponse>('/api/workspaces'),
  addWorkspace: (path: string, initialize = false) =>
    request<WorkspacesResponse>('/api/workspaces', { method: 'POST', body: JSON.stringify({ path, initialize }) }),
  switchWorkspace: (path: string) =>
    request<WorkspacesResponse>('/api/workspaces/switch', { method: 'POST', body: JSON.stringify({ path }) }),
  removeWorkspace: (path: string) =>
    request<WorkspacesResponse>('/api/workspaces/remove', { method: 'POST', body: JSON.stringify({ path }) }),
  getRepositories: () => request<RepositoryItem[]>('/api/repositories'),
  getSessions: () => request<SessionItem[]>('/api/sessions'),
  getSession: (id: string) => request<SessionDetail>(`/api/sessions/${id}`),
  createSession: (data: { title?: string; mode?: string; project?: string }) =>
    request<SessionItem>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  renameSession: (id: string, data: { title: string; target_kind?: string; target?: string }) =>
    request<SessionItem>(`/api/sessions/${id}/rename`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  setSessionCommands: (id: string, enabled: boolean) =>
    request<{ id: string; commands_enabled: boolean }>(`/api/sessions/${id}/commands`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),
  deleteSession: (id: string) =>
    request<{ deleted: boolean }>(`/api/sessions/${id}/delete`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  getPreflight: (dryRun = false) => request<PreflightResponse>(`/api/preflight${dryRun ? '?dry_run=1' : ''}`),
  getActivity: () => request<ActivityResponse>('/api/activity'),
  getGlobalSessions: () => request<{ sessions: Array<{ id: string; title: string; mode: string; target?: string; messages_count: number; updated_at: number; workspace: string; workspace_path: string; current: boolean }>; readonly: boolean }>("/api/sessions/global"),
  getGlobalBoard: () => request<GlobalBoardResponse>('/api/board/global'),
  inspectWorktree: (key: string) => request<WorktreeInspect>(`/api/workspace/worktree?key=${encodeURIComponent(key)}`),
  exportPatch: (key?: string) => request<PatchExport>('/api/workspace/worktree/patch', { method: 'POST', body: JSON.stringify({ key }) }),
  cleanupWorktrees: () => request<{ removed: string[]; kept_busy: string[] }>('/api/workspace/worktree/cleanup', { method: 'POST', body: JSON.stringify({}) }),
  downloadUrl: (file: string) => `/api/share/download?file=${encodeURIComponent(file)}`,
  compareProviders: (data: { prompt: string; sides: Array<{ provider: string; model: string }>; confirm_cloud?: boolean }) =>
    request<{ results: Array<{ provider: string; model: string; ok: boolean; latency_ms: number; json_ok: boolean; tool_calls: number; answer: string; prompt_tokens: number; completion_tokens: number; error: string }>; cloud: boolean }>('/api/providers/compare', { method: 'POST', body: JSON.stringify(data) }),
  getMetricsSeries: (scope: 'project' | 'global' = 'project', bucket: 'hour' | 'day' = 'day') => request<MetricsSeries>(`/api/metrics/series?scope=${scope}&bucket=${bucket}`),
  cloneSkill: (name: string) => request<SkillInfo>('/api/skills/clone', { method: 'POST', body: JSON.stringify({ name }) }),
  getSharePreview: (opts: { format: 'zip' | 'tar.gz' | 'dir'; include_code: boolean; include_docs: boolean; include_skills: boolean }) =>
    request<SharePreview>(`/api/share/preview?format=${opts.format}&include_code=${+opts.include_code}&include_docs=${+opts.include_docs}&include_skills=${+opts.include_skills}`),
  getWorkspaceStatus: () => request<WorkspaceStatus>('/api/workspace/status'),
  getWorkspaceFiles: () => request<{ files: string[] }>('/api/workspace/files'),
  getWorkspaceDiff: (worktreeKey?: string) =>
    request<WorkspaceDiffResponse>(worktreeKey ? `/api/workspace/diff?worktree=${encodeURIComponent(worktreeKey)}` : '/api/workspace/diff'),
  discardWorktree: (key: string) =>
    request<{ key: string; removed: boolean; branch_deleted: boolean; preserved_preexisting_branch: boolean }>(
      '/api/workspace/worktree/discard',
      { method: 'POST', body: JSON.stringify({ key }) }
    ),
  convertToTask: (data: { text: string; queue?: string; skill?: string; tier?: string }) =>
    request<{ id: number; queue: string; why: string }>('/api/workspace/convert_task', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  addMessage: (
    sessionId: string,
    data: {
      content: string
      mode?: string
      model?: string
      provider?: string
      agent?: string
      tier?: string
      target_kind?: "model" | "agent" | "tier" | "provider" | "intent"
      target?: string
      intent?: string
      profile?: string
      isolated?: boolean
    }
  ) =>
    request<{ run_id: string; task_id?: number; attached?: string[]; refused?: string[]; worktree?: WorktreeInfo }>(`/api/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getOrchestrateOptions: (goal = '') => request<OrchestrateOptions>(`/api/orchestrate/options?goal=${encodeURIComponent(goal.slice(0, 600))}`),
  planOrchestration: (data: { goal: string; orchestrator?: string; pool?: string[] }) =>
    request<OrchestrationPlan>('/api/orchestrate/plan', { method: 'POST', body: JSON.stringify(data) }),
  launchOrchestration: (sessionId: string, plan: OrchestrationPlan) =>
    request<{ run_id: string; plan: OrchestrationPlan }>('/api/orchestrate/launch', { method: 'POST', body: JSON.stringify({ session_id: sessionId, plan }) }),
  getRun: (id: string) => request<ExecutionRun>(`/api/runs/${id}`),
  cancelRun: (id: string) => request<ExecutionRun>(`/api/runs/${id}/cancel`, { method: 'POST', body: JSON.stringify({}) }),
  decideRun: (id: string, step: number, approve: boolean, trust_session = false) =>
    request<ExecutionRun>(`/api/runs/${id}/decision`, { method: 'POST', body: JSON.stringify({ step, approve, trust_session }) }),
  saveCustomProvider: (data: Partial<ProviderItem> & { scope?: string }) =>
    request<ProviderItem>('/api/providers', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  testProvider: (id: string, base_url?: string) =>
    request<ProviderTest>('/api/providers/test', { method: 'POST', body: JSON.stringify({ id, base_url }) }),
  smokeProvider: (provider: string, model?: string, base_url?: string) =>
    request<ProviderTest>('/api/providers/smoke', { method: 'POST', body: JSON.stringify({ provider, model, base_url }) }),
  saveProviderKey: (provider: string, secret: string, storage: "auto" | "keyring" | "env_local" | "project_env" = "auto") =>
    request<{ ok: boolean; saved: boolean; storage: string; env: string; masked: string }>('/api/providers/key', {
      method: 'POST',
      body: JSON.stringify({ provider, secret, storage }),
    }),
  saveOllamaHost: (data: { url?: string; label?: string; id?: string; remove?: boolean }) =>
    request<{ hosts: OllamaHost[]; probe: { online: boolean; hosts: OllamaHost[]; models: string[] } }>('/api/providers/ollama-hosts', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  saveIntentOverride: (intent: string, provider: string, model: string) =>
    request<Record<string, IntentResolution>>('/api/intents', {
      method: 'POST',
      body: JSON.stringify({ intent, provider, model }),
    }),
  addAgent: (data: { kind: 'cli'; id: string; name?: string; model?: string } | { kind: 'api'; provider: string; model: string; name?: string }) =>
    request<{ name: string; agents: string[] }>('/api/agents', { method: 'POST', body: JSON.stringify(data) }),
  saveFailover: (data: Partial<FailoverPolicy>) =>
    request<FailoverPolicy>('/api/providers/failover', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getMetrics: (scope: "project" | "global" = "project") =>
    request<MetricsResponse>(`/api/metrics?scope=${scope}`),
  demoteMetric: (provider: string, model: string, demoted = true, reason?: string) =>
    request<{ ok: boolean; key: string; demotions: Record<string, unknown> }>('/api/metrics/demote', {
      method: 'POST',
      body: JSON.stringify({ provider, model, demoted, reason }),
    }),
  getTools: () => request<{ tools: ToolInfo[] }>('/api/tools'),
  saveSkill: (data: { name: string; description: string; body: string; category?: string }) =>
    request<SkillInfo>('/api/skills/save', { method: 'POST', body: JSON.stringify(data) }),
  shareDoctor: (files?: string[]) =>
    request<ShareDoctorResponse>('/api/share/doctor', { method: 'POST', body: JSON.stringify({ files }) }),
  sharePack: (data: { include_code?: boolean; include_docs?: boolean; include_skills?: boolean; format?: "zip" | "dir" | "tar.gz"; files?: string[] }) =>
    request<SharePackResponse>('/api/share/pack', { method: 'POST', body: JSON.stringify(data) }),
  shareUpload: (path: string, parent_id?: string) =>
    request<ShareUploadResponse>('/api/share/upload', { method: 'POST', body: JSON.stringify({ path, parent_id }) }),
  getShareExports: () => request<ShareExportsResponse>('/api/share/exports'),
  getTask: (id: number) => request<TaskDetail>(`/api/task/${id}`),
  addTask: (data: { text: string; queue?: string; skill?: string; tier?: string }) =>
    request<{ id: number; queue: string; why: string }>('/api/task', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  runPending: () =>
    request<{ started: boolean }>('/api/run', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  reviewTask: (id: number, verdict: 'ok' | 'redo' | 'verify' | 'superseded', note?: string) =>
    request<{ id: number; verdict: string }>(`/api/task/${id}/review`, {
      method: 'POST',
      body: JSON.stringify({ verdict, note }),
    }),
  moveTask: (id: number, queue: string) =>
    request<{ id: number; queue: string }>(`/api/task/${id}/move`, { method: 'POST', body: JSON.stringify({ queue }) }),
  discardTask: (id: number) =>
    request<{ id: number }>(`/api/task/${id}/discard`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
}
