import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { api } from './api'
import { gatesReading, TrendChart } from './components/MetricsView'
import { Markdown } from './components/Markdown'
import { byTopDir, ShareView } from './components/ShareView'
import { ProvidersView } from './components/ProvidersView'
import { SkillsView } from './components/SkillsView'

const provider = (over: object) => ({ type: 'cloud', status: 'missing_key', quota: '', cost_per_m: 'not measured', models: [], default_model: '', description: '', ...over })
const PROVIDERS = {
  providers: [
    provider({ id: 'ollama', name: 'Ollama', type: 'local', status: 'online', models: ['qwen2.5:7b', 'llama3.2:3b'], default_model: 'qwen2.5:7b', model_details: [{ name: 'qwen2.5:7b', size: 4.7e9, parameter_size: '7.6B', quantization: 'Q4_K_M', family: 'qwen2' }, { name: 'llama3.2:3b', size: 2e9, parameter_size: '3.2B', quantization: 'Q4_K_M', family: 'llama' }] }),
    provider({ id: 'openai', name: 'OpenAI', status: 'key_present', default_model: 'gpt-4.1-mini', api_key_env: 'OPENAI_API_KEY' }),
    provider({ id: 'openrouter', name: 'OpenRouter', default_model: 'openrouter/free', api_key_env: 'OPENROUTER_API_KEY', free_models: ['openrouter/free', 'nvidia/nemotron-3-ultra-550b-a55b:free'], tier_hint: 'Free :free tier: 20 RPM / 50 RPD' }),
    provider({ id: 'nvidia', name: 'NVIDIA NIM', default_model: 'deepseek-ai/deepseek-v4-flash', api_key_env: 'NVIDIA_API_KEY', free_models: ['deepseek-ai/deepseek-v4-flash'] }),
  ],
  ollama_hosts: [{ id: 'local', label: 'Local Ollama', url: 'http://127.0.0.1:11434', online: true, models: ['qwen2.5:7b', 'llama3.2:3b'] }],
  intents: {}, active_failover: { enabled: false, strategy: 'sequential', fallback_target: 'ollama', fallback_model: '', description: '' },
  clis: [{ id: 'opencode', label: 'OpenCode CLI', account: 'x', installed: true, command: 'opencode run -m opencode/glm-5.3-flash-free', added: false, free_models: ['opencode/glm-5.3-flash-free', 'opencode/beam-free'] }],
  api_agents: [],
}
const TIERS = [{ tier: 'low', needs: 0.75, action: 'route', system: 'llama3.2:3b', agent: null, reason: '' }]
const PROFILES = [{ system: 'llama3.2:3b', measured: '', precision: 0.883, precision_lo: 0.778, coverage: 0.9, seconds_per_1000: 1177, tokens_per_1000: null, n: 40 }]

const view = (scope: 'project' | 'global' = 'project') => render(<ProvidersView agents={[]} profiles={PROFILES} tiers={TIERS} scope={scope} onAgentsChanged={() => undefined} onUseModel={() => undefined} />)

describe('Metrics pieces', () => {
  it('reads the repository gates without claiming more than was checked', () => {
    expect(gatesReading({ mutation: { caught: 26, total: 26 }, regress_status: 'pass' })).toMatchObject({ value: 'PASS', tone: 'pass' })
    expect(gatesReading({ mutation: { caught: 25, total: 26 }, regress_status: 'pass' })).toMatchObject({ value: 'REVISAR', tone: 'fail' })
    expect(gatesReading({ mutation: { caught: 26, total: 26 }, regress_status: 'check' }).value).toBe('REVISAR')       // the backend says "check", never "fail"
    expect(gatesReading({ mutation: { caught: 26, total: 26 }, regress_status: null })).toMatchObject({ value: 'PARCIAL', sub: 'mut 26/26 · regress sin verificar' })
    expect(gatesReading({ mutation: null, regress_status: null })).toMatchObject({ value: 'SIN VERIFICAR', tone: 'idle' })
  })

  it('says so when there are too few runs, and draws a real trend when there are enough', () => {
    const { rerender } = render(<TrendChart series={{ scope: 'project', bucket: 'day', min_runs: 5, total_runs: 3, enough: false, points: [] }} />)
    expect(screen.getByText('Aún no hay tendencia que mostrar')).toBeInTheDocument()
    expect(screen.getByText(/Hay 3 run\(s\) registrados; la gráfica aparece desde 5/)).toBeInTheDocument()
    rerender(<TrendChart series={{ scope: 'project', bucket: 'day', min_runs: 5, total_runs: 9, enough: true, points: [{ t: 1700000000, runs: 4, ok: 4, success_rate: 1, p50_ms: 300 }, { t: 1700086400, runs: 5, ok: 4, success_rate: 0.8, p50_ms: 500 }] }} />)
    expect(screen.getByRole('img', { name: /Tendencia/ })).toBeInTheDocument()
    expect(screen.getByText(/9 runs/)).toBeInTheDocument()
  })
})

describe('Markdown and Share helpers', () => {
  it('shows a skill body as text and never as HTML', () => {
    const { container } = render(<Markdown text={'# Title\n\n- **bold** and `code`\n\n<img src=x onerror=alert(1)>\n\n```\nraw <b>\n```'} />)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument()
    expect(container.querySelector('strong')?.textContent).toBe('bold')
    expect(container.querySelector('h3')?.textContent).toBe('Title')
  })
  it('groups a pack by its first folder', () => {
    expect(byTopDir([{ path: 'README.md' }, { path: 'src/a.py' }, { path: 'src/b.py' }, { path: 'docs/x.md' }]).map((g) => [g.dir, g.items.length])).toEqual([['(raíz)', 1], ['docs/', 1], ['src/', 2]])
  })
})

describe('ProvidersView', () => {
  beforeEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.spyOn(api, 'getProviders').mockResolvedValue(PROVIDERS as any)
  })

  it('lists every local model in a table, never hidden behind a count, with its measured precision', async () => {
    view()
    fireEvent.click(await screen.findByRole('tab', { name: /Modelos Locales/i }))
    const region = await screen.findByRole('region', { name: 'Modelos locales' })
    const more = within(region).queryByRole('button', { name: /models not measured/ })   // the unmeasured tail is folded, one click away
    if (more) fireEvent.click(more)
    const table = within(region).getByRole('table')
    expect(within(table).getByText('qwen2.5:7b')).toBeInTheDocument()
    expect(within(table).getByText('llama3.2:3b')).toBeInTheDocument()
    expect(within(table).getByText('77.8%', { exact: false })).toBeInTheDocument()          // the 95% lower bound
    expect(within(table).getAllByRole('button', { name: 'Smoke' })).toHaveLength(2)
    expect(within(table).getAllByRole('button', { name: /Usar en Console/ })).toHaveLength(2)
    expect(within(table).getAllByRole('button', { name: /Promover/ })).toHaveLength(2)
  })

  it('shows free-tier chips, the tier hint and NVIDIA NIM; an unkeyed provider opens its key form inline', async () => {
    const save = vi.spyOn(api, 'saveProviderKey').mockResolvedValue({ ok: true, saved: true, storage: '.harness/.env.local', env: 'NVIDIA_API_KEY', masked: 'nva••••1234' })
    view()
    const card = (await screen.findByText('NVIDIA NIM')).closest('article') as HTMLElement
    expect(within(card).getByText('falta NVIDIA_API_KEY')).toBeInTheDocument()
    const or = screen.getByText('OpenRouter').closest('article') as HTMLElement
    expect(within(or).getByText('nvidia/nemotron-3-ultra-550b-a55b:free')).toBeInTheDocument()
    expect(within(or).getByText(/20 RPM \/ 50 RPD/)).toBeInTheDocument()
    fireEvent.click(within(card).getByRole('button', { name: /Key/ }))
    fireEvent.change(within(card).getByLabelText('Clave de NVIDIA NIM'), { target: { value: 'nvapi-0123456789abcdef' } })
    fireEvent.click(within(card).getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(save).toHaveBeenCalledWith('nvidia', 'nvapi-0123456789abcdef', 'env_local'))   // the project scope stores it in the project's .env.local
  })

  it('stores a key globally when the scope is global, and hides project-only sections', async () => {
    const save = vi.spyOn(api, 'saveProviderKey').mockResolvedValue({ ok: true, saved: true, storage: 'system keyring', env: 'X', masked: 'a••••b' })
    view('global')
    const card = (await screen.findByText('NVIDIA NIM')).closest('article') as HTMLElement
    fireEvent.click(within(card).getByRole('button', { name: /Key/ }))
    fireEvent.change(within(card).getByLabelText('Clave de NVIDIA NIM'), { target: { value: 'nvapi-0123456789abcdef' } })
    fireEvent.click(within(card).getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(save).toHaveBeenCalledWith('nvidia', 'nvapi-0123456789abcdef', 'auto'))
    expect(screen.queryByText('Agentes CLI locales')).not.toBeInTheDocument()
    expect(screen.queryByText('Router por intención')).not.toBeInTheDocument()
  })

  it('adds OpenCode CLI with the free model that was chosen', async () => {
    const add = vi.spyOn(api, 'addAgent').mockResolvedValue({ name: 'opencode', agents: [] })
    view()
    fireEvent.change(await screen.findByLabelText('Modelo de OpenCode CLI'), { target: { value: 'opencode/beam-free' } })
    fireEvent.click(screen.getByRole('button', { name: 'Agregar al Board' }))
    await waitFor(() => expect(add).toHaveBeenCalledWith(expect.objectContaining({ kind: 'cli', id: 'opencode', model: 'opencode/beam-free' })))
  })

  it('compares local against local directly, and asks before spending cloud quota', async () => {
    const compare = vi.spyOn(api, 'compareProviders').mockResolvedValue({ cloud: false, results: [
      { provider: 'ollama', model: 'qwen2.5:7b', ok: true, latency_ms: 420, json_ok: false, tool_calls: 0, answer: 'hola', prompt_tokens: 5, completion_tokens: 2, error: '' },
      { provider: 'ollama', model: 'llama3.2:3b', ok: true, latency_ms: 210, json_ok: true, tool_calls: 0, answer: '{"a":1}', prompt_tokens: 5, completion_tokens: 3, error: '' }] })
    view()
    fireEvent.click(await screen.findByRole('tab', { name: /Router y Comparador/i }))
    const a = await screen.findByLabelText('Motor A')
    expect((a as HTMLSelectElement).value).toBe('ollama::llama3.2:3b')                                  // measured models come first
    await waitFor(() => expect((screen.getByLabelText('Motor B') as HTMLSelectElement).value).toBe('ollama::qwen2.5:7b'))   // local against local by default
    fireEvent.click(screen.getByRole('button', { name: 'Comparar' }))
    await waitFor(() => expect(compare).toHaveBeenCalledTimes(1))
    expect(compare.mock.calls[0][0].confirm_cloud).toBeUndefined()
    expect(await screen.findByText('420 ms')).toBeInTheDocument()
    expect(screen.getByText('JSON válido')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Motor B'), { target: { value: 'openai::gpt-4.1-mini' } })
    fireEvent.click(screen.getByRole('button', { name: 'Comparar' }))
    const dialog = await screen.findByRole('alertdialog', { name: /Confirmar uso de la nube/ })
    expect(within(dialog).getByText(/openai · gpt-4.1-mini/)).toBeInTheDocument()
    expect(compare).toHaveBeenCalledTimes(1)                                                              // nothing was sent yet
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirmar y comparar' }))
    await waitFor(() => expect(compare).toHaveBeenCalledTimes(2))
    expect(compare.mock.calls[1][0].confirm_cloud).toBe(true)
  })
})

describe('SkillsView', () => {
  beforeEach(() => { cleanup(); vi.restoreAllMocks(); vi.spyOn(api, 'getTools').mockResolvedValue({ tools: [{ id: 'mcp:memory', name: 'memory', kind: 'mcp', status: 'ready', summary: 'python -m x', shareable: true }, { id: 'ws-read', name: 'Workspace Reader', kind: 'builtin', status: 'online', summary: 'read_file', shareable: true }] }) })

  it('keeps a bundle skill read-only and clones it into the project to edit it', async () => {
    const clone = vi.spyOn(api, 'cloneSkill').mockResolvedValue({ name: 'coder', description: 'd', local: true } as any)
    const changed = vi.fn()
    render(<SkillsView skills={[{ name: 'coder', description: 'Writing and fixing code in a repository', category: 'Código & Infra', local: false, body: '# Coder\n\n- one' }, { name: 'mine', description: 'My own project rules', local: true, body: '# Mine' }]} onSkillsChanged={changed} />)
    fireEvent.click(await screen.findByRole('button', { name: /coder/ }))
    expect(screen.getByText('bundle · solo lectura')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Guardar$/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Clonar a Proyecto/ }))
    await waitFor(() => expect(clone).toHaveBeenCalledWith('coder'))
    expect(changed).toHaveBeenCalled()
  })

  it('edits a local skill with a Markdown preview, and keeps MCP servers apart from harness tools', async () => {
    const save = vi.spyOn(api, 'saveSkill').mockResolvedValue({ name: 'mine', description: 'x', local: true } as any)
    render(<SkillsView skills={[{ name: 'mine', description: 'My own project rules', local: true, category: 'Proyecto', body: '# Mine\n\n- rule' }]} />)
    expect(await screen.findByText('local del proyecto')).toBeInTheDocument()
    expect(screen.getByText('rule')).toBeInTheDocument()                                  // preview of the Markdown
    fireEvent.click(screen.getByRole('button', { name: /Editar/ }))
    fireEvent.change(screen.getByLabelText('SKILL.md'), { target: { value: '# Mine\n\n- changed' } })
    fireEvent.click(screen.getByRole('button', { name: /^Guardar$/ }))
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ name: 'mine', body: '# Mine\n\n- changed' })))
    fireEvent.click(screen.getByRole('tab', { name: /MCP & Tools/ }))
    const mcp = (await screen.findByText(/Servidores MCP/)).closest('section') as HTMLElement
    expect(within(mcp).getByText('memory')).toBeInTheDocument()
    expect(within(mcp).queryByText('Workspace Reader')).not.toBeInTheDocument()
  })
})

describe('ShareView', () => {
  it('asks the server for a preview of the chosen format and options, and shows what stays out and why', async () => {
    cleanup(); vi.restoreAllMocks()
    vi.spyOn(api, 'getShareExports').mockResolvedValue({ exports: [], gdrive_connected: false })
    const prev = vi.spyOn(api, 'getSharePreview').mockResolvedValue({ ok: true, dry_run: true, format: 'tar.gz', included: [{ path: 'a.py', size: 10, redacted_lines: 0 }], generated: [{ path: 'TEAM_SETUP.md', size: 5 }], excluded: [{ path: '.env', reason: 'secret or database file' }], redactions: [], redacted_paths: [], unscanned: [], files_count: 2, total_bytes: 15, skills_included: [], sanitization: [{ id: 'secret_files', label: '1 secret or database file(s) left out', ok: true }], onboarding: ['pip install -e .'] })
    render(<ShareView />)
    await waitFor(() => expect(prev).toHaveBeenCalledWith({ format: 'zip', include_code: true, include_docs: true, include_skills: true }))
    fireEvent.click(screen.getByRole('button', { name: 'TAR.GZ' }))
    await waitFor(() => expect(prev).toHaveBeenLastCalledWith({ format: 'tar.gz', include_code: true, include_docs: true, include_skills: true }))
    fireEvent.click(screen.getByLabelText('Docs'))
    await waitFor(() => expect(prev).toHaveBeenLastCalledWith({ format: 'tar.gz', include_code: true, include_docs: false, include_skills: true }))
    expect((await screen.findAllByText('.env')).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('secret or database file')).toBeInTheDocument()
    expect(screen.getByText('1 secret or database file(s) left out')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copiar pip install -e .' })).toBeInTheDocument()
  })
})
