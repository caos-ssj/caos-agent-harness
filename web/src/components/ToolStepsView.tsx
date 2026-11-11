import React, { useState } from 'react'
import {
  Terminal,
  FileCode,
  BookOpen,
  Cpu,
  Database,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  Clock,
  AlertCircle,
  Copy,
  Check,
} from 'lucide-react'
import { ToolStep } from '../api'

interface ToolStepsViewProps {
  steps: ToolStep[]
}

export const ToolStepsView: React.FC<ToolStepsViewProps> = ({ steps }) => {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)

  if (!steps || steps.length === 0) return null

  const getStepIcon = (kind: ToolStep['kind']) => {
    switch (kind) {
      case 'bash':
        return <Terminal className="w-3.5 h-3.5 text-caos-greenText" />
      case 'write':
        return <FileCode className="w-3.5 h-3.5 text-caos-ambar" />
      case 'read':
        return <BookOpen className="w-3.5 h-3.5 text-caos-champan" />
      case 'skill':
        return <Cpu className="w-3.5 h-3.5 text-caos-blueText" />
      case 'memory':
        return <Database className="w-3.5 h-3.5 text-purple-400" />
      default:
        return <Terminal className="w-3.5 h-3.5 text-caos-gris" />
    }
  }

  const handleCopy = (text: string, idx: number) => {
    navigator.clipboard.writeText(text)
    setCopiedIndex(idx)
    setTimeout(() => setCopiedIndex(null), 1800)
  }

  return (
    <div className="my-3 space-y-1.5 font-mono text-xs">
      <div className="text-[11px] font-bold text-caos-tenue uppercase tracking-wider flex items-center gap-1.5 mb-1.5">
        <span>Commands ({steps.length}):</span>
      </div>

      <div className="tool-list border border-caos-borde bg-caos-negro divide-y divide-caos-borde">
        {steps.map((step, idx) => {
          const isExpanded = expandedIndex === idx

          return (
            <div key={idx} className="transition-colors">
              <button
                type="button"
                aria-expanded={isExpanded}
                onClick={() => setExpandedIndex(isExpanded ? null : idx)}
                className="w-full p-2.5 flex items-center justify-between text-left hover:bg-caos-tinta cursor-pointer transition-colors"
              >
                <div className="flex items-center gap-2 min-w-0">
                  {getStepIcon(step.kind)}
                  <span className="font-bold text-caos-hueso truncate">
                    {step.name}
                  </span>
                  {step.input && (
                    <span className="text-caos-tenue text-[11px] truncate max-w-xs hidden sm:inline">
                      {step.input}
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-3 shrink-0 text-[11px]">
                  {step.duration_ms && (
                    <span className="text-caos-tenue">
                      {step.duration_ms > 1000
                        ? `${(step.duration_ms / 1000).toFixed(2)}s`
                        : `${step.duration_ms}ms`}
                    </span>
                  )}

                  {step.status === 'completed' && (
                    <span className="flex items-center gap-1 text-caos-greenText">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span className="hidden md:inline">completado</span>
                    </span>
                  )}

                  {step.status === 'awaiting_approval' && <span className="text-caos-champan">waiting for your approval</span>}
                  {step.status === 'denied' && <span className="text-caos-gris">rechazado</span>}
                  {step.status === 'running' && (
                    <span className="flex items-center gap-1 text-caos-ambar animate-pulse">
                      <Clock className="w-3.5 h-3.5 animate-spin" />
                      <span>ejecutando</span>
                    </span>
                  )}

                  {step.status === 'failed' && (
                    <span className="flex items-center gap-1 text-caos-redText">
                      <AlertCircle className="w-3.5 h-3.5" />
                      <span>failed</span>
                    </span>
                  )}

                  {isExpanded ? (
                    <ChevronDown className="w-3.5 h-3.5 text-caos-tenue" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5 text-caos-tenue" />
                  )}
                </div>
              </button>

              {isExpanded && (
                <div className="tool-details p-3 bg-caos-tinta/80 border-t border-caos-borde/70 space-y-2 text-[11px]">
                  {step.input && (
                    <div>
                      <div className="text-caos-champan font-bold uppercase text-[10px] mb-1">
                        Command:
                      </div>
                      <div className="p-2 bg-caos-negro border border-caos-borde text-caos-gris font-mono whitespace-pre-wrap break-all">
                        {step.input}
                      </div>
                    </div>
                  )}

                  {step.output && (
                    <div>
                      <div className="flex items-center justify-between text-caos-champan font-bold uppercase text-[10px] mb-1">
                        <span>Output:</span>
                        <button
                          type="button"
                          onClick={() => handleCopy(step.output || '', idx)}
                          className="flex items-center gap-1 text-caos-tenue hover:text-caos-hueso transition-colors cursor-pointer"
                        >
                          {copiedIndex === idx ? (
                            <>
                              <Check className="w-3 h-3 text-caos-greenText" />
                              <span className="text-caos-greenText">Copiado</span>
                            </>
                          ) : (
                            <>
                              <Copy className="w-3 h-3" />
                              <span>Copy</span>
                            </>
                          )}
                        </button>
                      </div>
                      <pre className="p-2.5 bg-caos-negro border border-caos-borde text-caos-hueso font-mono overflow-x-auto whitespace-pre-wrap break-all max-h-48 overflow-y-auto leading-relaxed">
                        {step.output}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
