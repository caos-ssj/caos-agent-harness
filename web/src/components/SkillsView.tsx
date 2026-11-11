import React from 'react'
import { SkillInfo, Agent } from '../api'
import { Bot, Terminal, Code2 } from 'lucide-react'

interface SkillsViewProps {
  skills: SkillInfo[]
  agents: Agent[]
}

export const SkillsView: React.FC<SkillsViewProps> = ({ skills, agents }) => {
  return (
    <div className="space-y-8">
      {/* Overview Card */}
      <div className="border border-caos-borde bg-caos-tinta p-6">
        <div className="flex items-center gap-3 border-b border-caos-borde pb-4">
          <img src="/art/policy.svg" alt="Skills" className="w-10 h-10 opacity-80" />
          <div>
            <h2 className="font-brand text-2xl text-caos-hueso tracking-wide">
              Agent Roles & Skills
            </h2>
            <p className="font-serif text-sm text-caos-champan">
              Public system roles loaded before dispatching tasks: determinism, rules, and bounded behavior.
            </p>
          </div>
        </div>

        <div className="mt-4 font-serif text-xs text-caos-tenue leading-relaxed">
          The harness enforces that each task dispatch can inject a skill pointer (e.g.{' '}
          <code className="font-mono text-caos-ambar">Load the skill 'qa' before starting. Task: ...</code>).
          This ensures the agent runs with strict tool allow-lists, output formats, and verification standards.
        </div>
      </div>

      {/* Skills Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {skills.map((skill) => (
          <div key={skill.name} className="border border-caos-borde bg-caos-tinta p-5 space-y-3">
            <div className="flex items-center justify-between border-b border-caos-borde pb-2">
              <div className="flex items-center gap-2">
                <Code2 className="w-4 h-4 text-caos-ambar" />
                <span className="font-mono text-sm font-bold text-caos-hueso uppercase">
                  {skill.name}
                </span>
              </div>
              <span className="font-mono text-[10px] uppercase px-2 py-0.5 border border-caos-borde text-caos-tenue bg-caos-negro">
                skills/{skill.name}/SKILL.md
              </span>
            </div>

            <p className="font-serif text-sm text-caos-champan/90 leading-relaxed">
              {skill.description}
            </p>

            <div className="pt-2 font-mono text-[11px] text-caos-tenue flex items-center gap-1.5">
              <Terminal className="w-3.5 h-3.5 text-caos-tenue" />
              <span>Pointer injected on stdin during dispatch</span>
            </div>
          </div>
        ))}
      </div>

      {/* Configured Agents Section */}
      <div className="border border-caos-borde bg-caos-tinta">
        <div className="px-6 py-4 border-b border-caos-borde bg-caos-negro flex items-center justify-between">
          <div className="font-mono text-xs uppercase tracking-wider text-caos-hueso font-semibold flex items-center gap-2">
            <Bot className="w-4 h-4 text-caos-ambar" />
            <span>Registered Harness Agents (`harness.toml`)</span>
          </div>
          <span className="font-mono text-[11px] text-caos-tenue">
            Standard dispatcher executes commands on loopback/CLI
          </span>
        </div>

        <div className="divide-y divide-caos-borde">
          {agents.map((agent) => (
            <div key={agent.name} className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-caos-tintaElevada transition-colors">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-bold text-caos-ambar">
                    @{agent.name}
                  </span>
                  {agent.system && (
                    <span className="font-mono text-[10px] px-1.5 py-0.5 border border-caos-borde text-caos-champan bg-caos-negro">
                      system: {agent.system}
                    </span>
                  )}
                  <span className="font-mono text-[11px] text-caos-tenue">
                    timeout: {agent.timeout}s
                  </span>
                </div>
                <div className="font-mono text-xs text-caos-gris bg-caos-negro px-2.5 py-1 border border-caos-borde inline-block">
                  $ {agent.command}
                </div>
              </div>

              <div className="flex items-center gap-4 font-mono text-xs shrink-0">
                <div>
                  <span className="text-caos-tenue">Pending: </span>
                  <span className="text-caos-hueso font-bold">{agent.pending}</span>
                </div>
                <div>
                  <span className="text-caos-tenue">Working: </span>
                  <span className="text-caos-blueText font-bold">{agent.working}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
