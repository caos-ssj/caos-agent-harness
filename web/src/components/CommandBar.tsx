import React, { useState } from 'react'
import { api, Agent, SkillInfo } from '../api'
import { PlusCircle, Shield, Bot, CheckCircle2 } from 'lucide-react'

interface CommandBarProps {
  agents: Agent[]
  skills: SkillInfo[]
  tiers: string[]
  onTaskCreated: () => void
}

export const CommandBar: React.FC<CommandBarProps> = ({
  agents,
  skills,
  tiers,
  onTaskCreated,
}) => {
  const [text, setText] = useState('')
  const [routeMode, setRouteMode] = useState<'tier' | 'agent'>('agent')
  const [tier, setTier] = useState<string>('medium')
  const [selectedAgent, setSelectedAgent] = useState<string>('qwen')
  const [selectedSkill, setSelectedSkill] = useState<string>('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [feedback, setFeedback] = useState<{ msg: string; isError?: boolean } | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!text.trim() || isSubmitting) return

    setIsSubmitting(true)
    setFeedback(null)

    try {
      const payload: { text: string; queue?: string; skill?: string; tier?: string } = {
        text: text.trim(),
      }

      if (routeMode === 'tier') {
        payload.tier = tier
      } else {
        if (selectedAgent) payload.queue = selectedAgent
      }

      if (selectedSkill) {
        payload.skill = selectedSkill
      }

      const res = await api.addTask(payload)
      setText('')
      setFeedback({
        msg: `Task ${res.id} added to the queue of ${res.queue === 'person' ? 'a person' : res.queue}. ${res.why}`,
      })
      onTaskCreated()
      setTimeout(() => setFeedback(null), 5000)
    } catch (err: any) {
      setFeedback({
        msg: err.message || 'The board refused the task',
        isError: true,
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="border border-caos-borde bg-caos-tinta p-4 sm:p-5 shadow-xl">
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Título y descripción clara */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-caos-borde pb-3">
          <div className="flex items-center gap-2.5">
            <PlusCircle className="w-5 h-5 text-caos-ambar" />
            <h2 className="text-base font-bold text-caos-hueso tracking-wide">
              New task
            </h2>
          </div>
          <span className="text-xs text-caos-tenue">
            Say what you need. It goes to a queue and stays open until you review what comes back.
          </span>
        </div>

        {/* Campo de texto principal con alta legibilidad */}
        <div>
          <label className="block text-xs font-semibold text-caos-gris uppercase tracking-wider mb-1.5">
            The task
          </label>
          <textarea
            required
            rows={3}
            placeholder="For example: check whether the memory module reconnects to the MCP server after a failure, and report what you find."
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="w-full p-3.5 bg-caos-negro border border-caos-borde text-caos-hueso text-sm leading-relaxed placeholder:text-caos-tenue focus:border-caos-ambar focus:outline-none transition-colors"
          />
        </div>

        {/* Selectores de Proveedor, Modelo y Habilidad */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* Selector de Modo de Enrutamiento / Modelo */}
          <div className="space-y-1">
            <label className="block text-xs font-semibold text-caos-gris uppercase tracking-wider flex items-center gap-1.5">
              <Bot className="w-3.5 h-3.5 text-caos-ambar" />
              <span>Who gets it</span>
            </label>
            <select
              value={routeMode === 'tier' ? `tier:${tier}` : `agent:${selectedAgent}`}
              onChange={(e) => {
                const val = e.target.value
                if (val.startsWith('tier:')) {
                  setRouteMode('tier')
                  setTier(val.replace('tier:', ''))
                } else {
                  setRouteMode('agent')
                  setSelectedAgent(val.replace('agent:', ''))
                }
              }}
              className="w-full p-2.5 bg-caos-negro border border-caos-borde text-caos-hueso text-xs focus:border-caos-ambar focus:outline-none cursor-pointer"
            >
              <optgroup label="An agent from harness.toml">
                {agents.map((a) => (
                  <option key={a.name} value={`agent:${a.name}`}>
                    {a.name === 'qwen'
                      ? 'qwen · qwen2.5:7b'
                      : a.name === 'llama'
                      ? 'llama · llama3.2:3b'
                      : a.name === 'echo'
                      ? 'echo · returns the task as is, for testing'
                      : `@${a.name} (${a.system || 'local'})`}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Let the router decide, by what a wrong answer costs">
                {tiers.map((t) => (
                  <option key={t} value={`tier:${t}`}>
                    Cost of an error: {t}{' '}
                    {t === 'critical' ? '(a person, unless a measured system reaches the bar)' : '(cheapest measured system that qualifies)'}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Mesa Humana">
                <option value="agent:person">
                  A person (no agent)
                </option>
              </optgroup>
            </select>
          </div>

          {/* Selector de Habilidad de Rol (Skill) */}
          <div className="space-y-1">
            <label className="block text-xs font-semibold text-caos-gris uppercase tracking-wider flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-caos-champan" />
              <span>Skill to load first (optional)</span>
            </label>
            <select
              value={selectedSkill}
              onChange={(e) => setSelectedSkill(e.target.value)}
              className="w-full p-2.5 bg-caos-negro border border-caos-borde text-caos-hueso text-xs focus:border-caos-ambar focus:outline-none cursor-pointer"
            >
              <option value="">No skill</option>
              {skills.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}{s.local ? ' · local' : ''} — {s.description.slice(0, 60)}…
                </option>
              ))}
            </select>
          </div>

          {/* Botón de Despacho */}
          <div className="flex items-end">
            <button
              type="submit"
              disabled={isSubmitting || !text.trim()}
              className="w-full py-2.5 px-4 bg-caos-ambar text-caos-negro text-xs uppercase font-bold tracking-wider hover:bg-caos-champan disabled:opacity-40 transition-all flex items-center justify-center gap-2 shadow-md cursor-pointer"
            >
              <PlusCircle className="w-4 h-4" />
              <span>{isSubmitting ? 'Adding…' : 'Add to the board'}</span>
            </button>
          </div>
        </div>

        {/* Mensaje de retroalimentación inmediato */}
        {feedback && (
          <div
            className={`p-3 border text-xs flex items-center gap-2 ${
              feedback.isError
                ? 'border-caos-redText bg-caos-redMuted text-caos-redText'
                : 'border-caos-greenText bg-caos-greenMuted text-caos-greenText'
            }`}
          >
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>{feedback.msg}</span>
          </div>
        )}
      </form>
    </div>
  )
}
