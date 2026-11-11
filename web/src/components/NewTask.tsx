import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { api, Agent, SkillInfo } from '../api'
import { queueName } from '../lib'

export interface NewTaskHandle { focus: () => void }
interface NewTaskProps {
  agents: Agent[]
  skills: SkillInfo[]
  tiers: string[]
  onCreated: (id: number) => void
}

/* One line to add work: what, and who gets it. The router can choose, by what a wrong answer would cost. */
export const NewTask = forwardRef<NewTaskHandle, NewTaskProps>(({ agents, skills, tiers, onCreated }, ref) => {
  const [text, setText] = useState('')
  const [who, setWho] = useState('')
  const [skill, setSkill] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<{ msg: string; err?: boolean } | null>(null)
  const field = useRef<HTMLTextAreaElement>(null)
  useImperativeHandle(ref, () => ({ focus: () => field.current?.focus() }))

  // Until the operator chooses, the default is the first agent this project defines; with none, the router decides.
  const chosen = who || (agents.length ? `agent:${agents[0].name}` : tiers.length ? `tier:${tiers.includes('medium') ? 'medium' : tiers[0]}` : '')

  useEffect(() => {
    const el = field.current
    if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 160)}px` }
  }, [text])

  const submit = async () => {
    if (!text.trim() || busy) return
    setBusy(true)
    setNote(null)
    try {
      const [kind, value] = chosen.split(':')
      const res = await api.addTask({ text: text.trim(), skill: skill || undefined, ...(kind === 'tier' ? { tier: value } : { queue: value }) })
      setText('')
      setNote({ msg: `Added as task ${res.id} for ${queueName(res.queue)}. ${res.why.charAt(0).toUpperCase()}${res.why.slice(1)}.` })
      onCreated(res.id)
    } catch (e: any) {
      setNote({ msg: e.message || 'The board refused the task.', err: true })
    } finally { setBusy(false) }
  }

  return (
    <form className="composer" onSubmit={(e) => { e.preventDefault(); submit() }} aria-label="Add a task">
      <textarea
        ref={field}
        className="composer-field"
        rows={1}
        value={text}
        aria-label="Task"
        placeholder="Add a task: say what you need, in your own words"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
      />
      <div className="composer-bar">
        <select aria-label="Who gets it" value={chosen} onChange={(e) => setWho(e.target.value)}>
          {agents.length > 0 && (
            <optgroup label="An agent from harness.toml">
              {agents.map((a) => <option key={a.name} value={`agent:${a.name}`}>{a.name}{a.system ? ` · ${a.system}` : ''}</option>)}
            </optgroup>
          )}
          <optgroup label="The router decides, by what a wrong answer costs">
            {tiers.map((t) => <option key={t} value={`tier:${t}`}>cost of an error: {t}</option>)}
          </optgroup>
          <optgroup label="Human review">
            <option value="agent:person">a person, no agent</option>
          </optgroup>
        </select>
        <select aria-label="Skill to load first" value={skill} onChange={(e) => setSkill(e.target.value)}>
          <option value="">no skill</option>
          {skills.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </select>
        <span className="grow" />
        <span className="kbd" aria-hidden="true">↵</span>
        <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !text.trim()}>{busy ? 'Adding…' : 'Add task'}</button>
      </div>
      {note && <p className={`composer-note ${note.err ? 'err' : ''}`} role={note.err ? 'alert' : 'status'}>{note.msg}</p>}
    </form>
  )
})
