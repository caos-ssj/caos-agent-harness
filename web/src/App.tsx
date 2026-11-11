import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ProviderItem, StateResponse } from './api'
import { View, isSpecialKey } from './lib'
import { usePrefs } from './prefs'
import { Header } from './components/Header'
import { Ledger } from './components/Ledger'
import { Desk } from './components/Desk'
import { Console } from './components/Console'
import { Library } from './components/Library'
import { Palette, PaletteItem } from './components/Palette'
import { Preferences } from './components/Preferences'

const VIEW_FROM_URL: Record<string, View> = { desk: 'desk', board: 'desk', console: 'console', library: 'library', measured: 'library', providers: 'library', skills: 'library' }

export const App: React.FC = () => {
  const query = useMemo(() => new URLSearchParams(window.location.search), [])
  const [prefs, setPrefs, resetPrefs] = usePrefs()
  const [view, setView] = useState<View>(() => VIEW_FROM_URL[query.get('tab') || ''] ?? prefs.start)
  const [state, setState] = useState<StateResponse | null>(null)
  const [providers, setProviders] = useState<ProviderItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<number | null>(() => Number(query.get('task')) || null)
  const [filter, setFilter] = useState<string | null>(null)
  const [palette, setPalette] = useState(false)
  const [prefsOpen, setPrefsOpen] = useState(false)
  const [composerSignal, setComposerSignal] = useState(0)
  const [consoleSignal, setConsoleSignal] = useState(0)
  const running = useRef(false)

  const load = useCallback(async () => {
    try { const s = await api.getState(); running.current = s.running; setState(s); setError(null) }
    catch (e: any) { setError(e.message || 'Cannot reach the harness on this machine. Is `caos-harness serve` still running?') }
  }, [])
  useEffect(() => { load(); api.getProviders().then((r) => setProviders(r.providers)).catch(() => undefined) }, [load])
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
  const newTask = useCallback(() => { setView('desk'); setComposerSignal((n) => n + 1) }, [])

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((p) => !p); return }
      if (e.metaKey || e.ctrlKey || e.altKey || isSpecialKey(e) || palette) return
      if (e.key === 'r') { e.preventDefault(); run() }
      if (e.key === 'n') { /* handled by the desk, which owns the composer */ }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [run, palette])

  const items: PaletteItem[] = [
    { id: 'v-desk', group: 'Go to', label: 'Desk', hint: 'queues, tasks, trace', run: () => go('desk') },
    { id: 'v-console', group: 'Go to', label: 'Console', hint: 'talk to a local model', run: () => { go('console'); setConsoleSignal((n) => n + 1) } },
    { id: 'v-library', group: 'Go to', label: 'Library', hint: 'measured systems, router, agents, skills, providers', run: () => go('library') },
    { id: 'a-new', group: 'Do', label: 'Add a task', hint: 'n', run: newTask },
    { id: 'a-run', group: 'Do', label: runnable ? `Run ${runnable} pending` : 'Run pending tasks', hint: runnable ? 'r' : 'nothing to send', run },
    ...(needsYou ? [{ id: 'a-needs', group: 'Do', label: `Show the ${needsYou} waiting for you`, hint: 'filter', run: () => { go('desk'); setFilter('needs') } }] : []),
    { id: 'p-density', group: 'Preferences', label: prefs.density === 'compact' ? 'Density: comfortable' : 'Density: compact', hint: 'how many tasks fit', run: () => setPrefs({ density: prefs.density === 'compact' ? 'comfortable' : 'compact' }) },
  ]

  return (
    <div className="app" data-density={prefs.density}>
      <a className="skip" href="#main">Skip to the content</a>
      <Header
        project={state?.project ?? ''} sample={!!state?.sample} view={view} onView={go}
        needsYou={needsYou} pending={runnable} running={!!state?.running} onRun={run}
        onOpenPalette={() => setPalette(true)} onTogglePrefs={() => setPrefsOpen((o) => !o)} prefsOpen={prefsOpen}
      />
      {state?.sample && <div className="sample-strip">Sample data: the tasks and answers here are made-up examples.</div>}
      {prefsOpen && <Preferences prefs={prefs} onChange={setPrefs} onReset={resetPrefs} onClose={() => setPrefsOpen(false)} />}
      {error && <div className="banner err" role="alert"><span>{error}</span><button type="button" className="btn btn-quiet btn-sm" onClick={() => load()}>Try again</button></div>}
      <main className="main" id="main" tabIndex={-1}>
        {view === 'desk' && (
          <div className="view" key="desk">
            <Ledger state={state} onNeeds={() => setFilter('needs')} />
            <Desk state={state} selectedId={selected} onSelect={setSelected} onChanged={load} onRun={run} runnable={runnable} filter={filter} onFilter={setFilter} focusComposer={composerSignal} />
          </div>
        )}
        {view === 'console' && (
          <div className="view" key="console"><Console project={state?.project ?? ''} skills={state?.skills ?? []} providers={providers} onBoardChanged={load} focusSignal={consoleSignal} /></div>
        )}
        {view === 'library' && <div className="view" key="library"><Library state={state} /></div>}
      </main>
      <footer className="foot">
        <span className="safe"><span className="pip on" aria-hidden="true" /><span className="long">{window.location.host} · this machine only · commands need your approval</span><span className="short">this machine only · commands ask first</span></span>
        <span className="motto" lang="es" title="Order emerges from the rigor of evidence">El orden emerge del rigor de la evidencia</span>
      </footer>
      <Palette open={palette} onClose={() => setPalette(false)} items={items} tasks={tasks} onTask={(id) => { setView('desk'); setFilter(null); setSelected(id) }} />
    </div>
  )
}
