import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AssetItem, DocumentMeta, ImportAssetResponse } from '../types'

interface Props {
  projectId: string | null
  activeDoc: DocumentMeta | null
  refreshKey?: number
  onAssetImported: (response: ImportAssetResponse) => Promise<void> | void
  onError: (message: string) => void
  onAuditChange?: () => void
}

export function AssetLibraryPanel({
  projectId,
  activeDoc,
  refreshKey = 0,
  onAssetImported,
  onError,
  onAuditChange,
}: Props) {
  const [assets, setAssets] = useState<AssetItem[]>([])
  const [query, setQuery] = useState('')
  const [tag, setTag] = useState('')
  const [tagsInput, setTagsInput] = useState('diligence')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)

  useEffect(() => {
    loadAssets().catch((error) => onError(error instanceof Error ? error.message : String(error)))
  }, [refreshKey])

  async function loadAssets(nextQuery = query, nextTag = tag) {
    setLoading(true)
    try {
      const listed = await api.listAssets(nextQuery.trim() || undefined, nextTag.trim() || undefined)
      setAssets(listed)
    } finally {
      setLoading(false)
    }
  }

  async function registerActiveDocument() {
    if (!projectId || !activeDoc) return
    setBusy('register')
    setStatus(null)
    try {
      const asset = await api.addDocumentAsset(projectId, activeDoc.id, splitTags(tagsInput))
      setStatus(`已加入资产库：${asset.filename}`)
      await loadAssets()
      onAuditChange?.()
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  async function importAsset(asset: AssetItem) {
    if (!projectId) return
    setBusy(`import:${asset.id}`)
    setStatus(null)
    try {
      const response = await api.importAsset(projectId, asset.id)
      await onAssetImported(response)
      setStatus(`已导入资产：${asset.filename}`)
      onAuditChange?.()
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  async function deleteAsset(asset: AssetItem) {
    if (!confirm(`删除资产库文件：${asset.filename}？`)) return
    setBusy(`delete:${asset.id}`)
    setStatus(null)
    try {
      await api.deleteAsset(asset.id)
      setStatus(`已删除资产：${asset.filename}`)
      await loadAssets()
      onAuditChange?.()
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  async function editAssetTags(asset: AssetItem) {
    const value = prompt(`编辑标签：${asset.filename}`, asset.tags.join(', '))
    if (value === null) return
    setBusy(`tags:${asset.id}`)
    setStatus(null)
    try {
      const updated = await api.updateAssetTags(asset.id, splitTags(value))
      setStatus(`已更新标签：${updated.filename}`)
      await loadAssets()
      onAuditChange?.()
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="panel asset-panel">
      <div className="asset-register">
        <div className="asset-register-text">
          <strong>{activeDoc ? activeDoc.filename : '未选择资料'}</strong>
          <span>把当前资料沉淀为跨项目可复用资产</span>
        </div>
        <input
          value={tagsInput}
          onChange={(event) => setTagsInput(event.target.value)}
          placeholder="tags: market, legal"
          aria-label="资产标签"
        />
        <button onClick={registerActiveDocument} disabled={!projectId || !activeDoc || busy !== null}>
          {busy === 'register' ? '加入中' : '加入资产库'}
        </button>
      </div>

      <div className="asset-search">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索文件名 / 标签"
          aria-label="搜索资产"
        />
        <input
          value={tag}
          onChange={(event) => setTag(event.target.value)}
          placeholder="标签"
          aria-label="按标签筛选资产"
        />
        <button onClick={() => loadAssets()} disabled={loading || busy !== null}>
          {loading ? '刷新中' : '刷新'}
        </button>
      </div>

      {status && <div className="asset-status">{status}</div>}
      {assets.length === 0 ? (
        <div className="asset-empty">资产库暂无匹配资料。</div>
      ) : (
        <div className="asset-list">
          {assets.map((asset) => (
            <div className="asset-item" key={asset.id}>
              <div className="asset-main">
                <div className="asset-name" title={asset.filename}>{asset.filename}</div>
                <div className="asset-meta">
                  <span>{asset.tags.join(', ') || 'untagged'}</span>
                  <span>{asset.source_refs.length} refs</span>
                </div>
              </div>
              <div className="asset-actions">
                <button onClick={() => importAsset(asset)} disabled={!projectId || busy !== null}>
                  {busy === `import:${asset.id}` ? '导入中' : '导入'}
                </button>
                <button onClick={() => editAssetTags(asset)} disabled={busy !== null}>
                  {busy === `tags:${asset.id}` ? '保存中' : '标签'}
                </button>
                <button className="danger" onClick={() => deleteAsset(asset)} disabled={busy !== null}>
                  {busy === `delete:${asset.id}` ? '删除中' : '删除'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function splitTags(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}
