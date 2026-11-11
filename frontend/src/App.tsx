import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { api } from './api/client'
import { ProjectSidebar } from './components/ProjectSidebar'
import { SearchPanel } from './components/SearchPanel'
import { PdfViewer, type Highlight } from './components/PdfViewer'
import { EvidencePanel } from './components/EvidencePanel'
import { ReviewPanel } from './components/ReviewPanel'
import { WorkflowPanel } from './components/WorkflowPanel'
import { MemoEditor } from './components/MemoEditor'
import { SlidePanel } from './components/SlidePanel'
import { ChartPanel } from './components/ChartPanel'
import { AnalysisPanel } from './components/AnalysisPanel'
import { AssetLibraryPanel } from './components/AssetLibraryPanel'
import { AuditPanel } from './components/AuditPanel'
import { ApiSettingsPanel } from './components/ApiSettingsPanel'
import { useColumnWidths, type ColKey } from './hooks/useColumnWidths'
import { parseBBox } from './types'
import type {
  BackendCapabilityStatus,
  Chunk,
  Citation,
  CitationTarget,
  Claim,
  DeleteDocumentPreview,
  DocumentMeta,
  HealthStatus,
  ImportAssetResponse,
  Project,
} from './types'

export default function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [documents, setDocuments] = useState<DocumentMeta[]>([])
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null)
  const [activeDoc, setActiveDoc] = useState<DocumentMeta | null>(null)

  const [memoMarkdown, setMemoMarkdown] = useState('')
  const [claims, setClaims] = useState<Claim[]>([])
  const [claimsLoading, setClaimsLoading] = useState(false)

  const [activeClaimId, setActiveClaimId] = useState<string | null>(null)
  const [activeCitationId, setActiveCitationId] = useState<string | null>(null)
  const [activeChunkId, setActiveChunkId] = useState<string | null>(null)
  const [highlights, setHighlights] = useState<Highlight[]>([])
  const [gotoPage, setGotoPage] = useState<number | null>(null)
  // 当前引用文本 + source_uri：用于 DOCX/XLSX 等无页面渲染格式的文本视图（诚实降级，计划书 §2.5/§13.2）
  const [activeQuote, setActiveQuote] = useState<{ text: string; sourceUri: string } | null>(null)
  const [activeTarget, setActiveTarget] = useState<CitationTarget | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [auditRefreshKey, setAuditRefreshKey] = useState(0)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [memoQuery, setMemoQuery] = useState('Revenue growth')
  const [generatingMemo, setGeneratingMemo] = useState(false)
  const [generationStatus, setGenerationStatus] = useState<string | null>(null)
  const [judgingClaimId, setJudgingClaimId] = useState<string | null>(null)
  const [supportJudgeStatus, setSupportJudgeStatus] = useState<string | null>(null)

  const activeClaim = useMemo(
    () => claims.find((c) => c.id === activeClaimId) ?? null,
    [claims, activeClaimId],
  )
  const activeCitation = useMemo(
    () => activeClaim?.citations.find((c) => c.id === activeCitationId) ?? null,
    [activeClaim, activeCitationId],
  )
  const healthWarnings = useMemo(() => summarizeHealthWarnings(health), [health])

  useEffect(() => {
    setSupportJudgeStatus(null)
  }, [activeClaimId])

  const saveColumnWidths = useCallback(
    (nextWidths: Record<ColKey, number>) => {
      if (!activeProjectId || api.isMock) return
      api.saveUiPreferences(activeProjectId, nextWidths).catch((e) => setError(errMsg(e)))
    },
    [activeProjectId],
  )

  const { widths, startResize, resetResize, applyWidths } = useColumnWidths(saveColumnWidths)
  const refreshAudit = useCallback(() => setAuditRefreshKey((value) => value + 1), [])

  // 初始化：项目列表
  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(errMsg(e)))
    api
      .listProjects()
      .then((ps) => {
        setProjects(ps)
        if (ps[0]) setActiveProjectId(ps[0].id)
      })
      .catch((e) => setError(errMsg(e)))
  }, [])

  // 项目切换：文档列表 + memo
  useEffect(() => {
    if (!activeProjectId) return
    // 防竞态：切换项目后，旧项目的迟到响应不得覆盖新项目状态
    let cancelled = false
    setActiveDoc(null)
    setActiveClaimId(null)
    setActiveCitationId(null)
    setActiveChunkId(null)
    setHighlights([])
    setActiveQuote(null)
    api
      .listDocuments(activeProjectId)
      .then((d) => { if (!cancelled) setDocuments(d) })
      .catch((e) => { if (!cancelled) setError(errMsg(e)) })
    api
      .getUiPreferences(activeProjectId)
      .then((prefs) => { if (!cancelled) applyWidths(prefs.column_widths) })
      .catch((e) => { if (!cancelled) setError(errMsg(e)) })
    api
      .getMemo(activeProjectId)
      .then((m) => { if (!cancelled) setMemoMarkdown(m.markdown) })
      .catch((e) => { if (!cancelled) setError(errMsg(e)) })
    // 审核台用全量 claim 列表（GET /api/claims），memo chips 仍能解析（memo claims ⊆ 全量）
    setClaimsLoading(true)
    api
      .listClaims(activeProjectId)
      .then((c) => { if (!cancelled) setClaims(c) })
      .catch((e) => { if (!cancelled) setError(errMsg(e)) })
      .finally(() => { if (!cancelled) setClaimsLoading(false) })
    return () => { cancelled = true }
  }, [activeProjectId, applyWidths])

  // 异步竞态防护用的请求序号（最后一次请求胜出）
  const docReqRef = useRef(0)
  const citationReqRef = useRef(0)

  const loadClaims = useCallback(() => {
    if (!activeProjectId) return
    setClaimsLoading(true)
    api
      .listClaims(activeProjectId)
      .then(setClaims)
      .catch((e) => setError(errMsg(e)))
      .finally(() => setClaimsLoading(false))
  }, [activeProjectId])

  const selectDoc = useCallback(
    (id: string) => {
      if (!activeProjectId) return
      // 防竞态：仅最后一次 selectDoc 的响应可写入 activeDoc，避免迟到的旧文档覆盖
      const token = ++docReqRef.current
      // 后端 /api/documents/{id} 已内嵌 pages
      api
        .getDocument(id, activeProjectId)
        .then((doc) => { if (token === docReqRef.current) setActiveDoc(doc) })
        .catch((e) => { if (token === docReqRef.current) setError(errMsg(e)) })
      setHighlights([])
      setActiveQuote(null)
    },
    [activeProjectId],
  )

  const refreshDocuments = useCallback(
    async (projectId: string) => {
      const nextDocuments = await api.listDocuments(projectId)
      setDocuments(nextDocuments)
      return nextDocuments
    },
    [],
  )

  async function handleCreateProject() {
    const name = window.prompt('输入项目名称')
    if (!name?.trim()) return
    const projectId = slugProjectId(name.trim())
    try {
      const created = await api.createProject(projectId, name.trim())
      const nextProjects = await api.listProjects()
      setProjects(nextProjects.some((p) => p.id === created.id) ? nextProjects : [created, ...nextProjects])
      setActiveProjectId(created.id)
      setDocuments([])
      setMemoMarkdown('')
      setClaims([])
      setActiveDoc(null)
    } catch (err) {
      setError(errMsg(err))
    }
  }

  async function handleRevealProject() {
    if (!activeProjectId) return
    try {
      const root = projects.find((p) => p.id === activeProjectId)?.root ?? (await api.getProjectRoot(activeProjectId))
      const result = await (window.loamtrace?.openPath?.(root) ?? window.loamtrace?.openProjectPath?.(root))
      if (result && !result.ok) {
        setError(`无法打开项目目录：${result.error ?? root}`)
        return
      }
      if (!result) setError(`项目目录：${root}`)
    } catch (err) {
      setError(errMsg(err))
    }
  }

  function handleCloseProject() {
    setActiveProjectId(null)
    setDocuments([])
    setMemoMarkdown('')
    setClaims([])
    setActiveDoc(null)
    setActiveClaimId(null)
    setActiveCitationId(null)
    setActiveChunkId(null)
    setHighlights([])
    setActiveQuote(null)
  }

  async function handleImport() {
    if (!activeProjectId) return
    const filePath =
      (await window.loamtrace?.selectDocumentPath?.()) ??
      window.prompt('输入本机文件完整路径（PDF / DOCX / XLSX）')
    if (!filePath?.trim()) return
    try {
      const imported = await api.importDocument(activeProjectId, filePath.trim())
      setDocuments((prev) => [{ ...imported, status: 'parsing' }, ...prev.filter((d) => d.id !== imported.id)])
      await api.parseDocument(activeProjectId, imported.id)
      await refreshDocuments(activeProjectId)
      await api.getDocument(imported.id, activeProjectId).then(setActiveDoc)
      setHighlights([])
      setActiveQuote(null)
      refreshAudit()
    } catch (err) {
      await refreshDocuments(activeProjectId).catch(() => undefined)
      setError(errMsg(err))
    }
  }

  async function handleDeleteDocument(doc: DocumentMeta) {
    if (!activeProjectId) return
    try {
      const preview = await api.previewDeleteDocument(activeProjectId, doc.id)
      const ok = window.confirm(formatDeleteDocumentPreview(preview))
      if (!ok) return
      await api.deleteDocument(activeProjectId, doc.id)
      const nextDocuments = await refreshDocuments(activeProjectId)
      const memo = await api.getMemo(activeProjectId)
      setMemoMarkdown(memo.markdown)
      loadClaims()
      setActiveClaimId(null)
      setActiveCitationId(null)
      setActiveChunkId(null)
      setHighlights([])
      setActiveQuote(null)
      if (activeDoc?.id === doc.id) {
        setActiveDoc(null)
        if (nextDocuments[0]) selectDoc(nextDocuments[0].id)
      }
      setError(`已删除资料：${doc.filename}`)
      refreshAudit()
    } catch (err) {
      setError(errMsg(err))
    }
  }

  async function handleManualText(doc: DocumentMeta, text: string) {
    if (!activeProjectId) return
    try {
      const updated = await api.applyManualText(activeProjectId, doc.id, text, 'Manual OCR correction')
      await refreshDocuments(activeProjectId)
      setActiveDoc(updated)
      setHighlights([])
      setActiveQuote(null)
      refreshAudit()
    } catch (err) {
      setError(errMsg(err))
      throw err
    }
  }

  async function handleAssetImported(response: ImportAssetResponse) {
    if (!activeProjectId) return
    setDocuments((prev) => [
      { ...response.document, status: 'parsing' },
      ...prev.filter((document) => document.id !== response.document.id),
    ])
    await api.parseDocument(activeProjectId, response.document.id)
    await refreshDocuments(activeProjectId)
    await api.getDocument(response.document.id, activeProjectId).then(setActiveDoc)
    setHighlights([])
    setActiveQuote(null)
    refreshAudit()
  }

  async function handleProjectImported(projectId: string) {
    const nextProjects = await api.listProjects()
    setProjects(nextProjects)
    setActiveProjectId(projectId)
    setDocuments([])
    setMemoMarkdown('')
    setClaims([])
    setActiveDoc(null)
    setActiveClaimId(null)
    setActiveCitationId(null)
    setActiveChunkId(null)
    setHighlights([])
    setActiveQuote(null)
    setError(`已导入项目快照：${projectId}`)
  }

  async function handleGenerateMemo(event?: FormEvent) {
    event?.preventDefault()
    if (!activeProjectId || !memoQuery.trim()) return
    setGeneratingMemo(true)
    setGenerationStatus(null)
    try {
      const result = await api.generateMemo(activeProjectId, memoQuery.trim())
      setMemoMarkdown(result.answer)
      setClaims(result.claims)
      setActiveClaimId(result.claims[0]?.id ?? null)
      setActiveCitationId(result.claims[0]?.citations[0]?.id ?? null)
      setGenerationStatus(generationStatusLabel(result.model_status, result.model_error))
      refreshAudit()
    } catch (err) {
      setError(errMsg(err))
    } finally {
      setGeneratingMemo(false)
    }
  }

  // 默认载入首个文档
  useEffect(() => {
    if (!activeDoc && documents[0]) selectDoc(documents[0].id)
  }, [documents, activeDoc, selectDoc])

  // 搜索结果点击：高亮 chunk 的 bbox 并跳页
  function onPickChunk(chunk: Chunk) {
    setActiveChunkId(chunk.id)
    setActiveClaimId(null)
    setActiveCitationId(null)
    setActiveTarget(null)
    if (chunk.document_id !== activeDoc?.id) selectDoc(chunk.document_id)
    setActiveQuote({ text: chunk.text, sourceUri: chunk.source_uri })
    const bbox = parseBBox(chunk.bbox_json)
    if (bbox) {
      setHighlights([{ id: chunk.id, bbox, active: true, label: chunk.heading_path }])
      setGotoPage(bbox.page)
    } else {
      setHighlights([])
    }
  }

  // memo 中点击 [E:claim] chip：选中 claim 并高亮其首个（已校验）citation
  function onClaimClick(claimId: string) {
    const claim = claims.find((c) => c.id === claimId)
    setActiveClaimId(claimId)
    setActiveChunkId(null)
    if (!claim) return
    const first = claim.citations[0]
    if (first) onCitationClick(first)
    else setHighlights([])
  }

  // citation 点击：在原文高亮 bbox（失败的标红）
  async function onCitationClick(c: Citation) {
    // 防竞态：快速切换 citation 时，迟到的 target 响应不得覆盖当前 citation 的上下文
    const token = ++citationReqRef.current
    setActiveCitationId(c.id)
    setActiveTarget(null)
    if (c.document_id !== activeDoc?.id) selectDoc(c.document_id)
    setActiveQuote({ text: c.quote, sourceUri: c.source_uri })
    if (activeProjectId) {
      try {
        const target = await api.getCitationTarget(activeProjectId, c.id)
        if (token === citationReqRef.current) setActiveTarget(target)
      } catch (err) {
        if (token === citationReqRef.current) setError(errMsg(err))
      }
    }
    const bbox = parseBBox(c.bbox_json)
    if (bbox) {
      setHighlights([{ id: c.id, bbox, active: true, failed: !c.verified, label: c.quote }])
      setGotoPage(bbox.page)
    } else {
      setHighlights([])
    }
  }

  async function replaceActiveCitationWithChunk(chunk: Chunk) {
    if (!activeProjectId || !activeCitation) return
    try {
      const updatedClaim = api.isMock
        ? null
        : await api.replaceCitation(activeProjectId, activeCitation.id, chunk.id, chunk.text)

      if (updatedClaim) {
        setClaims((prev) => prev.map((claim) => (claim.id === updatedClaim.id ? updatedClaim : claim)))
        setActiveClaimId(updatedClaim.id)
        const updatedCitation = updatedClaim.citations.find((cit) => cit.id === activeCitation.id)
        if (updatedCitation) onCitationClick(updatedCitation)
        refreshAudit()
        return
      }

      setClaims((prev) =>
        prev.map((claim) => {
          if (claim.id !== activeCitation.claim_id) return claim
          const mockVerified = numbersCovered(claim.text, chunk.text)
          const citations = claim.citations.map((cit) =>
            cit.id === activeCitation.id
              ? {
                  ...cit,
                  chunk_id: chunk.id,
                  document_id: chunk.document_id,
                  quote: chunk.text,
                  source_uri: chunk.source_uri,
                  bbox_json: chunk.bbox_json,
                  verified: mockVerified,
                  verification_method: mockVerified ? ('normalized_exact' as const) : null,
                  failure_reason: mockVerified ? null : 'number_not_found',
                }
              : cit,
          )
          return { ...claim, citations, status: mockVerified ? 'verified' : 'blocked' }
        }),
      )
      onPickChunk(chunk)
    } catch (err) {
      setError(errMsg(err))
    }
  }

  // citation review 操作：approve/reject/replace 都会更新 claim 状态。
  async function onCitationAction(c: Citation, action: 'approve' | 'reject' | 'replace' | 'correct') {
    if (!activeProjectId) return

    if (action === 'replace') {
      onCitationClick(c)
      setError('已选中 citation。请在检索结果中点击“替换为此证据”。')
      return
    }

    if (action === 'correct') {
      const currentClaim = claims.find((claim) => claim.id === c.claim_id)
      if (!currentClaim) return
      const text = window.prompt('纠正 claim 文本', currentClaim.text)
      if (text === null) return
      const quote = window.prompt('纠正 quote', c.quote)
      if (quote === null) return
      const chunkId = window.prompt('纠正 chunk id（留空则沿用当前引用）', c.chunk_id)
      if (chunkId === null) return
      const note = window.prompt('修正说明（可留空）', '')
      if (note === null) return

      if (!api.isMock) {
        try {
          const updatedClaim = await api.correctClaim(activeProjectId, c.claim_id, {
            text,
            citation_id: c.id,
            chunk_id: chunkId.trim() || c.chunk_id,
            quote,
            reviewer: 'local-user',
            note: note.trim() || undefined,
          })
          setClaims((prev) => prev.map((claim) => (claim.id === updatedClaim.id ? updatedClaim : claim)))
          setActiveClaimId(updatedClaim.id)
          const updatedCitation = updatedClaim.citations.find((cit) => cit.id === c.id)
          if (updatedCitation) onCitationClick(updatedCitation)
          refreshAudit()
        } catch (err) {
          setError(errMsg(err))
        }
        return
      }

      setClaims((prev) =>
        prev.map((claim) => {
          if (claim.id !== c.claim_id) return claim
          const correctedText = text.trim() || claim.text
          const correctedQuote = quote.trim() || c.quote
          const citations = claim.citations.map((cit) =>
            cit.id === c.id
              ? {
                  ...cit,
                  chunk_id: chunkId.trim() || cit.chunk_id,
                  quote: correctedQuote,
                  verified: numbersCovered(correctedText, correctedQuote),
                  verification_method: numbersCovered(correctedText, correctedQuote) ? ('normalized_exact' as const) : null,
                  failure_reason: numbersCovered(correctedText, correctedQuote) ? null : 'number_not_found',
                  reviewer: 'local-user',
                  review_note: note.trim() || null,
                  reviewed_at: new Date().toISOString(),
                }
              : cit,
          )
          const status: Claim['status'] = citations.every((cit) => cit.verified) ? 'verified' : 'blocked'
          return { ...claim, text: correctedText, citations, status }
        }),
      )
      return
    }

    if (!api.isMock) {
      try {
        const updatedClaim = await api.reviewCitation(activeProjectId, c.id, action)
        setClaims((prev) => prev.map((claim) => (claim.id === updatedClaim.id ? updatedClaim : claim)))
        setActiveClaimId(updatedClaim.id)
        refreshAudit()
        return
      } catch (err) {
        setError(errMsg(err))
        return
      }
    }

    setClaims((prev) =>
      prev.map((claim) => {
        if (claim.id !== c.claim_id) return claim
        const citations = claim.citations.map((cit) =>
          cit.id === c.id
            ? action === 'approve'
              ? { ...cit, reviewer: 'reviewer', reviewed_at: new Date().toISOString() }
              : { ...cit, verified: false, failure_reason: 'manual_rejected' }
            : cit,
        )
        const status: Claim['status'] =
          action === 'approve'
            ? citations.every((cit) => cit.verified)
              ? 'verified'
              : 'blocked'
            : action === 'reject'
              ? 'rejected'
              : claim.status
        return { ...claim, citations, status }
      }),
    )
  }

  async function onJudgeSupport(claim: Claim) {
    if (!activeProjectId) return
    setJudgingClaimId(claim.id)
    setSupportJudgeStatus(null)
    try {
      const result = await api.judgeClaimSupport(activeProjectId, claim.id)
      setClaims((prev) => prev.map((item) => (item.id === result.claim.id ? result.claim : item)))
      setActiveClaimId(result.claim.id)
      setSupportJudgeStatus(supportJudgeLabel(result.judge_status, result.model_error))
      refreshAudit()
    } catch (err) {
      setError(errMsg(err))
    } finally {
      setJudgingClaimId(null)
    }
  }

  const resizer = (key: ColKey) => (
    <div
      className="resizer"
      role="separator"
      aria-orientation="vertical"
      title="拖动调整宽度 · 双击复位"
      onPointerDown={startResize(key)}
      onDoubleClick={resetResize(key)}
    />
  )

  return (
    <div className="app">
      <ProjectSidebar
        width={widths.sidebar}
        projects={projects}
        documents={documents}
        activeProjectId={activeProjectId}
        activeDocId={activeDoc?.id ?? null}
        onSelectProject={setActiveProjectId}
        onSelectDoc={selectDoc}
        onCreateProject={handleCreateProject}
        onRevealProject={handleRevealProject}
        onCloseProject={handleCloseProject}
        onImport={handleImport}
        onDeleteDoc={handleDeleteDocument}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      {resizer('sidebar')}

      <main className="workspace">
        {error && (
          <div className="toast" onClick={() => setError(null)} role="alert">
            {error}
            <span className="toast-close">×</span>
          </div>
        )}
        {api.isMock && <div className="mock-banner">MOCK 模式（VITE_USE_MOCK=1）：使用内置假数据，后端就绪后置 0 切真实接口</div>}
        {healthWarnings.length > 0 && (
          <div className="health-banner" role="status">
            {healthWarnings.map((warning, index) => (
              <span className="health-item" key={warning}>
                {index > 0 && <span className="health-separator">|</span>}
                {warning}
              </span>
            ))}
          </div>
        )}

        <WorkflowPanel projectId={activeProjectId} refreshKey={auditRefreshKey} onError={setError} />

        <div className="columns">
          <section className="col col-memo" style={{ width: widths.memo }}>
            <header className="col-header">Memo · 工作区</header>
            <form className="memo-generate-bar" onSubmit={handleGenerateMemo}>
              <input
                value={memoQuery}
                onChange={(event) => setMemoQuery(event.target.value)}
                placeholder="输入 memo 问题"
                aria-label="生成 memo 的问题"
              />
              <button type="submit" disabled={!activeProjectId || !memoQuery.trim() || generatingMemo}>
                {generatingMemo ? '生成中' : '生成'}
              </button>
              {generationStatus && <span className="generation-status">{generationStatus}</span>}
            </form>
            <MemoEditor
              markdown={memoMarkdown}
              claims={claims}
              activeClaimId={activeClaimId}
              onClaimClick={onClaimClick}
            />
            <header className="col-header">检索</header>
            <SearchPanel
              projectId={activeProjectId}
              onPick={onPickChunk}
              onUseForReplacement={replaceActiveCitationWithChunk}
              activeChunkId={activeChunkId}
              canReplace={Boolean(activeCitation)}
              onAuditChange={refreshAudit}
            />
          </section>

          {resizer('memo')}

          <section className="col col-viewer" style={{ width: widths.viewer }}>
            <header className="col-header">原文 · 引用高亮</header>
            <PdfViewer
              doc={activeDoc}
              projectId={activeProjectId}
              highlights={highlights}
              gotoPage={gotoPage}
              activeQuote={activeQuote}
              activeTarget={activeTarget}
              onManualText={handleManualText}
            />
          </section>

          {resizer('viewer')}

          <section className="col col-evidence">
            <header className="col-header">审核台 · Claims</header>
            <ReviewPanel
              projectId={activeProjectId}
              claims={claims}
              activeClaimId={activeClaimId}
              onSelectClaim={onClaimClick}
              onRefresh={loadClaims}
              onAuditChange={refreshAudit}
              onError={setError}
              loading={claimsLoading}
            />
            <header className="col-header">证据 · Citation Review</header>
            <EvidencePanel
              claim={activeClaim}
              activeCitationId={activeCitationId}
              onCitationClick={onCitationClick}
              onCitationAction={onCitationAction}
              onJudgeSupport={onJudgeSupport}
              judgingSupport={activeClaim ? judgingClaimId === activeClaim.id : false}
              supportJudgeStatus={supportJudgeStatus}
            />
            <header className="col-header">Slides · PPTX</header>
            <SlidePanel
              projectId={activeProjectId}
              claims={claims}
              onError={setError}
              onAuditChange={refreshAudit}
              onProjectImported={handleProjectImported}
            />
            <header className="col-header">Charts · 表格图表</header>
            <ChartPanel
              projectId={activeProjectId}
              activeDocumentId={activeDoc?.id ?? null}
              refreshKey={auditRefreshKey}
              onError={setError}
              onAuditChange={refreshAudit}
            />
            <header className="col-header">Analysis · 风险扫描</header>
            <AnalysisPanel
              projectId={activeProjectId}
              onError={setError}
              onAuditChange={refreshAudit}
            />
            <header className="col-header">Assets · 资料库</header>
            <AssetLibraryPanel
              projectId={activeProjectId}
              activeDoc={activeDoc}
              refreshKey={auditRefreshKey}
              onAssetImported={handleAssetImported}
              onError={setError}
              onAuditChange={refreshAudit}
            />
            <header className="col-header">Audit · 日志</header>
            <AuditPanel projectId={activeProjectId} refreshKey={auditRefreshKey} onError={setError} />
          </section>
        </div>
        {settingsOpen && (
          <div className="modal-backdrop" role="presentation" onMouseDown={() => setSettingsOpen(false)}>
            <div className="settings-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
              <div className="settings-modal-head">
                <div>
                  <div className="settings-modal-title">设置</div>
                  <div className="settings-modal-subtitle">API 与模型配置</div>
                </div>
                <button className="modal-close" onClick={() => setSettingsOpen(false)} aria-label="关闭设置">
                  ×
                </button>
              </div>
              <ApiSettingsPanel onError={setError} />
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

function supportJudgeLabel(status: string, modelError?: string | null): string {
  if (status === 'used') return '已写入支撑性信号'
  if (status === 'not_configured') return '未配置模型'
  if (status === 'no_verified_citations') return '没有已校验 citation'
  if (status === 'no_applicable_judgements') return '没有可应用判断'
  if (status === 'failed') return modelError ? `失败：${modelError}` : '判断失败'
  return status
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function formatDeleteDocumentPreview(preview: DeleteDocumentPreview): string {
  const existingFileCount = preview.file_impacts.filter((item) => item.exists).length
  const lines = [
    `删除资料“${preview.filename}”？`,
    '',
    '影响预览：',
    `- 删除引用：${preview.removed_citation_ids.length}`,
    `- 删除结论：${preview.removed_claim_ids.length}`,
    `- 降级为需复核的结论：${preview.retained_claim_ids.length}`,
    `- 移除文件/渲染目录：${existingFileCount}`,
  ]

  appendClaimPreview(lines, '将删除的结论', preview.removed_claims)
  appendClaimPreview(lines, '将降级的结论', preview.retained_claims)
  lines.push('', '确认删除？')
  return lines.join('\n')
}

function appendClaimPreview(lines: string[], heading: string, claims: DeleteDocumentPreview['removed_claims']) {
  if (!claims.length) return
  lines.push('', `${heading}：`)
  for (const claim of claims.slice(0, 3)) {
    lines.push(`- ${clipText(claim.text, 90)}`)
  }
  if (claims.length > 3) lines.push(`- 另有 ${claims.length - 3} 条`)
}

function clipText(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}...` : text
}

function summarizeHealthWarnings(health: HealthStatus | null): string[] {
  if (!health) return []
  const warnings: string[] = []
  const vector = health.vector
  if (vector && shouldWarnVectorCapability(vector)) {
    warnings.push(formatCapabilityWarning('Vector', vector.backend, vector.reason))
  }
  const ocr = health.ocr
  if (ocr && shouldWarnOcrCapability(ocr)) {
    warnings.push(formatCapabilityWarning('OCR', ocr.backend, ocr.reason))
  }
  return warnings
}

function generationStatusLabel(status?: string, error?: string | null): string {
  if (!status) return '生成完成'
  const labels: Record<string, string> = {
    used: 'AI 生成 · 已校验',
    fallback_not_configured: '规则生成 · 未配置模型',
    fallback_no_valid_claims: '规则生成 · AI 输出未通过',
    fallback_after_model_error: '规则生成 · AI 调用失败',
    mock: 'Mock 生成',
  }
  const label = labels[status] ?? status
  return error ? `${label}：${error.slice(0, 120)}` : label
}

function shouldWarnVectorCapability(vector: BackendCapabilityStatus): boolean {
  if (vector.backend === 'mock' || vector.backend === 'sqlite-vec') return false
  // The JSON embedding fallback is the intended local fallback path. Keep it
  // out of the global warning banner so the UI only alerts on blocking issues.
  if (vector.backend === 'json-fallback') return false
  return vector.sqlite_vec_available === false
}

function shouldWarnOcrCapability(ocr: BackendCapabilityStatus): boolean {
  if (ocr.backend === 'mock' || ocr.backend === 'tesseract') return false
  // OCR absence is surfaced when a specific scanned PDF requires OCR. A global
  // banner makes normal DOCX/XLSX/text-layer PDF work look broken.
  if (ocr.backend === 'unavailable' && ocr.reason === 'tesseract_not_found') return false
  return ocr.available === false
}

function formatCapabilityWarning(label: string, backend?: string, reason?: string): string {
  const backendLabel = backend || 'unavailable'
  return reason ? `${label}: ${backendLabel} (${reason})` : `${label}: ${backendLabel}`
}

function slugProjectId(name: string): string {
  const slug = name
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 48)
  const suffix = Date.now().toString(36)
  return slug ? `project_${slug}_${suffix}` : `project_${suffix}`
}

function numbersCovered(claimText: string, evidenceText: string): boolean {
  const numbers = claimText.match(/-?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|million|billion|thousand|mn|bn|x)?/gi)
  if (!numbers) return true
  const normalizedEvidence = normalizeNumberText(evidenceText)
  return numbers.every((n) => normalizedEvidence.includes(normalizeNumberText(n)))
}

function normalizeNumberText(value: string): string {
  return value.toLowerCase().replace(/,/g, '').replace(/\s+/g, '')
}
