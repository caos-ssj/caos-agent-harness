import { TaskDetail } from './api'
import { clock, pad, queueName, routeText, stateLabel } from './lib'

/* A task's whole life as a file you can keep or attach: what was asked, who got it and why, what came back, the verdict
   and the trace. Built in the browser from what the dashboard already shows; nothing is sent anywhere. */
function save(name: string, type: string, body: string) {
  const url = URL.createObjectURL(new Blob([body], { type }))
  const a = document.createElement('a')
  a.href = url; a.download = name
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function exportMarkdown(d: TaskDetail) {
  const lines = [
    `# Task ${pad(d.id)}: ${d.text}`, '',
    `State: ${stateLabel(d)} · queue: ${queueName(d.queue)}${d.skill ? ` · skill: ${d.skill}` : ''} · ${d.router ? `router: ${routeText(d)}` : 'queue chosen by the operator'}`, '',
    '## Delivered', '', d.result != null ? '```\n' + (d.result || '(the agent printed nothing)') + '\n```' : '(nothing delivered)', '',
    ...(d.review_note ? [`Reviewer’s note: ${d.review_note}`, ''] : []),
    '## Trace', '', '| time | source | event | reason |', '|---|---|---|---|',
    ...d.timeline.map((e) => `| ${clock(e.ts)} | ${e.source} | ${[e.status || e.kind, e.name].filter(Boolean).join(' · ')} | ${e.reason ?? ''} |`),
    '', `Exported from caos-agent-harness on ${new Date().toISOString().slice(0, 10)}.`, '',
  ]
  save(`task-${pad(d.id)}.md`, 'text/markdown', lines.join('\n'))
}

export function exportJson(d: TaskDetail) {
  save(`task-${pad(d.id)}.json`, 'application/json', JSON.stringify({ id: d.id, text: d.text, state: d.state, queue: d.queue, skill: d.skill, router: d.router ?? null, review: d.review, review_note: d.review_note, result: d.result, trace: d.timeline }, null, 2))
}
