import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, CloudUpload, Copy, FileArchive, FolderGit2, ShieldCheck } from '../icons'
import { api, SharePackResponse, SharePreview, ShareDoctorResponse, ShareExportsResponse } from '../api'

type Fmt = 'zip' | 'tar.gz' | 'dir'
type ExportItem = ShareExportsResponse['exports'][number]
const kib = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KiB` : `${(n / 1048576).toFixed(1)} MiB`)

/** Groups paths by their first folder, the way a person reads a tree. */
export function byTopDir<T extends { path: string }>(items: T[]): Array<{ dir: string; items: T[] }> {
  const m = new Map<string, T[]>()
  for (const it of items) { const d = it.path.includes('/') ? it.path.split('/')[0] + '/' : '(raíz)'; m.set(d, [...(m.get(d) ?? []), it]) }
  return [...m.entries()].sort(([a], [b]) => (a === '(raíz)' ? -1 : b === '(raíz)' ? 1 : a.localeCompare(b))).map(([dir, items]) => ({ dir, items }))
}

export const ShareView: React.FC = () => {
  const [fmt, setFmt] = useState<Fmt>('zip')
  const [code, setCode] = useState(true)
  const [docs, setDocs] = useState(true)
  const [skills, setSkills] = useState(true)
  const [preview, setPreview] = useState<SharePreview | null>(null)
  const [pErr, setPErr] = useState<string | null>(null)
  const [doctor, setDoctor] = useState<ShareDoctorResponse | null>(null)
  const [pack, setPack] = useState<SharePackResponse | null>(null)
  const [exportsList, setExportsList] = useState<ExportItem[]>([])
  const [drive, setDrive] = useState(false)
  const [parentId, setParentId] = useState('')
  const [uploadRes, setUploadRes] = useState<{ ok: boolean; text: string; url?: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const loadExports = useCallback(() => {
    api.getShareExports().then((r) => { setExportsList(r.exports || []); setDrive(r.gdrive_connected) }).catch(() => undefined)
  }, [])
  useEffect(loadExports, [loadExports])

  useEffect(() => {
    let alive = true
    setPErr(null)
    api.getSharePreview({ format: fmt, include_code: code, include_docs: docs, include_skills: skills })
      .then((r) => { if (alive) setPreview(r) })
      .catch((e) => { if (alive) setPErr(e.message || 'No se pudo calcular la vista previa') })
    return () => { alive = false }
  }, [fmt, code, docs, skills])

  const runDoctor = async () => {
    setBusy('doctor'); setErr(null)
    try { setDoctor(await api.shareDoctor()) } catch (e: any) { setErr(e.message) } finally { setBusy(null) }
  }
  const build = async () => {
    setBusy('pack'); setErr(null)
    try { setPack(await api.sharePack({ include_code: code, include_docs: docs, include_skills: skills, format: fmt })); loadExports() } catch (e: any) { setErr(e.message || 'No se pudo generar el paquete') } finally { setBusy(null) }
  }
  const upload = async (rel?: string) => {
    const path = rel || pack?.relative_path
    if (!path) return
    setBusy('upload')
    try {
      const r = await api.shareUpload(path, parentId.trim() || undefined)
      setUploadRes({ ok: !!r.ok, text: r.ok ? `Subido: ${r.filename ?? path}` : r.message || 'No se pudo subir', url: r.url })
    } catch (e: any) { setUploadRes({ ok: false, text: e.message }) } finally { setBusy(null) }
  }
  const copy = (text: string) => { void navigator.clipboard?.writeText(text); setCopied(text); window.setTimeout(() => setCopied((c) => (c === text ? null : c)), 1400) }

  const tree = useMemo(() => byTopDir(preview?.included ?? []), [preview])
  const gen = preview?.generated ?? []
  const excluded = preview?.excluded ?? []
  const nIssues = doctor?.total_issues ?? doctor?.issues.length ?? 0

  return (
    <div className="page">
      <div className="page-inner share-page">
        <div className="page-bar"><h1>Share / Team</h1>
          <div className="page-bar-right"><button type="button" className="btn btn-sm" onClick={() => void runDoctor()} disabled={busy === 'doctor'}><ShieldCheck className="icon icon-sm" />{busy === 'doctor' ? 'Escaneando…' : 'Ejecutar Doctor'}</button></div></div>
        {err && <div className="banner err" role="alert"><span>{err}</span></div>}

        <div className="share-split">
          <div className="share-col">
            <section className="card share-card" aria-label="Doctor">
              <div className="card-head"><h2>1. Doctor pre-push</h2></div>
              {!doctor ? <p className="muted">Escanea el proyecto en busca de claves, archivos <code>.env</code>, bases locales o rutas privadas antes de empaquetar.</p> : (
                <>
                  <div className={`status-banner ${doctor.clean ? 'sage' : 'amber'}`}>{doctor.clean ? `0 fugas detectadas · ${doctor.scanned} archivos` : `${nIssues} hallazgo(s) en ${doctor.scanned} archivos`}</div>
                  {doctor.issues.length > 0 && <ul className="issue-list">{doctor.issues.slice(0, 6).map((i, k) => <li key={k}><span className="chip coral-chip">{i.kind}</span><span className="mono">{i.path}{i.line ? `:${i.line}` : ''}</span></li>)}</ul>}
                </>
              )}
              {preview?.sanitization && preview.sanitization.length > 0 && (
                <ul className="checklist" aria-label="Checklist de sanitización">
                  {preview.sanitization.map((c) => <li key={c.id} className={c.ok ? 'ok' : 'note'}><span aria-hidden="true">{c.ok ? '✓' : '▲'}</span>{c.label}</li>)}
                </ul>
              )}
            </section>

            <section className="card share-card" aria-label="Share Pack">
              <div className="card-head"><h2>2. Share Pack para equipo</h2>
                <div className="seg" role="group" aria-label="Formato">{(['zip', 'tar.gz', 'dir'] as Fmt[]).map((f) => <button key={f} type="button" aria-pressed={fmt === f} onClick={() => setFmt(f)}>{f === 'dir' ? 'Carpeta' : f.toUpperCase()}</button>)}</div></div>
              <div className="check-row">
                <label><input type="checkbox" checked={code} onChange={(e) => setCode(e.target.checked)} />Código</label>
                <label><input type="checkbox" checked={docs} onChange={(e) => setDocs(e.target.checked)} />Docs</label>
                <label><input type="checkbox" checked={skills} onChange={(e) => setSkills(e.target.checked)} />Skills equipo</label>
              </div>
              <button type="button" className="btn btn-primary" onClick={() => void build()} disabled={busy === 'pack'}><FileArchive className="icon" />{busy === 'pack' ? 'Generando…' : 'Generar Share Pack'}</button>
              {pack && (
                <div className="pack-result">
                  <b className="mono">{pack.filename}</b>
                  <span className="mono muted">{`${pack.files_count} archivos · ${kib(pack.size_bytes)} · ${pack.format}`}</span>
                  <span className={pack.verified === false ? 'coral' : 'sage'}>{pack.verified === false ? 'El escaneo final encontró algo: revisa' : <><Check className="icon icon-xs" /> escaneo final limpio</>}</span>
                </div>
              )}
            </section>

            <section className="card share-card" aria-label="Google Drive y exportaciones">
              <div className="card-head"><h2>3. Drive y exportaciones</h2><span className={`chip ${drive ? 'sage-chip' : 'dim'}`}>{drive ? 'gdrive conectado' : 'sin gdrive'}</span></div>
              <div className="drive-row"><input className="field field-sm" value={parentId} onChange={(e) => setParentId(e.target.value)} placeholder="Folder ID en Drive (opcional)" aria-label="Folder ID" />
                <button type="button" className="btn btn-sm" disabled={!pack?.relative_path || busy === 'upload'} onClick={() => void upload()}><CloudUpload className="icon icon-sm" />{busy === 'upload' ? 'Subiendo…' : 'Subir a Drive'}</button></div>
              {uploadRes && <div className={`status-banner ${uploadRes.ok ? 'sage' : 'amber'}`}><span>{uploadRes.text}</span>{uploadRes.url && <a href={uploadRes.url} target="_blank" rel="noreferrer">Abrir</a>}</div>}
              <div className="exports-list">
                {exportsList.slice(0, 4).map((ex) => (
                  <div key={ex.filename} className="export-item"><span className="mono" title={ex.filename}>{ex.filename}</span><span className="mono muted">{ex.is_dir ? 'carpeta' : kib(ex.size_bytes)}</span>
                    {!ex.is_dir && <a className="btn btn-quiet btn-xs" href={api.downloadUrl(ex.filename)} download>Descargar</a>}
                    <button type="button" className="btn btn-quiet btn-xs" onClick={() => void upload(ex.relative_path)}>Drive</button></div>
                ))}
                {exportsList.length === 0 && <span className="muted mono">Sin paquetes generados todavía.</span>}
              </div>
            </section>
          </div>

          <div className="share-col">
            <section className="card share-card preview-card" aria-label="Vista previa del paquete">
              <div className="card-head"><h2>Vista previa real</h2>{preview && <span className="mono muted">{`${preview.files_count} archivos · ${kib(preview.total_bytes)} · nada se escribe`}</span>}</div>
              {pErr && <p className="verdict-err" role="alert">{pErr}</p>}
              {!preview && !pErr && <p className="muted mono">Calculando lo que entraría…</p>}
              {preview && (
                <div className="preview-body">
                  <h3 className="prov-sub">{`Incluidos (${preview.included.length})`}</h3>
                  <div className="tree">{tree.map((g) => (
                    <details key={g.dir} className="tree-dir" open={tree.length <= 3}><summary><FolderGit2 className="icon icon-sm champagne" aria-hidden="true" /><b className="mono">{g.dir}</b><span className="chip">{g.items.length}</span></summary>
                      <ul>{g.items.slice(0, 30).map((it) => <li key={it.path}><span className="mono">{it.path}</span><span className="mono muted">{kib(it.size)}</span>{it.redacted_lines > 0 && <span className="chip amber-chip">{`${it.redacted_lines} línea(s) redactada(s)`}</span>}{it.sanitized && <span className="chip steel-chip">sanitizado</span>}</li>)}{g.items.length > 30 && <li className="muted mono">{`… y ${g.items.length - 30} más`}</li>}</ul></details>
                  ))}</div>
                  <h3 className="prov-sub">{`Generados (${gen.length})`}</h3>
                  <ul className="tree-flat">{gen.slice(0, 8).map((g) => <li key={g.path}><span className="mono">{g.path}</span><span className="mono muted">{kib(g.size)}</span></li>)}{gen.length > 8 && <li className="muted mono">{`… y ${gen.length - 8} skills más`}</li>}</ul>
                  <h3 className="prov-sub">{`Excluidos (${excluded.length})`}</h3>
                  {excluded.length === 0 ? <p className="muted mono">Nada excluido.</p> : <ul className="tree-flat">{excluded.slice(0, 10).map((e) => <li key={e.path}><span className="mono">{e.path}</span><span className="chip coral-chip">{e.reason}</span></li>)}</ul>}
                  <h3 className="prov-sub">{`Rutas privadas redactadas (${preview.redacted_paths.length})`}</h3>
                  {preview.redacted_paths.length === 0 ? <p className="muted mono">Ninguna ruta privada que reescribir.</p> : <ul className="tree-flat">{preview.redactions.slice(0, 8).map((r) => <li key={r.path}><span className="mono">{r.path}</span><span className="mono muted">líneas {r.lines.slice(0, 6).join(', ')}</span></li>)}</ul>}
                </div>
              )}
            </section>

            <section className="card share-card" aria-label="Onboarding de equipo">
              <div className="card-head"><h2>Onboarding rápido de equipo</h2><span className="mono muted">lo que tu compañero ejecuta</span></div>
              <ol className="onboard">{(preview?.onboarding ?? ['pip install -e .', 'cp .env.example .harness/.env.local', 'caos-harness doctor --dry-run', 'caos-harness']).map((cmd) => (
                <li key={cmd}><code>{cmd}</code><button type="button" className="btn btn-quiet btn-xs" onClick={() => copy(cmd)} aria-label={`Copiar ${cmd}`}>{copied === cmd ? <Check className="icon icon-xs" /> : <Copy className="icon icon-xs" />}{copied === cmd ? 'Copiado' : 'Copiar'}</button></li>
              ))}</ol>
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}
