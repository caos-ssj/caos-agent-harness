import React from 'react'
import { BookOpen, Code, FileText, Megaphone, PenLine, Route, Search, ShieldCheck, Sparkles } from 'lucide-react'
import { SkillInfo, Agent } from '../api'
import { PageHead } from './PageHead'

const ICONS: Record<string, React.ElementType> = { coder: Code, 'model-selection': Route, proposals: FileText, qa: ShieldCheck, 'social-content': Megaphone, 'source-research': Search, writer: PenLine }

export const SkillsView: React.FC<{ skills: SkillInfo[]; agents: Agent[] }> = ({ skills }) => (
  <div className="page"><div className="page-inner">
    <PageHead title="Skills" art="memory" lead="A skill is a short instruction file. Naming one on a task makes the agent read it first, so the same rules travel with the work." />
    <div className="card how" style={{ marginTop: 0, marginBottom: 20 }}>
      <BookOpen className="icon" aria-hidden="true" />
      <div>The agent receives a pointer on its standard input, then the task: <code className="mono" style={{ color: 'var(--ink)' }}>Load the skill 'qa' before starting. Task: …</code> The skill sets the tools it may use, the output format and what counts as verified.</div>
    </div>
    <div className="grid">
      {skills.map((s) => {
        const Icon = ICONS[s.name] ?? Sparkles
        return (
          <article key={s.name} className="card skill">
            <header><span className="badge"><Icon className="icon" aria-hidden="true" /></span><h3>{s.name}</h3></header>
            <p>{s.description}</p>
            <footer><span className="chip">skills/{s.name}/SKILL.md{s.local ? ' · local' : ''}</span></footer>
          </article>
        )
      })}
    </div>
    {skills.length === 0 && <div className="empty-card"><img src="/art/policy.svg" alt="" aria-hidden="true" /><p>No skills are installed. They ship in the package under skills/.</p></div>}
  </div></div>
)
