import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ProviderItem, RouterResponse, StateResponse } from './api'
import { View, isSpecialKey } from './lib'
import { usePrefs } from './prefs'
import { Header } from './components/Header'
import { Board } from './components/Board'
import { Console } from './components/Console'
import { ProvidersView } from './components/ProvidersView'
import { StatsView } from './components/StatsView'
import { SkillsView } from './components/SkillsView'
import { Palette, PaletteItem } from './components/Palette'
import { Preferences } from './components/Preferences'
import { PageHead } from './components/PageHead'

const VIEW_FROM_URL: Record<string, View> = { board: 'board', desk: 'board', console: 'console', providers: 'providers', measured: 'measured', skills: 'skills' }

export const App: React.FC = () => {
  const query = useMemo(() => new URLSearchParams(window.location.search), [])
  const [prefs, setPrefs, resetPrefs] = usePrefs()
  const [view, setView] = useState<View>(() => VIEW_FROM_URL[query.get('tab') || ''] ?? prefs.start)
  const [state, setState] = useState<StateResponse | null>(null)
  const [providers, setProviders] = useState<ProviderItem[]>([])
  const [router, setRouter] = useState<RouterResponse | null>(null)
  const [wsKey, setWsKey] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<number | null>(() => Number(query.get('task')) || null)
  const [filter, setFilter] = useState<string | null>(null)
  const [palette, setPalette] = useState(false)
  const [prefsOpen, setPrefsOpen] = useState(false)
  const [newTask, setNewTask] = useState(0)
  const [consoleSignal, setConsoleSignal] = useState(0)
  const running = useRef(false)

  const load = useCallback(async () => {
    try { const s = await api.getState(); running.current = s.running; setState(s); setError(null) }
    catch (e: any) { setError(e.message || 'Cannot reach the harness on this machine. Is `caos-harness serve` still running?') }
  }, [])
  const loadStatic = useCallback(() => { api.getProviders().then((r) => setProviders(r.providers)).catch(() => undefined); api.getRouter().then(setRouter).catch(() => undefined) }, [])
  useEffect(() => { load(); loadStatic() }, [load, loadStatic])
  const switched = useCallback(() => { setSelected(null); setFilter(null); setWsKey((n) => n + 1); load(); loadStatic() }, [load, loadStatic])
  // Poll quickly while a run is going, slowly otherwise, and not at all while the tab is hidden.
  useEffect(() => {
    const t = window.setInterval(() => { if (!document.hidden) load() }, state?.running ? 1200 : 8000)
    return () => window.clearInterval(t)
  }, [load, state?.running])

  const tasks = state?.tasks ?? []
  const needsYou = tasks.filter((t) => t.state === 'to_review' || t.state === 'verify' || t.state === 'person').length
  // `run` only sends to agents: a task in the person queue is waiting for a human, not for a run.
  const runnable = tasks.filter((t) => t.state === 'pending' && t.queue !== 'person').length

  const run = useCallback(async () => {
    if (running.current || runnable === 0) return
    try { await api.runPending(); running.current = true; await load() } catch (e: any) { setError(e.message || 'The run did not start.') }
  }, [load, runnable])
  const go = useCallback((v: View) => { setView(v); setPrefsOpen(false) }, [])
  const openNewTask = useCallback(() => { setView('board'); setNewTask((n) => n + 1) }, [])

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((p) => !p); return }
      if (e.metaKey || e.ctrlKey || e.altKey || isSpecialKey(e) || palette) return
      if (e.key === 'r') { e.preventDefault(); run() }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [run, palette])

  const items: PaletteItem[] = [
    { id: 'v-board', group: 'Go to', label: 'Board', hint: 'queues and tasks', run: () => go('board') },
    { id: 'v-console', group: 'Go to', label: 'Console', hint: 'talk to a local model', run: () => { go('console'); setConsoleSignal((n) => n + 1) } },
    { id: 'v-providers', group: 'Go to', label: 'Providers', hint: 'what can run here', run: () => go('providers') },
    { id: 'v-measured', group: 'Go to', label: 'Measured', hint: 'figures and the router', run: () => go('measured') },
    { id: 'v-skills', group: 'Go to', label: 'Skills', hint: 'instructions an agent reads first', run: () => go('skills') },
    { id: 'a-new', group: 'Do', label: 'Add a task', hint: 'n', run: openNewTask },
    { id: 'a-run', group: 'Do', label: runnable ? `Run ${runnable} pending` : 'Run pending tasks', hint: runnable ? 'r' : 'nothing to send', run },
    ...(needsYou ? [{ id: 'a-needs', group: 'Do', label: `Show the ${needsYou} waiting for you`, hint: 'filter', run: () => { go('board'); setFilter('needs') } }] : []),
    { id: 'p-density', group: 'Preferences', label: prefs.density === 'compact' ? 'Density: comfortable' : 'Density: compact', hint: 'how many tasks fit', run: () => setPrefs({ density: prefs.density === 'compact' ? 'comfortable' : 'compact' }) },
    { id: 'p-text', group: 'Preferences', label: prefs.text === 'large' ? 'Text: standard size' : 'Text: large size', hint: 'easier to read', run: () => setPrefs({ text: prefs.text === 'large' ? 'standard' : 'large' }) },
  ]

  return (
    <div className="app" data-density={prefs.density} data-text={prefs.text}>
      <a className="skip" href="#main">Skip to the content</a>
      <Header
        project={state?.project ?? ''} root={state?.root} onSwitched={switched} sample={!!state?.sample} view={view} onView={go}
        needsYou={needsYou} runnable={runnable} running={!!state?.running} onRun={run}
        onOpenPalette={() => setPalette(true)} onTogglePrefs={() => setPrefsOpen((o) => !o)} prefsOpen={prefsOpen}
      />
      {state?.sample && <div className="sample-strip">Sample data: the tasks and answers here are made-up examples.</div>}
      {prefsOpen && <Preferences prefs={prefs} onChange={setPrefs} onReset={resetPrefs} onClose={() => setPrefsOpen(false)} />}
      {error && <div className="banner err" role="alert"><span>{error}</span><button type="button" className="btn btn-quiet btn-sm" onClick={() => load()}>Try again</button></div>}
      <main className="main" id="main" tabIndex={-1}>
        {view === 'board' && <div className="view" key={`board-${wsKey}`}><Board router={router} state={state} selectedId={selected} onSelect={setSelected} onChanged={load} onRun={run} runnable={runnable} filter={filter} onFilter={setFilter} newTaskSignal={newTask} /></div>}
        {view === 'console' && <div className="view" key={`console-${wsKey}`}><Console agents={state?.agents ?? []} profiles={router?.profiles ?? []} tiers={router?.tiers ?? []} project={state?.project ?? ''} skills={state?.skills ?? []} providers={providers} onBoardChanged={load} focusSignal={consoleSignal} /></div>}
        {view === 'providers' && (
          <div className="view" key="providers"><div className="page"><div className="page-inner">
            <PageHead title="Providers" art="models" lead="Where models come from, which of them were measured, and which agents run them. A key is never typed or stored here." />
            <ProvidersView agents={state?.agents ?? []} profiles={router?.profiles ?? []} tiers={router?.tiers ?? []} onUseModel={(m) => { try { localStorage.setItem('caos_model', m) } catch { /* ignore */ } setConsoleSignal((n) => n + 1); setView('console') }} />
          </div></div></div>
        )}
        {view === 'measured' && <div className="view" key="measured"><StatsView state={state} /></div>}
        {view === 'skills' && <div className="view" key="skills"><SkillsView skills={state?.skills ?? []} agents={state?.agents ?? []} /></div>}
      </main>
      <footer className="foot">
        <span className="brandline"><b>BRAYNER JAIME</b><span className="fk">caos</span><span className="long">{window.location.host}</span></span>
        <span className="motto" lang="es" title="Order emerges from the rigor of evidence">El orden emerge del rigor de la evidencia</span>
        <span><span className="long">Runs on this machine · commands need your approval · Ctrl/⌘ K for commands</span><span className="short">this machine only</span></span>
      </footer>
      <Palette open={palette} onClose={() => setPalette(false)} items={items} tasks={tasks} onTask={(id) => { setView('board'); setFilter(null); setSelected(id) }} />
    </div>
  )
}
