import React, { useEffect, useState } from 'react'
import {
  X,
  FolderGit2,
  GitBranch,
  Shield,
  Layers,
  Check,
  Send,
  AlertCircle,
} from 'lucide-react'
import { api, WorkspaceStatus } from '../api'

interface WorkspaceDrawerProps {
  isOpen: boolean
  onClose: () => void
  activeRepo: string
  onTaskCreated?: () => void
}

export const WorkspaceDrawer: React.FC<WorkspaceDrawerProps> = ({
  isOpen,
  onClose,
  activeRepo,
  onTaskCreated,
}) => {
  const [status, setStatus] = useState<WorkspaceStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [taskText, setTaskText] = useState('')
  const [taskTier, setTaskTier] = useState('medium')
  const [submittingTask, setSubmittingTask] = useState(false)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const loadStatus = () => {
    setLoading(true)
    api
      .getWorkspaceStatus()
      .then((res) => {
        setStatus(res)
        setLoading(false)
      })
      .catch((err) => {
        console.error(err)
        setLoading(false)
      })
  }

  useEffect(() => {
    if (isOpen) {
      loadStatus()
    }
  }, [isOpen, activeRepo])

  const handleConvert = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!taskText.trim()) return

    setSubmittingTask(true)
    setErrorMsg(null)
    setSuccessMsg(null)

    try {
      const res = await api.convertToTask({
        text: taskText.trim(),
        tier: taskTier,
      })
      setSuccessMsg(`Task ${res.id} added to the queue of ${res.queue}`)
      setTaskText('')
      if (onTaskCreated) onTaskCreated()
      loadStatus()
    } catch (err: any) {
      setErrorMsg(err.message || 'The board refused the task')
    } finally {
      setSubmittingTask(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="absolute right-0 top-0 bottom-0 w-[min(20rem,100%)] lg:relative lg:w-80 shrink-0 border-l border-caos-borde bg-caos-tinta flex flex-col h-full min-h-0 shadow-2xl z-20 work-surface">
      {/* Cabecera */}
      <div className="shrink-0 p-3.5 border-b border-caos-borde bg-caos-negro flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FolderGit2 className="w-4 h-4 text-caos-ambar" />
          <h4 className="font-mono text-xs font-bold text-caos-hueso uppercase tracking-wider">
            Project context
          </h4>
        </div>
        <button
          onClick={onClose}
          aria-label="Close context"
          className="p-1 text-caos-tenue hover:text-caos-hueso border border-caos-borde bg-caos-tinta transition-colors cursor-pointer"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Cuerpo scrolleable */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-5 text-xs font-mono">
        {loading && (
          <div className="text-caos-tenue text-center py-6">
            Inspeccionando espacio de trabajo...
          </div>
        )}

        {status && (
          <>
            {/* 1. Datos Git y Directorio */}
            <div className="p-3 bg-caos-negro border border-caos-borde space-y-2">
              <div className="text-[11px] text-caos-tenue uppercase font-bold flex items-center justify-between">
                <span>Repositorio Activo</span>
                <span className="text-caos-greenText">Enlace Local</span>
              </div>
              <div className="text-sm font-bold text-caos-hueso truncate">
                {status.repo}
              </div>
              <div className="flex items-center gap-2 text-[11px] text-caos-champan">
                <GitBranch className="w-3.5 h-3.5 text-caos-ambar" />
                <span>rama: {status.branch}</span>
              </div>
            </div>

            {/* 2. Archivos Modificados / Git Status */}
            <div>
              <div className="text-[11px] font-bold text-caos-tenue uppercase tracking-wider mb-2 flex items-center justify-between">
                <span>Archivos Tocados ({status.dirty_files.length})</span>
                {status.dirty_files.length > 0 && (
                  <span className="text-caos-ambar font-bold">Uncommitted</span>
                )}
              </div>

              {status.dirty_files.length === 0 ? (
                <div className="p-3 bg-caos-negro border border-caos-borde text-[11px] text-caos-tenue text-center">
                  Working tree clean
                </div>
              ) : (
                <div className="border border-caos-borde bg-caos-negro divide-y divide-caos-borde max-h-40 overflow-y-auto text-[11px]">
                  {status.dirty_files.map((file, idx) => (
                    <div key={idx} className="p-2 text-caos-gris truncate hover:text-caos-hueso">
                      {file}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* 3. Habilidades y Agentes Disponibles */}
            <div>
              <div className="text-[11px] font-bold text-caos-tenue uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-caos-blueText" />
                <span>Skills ({status.skills.length})</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {status.skills.slice(0, 6).map((skill, idx) => (
                  <span
                    key={idx}
                    className="px-2 py-0.5 border border-caos-borde bg-caos-negro text-[10px] text-caos-champan font-mono"
                  >
                    {skill}
                  </span>
                ))}
              </div>
            </div>

            {/* 4. Convertir Instrucción en Encargo Formal (Handoff a Mesa de Trabajo) */}
            <div className="p-3.5 border border-caos-borde bg-caos-negro space-y-3">
              <div className="text-[11px] font-bold text-caos-ambar uppercase tracking-wider flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5" />
                <span>Add a task to the board</span>
              </div>

              <form onSubmit={handleConvert} className="space-y-2.5">
                <textarea
                  rows={2}
                  value={taskText}
                  onChange={(e) => setTaskText(e.target.value)}
                  placeholder="What needs doing, and reviewing…"
                  className="w-full p-2 bg-caos-tinta border border-caos-borde text-xs text-caos-hueso placeholder:text-caos-tenue focus:outline-none resize-none"
                />

                <div className="flex items-center gap-2">
                  <select
                    value={taskTier}
                    onChange={(e) => setTaskTier(e.target.value)}
                    className="bg-caos-tinta border border-caos-borde text-xs text-caos-hueso p-1.5 focus:outline-none flex-1 cursor-pointer"
                  >
                    <option value="low">Cost of an error: low</option>
                    <option value="medium">Cost of an error: medium</option>
                    <option value="high">Tier High (Razonamiento CoT)</option>
                    <option value="critical">Cost of an error: critical</option>
                  </select>

                  <button
                    type="submit"
                    disabled={submittingTask || !taskText.trim()}
                    className="px-3 py-1.5 border border-caos-ambar bg-caos-ambar text-caos-negro font-bold text-xs uppercase hover:bg-caos-champan transition-all cursor-pointer disabled:opacity-40"
                  >
                    {submittingTask ? '...' : <Send className="w-3.5 h-3.5" />}
                  </button>
                </div>

                {successMsg && (
                  <div className="p-2 border border-caos-greenText/40 bg-caos-greenMuted text-caos-greenText text-[11px] flex items-center gap-1.5">
                    <Check className="w-3.5 h-3.5 shrink-0" />
                    <span>{successMsg}</span>
                  </div>
                )}

                {errorMsg && (
                  <div className="p-2 border border-caos-redText/40 bg-caos-redMuted text-caos-redText text-[11px] flex items-center gap-1.5">
                    <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                    <span>{errorMsg}</span>
                  </div>
                )}
              </form>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
