import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type {
  Claim,
  Deck,
  ExportArtifact,
  ExportProjectSnapshotResponse,
  ExportPptxResponse,
  ExportResearchPackageResponse,
  ImportProjectSnapshotResponse,
  PushProjectSnapshotResponse,
  SlideTemplate,
  SyncSnapshot,
} from '../types'

interface Props {
  projectId: string | null
  claims: Claim[]
  onError: (message: string) => void
  onAuditChange?: () => void
  onProjectImported?: (projectId: string) => void | Promise<void>
}

const allowedStatuses = new Set<Claim['status']>(['verified', 'approved'])
type SyncResult = PushProjectSnapshotResponse | ImportProjectSnapshotResponse | (SyncSnapshot & { deleted: boolean })

/**
 * Slide JSON / PPTX export surface.
 * The backend enforces the trust gate again; the UI mirrors it so users can see
 * why blocked claims are excluded before asking for a deck.
 */
export function SlidePanel({ projectId, claims, onError, onAuditChange, onProjectImported }: Props) {
  const [title, setTitle] = useState('Evidence Deck')
  const [deck, setDeck] = useState<Deck | null>(null)
  const [exportResult, setExportResult] = useState<ExportPptxResponse | null>(null)
  const [packageResult, setPackageResult] = useState<ExportResearchPackageResponse | null>(null)
  const [snapshotResult, setSnapshotResult] = useState<ExportProjectSnapshotResponse | null>(null)
  const [importResult, setImportResult] = useState<ImportProjectSnapshotResponse | null>(null)
  const [artifacts, setArtifacts] = useState<ExportArtifact[]>([])
  const [templates, setTemplates] = useState<SlideTemplate[]>([])
  const [templateId, setTemplateId] = useState('')
  const [snapshotPath, setSnapshotPath] = useState('')
  const [restoreProjectId, setRestoreProjectId] = useState('')
  const [overwriteSnapshot, setOverwriteSnapshot] = useState(false)
  const [syncTargetDir, setSyncTargetDir] = useState('')
  const [syncSnapshots, setSyncSnapshots] = useState<SyncSnapshot[]>([])
  const [selectedSyncSnapshotId, setSelectedSyncSnapshotId] = useState('')
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null)
  const [artifactsLoading, setArtifactsLoading] = useState(false)
  const [busy, setBusy] = useState<'generate' | 'template' | 'export' | 'package' | 'snapshot' | 'importSnapshot' | 'syncPush' | 'syncList' | 'syncPull' | 'syncDelete' | null>(null)

  const allowedClaims = useMemo(
    () => claims.filter((claim) => allowedStatuses.has(claim.status)),
    [claims],
  )
  const blockedCount = claims.length - allowedClaims.length

  useEffect(() => {
    loadArtifacts().catch((err) => onError(errMsg(err)))
  }, [projectId])

  useEffect(() => {
    api
      .listSlideTemplates()
      .then((items) => {
        setTemplates(items)
        setTemplateId((current) => current || items[0]?.id || '')
      })
      .catch((err) => onError(errMsg(err)))
  }, [])

  async function loadArtifacts() {
    if (!projectId) {
      setArtifacts([])
      return
    }
    setArtifactsLoading(true)
    try {
      setArtifacts(await api.listExportArtifacts(projectId))
    } finally {
      setArtifactsLoading(false)
    }
  }

  async function generateDeck() {
    if (!projectId) return
    setBusy('generate')
    setExportResult(null)
    setPackageResult(null)
    setSnapshotResult(null)
    try {
      const response = await api.generateSlides(
        projectId,
        title.trim() || 'Evidence Deck',
        allowedClaims.map((claim) => claim.id),
      )
      setDeck(response.deck)
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function generateTemplateDeck() {
    if (!projectId || !templateId) return
    setBusy('template')
    setExportResult(null)
    setPackageResult(null)
    setSnapshotResult(null)
    try {
      const response = await api.generateTemplateSlides(
        projectId,
        templateId,
        title.trim() || undefined,
        allowedClaims.map((claim) => claim.id),
      )
      setDeck(response.deck)
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function exportDeck() {
    if (!projectId || !deck) return
    setBusy('export')
    try {
      const response = await api.exportPptx(projectId, deck.deck_id)
      setExportResult(response)
      await loadArtifacts()
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function exportPackage() {
    if (!projectId) return
    setBusy('package')
    try {
      const response = await api.exportResearchPackage(projectId, deck?.deck_id ?? null)
      setPackageResult(response)
      await loadArtifacts()
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function exportSnapshot() {
    if (!projectId) return
    setBusy('snapshot')
    try {
      const response = await api.exportProjectSnapshot(projectId, true)
      setSnapshotResult(response)
      setSnapshotPath(response.archive_path)
      await loadArtifacts()
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function importSnapshot() {
    if (!snapshotPath.trim()) return
    setBusy('importSnapshot')
    try {
      const response = await api.importProjectSnapshot(
        snapshotPath.trim(),
        restoreProjectId.trim() || undefined,
        overwriteSnapshot,
      )
      setImportResult(response)
      await onProjectImported?.(response.project_id)
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function pushSyncSnapshot() {
    if (!projectId || !syncTargetDir.trim()) return
    setBusy('syncPush')
    try {
      const response = await api.pushProjectSnapshot(projectId, syncTargetDir.trim(), true)
      setSyncResult(response)
      const snapshots = await api.listSyncedSnapshots(syncTargetDir.trim())
      setSyncSnapshots(snapshots)
      setSelectedSyncSnapshotId(response.snapshot_id)
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function listSyncSnapshots() {
    if (!syncTargetDir.trim()) return
    setBusy('syncList')
    try {
      const snapshots = await api.listSyncedSnapshots(syncTargetDir.trim())
      setSyncSnapshots(snapshots)
      setSelectedSyncSnapshotId((current) => current || snapshots[0]?.snapshot_id || '')
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function chooseSyncTargetDir() {
    const selected = await window.loamtrace?.selectSyncDirectory?.()
    if (selected) setSyncTargetDir(selected)
  }

  async function pullSyncSnapshot() {
    if (!syncTargetDir.trim() || !selectedSyncSnapshotId) return
    setBusy('syncPull')
    try {
      const response = await api.pullProjectSnapshot(
        syncTargetDir.trim(),
        selectedSyncSnapshotId,
        restoreProjectId.trim() || undefined,
        overwriteSnapshot,
      )
      setSyncResult(response)
      await onProjectImported?.(response.project_id)
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function pushProviderSnapshot() {
    if (!projectId) return
    setBusy('syncPush')
    try {
      const response = await api.pushProviderProjectSnapshot(projectId, true)
      setSyncResult(response)
      const snapshots = await api.listProviderSyncedSnapshots()
      setSyncSnapshots(snapshots)
      setSelectedSyncSnapshotId(response.snapshot_id)
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function listProviderSnapshots() {
    setBusy('syncList')
    try {
      const snapshots = await api.listProviderSyncedSnapshots()
      setSyncSnapshots(snapshots)
      setSelectedSyncSnapshotId((current) => current || snapshots[0]?.snapshot_id || '')
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function pullProviderSnapshot() {
    if (!selectedSyncSnapshotId) return
    setBusy('syncPull')
    try {
      const response = await api.pullProviderProjectSnapshot(
        selectedSyncSnapshotId,
        restoreProjectId.trim() || undefined,
        overwriteSnapshot,
      )
      setSyncResult(response)
      await onProjectImported?.(response.project_id)
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function deleteSyncSnapshot() {
    if (!syncTargetDir.trim() || !selectedSyncSnapshotId) return
    setBusy('syncDelete')
    try {
      const deleted = await api.deleteSyncedSnapshot(syncTargetDir.trim(), selectedSyncSnapshotId)
      const snapshots = await api.listSyncedSnapshots(syncTargetDir.trim())
      setSyncSnapshots(snapshots)
      setSelectedSyncSnapshotId(snapshots[0]?.snapshot_id || '')
      setSyncResult(deleted)
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function deleteProviderSnapshot() {
    if (!selectedSyncSnapshotId) return
    setBusy('syncDelete')
    try {
      const deleted = await api.deleteProviderSyncedSnapshot(selectedSyncSnapshotId)
      const snapshots = await api.listProviderSyncedSnapshots()
      setSyncSnapshots(snapshots)
      setSelectedSyncSnapshotId(snapshots[0]?.snapshot_id || '')
      setSyncResult(deleted)
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusy(null)
    }
  }

  async function openExportPath(path: string, label: string) {
    const result = await window.loamtrace?.openPath?.(path)
    if (result && !result.ok) {
      onError(`无法打开${label}：${result.error ?? path}`)
      return
    }
    if (!result) onError(`${label}位置：${path}`)
  }

  return (
    <div className="panel slide-panel">
      <div className="slide-toolbar">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          aria-label="Deck title"
          disabled={!projectId}
        />
        <button
          onClick={generateDeck}
          disabled={!projectId || allowedClaims.length === 0 || busy !== null}
        >
          {busy === 'generate' ? '生成中' : '生成'}
        </button>
      </div>

      <div className="template-toolbar">
        <select
          value={templateId}
          onChange={(event) => setTemplateId(event.target.value)}
          disabled={!projectId || templates.length === 0 || busy !== null}
          aria-label="Deck template"
        >
          {templates.map((template) => (
            <option key={template.id} value={template.id}>
              {template.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={generateTemplateDeck}
          disabled={!projectId || !templateId || allowedClaims.length === 0 || busy !== null}
        >
          {busy === 'template' ? '套用中' : '按模板生成'}
        </button>
      </div>
      {templateId && (
        <div className="template-hint">
          {templates.find((template) => template.id === templateId)?.description}
        </div>
      )}

      <div className="slide-gate">
        <span>{allowedClaims.length} 条可导出 claim</span>
        {blockedCount > 0 && <span className="slide-blocked">{blockedCount} 条被闸门排除</span>}
      </div>

      {!deck && (
        <div className="slide-empty">
          {allowedClaims.length === 0 ? '没有 verified/approved claim，暂不能生成 PPT。' : '生成后可预览 Slide JSON 并导出 PPTX。'}
        </div>
      )}

      {deck && (
        <>
          <div className="deck-meta">
            <span className="deck-id">{deck.deck_id}</span>
            {deck.template_name && <span>{deck.template_name}</span>}
            <span>{deck.slides.length} slides</span>
          </div>
          <div className="slide-list">
            {deck.slides.map((slide, index) => (
              <div key={slide.id} className="slide-item">
                <div className="slide-num">{index + 1}</div>
                <div className="slide-copy">
                  <div className="slide-title">{slide.title}</div>
                  <div className="slide-note">
                    {slide.main_claim_id ? `claim ${slide.main_claim_id}` : slide.layout}
                  </div>
                  <div className="slide-elements">
                    {slide.elements
                      .filter((element) => element.text && element.role !== 'title')
                      .slice(0, 2)
                      .map((element, elementIndex) => (
                        <div key={`${slide.id}-${elementIndex}`} className="slide-element-line">
                          {element.text}
                        </div>
                      ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <button className="export-btn" onClick={exportDeck} disabled={busy !== null}>
            {busy === 'export' ? '导出中' : '导出 PPTX'}
          </button>
          {exportResult && (
            <ExportPathRow
              label="PPTX"
              path={exportResult.path}
              onOpen={() => openExportPath(exportResult.path, 'PPTX')}
            />
          )}
        </>
      )}
      <button className="package-btn" onClick={exportPackage} disabled={!projectId || busy !== null}>
        {busy === 'package' ? '打包中' : '导出研究包'}
      </button>
      {packageResult && (
        <div className="package-result">
          <ExportPathRow
            label="目录"
            path={packageResult.path}
            onOpen={() => openExportPath(packageResult.path, '研究包目录')}
          />
          {packageResult.archive_path && (
            <ExportPathRow
              label="ZIP"
              path={packageResult.archive_path}
              onOpen={() => openExportPath(packageResult.archive_path!, '研究包 ZIP')}
            />
          )}
        </div>
      )}
      <button className="package-btn" onClick={exportSnapshot} disabled={!projectId || busy !== null}>
        {busy === 'snapshot' ? '快照中' : '导出项目快照'}
      </button>
      {snapshotResult && (
        <div className="package-result">
          <ExportPathRow
            label="快照 ZIP"
            path={snapshotResult.archive_path}
            onOpen={() => openExportPath(snapshotResult.archive_path, '项目快照 ZIP')}
          />
        </div>
      )}
      <div className="snapshot-import">
        <div className="snapshot-import-title">导入项目快照</div>
        <input
          value={snapshotPath}
          onChange={(event) => setSnapshotPath(event.target.value)}
          placeholder="/path/to/snapshot.zip"
          disabled={busy !== null}
        />
        <input
          value={restoreProjectId}
          onChange={(event) => setRestoreProjectId(event.target.value)}
          placeholder="恢复为项目 ID（留空用快照原 ID）"
          disabled={busy !== null}
        />
        <label className="snapshot-overwrite">
          <input
            type="checkbox"
            checked={overwriteSnapshot}
            onChange={(event) => setOverwriteSnapshot(event.target.checked)}
            disabled={busy !== null}
          />
          覆盖同名项目
        </label>
        <button type="button" onClick={importSnapshot} disabled={!snapshotPath.trim() || busy !== null}>
          {busy === 'importSnapshot' ? '导入中' : '导入快照'}
        </button>
        {importResult && (
          <div className="snapshot-import-result">
            已恢复 {importResult.project_id} · {importResult.file_count} files
            <code title={importResult.root}>{importResult.root}</code>
          </div>
        )}
      </div>
      <div className="snapshot-import sync-panel">
        <div className="snapshot-import-title">私有同步</div>
        <input
          value={syncTargetDir}
          onChange={(event) => setSyncTargetDir(event.target.value)}
          placeholder="同步目录，例如 /Volumes/PrivateSync/LoamTrace"
          disabled={busy !== null}
        />
        <button type="button" onClick={chooseSyncTargetDir} disabled={busy !== null || !window.loamtrace?.selectSyncDirectory}>
          选择目录
        </button>
        <div className="sync-actions">
          <button type="button" onClick={pushSyncSnapshot} disabled={!projectId || !syncTargetDir.trim() || busy !== null}>
            {busy === 'syncPush' ? '推送中' : '推送当前项目'}
          </button>
          <button type="button" onClick={listSyncSnapshots} disabled={!syncTargetDir.trim() || busy !== null}>
            {busy === 'syncList' ? '读取中' : '列出快照'}
          </button>
        </div>
        <div className="sync-actions">
          <button type="button" onClick={pushProviderSnapshot} disabled={!projectId || busy !== null}>
            {busy === 'syncPush' ? '推送中' : '推送到配置'}
          </button>
          <button type="button" onClick={listProviderSnapshots} disabled={busy !== null}>
            {busy === 'syncList' ? '读取中' : '列出配置'}
          </button>
        </div>
        {syncSnapshots.length > 0 && (
          <>
            <select
              value={selectedSyncSnapshotId}
              onChange={(event) => setSelectedSyncSnapshotId(event.target.value)}
              disabled={busy !== null}
              aria-label="Synced snapshot"
            >
              {syncSnapshots.map((snapshot) => (
                <option key={snapshot.snapshot_id} value={snapshot.snapshot_id}>
                  {snapshot.project_id} · {snapshot.snapshot_id}
                  {snapshot.integrity_status && snapshot.integrity_status !== 'ok' ? ` · ${snapshot.integrity_status}` : ''}
                </option>
              ))}
            </select>
            <button type="button" onClick={pullSyncSnapshot} disabled={!selectedSyncSnapshotId || busy !== null}>
              {busy === 'syncPull' ? '恢复中' : '恢复选中快照'}
            </button>
            <button type="button" onClick={pullProviderSnapshot} disabled={!selectedSyncSnapshotId || busy !== null}>
              {busy === 'syncPull' ? '恢复中' : '恢复配置快照'}
            </button>
            <button type="button" onClick={deleteSyncSnapshot} disabled={!syncTargetDir.trim() || !selectedSyncSnapshotId || busy !== null}>
              {busy === 'syncDelete' ? '删除中' : '删除目录快照'}
            </button>
            <button type="button" onClick={deleteProviderSnapshot} disabled={!selectedSyncSnapshotId || busy !== null}>
              {busy === 'syncDelete' ? '删除中' : '删除配置快照'}
            </button>
          </>
        )}
        {syncResult && (
          <div className="snapshot-import-result">
            {'deleted' in syncResult
              ? `已删除 ${syncResult.snapshot_id}`
              : 'archive_path' in syncResult
                ? `已同步 ${syncResult.snapshot_id}`
                : `已恢复 ${syncResult.project_id}`}
            <code title={'archive_path' in syncResult ? syncResult.archive_path : syncResult.root}>
              {'archive_path' in syncResult ? syncResult.archive_path : syncResult.root}
            </code>
          </div>
        )}
      </div>
      <div className="export-artifacts">
        <div className="export-artifacts-head">
          <span>最近导出</span>
          <button type="button" onClick={() => loadArtifacts().catch((err) => onError(errMsg(err)))} disabled={!projectId || artifactsLoading}>
            {artifactsLoading ? '刷新中' : '刷新'}
          </button>
        </div>
        {artifacts.length === 0 ? (
          <div className="slide-empty compact">暂无导出物。</div>
        ) : (
          <div className="export-artifact-list">
            {artifacts.slice(0, 6).map((artifact) => (
              <div className="export-artifact-item" key={artifact.id}>
                <div className="export-artifact-main">
                  <div className="export-artifact-title">
                    <span>{artifact.label}</span>
                    <code title={artifact.path}>{artifact.name}</code>
                  </div>
                  <div className="export-artifact-meta">
                    {shortDate(artifact.modified_at)}
                    {artifact.size_bytes != null && ` · ${formatBytes(artifact.size_bytes)}`}
                  </div>
                </div>
                <button type="button" className="open-export-btn" onClick={() => openExportPath(artifact.path, artifact.label)}>
                  打开
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function ExportPathRow({ label, path, onOpen }: { label: string; path: string; onOpen: () => void }) {
  return (
    <div className="export-path-row">
      <div className="export-path" title={path}>
        {label}：{path}
      </div>
      <button type="button" className="open-export-btn" onClick={onOpen}>
        打开
      </button>
    </div>
  )
}

function shortDate(value: string): string {
  return value.replace('T', ' ').replace('Z', '')
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}
