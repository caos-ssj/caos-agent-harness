export interface Agent {
  name: string
  system: string | null
  command: string
  timeout: number
  pending: number
  working: number
}

export interface TaskRouterInfo {
  tier: string
  system: string | null
  action: string
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

export interface Quality {
  mutation?: { caught: number; total: number; source: string }
}

export interface SkillInfo {
  name: string
  description: string
  local?: boolean
}

export interface StateResponse {
  project: string
  root?: string
  now: number
  agents: Agent[]
  tasks: Task[]
  stats: BoardStats
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
  coverage: number
  seconds_per_1000: number
  tokens_per_1000: number | null
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
  status: "online" | "ready" | "missing_key" | "offline"
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
  wired?: boolean
}

export interface FailoverPolicy {
  enabled: boolean
  strategy: string
  fallback_target: string
  fallback_model: string
  description: string
}

export interface ProvidersResponse {
  providers: ProviderItem[]
  active_failover: FailoverPolicy
}

export interface ToolStep {
  name: string
  kind: 'read' | 'write' | 'bash' | 'skill' | 'memory'
  status: 'awaiting_approval' | 'running' | 'completed' | 'failed' | 'denied'
  input?: string
  output?: string
  duration_ms?: number
}

export interface ExecutionRun {
  id: string
  status: "queued" | "running" | "awaiting_approval" | "finishing" | "completed" | "failed"
  model: string
  workspace: string
  steps: ToolStep[]
  answer: string
  error: string
}

export interface WorkspaceStatus {
  repo: string
  path: string
  branch: string
  dirty_files: string[]
  skills: string[]
  agents: string[]
  stats: BoardStats
  quality?: Quality
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
  agent?: string
  tier?: string
  tokens?: number
  cost_saved?: number
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
  created_at: number
  updated_at: number
  mode: "plan" | "act"
  messages_count: number
}

export interface SessionDetail extends SessionItem {
  active_run?: string | null
  commands_enabled?: boolean
  messages: MessageItem[]
}

export interface RepositoryItem {
  name: string
  path: string
  current: boolean
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

export const api = {
  getState: () => request<StateResponse>('/api/state'),
  getRouter: () => request<RouterResponse>('/api/router'),
  getProviders: () => request<ProvidersResponse>('/api/providers'),
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
  getWorkspaceStatus: () => request<WorkspaceStatus>('/api/workspace/status'),
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
    }
  ) =>
    request<{ run_id: string }>(`/api/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getRun: (id: string) => request<ExecutionRun>(`/api/runs/${id}`),
  decideRun: (id: string, step: number, approve: boolean) => request<ExecutionRun>(`/api/runs/${id}/decision`, { method: 'POST', body: JSON.stringify({step, approve}) }),
  saveCustomProvider: (data: Partial<ProviderItem>) =>
    request<ProviderItem>('/api/providers', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  saveFailover: (data: Partial<FailoverPolicy>) =>
    request<FailoverPolicy>('/api/providers/failover', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
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
  discardTask: (id: number) =>
    request<{ id: number }>(`/api/task/${id}/discard`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
}
