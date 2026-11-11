import React, { useState, useEffect, useRef } from 'react'
import { api, SessionDetail, ProviderItem, MessageItem, AlignmentQuestion, ExecutionRun } from '../api'
import {
  CornerDownLeft,
  Sparkles,
  Zap,
  Bot,
  User,
  Terminal,
  FileCode,
  Check,
  Copy,
  Layers,
  FolderGit2,
  Shield,
} from 'lucide-react'
import { ToolStepsView } from './ToolStepsView'
import { WorkspaceDrawer } from './WorkspaceDrawer'

interface HackerConsoleProps {
  currentSession: SessionDetail | null
  providers: ProviderItem[]
  activeRepo: string
  onMessageSent: () => void
  onOpenPalette: () => void
  onCreateSession: () => void
}

export const HackerConsole: React.FC<HackerConsoleProps> = ({
  currentSession,
  providers,
  activeRepo,
  onMessageSent,
  onOpenPalette,
  onCreateSession,
}) => {
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<'plan' | 'act'>('plan')
  // Shell commands are off until the operator turns them on for this session (server-side switch, lost on restart).
  const [commandsOn, setCommandsOn] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState('ollama')
  const [selectedModel, setSelectedModel] = useState('qwen3.5:4b')
  const [selectedAgent, setSelectedAgent] = useState('auto')
  const selectedTier = 'medium'
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [copiedIndex, setCopiedIndex] = useState<string | null>(null)
  const [statusMsg, setStatusMsg] = useState<string | null>(null)
  const [execution, setExecution] = useState<ExecutionRun | null>(null)
  const feedEndRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const field = composerRef.current
    if (field) {
      field.style.height = 'auto'
      field.style.height = `${Math.min(field.scrollHeight, 160)}px`
    }
  }, [input])

  // Sincronizar el modo de la sesión
  useEffect(() => {
    const on = !!currentSession?.commands_enabled
    setCommandsOn(on)
    setMode(currentSession?.mode === 'act' && on ? 'act' : 'plan')
  }, [currentSession])

  useEffect(() => {
    let cancelled = false
    setExecution(null)
    setIsSubmitting(false)
    if (currentSession?.active_run) {
      api.getRun(currentSession.active_run).then((run) => {
        if (!cancelled) { setExecution(run); setIsSubmitting(!['completed', 'failed'].includes(run.status)) }
      }).catch(() => { if (!cancelled) setStatusMsg('Could not recover the run in progress.') })
    }
    return () => { cancelled = true }
  }, [currentSession?.id])

  // Scroll automático hacia el final del feed
  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [currentSession?.messages, isSubmitting])

  const handleSend = async (contentToSend?: string) => {
    const text = contentToSend || input
    setExecution(null)
    if (!text.trim() || !currentSession || isSubmitting) return

    setIsSubmitting(true)

    try {
      const started = await api.addMessage(currentSession.id, {
        content: text.trim(),
        mode,
        model: selectedModel,
        provider: selectedProvider,
        agent: selectedAgent,
        tier: selectedTier,
      })
      if (!contentToSend) setInput('')
      const currentRun = await api.getRun(started.run_id)
      setExecution(currentRun)
      if (['completed', 'failed'].includes(currentRun.status)) setIsSubmitting(false)
      onMessageSent()
    } catch (err) {
      console.error(err)
      setStatusMsg(err instanceof Error ? err.message : 'The message was not sent.')
      setIsSubmitting(false)
    }
  }

  useEffect(() => {
    if (!execution || execution.status === 'completed' || execution.status === 'failed') return
    const timer = window.setInterval(async () => {
      try {
        const next = await api.getRun(execution.id)
        setExecution(next)
        if (next.status === 'completed' || next.status === 'failed') {
          setIsSubmitting(false)
          onMessageSent()
        }
      } catch { setStatusMsg('Could not read the run. Check that the server is still up.') }
    }, 700)
    return () => window.clearInterval(timer)
  }, [execution?.id, execution?.status, currentSession?.id])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const copyCode = (text: string, id: string) => {
    navigator.clipboard.writeText(text)
    setCopiedIndex(id)
    setTimeout(() => setCopiedIndex(null), 2000)
  }

  const decideCommand = async (approve: boolean) => {
    if (!execution) return
    try {
      setExecution(await api.decideRun(execution.id, execution.steps.length - 1, approve))
    } catch (err) {
      setStatusMsg(err instanceof Error ? err.message : 'The decision was not recorded.')
    }
  }

  const handleConvertToTask = async (content: string) => {
    try {
      const summary = content.trim()
      const res = await api.convertToTask({
        text: summary,
        tier: selectedTier,
      })
      setStatusMsg(`Task ${res.id} added to the board`)
      setTimeout(() => setStatusMsg(null), 3000)
      onMessageSent()
    } catch (err: any) {
      alert(err.message || 'The board refused the task')
    }
  }

  return (
    <div className="flex-1 min-w-0 flex h-full min-h-0 overflow-hidden">
      {/* Columna Central de la Consola Hacker */}
      <div className="flex-1 min-w-0 flex flex-col h-full min-h-0 border-l border-caos-borde bg-caos-tinta overflow-hidden">
        <div className="local-notice"><span className="local-notice-dot" aria-hidden="true" /><span><strong>Runs on this machine</strong><span className="local-notice-detail"> · Commands are off until you switch them on for a session. Each one needs your approval and runs with your permissions, not in a sandbox.</span></span></div>
        {/* 1. Barra de Control de Modo, Enrutamiento de Agente y Modelos */}
        <div className="console-toolbar">
          {/* Selector de Modo: Plan vs Act */}
          <div className="console-modes" role="group" aria-label="Modo de trabajo">
            <button
              type="button"
              aria-pressed={mode === 'plan'}
              onClick={() => setMode('plan')}
              className={`flex items-center gap-1.5 px-2.5 py-1 text-xs uppercase font-bold tracking-wider transition-all cursor-pointer ${
                mode === 'plan'
                  ? 'mode-active'
                  : 'text-caos-gris hover:text-caos-hueso'
              }`}
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Plan</span>
            </button>

            <button
              type="button"
              aria-pressed={mode === 'act'}
              onClick={() => (commandsOn ? setMode('act') : setStatusMsg('Commands are off for this session. Turn them on with the switch on the right.'))}
              title={commandsOn ? 'Act: the model may propose commands for your approval' : 'Commands are off for this session'}
              className={`flex items-center gap-1.5 px-2.5 py-1 text-xs uppercase font-bold tracking-wider transition-all cursor-pointer ${
                mode === 'act'
                  ? 'mode-active'
                  : 'text-caos-gris hover:text-caos-hueso'
              }`}
            >
              <Zap className="w-3.5 h-3.5" />
              <span>Act</span>
            </button>
          </div>

          {/* Selector de Rol de Agente y Nivel de Riesgo */}
          <div className="flex flex-wrap items-center gap-2 min-w-0 font-mono text-xs">
            {/* Rol de Agente */}
            <div className="console-select flex items-center gap-2 bg-caos-tinta px-2.5 py-1 border border-caos-borde">
              <Shield className="w-3 h-3 text-caos-blueText" />
              <select
                aria-label="Skill"
                title="The skill whose instructions the model receives"
                value={selectedAgent}
                onChange={(e) => setSelectedAgent(e.target.value)}
                className="bg-transparent text-caos-hueso focus:outline-none cursor-pointer"
              >
                <option value="auto">No skill</option>
                <option value="coder">coder</option>
                <option value="writer">writer</option>
                <option value="social-content">social-content</option>
                <option value="qa">qa</option>
              </select>
            </div>

            {/* Selector de Modelo y Proveedor */}
            <div className="console-select flex items-center gap-2 bg-caos-tinta px-2.5 py-1 border border-caos-borde">
              <Bot className="w-3 h-3 text-caos-champan" />
              <select
                aria-label="Local model"
                title="A model installed in Ollama"
                value={`${selectedProvider}:${selectedModel}`}
                onChange={(e) => {
                  const [p, ...parts] = e.target.value.split(':')
                  const m = parts.join(':')
                  setSelectedProvider(p)
                  setSelectedModel(m)
                }}
                className="bg-transparent text-caos-hueso focus:outline-none cursor-pointer max-w-[210px] truncate"
              >
                {providers && providers.some((p) => p.id === 'ollama') ? (
                  providers.filter((p) => p.id === 'ollama').map((p) => (
                    <optgroup
                      key={p.id}
                      label={`${p.name} (${p.type === 'local' ? 'Local $0' : p.type === 'custom' ? 'Custom' : 'Nube'})`}
                    >
                      {!p.models.includes(selectedModel) && <option value={`ollama:${selectedModel}`} disabled>{selectedModel} · not installed</option>}
                      {p.models.filter((m) => !m.toLowerCase().includes('embed')).map((m) => (
                        <option key={`${p.id}:${m}`} value={`${p.id}:${m}`}>
                          {m}
                        </option>
                      ))}
                    </optgroup>
                  ))
                ) : (
                  <option value="ollama:qwen3.5:4b">qwen3.5:4b · Ollama</option>
                )}
              </select>
            </div>

            {/* Toggle Drawer Contexto */}
            <button
              onClick={() => setIsDrawerOpen(!isDrawerOpen)}
              aria-label="Open repository context"
              aria-expanded={isDrawerOpen}
              title="Repository context"
              className={`flex items-center gap-1.5 px-2.5 py-1 border transition-colors cursor-pointer ${
                isDrawerOpen
                  ? 'border-caos-ambar bg-caos-ambar text-caos-negro font-bold'
                  : 'border-caos-borde bg-caos-tinta text-caos-gris hover:text-caos-hueso'
              }`}
            >
              <FolderGit2 className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Context</span>
            </button>

            {/* Atajo Ctrl+K */}
            <button
              onClick={onOpenPalette}
              className="flex items-center gap-1 px-2 py-1 bg-caos-tinta border border-caos-borde text-caos-tenue hover:text-caos-hueso transition-colors cursor-pointer"
            >
              <span>⌘K</span>
            </button>
          </div>
        </div>

        <div className="console-context-line" aria-live="polite">
          <span>{mode === 'plan' ? 'Plans and answers. No commands run.' : 'May propose commands. Each one runs only after you approve it.'}</span>
          <label className="flex items-center gap-2 cursor-pointer select-none font-mono text-[11px] text-caos-gris" title="Off by default. Applies to this session only and resets when the server restarts.">
            <input
              type="checkbox"
              className="accent-caos-ambar"
              checked={commandsOn}
              disabled={!currentSession}
              onChange={async (e) => {
                if (!currentSession) return
                try {
                  const r = await api.setSessionCommands(currentSession.id, e.target.checked)
                  setCommandsOn(r.commands_enabled)
                  if (!r.commands_enabled) setMode('plan')
                } catch (err: any) {
                  setStatusMsg(err.message || 'Could not change the command switch')
                }
              }}
            />
            <span className={commandsOn ? 'text-caos-ambar' : ''}>shell commands {commandsOn ? 'on for this session' : 'off'}</span>
          </label>
          <span className="context-model"><span className={`connection-dot ${providers.find((provider) => provider.id === 'ollama')?.status === 'online' ? 'online' : ''}`} aria-hidden="true" />{providers.find((provider) => provider.id === 'ollama')?.status === 'online' ? 'Ollama is up' : 'Ollama is not reachable'}</span>
        </div>
        {/* Notificación de estado de acción rápida */}
        {statusMsg && (
          <div className="shrink-0 p-2 bg-caos-tintaElevada border-b border-caos-borde text-caos-hueso text-xs font-mono flex items-center justify-between px-4 animate-in fade-in">
            <span>{statusMsg}</span>
            <button onClick={() => setStatusMsg(null)} className="hover:underline cursor-pointer">
              Close
            </button>
          </div>
        )}

        {/* 2. Feed de Conversación, Streaming y Diálogo de Criterio */}
        <div className="console-feed flex-1 min-h-0 overflow-y-auto p-4 sm:p-6 space-y-5">
          {!currentSession || currentSession.messages.length === 0 ? (
            <div className="console-empty">
              <div className="console-empty-mark"><img src="/art/mark.svg" alt="" /></div>
              <p className="console-empty-voice">El orden emerge del rigor de la evidencia.</p>
              <h1>{currentSession ? 'What are we working on?' : 'Your workspace'}</h1>
              <p className="console-empty-copy">{currentSession ? 'Describe a goal to plan it. Switch commands on for this session if you want the model to propose them.' : 'Start a session to begin.'}</p>
              {!currentSession && <button type="button" onClick={onCreateSession} className="empty-primary">New session <span aria-hidden="true">↗</span></button>}
              {currentSession && <div className="console-starters">
                <button type="button" onClick={() => handleSend('Help me plan a review of this project.')}>Plan a review <span>↗</span></button>
                <button type="button" onClick={() => handleSend('Help me understand how this project is organised.')}>Explore the project <span>↗</span></button>
              </div>}
            </div>
          ) : (
            currentSession.messages.map((msg: MessageItem) => {
              const isUser = msg.role === 'user'

              return (
                <div
                  key={msg.id}
                  className={`conversation-row flex gap-3.5 ${isUser ? 'justify-end' : 'justify-start'}`}
                >
                  {!isUser && (
                    <div className="hidden sm:flex w-8 h-8 rounded-none border border-caos-borde bg-caos-negro items-center justify-center shrink-0 mt-1">
                      <Bot className="w-4 h-4 text-caos-ambar" />
                    </div>
                  )}

                  <div
                    className={`max-w-3xl space-y-3 ${
                      isUser
                        ? 'message-user bg-caos-tintaElevada p-4 text-caos-hueso'
                        : 'message-agent bg-caos-negro p-5 text-caos-hueso w-full'
                    }`}
                  >
                    {!isUser && !msg.run_id && <div className="historic-note">Older message, origin not recorded</div>}
                    {/* Encabezado del mensaje */}
                    <div className="flex items-center justify-between text-xs font-mono border-b border-caos-borde/60 pb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-caos-champan">
                          {isUser ? 'Operador' : `${msg.model || 'Agente'} (${msg.provider || 'local'})`}
                        </span>
                        {!isUser && msg.agent && msg.agent !== 'auto' && (
                          <span className="px-1.5 py-0.2 border border-caos-borde bg-caos-tinta text-[10px] text-caos-champan">
                            rol: {msg.agent}
                          </span>
                        )}
                        {!isUser && msg.tier && (
                          <span className="px-1.5 py-0.2 border border-caos-borde bg-caos-tinta text-[10px] text-caos-tenue">
                            tier: {msg.tier}
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-3 text-caos-tenue text-[11px]">
                        {msg.tokens && (
                          <span>{msg.tokens.toLocaleString("en-US")} tokens</span>
                        )}
                        {msg.cost_saved && msg.cost_saved > 0 && (
                          <span className="text-caos-greenText font-bold">
                            +${msg.cost_saved} ahorrado
                          </span>
                        )}
                        <span>{new Date(msg.timestamp * 1000).toLocaleTimeString([], { hour12: false })}</span>
                      </div>
                    </div>

                    {/* Contenido en Texto */}
                    <div className="text-sm leading-relaxed whitespace-pre-wrap font-sans text-caos-hueso">
                      {msg.content.split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith('**') && part.endsWith('**') ? <strong key={index}>{part.slice(2, -2)}</strong> : part)}
                    </div>

                    {/* Cadena de Herramientas Ejecutadas (Tool Steps) */}
                    {msg.tool_steps && msg.tool_steps.length > 0 && (
                      <ToolStepsView steps={msg.tool_steps} />
                    )}

                    {/* Bloque de Diff de Código (Modo Act) */}
                    {msg.diff && (
                      <div className="space-y-1.5 mt-3">
                        <div className="flex items-center justify-between text-xs font-mono text-caos-champan">
                          <span className="flex items-center gap-1.5">
                            <FileCode className="w-3.5 h-3.5 text-caos-greenText" />
                            <span>Cambios en el Repositorio (Git Diff):</span>
                          </span>
                          <button
                            type="button"
                            onClick={() => copyCode(msg.diff || '', `diff-${msg.id}`)}
                            className="flex items-center gap-1 text-[11px] text-caos-tenue hover:text-caos-hueso transition-colors cursor-pointer"
                          >
                            {copiedIndex === `diff-${msg.id}` ? (
                              <>
                                <Check className="w-3 h-3 text-caos-greenText" />
                                <span className="text-caos-greenText">Copiado</span>
                              </>
                            ) : (
                              <>
                                <Copy className="w-3 h-3" />
                                <span>Copy diff</span>
                              </>
                            )}
                          </button>
                        </div>
                        <pre className="p-3 bg-caos-tinta border border-caos-borde text-xs font-mono overflow-x-auto text-caos-hueso leading-relaxed whitespace-pre">
                          {msg.diff}
                        </pre>
                      </div>
                    )}

                    {/* Bloque de Logs de Bash (Modo Act) */}
                    {msg.bash_logs && (
                      <div className="space-y-1.5 mt-3">
                        <div className="flex items-center justify-between text-xs font-mono text-caos-champan">
                          <span className="flex items-center gap-1.5">
                            <Terminal className="w-3.5 h-3.5 text-caos-ambar" />
                            <span>Terminal output:</span>
                          </span>
                          <button
                            type="button"
                            onClick={() => copyCode(msg.bash_logs || '', `logs-${msg.id}`)}
                            className="flex items-center gap-1 text-[11px] text-caos-tenue hover:text-caos-hueso transition-colors cursor-pointer"
                          >
                            {copiedIndex === `logs-${msg.id}` ? (
                              <>
                                <Check className="w-3 h-3 text-caos-greenText" />
                                <span className="text-caos-greenText">Copiado</span>
                              </>
                            ) : (
                              <>
                                <Copy className="w-3 h-3" />
                                <span>Copy output</span>
                              </>
                            )}
                          </button>
                        </div>
                        <pre className="p-3 bg-caos-tinta border border-caos-borde text-xs font-mono overflow-x-auto text-caos-tenue leading-relaxed whitespace-pre">
                          {msg.bash_logs}
                        </pre>
                      </div>
                    )}

                    {/* Preguntas de Criterio Interactivas (Chips de 1 clic) */}
                    {msg.questions && msg.questions.length > 0 && (
                      <div className="mt-4 pt-3 border-t border-caos-borde space-y-3">
                        <div className="text-xs font-bold text-caos-ambar uppercase tracking-wider flex items-center gap-1.5">
                          <Sparkles className="w-3.5 h-3.5" />
                          <span>Ajuste de Criterio del Operador:</span>
                        </div>

                        {msg.questions.map((q: AlignmentQuestion, qIdx: number) => (
                          <div key={qIdx} className="space-y-2">
                            <div className="text-xs text-caos-gris font-medium">
                              {q.question}
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {q.chips.map((chip: string, cIdx: number) => (
                                <button
                                  key={cIdx}
                                  type="button"
                                  onClick={() => handleSend(chip)}
                                  disabled={isSubmitting}
                                  className="px-3 py-1.5 border border-caos-ambar/70 bg-caos-ambarMuted text-caos-champan text-xs font-medium hover:bg-caos-ambar hover:text-caos-negro transition-all cursor-pointer disabled:opacity-40"
                                >
                                  {chip}
                                </button>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Acción Rápida: Escalar como Encargo al Tablón */}
                    {!isUser && (
                      <div className="pt-2 border-t border-caos-borde/40 flex justify-end">
                        <button
                          type="button"
                          onClick={() => handleConvertToTask(msg.content)}
                          className="text-[11px] font-mono text-caos-tenue hover:text-caos-ambar flex items-center gap-1.5 transition-colors cursor-pointer"
                        >
                          <Layers className="w-3.5 h-3.5" />
                          <span>Turn this answer into a board task</span>
                        </button>
                      </div>
                    )}
                  </div>

                  {isUser && (
                    <div className="hidden sm:flex w-8 h-8 rounded-none border border-caos-borde bg-caos-tinta items-center justify-center shrink-0 mt-1">
                      <User className="w-4 h-4 text-caos-champan" />
                    </div>
                  )}
                </div>
              )
            })
          )}

          {execution && !['completed', 'failed'].includes(execution.status) && (
            <div className="execution-card" role="status">
              <div className="execution-heading"><span className={`execution-indicator ${execution.status !== 'awaiting_approval' ? 'is-running' : ''}`} aria-hidden="true" /><div className="text-caos-champan font-semibold">{execution.status === 'awaiting_approval' ? 'A command is waiting for your decision' : 'Running'}</div></div>
              <div className="text-caos-gris text-xs mt-1 break-all">Ollama · {execution.model} · {execution.workspace}</div>
              <ToolStepsView steps={execution.status === 'awaiting_approval' ? execution.steps.slice(0, -1) : execution.steps} />
              {execution.status === 'awaiting_approval' && <pre className="command-preview mt-3 p-3 bg-caos-tinta text-caos-hueso whitespace-pre-wrap break-all">{execution.steps[execution.steps.length - 1]?.input}</pre>}
              {execution.status === 'awaiting_approval' && <div className="mt-3 flex gap-2">
                <button className="decision-primary" onClick={() => decideCommand(true)}>Run command</button>
                <button className="decision-secondary" onClick={() => decideCommand(false)}>Reject</button>
              </div>}
            </div>
          )}
          {isSubmitting && !execution && (
            <div className="flex gap-3.5 items-center text-xs font-mono text-caos-ambar animate-pulse p-4 bg-caos-negro border border-caos-borde">
              <Bot className="w-4 h-4 animate-spin" />
              <span>
                {mode === 'plan'
                  ? `Thinking with ${selectedModel}…`
                  : `Working in ${activeRepo} with ${selectedModel}…`}
              </span>
            </div>
          )}

          <div ref={feedEndRef} />
        </div>

        {/* 3. Consola de Prompt Dominante (Fija abajo) */}
        <div className="composer-shell border-t border-caos-borde p-3 sm:p-4 bg-caos-negro shrink-0">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              handleSend()
            }}
            className="composer-form space-y-2"
          >
            <div className="composer-box relative border border-caos-borde bg-caos-tinta focus-within:border-caos-ambar transition-colors">
              <textarea
                rows={2}
                ref={composerRef}
                aria-label="Message"
                disabled={!currentSession}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  mode === 'plan'
                    ? 'Describe your goal, or ask a question…'
                    : 'Describe the task…'
                }
                className="w-full max-h-40 overflow-y-auto p-3.5 bg-transparent text-sm text-caos-hueso placeholder:text-caos-tenue focus:outline-none resize-none leading-relaxed"
              />

              <div className="flex items-center justify-between p-2.5 bg-caos-negro border-t border-caos-borde text-xs font-mono text-caos-tenue">
                <div className="flex items-center gap-2">
                  <span className="text-caos-champan font-bold">
                    {mode === 'plan' ? '[plan]' : '[act]'}
                  </span>
                  <span className="hidden sm:inline">•</span>
                  <span className="hidden sm:inline">
                    skill: <strong className="text-caos-hueso">{selectedAgent}</strong>
                  </span>
                  <span className="hidden sm:inline">•</span>
                  <span className="hidden sm:inline">
                    repo: <strong className="text-caos-hueso">{activeRepo}</strong>
                  </span>
                </div>

                <div className="flex items-center gap-3">
                  <span className="hidden sm:inline text-[11px]">
                    Shift+Enter for a new line
                  </span>
                  <button
                    type="submit"
                    disabled={!currentSession || isSubmitting || !input.trim()}
                    className="flex items-center gap-1.5 px-4 py-1.5 bg-caos-ambar text-caos-negro font-bold text-xs uppercase tracking-wider hover:bg-caos-champan disabled:opacity-40 transition-all cursor-pointer shadow-md"
                  >
                    <span>Send</span>
                    <CornerDownLeft className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          </form>
        </div>
      </div>

      {/* Cajón Lateral de Herramientas y Project context */}
      <WorkspaceDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        activeRepo={activeRepo}
        onTaskCreated={onMessageSent}
      />
    </div>
  )
}
