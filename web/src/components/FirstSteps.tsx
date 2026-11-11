import React from 'react'
import { Check } from 'lucide-react'
import { Agent, Task } from '../api'

interface FirstStepsProps {
  tasks: Task[]
  agents: Agent[]
  runnable: number
  running: boolean
  onAdd: () => void
  onRun: () => void
  onDismiss?: () => void
}

/* The way in. Each step is checked off by what the board actually holds, not by what was clicked. */
export const FirstSteps: React.FC<FirstStepsProps> = ({ tasks, agents, runnable, running, onAdd, onRun, onDismiss }) => {
  const hasTask = tasks.length > 0
  const delivered = tasks.some((t) => t.delivered)
  const reviewed = tasks.some((t) => t.review)
  const first = agents[0]?.name ?? 'echo'
  const cls = (done: boolean, now: boolean) => (done ? 'done' : now ? 'now' : 'wait')
  return (
    <section className="steps" aria-labelledby="steps-title">
      {!hasTask && <img className="steps-plate" src="/art/board.svg" alt="" aria-hidden="true" />}
      <div className="steps-head">
        <h3 id="steps-title">{hasTask ? 'Where you are' : 'Start here'}</h3>
        {onDismiss && <button type="button" onClick={onDismiss}>Hide</button>}
      </div>
      <p className="steps-lead">
        {hasTask ? 'The board is working; two steps are left before the first task closes.' : 'The board is empty. A task goes in, an agent runs it, and nothing closes until you give a verdict.'}
      </p>
      <ol>
        <li className={cls(hasTask, !hasTask)}>
          <span className="step-mark" aria-hidden="true">{hasTask ? <Check size={15} strokeWidth={2} /> : 1}</span>
          <span className="steps-title">Add a task</span>
          <p className="steps-text">Say what you need and who gets it: an agent, or the router, by what a wrong answer would cost. From a terminal: <code>caos-harness task add "…" --queue {first}</code></p>
          {!hasTask && <button type="button" className="btn btn-primary btn-sm" onClick={onAdd}>Write a task</button>}
        </li>
        <li className={cls(delivered, hasTask && !delivered)}>
          <span className="step-mark" aria-hidden="true">{delivered ? <Check size={15} strokeWidth={2} /> : 2}</span>
          <span className="steps-title">Run it</span>
          <p className="steps-text">Sends what is pending to its agent and keeps whatever the agent prints. From a terminal: <code>caos-harness run</code></p>
          {hasTask && !delivered && <button type="button" className="btn btn-primary btn-sm" onClick={onRun} disabled={running || runnable === 0}>{running ? 'Running…' : runnable ? `Run ${runnable}` : 'Nothing to run'}</button>}
        </li>
        <li className={cls(reviewed, delivered && !reviewed)}>
          <span className="step-mark" aria-hidden="true">{reviewed ? <Check size={15} strokeWidth={2} /> : 3}</span>
          <span className="steps-title">Review what came back</span>
          <p className="steps-text">Open the task on the right, read the delivery and its trace, then accept it, return it with a note, or ask for evidence. From a terminal: <code>caos-harness review 1 ok "ran the tests"</code></p>
        </li>
      </ol>
    </section>
  )
}
