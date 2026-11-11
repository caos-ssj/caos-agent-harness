import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Copy, FileSearch, FolderGit2, Layers, ListChecks, MessageSquarePlus, PanelLeft, Plus, ShieldCheck, X, ChevronRight } from 'lucide-react'
import { api, Agent, ExecutionRun, MessageItem, ModelProfile, ProviderItem, RouterTier, SessionDetail, SessionItem, SkillInfo } from '../api'
import { ModelPicker } from './ModelPicker'
import { ToolStepsView } from './ToolStepsView'
import { WorkspaceDrawer } from './WorkspaceDrawer'

interface ConsoleProps {
  agents: Agent[]
  profiles: ModelProfile[]
  tiers: RouterTier[]
  project: string
  skills: SkillInfo[]
  providers: ProviderItem[]
  onBoardChanged: () => void
  focusSignal: number
}

const STARTERS: Array<[string, string, string, React.ElementType]> = [
  ['Explain how this project is organised', 'Reads the folder and answers in plain words. Nothing is changed.', 'Help me understand how this project is organised.', FileSearch],
  ['Plan a review of this project', 'Turns "check it over" into a short list you can turn into board tasks.', 'Help me plan a review of this project.', ListChecks],
  ['Draft the next task for the board', 'Describe a goal; each answer can become a task on the desk with one click.', 'I want to hand a piece of work to an agent. Ask me what you need to know to write it as one clear task.', MessageSquarePlus],
]

/* The console is a conversation with a local Ollama model about this project. It plans and answers; it can propose shell
   commands only after the operator switches them on for the session, and each one waits for approval. */
export const Console: React.FC<ConsoleProps> = ({ agents, profiles, tiers, project, skills, providers, onBoardChanged, focusSignal }) => {
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [sid, setSid] = useState<string | null>(null)
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [rail, setRail] = useState(() => !window.matchMedia('(max-width: 860px)').matches)
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<'plan' | 'act'>('plan')
  const [commandsOn, setCommandsOn] = useState(false)
  const [model, setModelState] = useState(() => { try { return localStorage.getItem('caos_model') || 'qwen3.5:4b' } catch { return 'qwen3.5:4b' } })
  const setModel = (m: string) => { setModelState(m); try { localStorage.setItem('caos_model', m) } catch { /* ignore */ } }
  const [skill, setSkill] = useState('auto')
  const [drawer, setDrawer] = useState(false)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [execution, setExecution] = useState<ExecutionRun | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLTextAreaElement>(null)
  const ollama = providers.find((p) => p.id === 'ollama')

  const loadSessions = useCallback(async (select = false) => {
    try {
      const list = await api.getSessions()
      setSessions(list)
      if (select && list.length) setSid((cur) => cur ?? list[0].id)
    } catch { /* the list stays as it was */ }
  }, [])
  const loadSession = useCallback(async (id: string) => { try { setSession(await api.getSession(id)) } catch { /* ignore */ } }, [])

  useEffect(() => { loadSessions(true) }, [loadSessions])
  useEffect(() => { if (sid) loadSession(sid); else setSession(null) }, [sid, loadSession])
  useEffect(() => { if (focusSignal) field.current?.focus() }, [focusSignal])
  useEffect(() => { const on = !!session?.commands_enabled; setCommandsOn(on); setMode(session?.mode === 'act' && on ? 'act' : 'plan') }, [session])
  useEffect(() => {
    const el = field.current
    if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 168)}px` }
  }, [input])

  useEffect(() => {
    let off = false
    setExecution(null); setBusy(false)
    if (session?.active_run) api.getRun(session.active_run).then((r) => { if (!off) { setExecution(r); setBusy(!['completed', 'failed'].includes(r.status)) } }).catch(() => { if (!off) setNotice('Could not recover the run in progress.') })
    return () => { off = true }
  }, [session?.id])

  useEffect(() => { if ((session?.messages.length ?? 0) > 0 || busy || execution) end.current?.scrollIntoView({ behavior: 'smooth' }) }, [session?.messages, busy, execution?.steps.length])

  useEffect(() => {
    if (!execution || ['completed', 'failed'].includes(execution.status)) return
    const t = window.setInterval(async () => {
      try {
        const next = await api.getRun(execution.id)
        setExecution(next)
        if (['completed', 'failed'].includes(next.status)) { setBusy(false); if (sid) loadSession(sid); loadSessions() }
      } catch { setNotice('Could not read the run. Check that the server is still up.') }
    }, 700)
    return () => window.clearInterval(t)
  }, [execution?.id, execution?.status, sid])

  const newSession = async (): Promise<string | null> => {
    try {
      const created = await api.createSession({ project, mode: 'plan' })
      await loadSessions()
      setSid(created.id)
      return created.id
    } catch (e: any) { setNotice(e.message || 'Could not create the session.'); return null }
  }

  const send = async (text: string) => {
    const content = text.trim()
    if (!content || busy) return
    const id = sid ?? (await newSession())
    if (!id) return
    setBusy(true); setExecution(null)
    try {
      const started = await api.addMessage(id, { content, mode: commandsOn ? mode : 'plan', model, provider: 'ollama', agent: skill, tier: 'medium' })
      setInput('')
      const run = await api.getRun(started.run_id)
      setExecution(run)
      if (['completed', 'failed'].includes(run.status)) setBusy(false)
      await loadSession(id); loadSessions()
    } catch (e: any) { setNotice(e.message || 'The message was not sent.'); setBusy(false) }
  }

  const toggleCommands = async (on: boolean) => {
    if (!session) { setNotice('Start the conversation first; the switch applies to one session.'); return }
    try { const r = await api.setSessionCommands(session.id, on); setCommandsOn(r.commands_enabled); if (!r.commands_enabled) setMode('plan') }
    catch (e: any) { setNotice(e.message || 'Could not change the command switch.') }
  }
  const decide = async (approve: boolean) => {
    if (!execution) return
    try { setExecution(await api.decideRun(execution.id, execution.steps.length - 1, approve)) }
    catch (e: any) { setNotice(e.message || 'The decision was not recorded.') }
  }
  const toTask = async (content: string) => {
    try { const r = await api.convertToTask({ text: content.trim(), tier: 'medium' }); setNotice(`Added to the desk as task ${r.id}.`); onBoardChanged() }
    catch (e: any) { setNotice(e.message || 'The board refused the task.') }
  }
  const copy = (text: string, key: string) => { navigator.clipboard?.writeText(text); setCopied(key); setTimeout(() => setCopied(null), 1800) }
  const remove = async (id: string) => {
    try { await api.deleteSession(id); await loadSessions(); if (sid === id) { setSid(null); setSession(null) } }
    catch (e: any) { setNotice(e.message || 'Could not delete the session.') }
  }

  const messages = session?.messages ?? []
  const running = execution && !['completed', 'failed'].includes(execution.status)

  return (
    <div className={`console ${rail ? '' : 'no-rail'}`}>
      <aside className="rail" aria-label="Sessions">
        <div className="rail-head">
          <h2>Sessions</h2>
          <button type="button" className="btn btn-quiet btn-sm btn-icon" onClick={newSession} aria-label="New session" title="New session"><Plus className="icon" aria-hidden="true" /></button>
        </div>
        <div className="scroll">
          {sessions.length === 0 && <p style={{ padding: '4px var(--pad)', color: 'var(--ink-2)', fontSize: 15.5 }}>None yet. Ask something and the first one starts itself.</p>}
          {sessions.map((s) => (
            <div key={s.id} className="sess" role="button" tabIndex={0} aria-current={s.id === sid} onClick={() => setSid(s.id)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSid(s.id) } }}>
              <span><b>{s.title || 'Untitled'}</b><small>{s.messages_count} {s.messages_count === 1 ? 'message' : 'messages'} · {new Date(s.updated_at * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</small></span>
              <button type="button" className="x" aria-label={`Delete ${s.title || 'session'}`} onClick={(e) => { e.stopPropagation(); remove(s.id) }}><X size={14} aria-hidden="true" /></button>
            </div>
          ))}
        </div>
      </aside>

      <section className="talk" aria-label="Conversation">
        <div className="talk-bar">
          <button type="button" className="btn btn-quiet btn-sm" onClick={() => setRail(!rail)} aria-label={rail ? 'Hide sessions' : 'Show sessions'} aria-pressed={rail}><PanelLeft size={16} aria-hidden="true" /></button>
          <div className="seg" role="group" aria-label="Mode" style={{ minWidth: 150 }}>
            <button type="button" aria-pressed={mode === 'plan'} onClick={() => setMode('plan')}>Plan</button>
            <button type="button" aria-pressed={mode === 'act'} onClick={() => (commandsOn ? setMode('act') : setNotice('Shell commands are off for this conversation. Switch them on below to use Act.'))}>Act</button>
          </div>
          <select className="select" aria-label="Skill the model reads first" value={skill} onChange={(e) => setSkill(e.target.value)}>
            <option value="auto">no skill</option>
            {skills.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
          </select>
          <ModelPicker provider={ollama} profiles={profiles} tiers={tiers} agents={agents} value={model} onChange={setModel} />
          <div className="push">
            <span className={`pip ${ollama?.status === 'online' ? 'on' : ''}`} aria-hidden="true" />
            <span>{ollama?.status === 'online' ? 'Ollama is running' : 'Ollama is not reachable'}</span>
            <button type="button" className="btn btn-quiet btn-sm" onClick={() => setDrawer(!drawer)} aria-expanded={drawer} title="Project context"><FolderGit2 size={16} aria-hidden="true" /></button>
          </div>
        </div>

        <div className={`safety ${commandsOn ? 'armed' : ''}`} aria-live="polite">
          <span>{commandsOn ? (mode === 'act' ? 'Act: the model may propose commands. Each runs only after you approve it, with your permissions, outside a sandbox.' : 'Commands are on for this conversation. Switch to Act to let the model propose them.') : 'Plan: the model answers and plans. No command can run.'}</span>
          <label title="Off by default. Applies to this conversation only and resets when the server restarts.">
            <input type="checkbox" checked={commandsOn} onChange={(e) => toggleCommands(e.target.checked)} />
            shell commands {commandsOn ? 'on' : 'off'}
          </label>
        </div>
        {notice && <div className="banner" role="status"><span>{notice}</span><button type="button" className="btn btn-quiet btn-sm" onClick={() => setNotice(null)}>Dismiss</button></div>}

        <div className="feed">
          {messages.length === 0 && !running && !busy ? (
            <div className="talk-empty">
              <img className="talk-plate" src="/art/policy.svg" alt="" aria-hidden="true" />
              <h2>Ask about this project, or plan the next piece of work.</h2>
              <p>The model runs on your machine through Ollama. Pick a way in, or write your own below; the first message starts the conversation.</p>
              <div className="starters">
                {STARTERS.map(([title, text, prompt, Icon]) => (
                  <button key={title} type="button" className="starter" onClick={() => send(prompt)} disabled={busy}>
                    <span className="badge" style={{ gridColumn: 1 }}><Icon className="icon" aria-hidden="true" /></span><b>{title}</b><span>{text}</span><i aria-hidden="true"><ChevronRight className="icon" /></i>
                  </button>
                ))}
              </div>
              <div className="limits"><ShieldCheck className="icon" aria-hidden="true" /><p style={{ margin: 0 }}><b>Limits.</b> Plan mode runs nothing. Shell commands stay off until you switch them on for a conversation, and each one asks first. Nothing here leaves this machine.</p></div>
            </div>
          ) : messages.map((m: MessageItem) => {
            const me = m.role === 'user'
            return (
              <article key={m.id} className={`turn ${me ? 'me' : ''}`}>
                <div className="turn-head">
                  <b>{me ? 'You' : `${m.model || 'Model'} · ${m.provider || 'local'}`}{!me && m.agent && m.agent !== 'auto' ? ` · skill ${m.agent}` : ''}</b>
                  <span>{m.tokens ? `${m.tokens.toLocaleString('en-US')} tokens · ` : ''}{new Date(m.timestamp * 1000).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })}</span>
                </div>
                <div className="turn-body">{m.content.split(/(\*\*[^*]+\*\*)/g).map((part, i) => part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : part)}</div>
                {m.tool_steps && m.tool_steps.length > 0 && <ToolStepsView steps={m.tool_steps} />}
                {m.diff && (<><pre>{m.diff}</pre><div className="turn-act"><button type="button" onClick={() => copy(m.diff || '', `d${m.id}`)}>{copied === `d${m.id}` ? <Check size={13} /> : <Copy size={13} />} Copy the diff</button></div></>)}
                {m.bash_logs && (<><pre>{m.bash_logs}</pre><div className="turn-act"><button type="button" onClick={() => copy(m.bash_logs || '', `b${m.id}`)}>{copied === `b${m.id}` ? <Check size={13} /> : <Copy size={13} />} Copy the output</button></div></>)}
                {!me && <div className="turn-act"><button type="button" onClick={() => toTask(m.content)}><Layers size={13} aria-hidden="true" /> Turn this answer into a task</button></div>}
              </article>
            )
          })}
          {running && execution && (
            <div className="run-card" role="status">
              <h3><span className="q-live" aria-hidden="true" />{execution.status === 'awaiting_approval' ? 'A command is waiting for your decision' : 'Working'}</h3>
              <div className="mono" style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 4, wordBreak: 'break-all' }}>{execution.model} · {execution.workspace}</div>
              <ToolStepsView steps={execution.status === 'awaiting_approval' ? execution.steps.slice(0, -1) : execution.steps} />
              {execution.status === 'awaiting_approval' && <pre>{execution.steps[execution.steps.length - 1]?.input}</pre>}
              {execution.status === 'awaiting_approval' && <div className="row"><button type="button" className="btn btn-primary" onClick={() => decide(true)}>Run this command</button><button type="button" className="btn" onClick={() => decide(false)}>Reject</button></div>}
            </div>
          )}
          {busy && !execution && <div className="thinking" role="status"><span className="q-live" aria-hidden="true" />{mode === 'plan' ? `Thinking with ${model}…` : `Working in ${project} with ${model}…`}</div>}
          <div ref={end} />
        </div>

        <div className="talk-compose">
          <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input) }}>
            <textarea ref={field} className="composer-field" rows={1} aria-label="Message" value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
              placeholder={mode === 'plan' ? 'Ask a question or describe a goal' : 'Describe the work; commands will wait for your approval'} />
            <div className="composer-bar"><span className="mono" style={{ fontSize: 12, color: 'var(--ink-3)' }}>{mode} · {skill === 'auto' ? 'no skill' : skill} · {model}</span><span className="grow" /><span className="kbd" aria-hidden="true">↵</span><button type="submit" className="btn btn-primary" disabled={busy || !input.trim()}>Send</button></div>
          </form>
        </div>
      </section>
      <WorkspaceDrawer isOpen={drawer} onClose={() => setDrawer(false)} activeRepo={project} onTaskCreated={onBoardChanged} />
    </div>
  )
}
