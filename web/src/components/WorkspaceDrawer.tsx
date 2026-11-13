import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Eye, FileCode2, FilePlus2, FolderGit2, GitBranch, ListChecks, RefreshCw, Trash2, X } from '../icons'
import { api, ToolStep, WorkspaceDiffResponse, WorkspaceStatus } from '../api'
import { ToolStepsView } from './ToolStepsView'
import { WorktreePanel } from './WorktreePanel'
import { DiffViewer } from './DiffViewer'
import { CaosTargetGlyph } from './CaosArt'
import { ConfirmButton } from './ConfirmButton'
import { useDialog } from '../hooks'
import { onTabKeys } from '../lib'

type InspectorTab = 'files' | 'diff' | 'preview' | 'steps' | 'worktree'

interface WorkspaceDrawerProps {
  isOpen: boolean
  /** The inspector is playing its exit: it is still drawn, but no longer takes clicks or the keyboard. */
  leaving?: boolean
  /** It covers the page (a phone): a modal sheet that keeps Tab inside. */
  modal?: boolean
  onClose: () => void
  activeRepo: string
  worktreeKey?: string | null
  initialTab?: InspectorTab
  refreshKey?: number
  onAttachFile?: (relPath: string) => void
  onCiteDiff?: (snippet: string) => void
  onWorktreeDiscarded?: () => void
  onTaskCreated?: () => void
  /** What the current run is doing: plan reads and act changes, shown here as they happen. */
  steps?: ToolStep[]
  /** The inspector's `+` on a diff line writes a draft that is sent together with the others. */
  onSendDrafts?: (text: string) => void
}

/* Contextual right dock: workspace files & @attach, unified diff with 1A sage/coral + line cite, and sandboxed HTML/SVG preview. */
export const WorkspaceDrawer: React.FC<WorkspaceDrawerProps> = ({
  isOpen,
  leaving = false,
  modal = false,
  onClose,
  activeRepo,
  worktreeKey,
  initialTab = 'files',
  refreshKey = 0,
  onAttachFile,
  onCiteDiff,
  onWorktreeDiscarded,
  steps = [],
  onSendDrafts,
}) => {
  const [tab, setTab] = useState<InspectorTab>(initialTab)
  const [status, setStatus] = useState<WorkspaceStatus | null>(null)
  const [diffData, setDiffData] = useState<WorkspaceDiffResponse | null>(null)
  const [files, setFiles] = useState<string[]>([])
  const [fileQuery, setFileQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const askedForPreview = useRef(false)     // the Preview tab was opened by hand, so it stays even when it has nothing to show
  const ref = useDialog<HTMLElement>(isOpen && !leaving, onClose, { modal, focus: modal, escapeAnywhere: true, initial: '[role="tab"][aria-selected="true"]' })

  useEffect(() => {
    setTab(initialTab)
    askedForPreview.current = false
  }, [initialTab, refreshKey])

  const reload = useCallback(async () => {
    setBusy(true)
    try {
      const [s, d, f] = await Promise.all([
        api.getWorkspaceStatus(),
        api.getWorkspaceDiff(worktreeKey || undefined),
        api.getWorkspaceFiles(),
      ])
      setStatus(s)
      setDiffData(d)
      setFiles(f.files || [])
      setError(null)
    } catch (e: any) {
      setError(e.message || 'Could not inspect workspace')
    } finally {
      setBusy(false)
    }
  }, [worktreeKey])

  useEffect(() => {
    if (isOpen) reload()
  }, [isOpen, activeRepo, worktreeKey, refreshKey, reload])

  // Opened on Preview by the harness, but there is nothing to preview: show what did change (or the files) instead of an empty panel.
  useEffect(() => {
    if (tab === 'preview' && diffData && !diffData.preview && !askedForPreview.current) setTab(diffData.files?.length ? 'diff' : 'files')
  }, [tab, diffData])

  if (!isOpen) return null

  const changedCount = diffData?.files?.length ?? status?.dirty_files?.length ?? 0
  const filteredFiles = files.filter((p) => !fileQuery.trim() || p.toLowerCase().includes(fileQuery.trim().toLowerCase())).slice(0, 80)

  const handleDiscardWt = async () => {
    if (!worktreeKey || busy) return
    setBusy(true)
    try {
      await api.discardWorktree(worktreeKey)
      await reload()
      onWorktreeDiscarded?.()
    } catch (e: any) {
      setError(e.message || 'Could not discard worktree')
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="ctx" ref={ref} data-leaving={leaving ? '' : undefined} role="dialog" aria-modal={modal ? 'true' : 'false'} aria-label="Workspace inspector">
      <div className="ctx-head">
        <h2>Inspector</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <button type="button" className="btn btn-quiet btn-sm btn-icon" onClick={reload} disabled={busy} aria-label="Refresh inspector" title="Refresh files and diff">
            <RefreshCw className="icon" style={{ width: 15, height: 15 }} aria-hidden="true" />
          </button>
          <button type="button" className="btn btn-quiet btn-sm btn-icon" onClick={onClose} aria-label="Close inspector" title="Close (Ctrl-])">
            <X className="icon" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="ctx-tabs" role="tablist" aria-label="Inspector sections" onKeyDown={onTabKeys}>
        <button type="button" role="tab" id="ctx-t-files" aria-controls="ctx-panel" aria-selected={tab === 'files'} tabIndex={tab === 'files' ? 0 : -1} onClick={() => setTab('files')}>
          <FolderGit2 className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />Files
        </button>
        <button type="button" role="tab" id="ctx-t-diff" aria-controls="ctx-panel" aria-selected={tab === 'diff'} tabIndex={tab === 'diff' ? 0 : -1} onClick={() => setTab('diff')}>
          <FileCode2 className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />Diff{changedCount ? ` (${changedCount})` : ''}
        </button>
        <button type="button" role="tab" id="ctx-t-steps" aria-controls="ctx-panel" aria-selected={tab === 'steps'} tabIndex={tab === 'steps' ? 0 : -1} onClick={() => setTab('steps')}>
          <ListChecks className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />Pasos{steps.length ? ` (${steps.length})` : ''}
        </button>
        <button type="button" role="tab" id="ctx-t-worktree" aria-controls="ctx-panel" aria-selected={tab === 'worktree'} tabIndex={tab === 'worktree' ? 0 : -1} onClick={() => setTab('worktree')}>
          <GitBranch className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />Worktree{status?.worktrees?.length ? ` (${status.worktrees.length})` : ''}
        </button>
        <button type="button" role="tab" id="ctx-t-preview" aria-controls="ctx-panel" aria-selected={tab === 'preview'} tabIndex={tab === 'preview' ? 0 : -1} className={diffData && !diffData.preview ? 'is-empty' : undefined} onClick={() => { askedForPreview.current = true; setTab('preview') }}>
          <Eye className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />Preview{diffData?.preview ? ' · ready' : ''}
        </button>
      </div>

      {diffData?.worktree && (
        <div className="wt-banner">
          <CaosTargetGlyph kind="worktree" size={14} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <b className="mono">{diffData.worktree.branch}</b>
            <small>{diffData.worktree.was_branch_pre_existing ? 'existing branch · protected' : 'isolated branch'}</small>
          </div>
          <ConfirmButton className="btn btn-quiet btn-sm" disabled={busy} title="Remove this isolated worktree" question={`Discard ${diffData.worktree.branch}? Its uncommitted work is lost.`} confirmLabel="Discard worktree" onConfirm={handleDiscardWt}>
            <Trash2 className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />Discard
          </ConfirmButton>
        </div>
      )}

      <div className="scroll" role="tabpanel" id="ctx-panel" aria-labelledby={`ctx-t-${tab}`} style={{ padding: '8px 16px 18px' }}>
        {error && <p className="verdict-err" role="alert">{error}</p>}
        {!status && !error && <p style={{ color: 'var(--ink-2)' }}>Inspecting the folder…</p>}

        {tab === 'files' && status && (
          <>
            <h3 className="ctx-sub">Folder</h3>
            <p className="mono" style={{ margin: 0 }}>{status.repo}</p>
            <p className="mono" style={{ margin: '2px 0 0', color: 'var(--ink-3)' }}>
              {diffData?.git_repo === false || status.git_repo === false
                ? 'not a git repository'
                : `branch ${diffData?.branch ?? status.branch ?? 'detached'}`}
            </p>

            <h3 className="ctx-sub">Changed files · {diffData?.files?.length ?? (status.dirty_files ?? []).length}</h3>
            {status.git_repo === false ? (
              <p className="mono" style={{ margin: 0, color: 'var(--ink-3)' }}>Git tracking is not active in this folder.</p>
            ) : (diffData?.files?.length ?? 0) === 0 ? (
              <p className="mono" style={{ margin: 0, color: 'var(--ink-3)' }}>The working tree is clean.</p>
            ) : (
              <ul className="ctx-file-list">
                {diffData!.files.map((f) => (
                  <li key={f.path}>
                    <span className={`f-st ${f.status}`}>{f.status === 'added' ? 'A' : f.status === 'deleted' ? 'D' : 'M'}</span>
                    <span className="mono f-path" title={f.path}>{f.path}</span>
                    <span className="mono f-delta">
                      {f.additions > 0 && <b className="plus">+{f.additions}</b>}
                      {f.deletions > 0 && <b className="minus">-{f.deletions}</b>}
                    </span>
                    {onAttachFile && (
                      <button type="button" className="btn btn-quiet btn-sm" onClick={() => onAttachFile(f.path)} title={`Attach @${f.path}`}>
                        <FilePlus2 className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <h3 className="ctx-sub">Project files ({files.length})</h3>
            <input
              className="field"
              style={{ width: '100%', minHeight: 34, marginBottom: 8, fontSize: 13 }}
              value={fileQuery}
              onChange={(e) => setFileQuery(e.target.value)}
              placeholder="Filter files to attach (@path)…"
              aria-label="Filter project files"
            />
            <ul className="ctx-file-list compact">
              {filteredFiles.map((rel) => (
                <li key={rel}>
                  <span className="mono f-path" title={rel}>{rel}</span>
                  {onAttachFile && (
                    <button type="button" className="btn btn-quiet btn-sm" onClick={() => onAttachFile(rel)} title={`Insert @${rel}`}>
                      @{rel.split('/').pop()}
                    </button>
                  )}
                </li>
              ))}
              {filteredFiles.length === 0 && <li className="mono" style={{ color: 'var(--ink-3)' }}>No matching files.</li>}
            </ul>

            <h3 className="ctx-sub">Skills it can read · {(status.skills ?? []).length}</h3>
            <div className="chips">{(status.skills ?? []).map((s) => <span key={s} className="chip">{s}</span>)}</div>
          </>
        )}

        {tab === 'diff' && diffData && (
          <DiffViewer
            diffText={diffData.diff}
            onAnnotateLine={onCiteDiff}
            onSendDrafts={onSendDrafts}
            annotateLabel="Insert into prompt"
            emptyMessage={diffData.git_repo === false ? 'Git tracking is not active in this folder.' : 'No uncommitted diff in this workspace.'}
          />
        )}

        {tab === 'steps' && (
          steps.length > 0
            ? <ToolStepsView steps={steps} />
            : <p className="ctx-empty"><ListChecks className="icon" style={{ width: 15, height: 15 }} aria-hidden="true" />Aún no hay pasos. Lo que el agente lea (Plan) o cambie (Act) aparece aquí mientras ocurre.</p>
        )}

        {tab === 'worktree' && <WorktreePanel status={status} onChanged={() => { void reload(); onWorktreeDiscarded?.() }} />}

        {tab === 'preview' && (
          <div className="ctx-preview">
            {diffData?.preview ? (
              <>
                <div className="ctx-preview-bar">
                  <span className="mono">{diffData.preview.path}</span>
                  <span className="chip">{diffData.preview.kind.toUpperCase()} · sandboxed</span>
                </div>
                <iframe
                  title={`Sandboxed preview of ${diffData.preview.path}`}
                  sandbox=""
                  srcDoc={diffData.preview.content}
                  className="ctx-iframe"
                />
              </>
            ) : (
              <p className="ctx-empty"><Eye className="icon" style={{ width: 15, height: 15 }} aria-hidden="true" />Nothing to preview: no changed <code>.html</code> or <code>.svg</code>. One written by an agent opens here, sandboxed.</p>
            )}
          </div>
        )}
      </div>
    </aside>
  )
}
