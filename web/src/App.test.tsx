import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App } from './App'
import { api } from './api'

const sampleState = {
  project: 'camiones-api',
  root: '/tmp/camiones-api',
  now: 1700000100,
  agents: [{ name: 'qwen-local', queue: 'qwen-local', model: 'qwen2.5:7b', system: 'qwen2.5:7b', timeout: 120, pending: 1 }],
  tasks: [
    { id: 1, text: 'Validar ruta despacho', state: 'to_review', queue: 'qwen-local', created: 1700000000, updated: 1700000050, review: null, review_note: null, delivered: true },
    { id: 2, text: 'Migración antigua', state: 'ok', queue: 'qwen-local', created: 1699999000, updated: 1699999500, review: 'ok', review_note: 'Verificado', delivered: true },
  ],
  stats: {
    tasks: 2,
    by_status: { to_review: 1, ok: 1 },
    review: { ok: 1, redo: 0 },
    deliveries: 2,
    agents: 1,
    runs: 2,
    run_errors: 0,
    retried: 0,
    tokens: { prompt: 120, completion: 80 },
  },
  summary: { total: 2, needs_you: 1, to_review: 1, verify: 0, with_person: 0, runnable: 0, running: 0, closed: 1 },
  running: false,
  sample: false,
  last_run: [],
  skills: [
    { name: 'caos-agente-codigo', description: 'Reglas para cambios de código e infra', local: false, category: 'Código & Infra', team_shareable: true, body: '# Codigo' },
    { name: 'camiones-check', description: 'Validar DTOs de camiones', local: true, category: 'Proyecto', team_shareable: true, body: '# Check' },
  ],
  tiers: ['low', 'medium', 'high', 'critical'],
}

const sampleRouter = {
  tiers: [
    { tier: 'low', action: 'route', needs: 0.55, max_ms: 5000, system: 'qwen2.5:7b', why: 'Triage rápido' },
    { tier: 'medium', action: 'route', needs: 0.72, max_ms: 15000, system: 'qwen2.5:7b', why: 'Código estándar' },
  ],
  profiles: [
    { system: 'qwen2.5:7b', precision: 0.88, precision_lo: 0.78, recall: 0.85, f1: 0.86, cases: 20, latency_ms: 420 },
  ],
}

const sampleProviders = {
  providers: [
    {
      id: 'ollama',
      name: 'Ollama (Local & Hosts)',
      type: 'local' as const,
      status: 'online' as const,
      quota: '1/1 hosts',
      cost_per_m: 'local compute',
      models: ['qwen2.5:7b'],
      model_details: [{ name: 'qwen2.5:7b', size: 4700000000, parameter_size: '7B', quantization: 'Q4_K_M', family: 'qwen2' }],
      default_model: 'qwen2.5:7b',
      description: 'Ollama hosts',
    },
    {
      id: 'anthropic',
      name: 'Anthropic Claude',
      type: 'cloud' as const,
      status: 'key_present' as const,
      quota: 'env / keyring',
      cost_per_m: 'not measured',
      models: ['claude-sonnet-4-5'],
      default_model: 'claude-sonnet-4-5',
      api_key_env: 'ANTHROPIC_API_KEY',
      key_source: 'env_local',
      description: 'Claude API',
    },
  ],
  ollama_hosts: [{ id: 'local', label: 'Local', url: 'http://127.0.0.1:11434', online: true, models: ['qwen2.5:7b'], latency_ms: 12 }],
  intents: {
    codigo: { intent: 'codigo', provider: 'ollama', model: 'qwen2.5:7b', pinned: false, healthy: true },
    rapido: { intent: 'rapido', provider: 'ollama', model: 'qwen2.5:7b', pinned: false, healthy: true },
    razonar: { intent: 'razonar', provider: 'anthropic', model: 'claude-sonnet-4-5', pinned: false, healthy: true },
    local: { intent: 'local', provider: 'ollama', model: 'qwen2.5:7b', pinned: false, healthy: true },
  },
  active_failover: { enabled: true, strategy: 'local', fallback_target: 'ollama', fallback_model: 'qwen2.5:7b', description: 'Local fallback' },
  clis: [],
  api_agents: [],
}


/** Opens a view by its tab name: a group tab first (Team or System) when the view lives on a second row. */
async function openTab(name: RegExp) {
  let tab = screen.queryByRole('tab', { name })
  for (const group of [/^Team/, /^System/]) {
    if (tab) break
    const g = screen.queryByRole('tab', { name: group })
    if (g) { fireEvent.click(g); tab = screen.queryByRole('tab', { name }) }
  }
  fireEvent.click(tab ?? (await screen.findByRole('tab', { name })))
}

describe('CAOS v2 unified Web UI', () => {
  beforeEach(() => {
    cleanup()
    localStorage.clear()
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1440 })
    window.history.replaceState(null, '', '#console')
    vi.restoreAllMocks()

    vi.spyOn(api, 'getState').mockResolvedValue(sampleState as any)
    vi.spyOn(api, 'getRouter').mockResolvedValue(sampleRouter as any)
    vi.spyOn(api, 'getProviders').mockResolvedValue(sampleProviders as any)
    vi.spyOn(api, 'getWorkspaceStatus').mockResolvedValue({ repo: 'camiones-api', git_repo: true, branch: 'main', dirty_files: [], ahead: 0, behind: 0, worktrees: [] } as any)
    vi.spyOn(api, 'getWorkspaceFiles').mockResolvedValue({ files: ['src/dispatch.py', 'README.md'] })
    vi.spyOn(api, 'getWorkspaceDiff').mockResolvedValue({ diff: '', files: [], worktree: null } as any)
    vi.spyOn(api, 'getWorkspaces').mockResolvedValue({ current: '/tmp/camiones-api', items: [{ name: 'camiones-api', path: '/tmp/camiones-api', current: true, ready: true }] })
    vi.spyOn(api, 'getTools').mockResolvedValue({ tools: [{ id: 't1', name: 'git-mcp', kind: 'mcp', status: 'configured', summary: 'Read git status', shareable: true }] })
    vi.spyOn(api, 'getSessions').mockResolvedValue([{ id: 's1', title: 'Despacho QA', project: 'camiones-api', created_at: 1, updated_at: 2, mode: 'plan', target_kind: 'model', target: 'qwen2.5:7b', messages_count: 1 }])
    vi.spyOn(api, 'getSession').mockResolvedValue({
      id: 's1',
      title: 'Despacho QA',
      project: 'camiones-api',
      created_at: 1,
      updated_at: 2,
      mode: 'plan',
      commands_enabled: false,
      messages_count: 2,
      messages: [
        { id: 'm1', role: 'user', content: 'Revisa despacho', ts: 1 },
        {
          id: 'm2',
          role: 'assistant',
          content: 'Propongo validar rutas antes de editar.',
          provider: 'ollama',
          model: 'qwen2.5:7b',
          ts: 2,
          questions: [{ question: '¿Ejecutar suite unitaria primero?', chips: ['Sí, correr pytest', 'Solo revisar diff'] }],
        },
      ],
    } as any)
    vi.spyOn(api, 'getTask').mockResolvedValue({ id: 1, text: 'Validar ruta despacho', state: 'to_review', queue: 'qwen-local', result: 'Tests ok', timeline: [{ seq: 1, ts: 1, source: 'worker', status: 'done', kind: 'exec' }] } as any)
    vi.spyOn(api, 'getMetrics').mockResolvedValue({
      scope: 'project',
      project: 'camiones-api',
      kpis: {
        runs_total: 12,
        run_success_rate: 0.92,
        human_redo_rate: 0.08,
        returned: 1,
        reviewed_total: 12,
        p50_latency_ms: 410,
        tokens: { prompt: 1200, completion: 640, total: 1840 },
        gates: { mutation: { caught: 26, total: 26 }, eval_precision: 0.9, regress_status: 'pass' },
      },
      models: [{ provider: 'ollama', model: 'qwen2.5:7b', runs: 12, ok: 11, errors: 1, success_rate: 0.92, p50_ms: 410, tokens: 1840, last_smoke: { ok: true, ms: 95, json_ok: true, ts: 10 }, demoted: false }],
    } as any)
    vi.spyOn(api, 'getPreflight').mockResolvedValue({ ok: true, verdict: 'ready', dry_run: false, tokens_spent: 0, project: 'camiones-api', summary: { ok: 3, info: 1, warning: 0, blocked: 0 }, checks: [{ id: 'project', label: 'Project', level: 'ok', detail: 'camiones-api', action: '' }], next_actions: [] })
    vi.spyOn(api, 'getActivity').mockResolvedValue({ events: [{ ts: 1700000050, kind: 'delegated', task_id: 1, text: 'Validar ruta despacho', agent: 'qwen-local', note: 'sent to qwen-local' }], summary: { needs_you: 1, running: 0, pending: 0, to_review: 1, with_person: 0, closed: 1 } })
    vi.spyOn(api, 'getGlobalBoard').mockResolvedValue({ readonly: true, workspaces: [{ name: 'camiones-api', path: '/tmp/camiones-api', current: true, error: '', counts: { needs_you: 1, open: 1 }, tasks: [{ id: 1, state: 'to_review', queue: 'qwen-local', text: 'Validar ruta despacho', created: 1700000000, needs_you: true }] }] })
    vi.spyOn(api, 'getGlobalSessions').mockResolvedValue({ readonly: true, sessions: [] })
    vi.spyOn(api, 'getMetricsSeries').mockResolvedValue({ scope: 'project', bucket: 'day', min_runs: 5, total_runs: 12, enough: true, points: [{ t: 1699920000, runs: 5, ok: 5, success_rate: 1, p50_ms: 400 }, { t: 1700006400, runs: 7, ok: 6, success_rate: 0.857, p50_ms: 420 }] })
    vi.spyOn(api, 'getSharePreview').mockResolvedValue({ ok: true, dry_run: true, format: 'zip', included: [{ path: 'src/dispatch.py', size: 120, redacted_lines: 0 }, { path: 'README.md', size: 40, redacted_lines: 1 }], generated: [{ path: '.env.example', size: 80 }], excluded: [{ path: 'leak.txt', reason: 'holds a credential' }], redactions: [{ path: 'README.md', lines: [3], kinds: ['private_path'] }], redacted_paths: ['README.md'], unscanned: [], files_count: 3, total_bytes: 240, skills_included: [], sanitization: [{ id: 'credentials', label: '1 file(s) holding a credential left out', ok: true }], onboarding: ['pip install -e .', 'caos-harness doctor --dry-run'] })
    vi.spyOn(api, 'getShareExports').mockResolvedValue({ exports: [], gdrive_connected: false })
  })

  it('orders the header in 4 groups, Run first, correctly and persists sidebar collapse + scope toggle', async () => {
    render(<App />)
    const tablist = await screen.findByRole('tablist', { name: 'Vistas principales' })
    const tabs = within(tablist).getAllByRole('tab')
    expect(tabs.map((t) => t.getAttribute('data-tab'))).toEqual(['run', 'board', 'team', 'system'])

    expect(screen.queryByRole('complementary', { name: 'Contexto del proyecto' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Expandir barra lateral' }))
    const sidebar = screen.getByRole('complementary', { name: 'Contexto del proyecto' })
    expect(sidebar.className).toContain('is-expanded')
    expect(localStorage.getItem('caos_sidebar_collapsed')).toBe('0')

    fireEvent.click(screen.getByRole('button', { name: 'Colapsar barra lateral' }))
    expect(screen.queryByRole('complementary', { name: 'Contexto del proyecto' })).not.toBeInTheDocument()
    expect(localStorage.getItem('caos_sidebar_collapsed')).toBe('1')
    fireEvent.click(screen.getByRole('button', { name: 'Global' }))
    expect(screen.getByRole('button', { name: 'Global' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('supports Console intent pills, Plan Q&A handoff to Act, and Act 3-line trust approval', async () => {
    const cmdSpy = vi.spyOn(api, 'setSessionCommands').mockResolvedValue({ id: 's1', commands_enabled: true })
    const msgSpy = vi.spyOn(api, 'addMessage').mockResolvedValue({ run_id: 'run123' } as any)
    vi.spyOn(api, 'getRun').mockResolvedValue({
      id: 'run123',
      session_id: 's1',
      status: 'awaiting_approval',
      steps: [
        {
          kind: 'bash',
          status: 'awaiting_approval',
          input: 'pytest -q',
          summary_what: 'Ejecutar suite de pruebas',
          summary_why: 'Verificar rutas de camiones',
          summary_goal: 'Sin regresiones antes de entregar',
        },
      ],
    } as any)
    const decideSpy = vi.spyOn(api, 'decideRun').mockResolvedValue({ ok: true, status: 'running' } as any)

    render(<App />)
    await screen.findByText(/¿Ejecutar suite unitaria primero\?/)

    // The intents live in the engine popover now (Ctrl+M or the engine button).
    fireEvent.keyDown(window, { key: 'm', ctrlKey: true })
    const dialog = await screen.findByRole('dialog', { name: 'Elegir motor' })
    expect(within(dialog).getByRole('tab', { name: /^Local/ })).toBeInTheDocument()   // one list at a time: Auto & agents, Local, Cloud
    expect(within(dialog).getByRole('tab', { name: /^Cloud/ })).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: /Razonamiento/ }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Elegir motor' })).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /razonar · claude-sonnet-4-5/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Sí, correr pytest' }))
    fireEvent.click(screen.getByRole('button', { name: /Pasar a Act con respuestas/i }))

    await waitFor(() => expect(cmdSpy).toHaveBeenCalledWith('s1', true))
    await waitFor(() => expect(msgSpy).toHaveBeenCalledWith('s1', expect.objectContaining({ mode: 'act', target_kind: 'intent', target: 'razonar' })))

    await screen.findByText('Aprobación requerida en Act')
    expect(screen.getByText('Ejecutar suite de pruebas')).toBeInTheDocument()
    expect(screen.getByText('Verificar rutas de camiones')).toBeInTheDocument()
    expect(screen.getByText('Sin regresiones antes de entregar')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Confiar en esta sesión' }))
    await waitFor(() => expect(decideSpy).toHaveBeenCalledWith('run123', 0, true, true))
  })

  it('switches Board Lista <-> Kanban, keeps Cerradas collapsed, and shows 5 Metrics KPIs + actions', async () => {
    const smokeSpy = vi.spyOn(api, 'smokeProvider').mockResolvedValue({ ok: true, latency_ms: 82 } as any)
    const demoteSpy = vi.spyOn(api, 'demoteMetric').mockResolvedValue({ ok: true, key: 'qwen2.5:7b', demotions: { 'qwen2.5:7b': 'test' } })

    render(<App />)
    fireEvent.click(await screen.findByRole('tab', { name: /Board/i }))

    const closedTitle = (await screen.findAllByText('Cerradas')).find((el) => el.classList.contains('acc-title'))
    expect(closedTitle?.closest('details')).not.toHaveAttribute('open')

    fireEvent.click(screen.getByRole('button', { name: /Kanban/i }))
    expect(localStorage.getItem('caos_board_layout')).toBe('kanban')
    expect(screen.getByText('A revisar')).toBeInTheDocument()

    await openTab(/Metrics/i)
    await screen.findByText('Éxito de runs')
    expect(screen.getByText('Retorno humano')).toBeInTheDocument()
    expect(screen.getByText('Latencia p50')).toBeInTheDocument()
    expect(screen.getByText('Tokens')).toBeInTheDocument()
    expect(screen.getByText('Gates repo')).toBeInTheDocument()
    expect(screen.getAllByText('92%').length).toBeGreaterThanOrEqual(1)

    expect(screen.getByText('PASS')).toBeInTheDocument()                                  // regress pass + mutation 26/26
    expect(await screen.findByRole('img', { name: /Tendencia de éxito/ })).toBeInTheDocument()
    expect(screen.getByText('Tier × Modelo')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Smoke' }))
    await waitFor(() => expect(smokeSpy).toHaveBeenCalledWith('ollama', 'qwen2.5:7b'))

    fireEvent.click(screen.getByRole('button', { name: /Degradar/i }))
    await waitFor(() => expect(demoteSpy).toHaveBeenCalledWith('ollama', 'qwen2.5:7b', true, 'degradado desde Metrics'))
  })

  it('renders categorized Skills + MCP accordion + new skill modal and Share Doctor / Pack', async () => {
    const saveSkillSpy = vi.spyOn(api, 'saveSkill').mockResolvedValue({ name: 'ruta-check', description: 'Valida ruta', local: true } as any)
    const docSpy = vi.spyOn(api, 'shareDoctor').mockResolvedValue({ clean: true, scanned: 14, issues: [] })
    const packSpy = vi.spyOn(api, 'sharePack').mockResolvedValue({
      ok: true,
      format: 'zip',
      path: '/tmp/camiones-api/.harness/exports/pack.zip',
      relative_path: '.harness/exports/pack.zip',
      filename: 'pack.zip',
      size_bytes: 2048,
      files_count: 10,
      skills_included: ['camiones-check'],
      doctor: { clean: true, scanned: 14, issues: [] },
    })

    render(<App />)
    await openTab(/Skills & Tools/i)
    await screen.findByText('caos-agente-codigo')

    fireEvent.click(screen.getByRole('tab', { name: /MCP & Tools/i }))
    expect(await screen.findByText('git-mcp')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /^Skills \(/ }))

    fireEvent.click(screen.getByRole('button', { name: /Nuevo Skill/i }))
    fireEvent.change(screen.getByPlaceholderText('mi-skill'), { target: { value: 'ruta-check' } })
    fireEvent.change(screen.getByPlaceholderText(/Cuándo debe usar/i), { target: { value: 'Valida ruta' } })
    fireEvent.click(screen.getByRole('button', { name: /^Guardar$/ }))
    await waitFor(() => expect(saveSkillSpy).toHaveBeenCalledWith(expect.objectContaining({ name: 'ruta-check', description: 'Valida ruta' })))

    await openTab(/Share \/ Team/i)
    expect(await screen.findByText('Vista previa real')).toBeInTheDocument()
    expect(await screen.findByText('leak.txt')).toBeInTheDocument()                        // excluded, with its reason
    fireEvent.click(await screen.findByRole('button', { name: /Ejecutar Doctor/i }))
    await waitFor(() => expect(docSpy).toHaveBeenCalled())
    expect(await screen.findByText(/0 fugas detectadas/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Generar Share Pack/i }))
    await waitFor(() => expect(packSpy).toHaveBeenCalled())
    expect(await screen.findByText('pack.zip')).toBeInTheDocument()
  })

  it('switches ProvidersView subtabs, saves Ollama host and intent pin, and jumps to Console on Usar', async () => {
    const hostSpy = vi.spyOn(api, 'saveOllamaHost').mockResolvedValue({ hosts: [] } as any)
    const intentSpy = vi.spyOn(api, 'saveIntentOverride').mockResolvedValue({} as any)

    render(<App />)
    await openTab(/Models & Providers/i)

    fireEvent.click(await screen.findByRole('tab', { name: /Modelos Locales/i }))
    await screen.findByText(/Ollama Multi-Host/i)
    fireEvent.click(screen.getByRole('button', { name: /Host LAN \/ Remoto/i }))
    fireEvent.change(screen.getByPlaceholderText('http://192.168.1.50:11434'), { target: { value: 'http://192.168.1.99:11434' } })
    fireEvent.click(screen.getByRole('button', { name: 'Guardar Host' }))
    await waitFor(() => expect(hostSpy).toHaveBeenCalledWith({ url: 'http://192.168.1.99:11434', label: '' }))

    fireEvent.click(screen.getByRole('tab', { name: /Router y Comparador/i }))
    const sel = await screen.findByRole('combobox', { name: 'Motor para codigo' })
    fireEvent.change(sel, { target: { value: 'anthropic::claude-sonnet-4-5' } })
    await waitFor(() => expect(intentSpy).toHaveBeenCalledWith('codigo', 'anthropic', 'claude-sonnet-4-5'))
  })

  it('opens Board with nothing selected, a full overview and a feed with a last-visit divider, then opens a task from the feed', async () => {
    localStorage.setItem('caos_board_seen:/tmp/camiones-api', '1700000060')
    render(<App />)
    fireEvent.click(await screen.findByRole('tab', { name: /Board/i }))
    const overview = await screen.findByRole('region', { name: 'Resumen del Board' })
    expect(screen.queryByLabelText(/Detalle tarea/)).not.toBeInTheDocument()          // no task is selected on its own
    expect(within(overview).getByText('Necesita de ti')).toBeInTheDocument()
    expect(screen.getByText('Esperando por ti')).toBeInTheDocument()
    expect(await within(overview).findByText(/última visita/)).toBeInTheDocument()
    fireEvent.click(within(overview).getByRole('button', { name: /Bloqueados · necesita de ti/ }))
    expect(within(overview).queryByText(/delegada/)).not.toBeInTheDocument()          // the filter keeps only blocked and returned
    fireEvent.click(within(overview).getByRole('button', { name: 'Todo' }))
    fireEvent.click(await within(overview).findByRole('button', { name: /delegada/ }))
    expect(await screen.findByLabelText(/Detalle tarea #01/)).toBeInTheDocument()
  })

  it('shows every project read-only under the single Global toggle and opens another project on a click', async () => {
    const switchSpy = vi.spyOn(api, 'switchWorkspace').mockResolvedValue({ current: '/tmp/otro', items: [] } as any)
    vi.spyOn(api, 'getGlobalBoard').mockResolvedValue({
      readonly: true,
      workspaces: [
        { name: 'camiones-api', path: '/tmp/camiones-api', current: true, error: '', counts: { needs_you: 1, open: 1 }, tasks: [{ id: 1, state: 'to_review', queue: 'qwen-local', text: 'Validar ruta despacho', created: 1700000000, needs_you: true }] },
        { name: 'otro', path: '/tmp/otro', current: false, error: '', counts: { needs_you: 1, open: 1 }, tasks: [{ id: 7, state: 'person', queue: 'person', text: 'Aprobar el despliegue de otro', created: 1700000001, needs_you: true }] },
      ],
    })
    render(<App />)
    fireEvent.click(await screen.findByRole('tab', { name: /Board/i }))
    expect(screen.getAllByRole('button', { name: 'Global' })).toHaveLength(1)           // one toggle, in the header only
    fireEvent.click(screen.getByRole('button', { name: 'Global' }))
    expect(await screen.findByText(/solo lectura/)).toBeInTheDocument()
    fireEvent.click(await screen.findByText('Aprobar el despliegue de otro'))
    await waitFor(() => expect(switchSpy).toHaveBeenCalledWith('/tmp/otro'))
  })

  it('keeps an empty Console free of emblem, instructions, and starter pills, showing up to 3 missions instead', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue({ id: 's1', title: 'Despacho QA', project: 'camiones-api', created_at: 1, updated_at: 2, mode: 'plan', commands_enabled: false, messages_count: 0, messages: [] } as any)
    vi.spyOn(api, 'getMissions').mockResolvedValue({
      scanned_files: 10,
      has_git: true,
      has_tests: true,
      missions: [
        { id: 'm1', kind: 'verify', score: 1, title: 'Revisar tests', subtitle: 'Cobertura', mode: 'plan', prompt: 'Revisa', citations: ['a.py:1'] },
        { id: 'm2', kind: 'tests', score: 0.9, title: 'Ajustar ruta', subtitle: 'Endpoint', mode: 'act', prompt: 'Ajusta', citations: ['b.py:2'] },
        { id: 'm3', kind: 'verify', score: 0.8, title: 'Auditar logs', subtitle: 'Errores', mode: 'plan', prompt: 'Audita', citations: [] },
        { id: 'm4', kind: 'verify', score: 0.7, title: 'Extra oculta', subtitle: 'Sobra', mode: 'plan', prompt: 'No debe verse', citations: [] },
      ],
    })
    render(<App />)
    await screen.findByText('Revisar tests')
    expect(screen.queryByRole('region', { name: 'Work cycle' })).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Arranques rápidos' })).not.toBeInTheDocument()
    expect(screen.queryByText('Extra oculta')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Lanzar' })).toHaveLength(3)
    expect(document.querySelector('.preflight-card')).toBeNull()                           // the preflight lives in the sidebar footer
    fireEvent.click(screen.getByRole('button', { name: 'Expandir barra lateral' }))
    expect(within(screen.getByRole('complementary', { name: 'Contexto del proyecto' })).getByText('Listo')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Act' }))
    expect(screen.getByRole('button', { name: 'Act' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('keeps the Console bar to one line with Opciones popover and navigation out of the sidebar', async () => {
    render(<App />)
    const bar = (await screen.findByRole('group', { name: 'Modo de ejecución' })).parentElement as HTMLElement
    expect(bar.className).toContain('one-line')
    const optsBtn = within(bar).getByRole('button', { name: /Opciones/ })
    fireEvent.click(optsBtn)
    for (const name of [/Worktree aislado/, /^Pipeline$/, /^Inspector$/]) expect(within(bar).getByRole('button', { name })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Expandir barra lateral' }))
    const sidebar = screen.getByRole('complementary', { name: 'Contexto del proyecto' })
    expect(within(sidebar).queryByRole('button', { name: 'Board' })).not.toBeInTheDocument()
    expect(within(sidebar).queryByRole('button', { name: 'Providers' })).not.toBeInTheDocument()
  })

  describe('orchestration', () => {
    const OPTIONS = {
      orchestrators: [
        { name: 'claude', family: 'claude', kind: 'cli', model: null, installed: true, capable: true },
        { name: 'opencode', family: 'opencode', kind: 'cli', model: null, installed: true, capable: true },
        { name: 'qwen', family: 'local', kind: 'local', model: 'qwen2.5:7b', installed: true, capable: true },
      ],
      pool: [
        { name: 'claude', family: 'claude', kind: 'cli', model: null, installed: true, capable: true },
        { name: 'opencode', family: 'opencode', kind: 'cli', model: null, installed: true, capable: true },
        { name: 'qwen', family: 'local', kind: 'local', model: 'qwen2.5:7b', installed: true, capable: true },
      ],
      suggested: { name: 'opencode', reason: 'fast', alternatives: ['claude', 'qwen'] },
      default_orchestrator: 'claude',
      scouts: [{ name: 'qwen', tier: 'free', model: 'qwen2.5:7b', family: 'local' }], suggested_scout: 'qwen', tiers: {}, installable: [{ id: 'agy', label: 'Antigravity CLI' }],
    }
    const PLAN = {
      goal: 'Migrar el cliente HTTP', orchestrator: 'claude', pool: ['opencode', 'qwen'], scout: null, summary: 'Dos frentes en paralelo.', recommended_orchestrator: '', source: 'orchestrator', note: '',
      subtasks: [
        { id: 's1', title: 'Mapear llamadas', agent: 'opencode', mode: 'readonly', skill: null, scout: false, task: 'Lista cada llamada HTTP del repo', criteria: 'Una lista con archivo y línea' },
        { id: 's2', title: 'Reescribir el cliente', agent: 'qwen', mode: 'isolated', skill: null, scout: false, task: 'Cambia el cliente a fetch', criteria: 'El diff solo toca el cliente' },
      ],
    }
    const emptySession = { id: 's1', title: 'Despacho QA', project: 'camiones-api', created_at: 1, updated_at: 2, mode: 'plan', commands_enabled: false, messages_count: 0, messages: [] }
    const runWith = (status: string, phase: string, states: string[]) => ({
      id: 'run-orch', status, model: 'claude', target_kind: 'orchestrate', target: 'claude', task_id: 10, steps: [], answer: phase === 'done' ? 'SINTESIS: todo cumplido' : '', error: '', workspace: '/tmp/x',
      orchestration: { goal: PLAN.goal, orchestrator: 'claude', summary: '', phase, parent_id: 10, synthesis: phase === 'done' ? 'SINTESIS: todo cumplido' : '',
        subtasks: PLAN.subtasks.map((st, i) => ({ ...st, state: states[i], task_id: 11 + i, worktree: st.mode === 'isolated' ? { key: 'orch-1-s2', path: '/x', branch: 'caos/x' } : null, duration_ms: states[i] === 'delivered' ? 1200 : null, elapsed_ms: 800, brief: '', scout_ms: null, scout_cached: false, result: states[i] === 'delivered' ? `entrega de ${st.agent}` : '', diff: '', error: '', note: '' })) },
    })

    beforeEach(() => {
      vi.spyOn(api, 'getSession').mockResolvedValue(emptySession as any)
      vi.spyOn(api, 'getOrchestrateOptions').mockResolvedValue(OPTIONS as any)
      vi.spyOn(api, 'getWorkspaceStatus').mockResolvedValue({ repo: 'camiones-api', git_repo: true, has_head: true, branch: 'main', dirty_files: [], worktrees: [] } as any)
    })

    const openOrchestrate = async () => {
      render(<App />)
      fireEvent.click(await screen.findByRole('button', { name: 'Orquestar' }))
      await screen.findByRole('group', { name: 'Orquestación' })
    }

    it('adds a third mode, offers the orchestrator, the workers and a one-click add, and suggests a better fit', async () => {
      await openOrchestrate()
      expect(screen.getByRole('button', { name: 'Orquestar' })).toHaveAttribute('aria-pressed', 'true')
      const bar = screen.getByRole('group', { name: 'Orquestación' })
      expect(within(bar).getByRole('combobox', { name: 'Orquestador' })).toHaveValue('claude')           // Claude by default
      expect(within(bar).getByText(/Sugerido:/)).toHaveTextContent('opencode')                           // and a badge when another one fits better
      fireEvent.click(within(bar).getByRole('button', { name: /Sugerido/ }))
      expect(within(bar).getByRole('combobox', { name: 'Orquestador' })).toHaveValue('opencode')
      const pool = within(bar).getByRole('group', { name: 'Subagentes disponibles' })
      expect(within(pool).getByRole('button', { name: 'claude' })).toHaveAttribute('aria-pressed', 'true')    // the orchestrator may also work
      expect(within(pool).getByRole('button', { name: 'qwen' })).toHaveAttribute('aria-pressed', 'true')
      fireEvent.click(within(pool).getByRole('button', { name: 'qwen' }))
      expect(within(pool).getByRole('button', { name: 'qwen' })).toHaveAttribute('aria-pressed', 'false')
      const add = vi.spyOn(api, 'addAgent').mockResolvedValue({ name: 'agy', agents: ['agy'] })
      fireEvent.click(within(bar).getByRole('button', { name: /Añadir agy/ }))
      await waitFor(() => expect(add).toHaveBeenCalledWith({ kind: 'cli', id: 'agy' }))
    })

    it('shows the plan on a critical desk where the orchestrator, every agent, mode and criterion can be changed before anything runs', async () => {
      const plan = vi.spyOn(api, 'planOrchestration').mockResolvedValue(PLAN as any)
      const launch = vi.spyOn(api, 'launchOrchestration').mockResolvedValue({ run_id: 'run-orch', plan: PLAN } as any)
      vi.spyOn(api, 'getRun').mockResolvedValue(runWith('running', 'delegating', ['running', 'running']) as any)
      await openOrchestrate()
      fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Migrar el cliente HTTP' } })
      fireEvent.click(screen.getByRole('button', { name: /Planificar/ }))
      await waitFor(() => expect(plan).toHaveBeenCalledWith(expect.objectContaining({ goal: 'Migrar el cliente HTTP', orchestrator: 'claude' })))
      const desk = await screen.findByRole('region', { name: 'Mesa crítica de delegación' })
      expect(within(desk).getAllByRole('listitem')).toHaveLength(2)
      expect(within(desk).getByRole('button', { name: 'Lanzar 2 subagentes en paralelo' })).toBeInTheDocument()

      fireEvent.change(within(desk).getByLabelText('Agente de la subtarea 1'), { target: { value: 'claude' } })               // reassign an agent
      fireEvent.change(within(desk).getByLabelText('Criterio de la subtarea 2'), { target: { value: 'Además pasan los tests' } })   // edit the criterion
      fireEvent.click(within(within(desk).getByRole('group', { name: 'Modo de la subtarea 1' })).getByRole('button', { name: /Edición \(worktree\)/ }))   // read-only -> edits in a worktree
      fireEvent.change(within(desk).getByLabelText('Orquestador del plan'), { target: { value: 'qwen' } })                         // change the orchestrator
      fireEvent.click(within(desk).getByRole('button', { name: /Subtarea$/ }))                                                    // add one
      expect(within(desk).getAllByRole('listitem')).toHaveLength(3)
      fireEvent.click(within(desk).getByLabelText('Quitar la subtarea 3'))                                                       // and remove it again
      expect(within(desk).getAllByRole('listitem')).toHaveLength(2)

      fireEvent.click(within(desk).getByRole('button', { name: 'Lanzar 2 subagentes en paralelo' }))
      await waitFor(() => expect(launch).toHaveBeenCalled())
      const [sid, sent] = launch.mock.calls[0] as any
      expect(sid).toBe('s1')
      expect(sent.orchestrator).toBe('qwen')
      expect(sent.subtasks[0]).toMatchObject({ agent: 'claude', mode: 'isolated', criteria: 'Una lista con archivo y línea' })
      expect(sent.subtasks[1]).toMatchObject({ agent: 'qwen', criteria: 'Además pasan los tests' })
      expect(sent.source).toBe('edited')
      expect(await screen.findByRole('region', { name: 'Subagentes en paralelo' })).toBeInTheDocument()
    })

    it('refuses to launch a subtask with no task and says when the plan is the harness own proposal', async () => {
      vi.spyOn(api, 'planOrchestration').mockResolvedValue({ ...PLAN, source: 'fallback', note: 'claude no respondió con un plan; es una propuesta', subtasks: [{ ...PLAN.subtasks[0], task: '' }] } as any)
      await openOrchestrate()
      fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'algo' } })
      fireEvent.click(screen.getByRole('button', { name: /Planificar/ }))
      const desk = await screen.findByRole('region', { name: 'Mesa crítica de delegación' })
      expect(within(desk).getByRole('status')).toHaveTextContent('es una propuesta')
      expect(within(desk).getByRole('button', { name: 'Lanzar 1 subagente' })).toBeDisabled()
      fireEvent.change(within(desk).getByLabelText('Tarea de la subtarea 1'), { target: { value: 'Ahora sí hay tarea' } })
      expect(within(desk).getByRole('button', { name: 'Lanzar 1 subagente' })).toBeEnabled()
    })

    it('shows every subagent side by side while it runs, then the orchestrator synthesis from the saved conversation', async () => {
      const done = runWith('completed', 'done', ['delivered', 'delivered'])
      vi.spyOn(api, 'planOrchestration').mockResolvedValue(PLAN as any)
      vi.spyOn(api, 'launchOrchestration').mockResolvedValue({ run_id: 'run-orch', plan: PLAN } as any)
      let finished = false
      const get = vi.spyOn(api, 'getRun').mockImplementation((async () => (finished ? done : runWith('running', 'delegating', ['running', 'queued']))) as any)
      await openOrchestrate()
      fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Migrar' } })
      fireEvent.click(screen.getByRole('button', { name: /Planificar/ }))
      fireEvent.click(await screen.findByRole('button', { name: 'Lanzar 2 subagentes en paralelo' }))
      const live = await screen.findByRole('region', { name: 'Subagentes en paralelo' })
      expect(within(live).getByText('trabajando')).toBeInTheDocument()
      expect(within(live).getByText('en cola')).toBeInTheDocument()
      const polls = get.mock.calls.length
      finished = true
      vi.spyOn(api, 'getSession').mockResolvedValue({ ...emptySession, messages_count: 2, messages: [{ id: 'u', role: 'user', content: 'Migrar', timestamp: 1 }, { id: 'a', role: 'assistant', content: 'SINTESIS: todo cumplido', timestamp: 2, run_id: 'run-orch', task_id: 10, orchestration: done.orchestration }] } as any)
      await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(polls), { timeout: 4000 })
      const synth = await screen.findByRole('region', { name: 'Síntesis final' }, { timeout: 4000 })
      expect(synth).toHaveTextContent('SINTESIS: todo cumplido')
      expect(screen.getAllByRole('button', { name: /Board #1[12]/ })).toHaveLength(2)         // each card links to its task on the Board
    })

    it('lets the user choose orchestrator model and subagent models in bar, top selector and critical desk', async () => {
      const richOpts = {
        ...OPTIONS,
        orchestrators: [
          { ...OPTIONS.orchestrators[0], model: 'sonnet', models: ['sonnet', 'opus', 'haiku'] },
          { ...OPTIONS.orchestrators[1], model: 'opencode/glm-5.3-flash-free', models: ['opencode/glm-5.3-flash-free', 'opencode/big-pickle'] },
          { ...OPTIONS.orchestrators[2], models: ['qwen2.5:7b', 'qwen3:8b'] },
        ],
        pool: [
          { ...OPTIONS.pool[0], model: 'sonnet', models: ['sonnet', 'opus', 'haiku'] },
          { ...OPTIONS.pool[1], model: 'opencode/glm-5.3-flash-free', models: ['opencode/glm-5.3-flash-free', 'opencode/big-pickle'] },
          { ...OPTIONS.pool[2], models: ['qwen2.5:7b', 'qwen3:8b'] },
        ],
      }
      vi.spyOn(api, 'getOrchestrateOptions').mockResolvedValue(richOpts as any)
      const richPlan = { ...PLAN, orchestrator_model: 'opus', subtasks: [{ ...PLAN.subtasks[0], model: 'opencode/big-pickle' }, { ...PLAN.subtasks[1], model: 'qwen2.5:7b' }] }
      const planSpy = vi.spyOn(api, 'planOrchestration').mockResolvedValue(richPlan as any)
      const launchSpy = vi.spyOn(api, 'launchOrchestration').mockResolvedValue({ run_id: 'run-orch', plan: richPlan } as any)
      vi.spyOn(api, 'getRun').mockResolvedValue(runWith('running', 'delegating', ['running', 'running']) as any)

      await openOrchestrate()
      const bar = screen.getByRole('group', { name: 'Orquestación' })
      const orchModelSel = within(bar).getByLabelText('Modelo del orquestador') as HTMLSelectElement
      expect(orchModelSel.value).toBe('sonnet')
      fireEvent.change(orchModelSel, { target: { value: 'opus' } })
      expect(orchModelSel.value).toBe('opus')

      // Top motor button reflects the active orchestrator + model and lets you switch model inside the popover
      const motorBtn = screen.getByRole('button', { name: /claude · opus/ })
      fireEvent.click(motorBtn)
      const pop = await screen.findByRole('dialog', { name: 'Elegir motor' })
      expect(within(pop).getByText('Orquestador y modelo activos')).toBeInTheDocument()
      fireEvent.click(within(pop).getByRole('button', { name: /haiku/ }))
      expect(orchModelSel.value).toBe('haiku')

      // Subagent model selector inside the bar
      fireEvent.change(within(bar).getByLabelText('Modelo de opencode'), { target: { value: 'opencode/big-pickle' } })

      fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Separar modelos' } })
      fireEvent.click(screen.getByRole('button', { name: /Planificar/ }))
      await waitFor(() => expect(planSpy).toHaveBeenCalledWith(expect.objectContaining({
        orchestrator: 'claude',
        orchestrator_model: 'haiku',
        agent_models: expect.objectContaining({ opencode: 'opencode/big-pickle' }),
      })))

      const desk = await screen.findByRole('region', { name: 'Mesa crítica de delegación' })
      fireEvent.change(within(desk).getByLabelText('Modelo del orquestador del plan'), { target: { value: 'sonnet' } })
      fireEvent.change(within(desk).getByLabelText('Modelo de la subtarea 1'), { target: { value: 'opencode/glm-5.3-flash-free' } })
      fireEvent.click(within(desk).getByRole('button', { name: 'Lanzar 2 subagentes en paralelo' }))
      await waitFor(() => expect(launchSpy).toHaveBeenCalled())
      const [, sentPlan] = launchSpy.mock.calls[0] as any
      expect(sentPlan.orchestrator_model).toBe('sonnet')
      expect(sentPlan.subtasks[0].model).toBe('opencode/glm-5.3-flash-free')
    })

    it('keeps orchestration selectors and quick add actions visible even when the workspace has no AI agents yet', async () => {
      vi.spyOn(api, 'getOrchestrateOptions').mockResolvedValue({
        orchestrators: [],
        pool: [{ name: 'echo', kind: 'command', family: null, installed: true, capable: false, model: null, models: [] }],
        installable: [{ id: 'claude', label: 'Claude Code' }],
        scouts: [],
        suggested_scout: null,
        tiers: {},
        suggested: { name: null, reason: 'default', alternatives: [] },
        default_orchestrator: null,
      })
      const addSpy = vi.spyOn(api, 'addAgent').mockResolvedValue({ name: 'claude', agents: ['claude'] })

      await openOrchestrate()
      const bar = await screen.findByRole('group', { name: 'Orquestación' })
      expect(within(bar).getByLabelText('Orquestador')).toBeDisabled()
      expect(within(bar).getByLabelText('Modelo del orquestador')).toBeDisabled()
      expect(screen.getByRole('button', { name: /Planificar/ })).toBeDisabled()

      const addBtn = within(bar).getByRole('button', { name: /Añadir claude/ })
      fireEvent.click(addBtn)
      await waitFor(() => expect(addSpy).toHaveBeenCalledWith({ kind: 'cli', id: 'claude' }))

      // Top motor button also indicates missing orchestrator and opens quick-add options
      const motorBtn = screen.getByRole('button', { name: /Sin orquestador/ })
      fireEvent.click(motorBtn)
      const pop = await screen.findByRole('dialog', { name: 'Elegir motor' })
      expect(within(pop).getByText('CLIs instalados listos para añadir')).toBeInTheDocument()
      expect(within(pop).getByText('Modelos locales en Ollama')).toBeInTheDocument()
    })
  })
})
