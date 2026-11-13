import React, { useEffect, useState } from 'react'
import { Ban, Check, CheckCircle2, ChevronDown, ChevronRight, Clock, Copy, FileCode2, FileText, Loader, ShieldAlert, Terminal, Wrench } from '../icons'
import { ToolStep } from '../api'
import { stripAnsi } from '../lib'

interface ToolStepsViewProps {
  steps: ToolStep[]
}

const STEP_ICON: Record<ToolStep['kind'], React.ElementType> = {
  read: FileText,
  write: FileCode2,
  bash: Terminal,
  skill: Wrench,
  memory: Wrench,
}

const STATUS_LABEL: Record<ToolStep['status'], string> = {
  completed: 'completed',
  running: 'running',
  awaiting_approval: 'awaiting you',
  failed: 'failed',
  denied: 'denied',
  expired: 'expired (no answer in time)',
}

export const ToolStepsView: React.FC<ToolStepsViewProps> = ({ steps }) => {
  const hasAwaiting = steps.some((s) => s.status === 'awaiting_approval')
  const [groupOpen, setGroupOpen] = useState(hasAwaiting)
  const [openSteps, setOpenSteps] = useState<Record<number, boolean>>({})
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null)

  useEffect(() => {
    if (hasAwaiting) setGroupOpen(true)
  }, [hasAwaiting])

  if (!steps || steps.length === 0) return null

  const totalMs = steps.reduce((acc, s) => acc + (s.duration_ms ?? 0), 0)
  const hasFailure = steps.some((s) => s.status === 'failed' || s.status === 'denied')
  const isRunning = steps.some((s) => s.status === 'running')
  const hasExpired = steps.some((s) => s.status === 'expired')
  const kinds = Array.from(new Set(steps.map((s) => s.kind))).join(' · ')
  const summaryState = hasAwaiting ? 'awaiting' : isRunning ? 'running' : hasFailure ? 'failed' : hasExpired ? 'expired' : 'done'
  const summaryText = hasAwaiting
    ? 'Awaiting your approval'
    : isRunning
      ? 'Executing step'
      : hasFailure
        ? 'Finished with halt or failure'
        : hasExpired
          ? 'An approval expired unanswered'
          : 'Completed cleanly'

  const toggleStep = (i: number) => setOpenSteps((cur) => ({ ...cur, [i]: !cur[i] }))
  const copyOut = (i: number, text: string, e: React.MouseEvent) => {
    e.stopPropagation()
    navigator.clipboard.writeText(text)
    setCopiedIdx(i)
    window.setTimeout(() => setCopiedIdx((c) => (c === i ? null : c)), 1400)
  }

  return (
    <div className="tools-wrap">
      <button
        type="button"
        className={`tool-summary ${summaryState}`}
        aria-expanded={groupOpen}
        onClick={() => setGroupOpen((o) => !o)}
      >
        {groupOpen ? <ChevronDown className="icon" style={{ width: 15, height: 15 }} aria-hidden="true" /> : <ChevronRight className="icon" style={{ width: 15, height: 15 }} aria-hidden="true" />}
        <span className="tool-summary-main">
          <b>{steps.length} {steps.length === 1 ? 'tool step' : 'tool steps'}</b>
          <span className="mono">{kinds}</span>
          {totalMs > 0 && <span className="mono">{totalMs} ms</span>}
        </span>
        <span className={`tool-pill ${summaryState}`}>
          {summaryState === 'awaiting' && <ShieldAlert className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />}
          {summaryState === 'running' && <Loader className="icon spin" style={{ width: 13, height: 13 }} aria-hidden="true" />}
          {summaryState === 'done' && <CheckCircle2 className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />}
          {summaryState === 'failed' && <Ban className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />}
          {summaryState === 'expired' && <Clock className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />}
          {summaryText}
        </span>
      </button>

      {groupOpen && (
        <div className="tool-list">
          {steps.map((step, i) => {
            const Icon = STEP_ICON[step.kind] ?? Wrench
            const isOpen = !!openSteps[i] || step.status === 'awaiting_approval'
            return (
              <div key={i} className={`tool-item ${step.status}`}>
                <button
                  type="button"
                  className="tool-item-head"
                  aria-expanded={isOpen}
                  onClick={() => toggleStep(i)}
                >
                  <span className="tool-item-left">
                    {isOpen ? <ChevronDown className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" /> : <ChevronRight className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />}
                    <Icon className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />
                    <b>{step.name}</b>
                    {step.input && <code className="tool-cmd-preview">{step.input}</code>}
                  </span>
                  <span className="tool-item-right">
                    {typeof step.exit_code === 'number' && <span className="chip">exit {step.exit_code}</span>}
                    {step.duration_ms !== undefined && <span className="tool-ms"><Clock className="icon" style={{ width: 12, height: 12 }} aria-hidden="true" />{step.duration_ms}ms</span>}
                    <span className={`tool-st ${step.status}`}>{step.status === 'running' && <Loader className="icon spin" style={{ width: 12, height: 12 }} aria-hidden="true" />}{STATUS_LABEL[step.status] ?? step.status}</span>
                  </span>
                </button>
                {isOpen && (
                  <div className="tool-details">
                    {step.input && (
                      <div className="tool-block">
                        <div className="tool-block-label">Command / input</div>
                        <pre>{stripAnsi(step.kind === 'bash' ? `$ ${step.input}` : step.input)}</pre>
                      </div>
                    )}
                    {step.output && (
                      <div className="tool-block">
                        <div className="tool-block-head">
                          <span className="tool-block-label">Output</span>
                          <button type="button" className="btn btn-quiet btn-sm" onClick={(e) => copyOut(i, step.output!, e)}>
                            {copiedIdx === i ? <Check className="icon" style={{ width: 12, height: 12 }} aria-hidden="true" /> : <Copy className="icon" style={{ width: 12, height: 12 }} aria-hidden="true" />}
                            {copiedIdx === i ? 'Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre>{stripAnsi(step.output)}</pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
