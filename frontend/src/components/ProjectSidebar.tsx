import type { DocumentMeta, Project } from '../types'

interface Props {
  projects: Project[]
  documents: DocumentMeta[]
  activeProjectId: string | null
  activeDocId: string | null
  onSelectProject: (id: string) => void
  onSelectDoc: (id: string) => void
  onCreateProject?: () => void
  onRevealProject?: () => void
  onCloseProject?: () => void
  onImport?: () => void
  onDeleteDoc?: (doc: DocumentMeta) => void
  onOpenSettings?: () => void
  /** 可调宽度（px），由 useColumnWidths 控制 */
  width?: number
}

export function ProjectSidebar({
  projects,
  documents,
  activeProjectId,
  activeDocId,
  onSelectProject,
  onSelectDoc,
  onCreateProject,
  onRevealProject,
  onCloseProject,
  onImport,
  onDeleteDoc,
  onOpenSettings,
  width,
}: Props) {
  return (
    <aside className="sidebar" style={width != null ? { width, minWidth: width } : undefined}>
      <div className="brand">
        <span className="brand-mark">◆</span> LoamTrace
      </div>

      <div className="sidebar-section">
        <div className="section-title">
          项目
          {onCreateProject && (
            <button className="import-btn" onClick={onCreateProject} title="新建项目">
              + 项目
            </button>
          )}
        </div>
        {projects.length === 0 && <div className="muted small">暂无项目</div>}
        {projects.map((p) => (
          <button
            key={p.id}
            className={`nav-item${p.id === activeProjectId ? ' active' : ''}`}
            onClick={() => onSelectProject(p.id)}
          >
            {p.name}
          </button>
        ))}
        {activeProjectId && (
          <div className="project-actions">
            {onRevealProject && (
              <button className="mini-btn" onClick={onRevealProject} title="打开项目目录">
                目录
              </button>
            )}
            {onCloseProject && (
              <button className="mini-btn" onClick={onCloseProject} title="关闭当前项目">
                关闭
              </button>
            )}
          </div>
        )}
      </div>

      <div className="sidebar-section">
        <div className="section-title">
          资料
          {onImport && (
            <button className="import-btn" onClick={onImport} title="导入文档">
              + 导入
            </button>
          )}
        </div>
        {documents.length === 0 && <div className="muted small">暂无文档</div>}
        {documents.map((d) => (
          <div
            key={d.id}
            className={`nav-item doc${d.id === activeDocId ? ' active' : ''}`}
            title={d.filename}
          >
            <button className="doc-main" onClick={() => onSelectDoc(d.id)}>
              <span className="doc-icon">▤</span>
              <span className="doc-label">{d.filename}</span>
              <span className={`doc-status ${d.ocr_required ? 's-ocr-required' : `s-${d.status}`}`}>
                {statusLabel(d)}
              </span>
            </button>
            {onDeleteDoc && (
              <button className="doc-delete" onClick={() => onDeleteDoc(d)} title={`删除 ${d.filename}`}>
                ×
              </button>
            )}
          </div>
        ))}
      </div>

      {onOpenSettings && (
        <div className="sidebar-footer">
          <button className="settings-entry" onClick={onOpenSettings} title="设置 API 与模型">
            <span className="settings-entry-icon">⚙</span>
            <span>设置</span>
          </button>
        </div>
      )}
    </aside>
  )
}

function statusLabel(doc: DocumentMeta): string {
  if (doc.ocr_required) return '需OCR'
  const map: Record<DocumentMeta['status'], string> = {
    imported: '已导入',
    parsing: '解析中',
    parsed: '已解析',
    failed: '失败',
  }
  return map[doc.status]
}
