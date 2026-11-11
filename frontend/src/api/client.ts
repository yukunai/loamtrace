// 统一 API 入口。VITE_USE_MOCK=1 时走内置 mock，否则打真实 /api。
//
// 真实路由以后端 loamtrace/main.py 当前实际实现为单一真相源（Agent B 已对齐原契约）：
//   GET  /api/projects                                   -> [{ id, name, root }]
//   POST /api/projects {project_id,name}                 -> { id, name, root }
//   GET  /api/projects/{project_id}/documents            -> [document]
//   POST /api/documents/import {project_id,file_path}    -> document
//   GET  /api/projects/{project_id}/documents/{id}/delete-preview -> deletion impact preview
//   DELETE /api/projects/{project_id}/documents/{id}     -> delete result
//   POST /api/documents/{id}/parse {project_id}          -> parse result
//   POST /api/documents/{id}/manual-text {project_id,text,heading}-> document
//   GET  /api/documents/{id}?project_id=                 -> { ...document, pages:[page] }
//   GET  /api/documents/{id}/pages/{n}/render?project_id=-> image/png
//   GET  /api/assets?query=&tag=                         -> [asset]
//   POST /api/assets/from-document {project_id,document_id,tags}-> asset
//   POST /api/assets/import {project_id,asset_id}         -> { asset, document }
//   DELETE /api/assets/{asset_id}                         -> delete result
//   PUT  /api/assets/{asset_id}/tags {tags}               -> asset
//   GET  /api/tables?project_id=&document_id=             -> [table metadata]
//   POST /api/charts/generate-data                        -> { run_id, run_dir, chart }
//   POST /api/search {project_id,query,top_n,rrf_k,...}  -> [chunk]    （裸数组，前端包成 {results}）
//   POST /api/verify/run {project_id,claims}             -> { run_id, claims }
//   GET  /api/memo/{project_id}                          -> { markdown, path, claims }
//   POST /api/generate/memo {project_id,query,top_n}     -> { run_id, answer, claims, retrieved_chunks }
//   POST /api/claims/{id}/correct {project_id,text?,citation_id?,chunk_id?,quote?}-> claim
//   POST /api/citations/{id}/review {project_id,action}  -> claim
//   POST /api/citations/{id}/replace {project_id,chunk_id,quote}-> claim
//   GET  /api/citations/{id}/target?project_id=          -> structured citation target
//   GET/PUT /api/projects/{project_id}/ui-preferences    -> project UI preferences
//   GET/PUT /api/projects/{project_id}/retrieval-preferences -> project retrieval defaults
//   GET/PUT /api/settings/api                            -> provider/API key settings
//   POST /api/settings/api/test                          -> provider connectivity test
//   GET  /api/review/tasks?project_id=&status=           -> [review task]
//   POST /api/review/tasks {project_id,claim_id,assignee,priority}-> review task
//   PATCH /api/review/tasks/{id} {project_id,status?,assignee?,priority?}-> review task
//   POST /api/review/tasks/{id}/comments {project_id,author,body}-> review task
//   POST /api/analysis/red-flags                         -> { run_id, findings }
//   POST /api/analysis/financial-consistency             -> { run_id, findings, observations }
//   POST /api/analysis/contract-clauses                  -> { run_id, findings, observations }
//   POST /api/slides/generate {project_id,title,claim_ids}-> { deck_id,path,deck }
//   GET  /api/templates/slides                           -> [slide template]
//   POST /api/slides/from-template {project_id,template_id,title?,claim_ids?}-> { deck_id,path,deck }
//   POST /api/slides/chart-deck {project_id,title,chart}  -> { deck_id,path,deck }
//   POST /api/slides/table-deck {project_id,table_id,title,max_rows,max_cols}-> { deck_id,path,deck }
//   GET  /api/slides/{deck_id}?project_id=               -> deck
//   POST /api/export/pptx {project_id,deck_id}           -> { deck_id,path,status }
//   POST /api/export/research-package {project_id,deck_id?}-> { package_id,path,archive_path,manifest }
//   POST /api/export/project-snapshot {project_id,include_index}-> { snapshot_id,path,archive_path,manifest }
//   POST /api/import/project-snapshot {archive_path,project_id?,overwrite}-> restored project
//   POST /api/sync/push-snapshot {project_id,target_dir,include_index}-> synced snapshot
//   GET  /api/sync/snapshots?target_dir=&project_id=     -> [synced snapshot]
//   POST /api/sync/pull-snapshot {target_dir,snapshot_id,project_id?,overwrite}-> restored project
//   POST /api/sync/delete-snapshot {target_dir,snapshot_id}-> deleted synced snapshot
//   GET/PUT /api/sync/settings                           -> encrypted sync provider settings
//   POST /api/sync/settings/test                         -> sync provider config test
//   POST /api/sync/provider/push-snapshot {project_id,include_index}-> synced snapshot via configured provider
//   GET  /api/sync/provider/snapshots?project_id=        -> [synced snapshot] via configured provider
//   POST /api/sync/provider/pull-snapshot {snapshot_id,project_id?,overwrite}-> restored project via configured provider
//   POST /api/sync/provider/delete-snapshot {snapshot_id}-> deleted synced snapshot via configured provider
//   GET  /api/export/artifacts?project_id=               -> [export artifact]
//   GET  /api/workflow/status?project_id=                -> workflow status
import type {
  AssetItem,
  Chunk,
  Claim,
  ClaimCorrectionInput,
  CitationTarget,
  Deck,
  DeleteDocumentPreview,
  DeleteDocumentResult,
  DocumentMeta,
  ExportPptxResponse,
  ExportArtifact,
  ExportProjectSnapshotResponse,
  ExportResearchPackageResponse,
  GenerateChartDataResponse,
  GenerateMemoResponse,
  GenerateSlidesResponse,
  AuditEvent,
  AnalysisScanResponse,
  ApiSettings,
  ApiConnectionTestResult,
  ApiSettingsUpdate,
  HealthStatus,
  ImportAssetResponse,
  ImportProjectSnapshotResponse,
  MemoResponse,
  Project,
  PullProjectSnapshotResponse,
  PushProjectSnapshotResponse,
  RetrievalPreferences,
  ReviewTask,
  ReviewTaskPriority,
  ReviewTaskStatus,
  SearchOptions,
  SearchResponse,
  SlideTemplate,
  SupportJudgeResponse,
  SyncSnapshot,
  SyncSettings,
  SyncSettingsTestResult,
  SyncSettingsUpdate,
  TableMeta,
  UiPreferences,
  WorkflowStatus,
} from '../types'
import { mockApi } from './mock'

const API_BASE = window.loamtrace?.apiBase ?? ''
const USE_MOCK = !API_BASE && import.meta.env.VITE_USE_MOCK === '1'

function apiUrl(path: string): string {
  if (!API_BASE || !path.startsWith('/api')) return path
  return `${API_BASE}${path}`
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText} — ${path}\n${body}`)
  }
  return res.json() as Promise<T>
}

const q = (params: Record<string, string | number | undefined>) => {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v != null) usp.set(k, String(v))
  const s = usp.toString()
  return s ? `?${s}` : ''
}

export const api = {
  isMock: USE_MOCK,

  health(): Promise<HealthStatus> {
    if (USE_MOCK) return mockApi.health()
    return http<HealthStatus>('/api/health')
  },

  async listProjects(): Promise<Project[]> {
    if (USE_MOCK) return mockApi.listProjects()
    const raw = await http<Array<{ id: string; name?: string; root?: string }>>('/api/projects')
    return raw.map((p) => ({ id: p.id, name: p.name ?? p.id, root: p.root }))
  },

  workflowStatus(projectId: string): Promise<WorkflowStatus> {
    if (USE_MOCK) return mockApi.workflowStatus(projectId)
    return http<WorkflowStatus>(`/api/workflow/status${q({ project_id: projectId })}`)
  },

  async createProject(projectId: string, name: string): Promise<Project> {
    if (USE_MOCK) return mockApi.createProject(projectId, name)
    const raw = await http<{ id: string; name?: string; root?: string }>('/api/projects', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, name }),
    })
    return { id: raw.id, name: raw.name ?? raw.id, root: raw.root }
  },

  async getProjectRoot(projectId: string): Promise<string> {
    if (USE_MOCK) return `workspace/projects/${projectId}`
    const raw = await http<{ root: string }>(`/api/project-root${q({ project_id: projectId })}`)
    return raw.root
  },

  listDocuments(projectId: string): Promise<DocumentMeta[]> {
    if (USE_MOCK) return mockApi.listDocuments(projectId)
    return http<DocumentMeta[]>(`/api/projects/${encodeURIComponent(projectId)}/documents`)
  },

  importDocument(projectId: string, filePath: string): Promise<DocumentMeta> {
    if (USE_MOCK) return mockApi.importDocument(projectId, filePath)
    return http<DocumentMeta>('/api/documents/import', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, file_path: filePath }),
    })
  },

  previewDeleteDocument(projectId: string, documentId: string): Promise<DeleteDocumentPreview> {
    if (USE_MOCK) return mockApi.previewDeleteDocument(projectId, documentId)
    return http<DeleteDocumentPreview>(
      `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/delete-preview`,
    )
  },

  deleteDocument(projectId: string, documentId: string): Promise<DeleteDocumentResult> {
    if (USE_MOCK) return mockApi.deleteDocument(projectId, documentId)
    return http<DeleteDocumentResult>(
      `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}`,
      { method: 'DELETE' },
    )
  },

  parseDocument(projectId: string, documentId: string): Promise<DocumentMeta> {
    if (USE_MOCK) return mockApi.parseDocument(projectId, documentId)
    return http<DocumentMeta>(`/api/documents/${encodeURIComponent(documentId)}/parse`, {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId }),
    })
  },

  listAssets(query?: string, tag?: string): Promise<AssetItem[]> {
    if (USE_MOCK) return mockApi.listAssets(query, tag)
    return http<AssetItem[]>(`/api/assets${q({ query, tag })}`)
  },

  addDocumentAsset(projectId: string, documentId: string, tags: string[]): Promise<AssetItem> {
    if (USE_MOCK) return mockApi.addDocumentAsset(projectId, documentId, tags)
    return http<AssetItem>('/api/assets/from-document', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, document_id: documentId, tags }),
    })
  },

  importAsset(projectId: string, assetId: string): Promise<ImportAssetResponse> {
    if (USE_MOCK) return mockApi.importAsset(projectId, assetId)
    return http<ImportAssetResponse>('/api/assets/import', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, asset_id: assetId }),
    })
  },

  deleteAsset(assetId: string): Promise<{ asset_id: string; deleted: boolean; file_deleted: boolean }> {
    if (USE_MOCK) return mockApi.deleteAsset(assetId)
    return http<{ asset_id: string; deleted: boolean; file_deleted: boolean }>(
      `/api/assets/${encodeURIComponent(assetId)}`,
      { method: 'DELETE' },
    )
  },

  updateAssetTags(assetId: string, tags: string[]): Promise<AssetItem> {
    if (USE_MOCK) return mockApi.updateAssetTags(assetId, tags)
    return http<AssetItem>(`/api/assets/${encodeURIComponent(assetId)}/tags`, {
      method: 'PUT',
      body: JSON.stringify({ tags }),
    })
  },

  listTables(projectId: string, documentId?: string): Promise<TableMeta[]> {
    if (USE_MOCK) return mockApi.listTables(projectId, documentId)
    return http<TableMeta[]>(`/api/tables${q({ project_id: projectId, document_id: documentId })}`)
  },

  generateChartData(
    projectId: string,
    tableId: string,
    labelColumn: number,
    valueColumns: number[] | null,
    chartType: 'line' | 'bar',
  ): Promise<GenerateChartDataResponse> {
    if (USE_MOCK) return mockApi.generateChartData(projectId, tableId, labelColumn, valueColumns, chartType)
    return http<GenerateChartDataResponse>('/api/charts/generate-data', {
      method: 'POST',
      body: JSON.stringify({
        project_id: projectId,
        table_id: tableId,
        label_column: labelColumn,
        value_columns: valueColumns,
        chart_type: chartType,
      }),
    })
  },

  generateChartDeck(projectId: string, title: string, chart: unknown): Promise<GenerateSlidesResponse> {
    if (USE_MOCK) return mockApi.generateChartDeck(projectId, title, chart)
    return http<GenerateSlidesResponse>('/api/slides/chart-deck', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, title, chart }),
    })
  },

  generateTableDeck(projectId: string, tableId: string, title: string, maxRows = 8, maxCols = 6): Promise<GenerateSlidesResponse> {
    if (USE_MOCK) return mockApi.generateTableDeck(projectId, tableId, title, maxRows, maxCols)
    return http<GenerateSlidesResponse>('/api/slides/table-deck', {
      method: 'POST',
      body: JSON.stringify({
        project_id: projectId,
        table_id: tableId,
        title,
        max_rows: maxRows,
        max_cols: maxCols,
      }),
    })
  },

  applyManualText(projectId: string, documentId: string, text: string, heading = 'Manual correction'): Promise<DocumentMeta> {
    if (USE_MOCK) return mockApi.applyManualText(projectId, documentId, text, heading)
    return http<DocumentMeta>(`/api/documents/${encodeURIComponent(documentId)}/manual-text`, {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, text, heading }),
    })
  },

  getUiPreferences(projectId: string): Promise<UiPreferences> {
    if (USE_MOCK) {
      return Promise.resolve({
        project_id: projectId,
        column_widths: { sidebar: 230, memo: 380, viewer: 560 },
        updated_at: null,
      })
    }
    return http<UiPreferences>(`/api/projects/${encodeURIComponent(projectId)}/ui-preferences`)
  },

  saveUiPreferences(
    projectId: string,
    columnWidths: UiPreferences['column_widths'],
  ): Promise<UiPreferences> {
    const normalized = normalizeColumnWidths(columnWidths)
    if (USE_MOCK) {
      return Promise.resolve({ project_id: projectId, column_widths: normalized, updated_at: null })
    }
    return http<UiPreferences>(`/api/projects/${encodeURIComponent(projectId)}/ui-preferences`, {
      method: 'PUT',
      body: JSON.stringify({ column_widths: normalized }),
    })
  },

  getRetrievalPreferences(projectId: string): Promise<RetrievalPreferences> {
    if (USE_MOCK) return mockApi.getRetrievalPreferences(projectId)
    return http<RetrievalPreferences>(`/api/projects/${encodeURIComponent(projectId)}/retrieval-preferences`)
  },

  saveRetrievalPreferences(projectId: string, options: SearchOptions): Promise<RetrievalPreferences> {
    if (USE_MOCK) return mockApi.saveRetrievalPreferences(projectId, options)
    return http<RetrievalPreferences>(`/api/projects/${encodeURIComponent(projectId)}/retrieval-preferences`, {
      method: 'PUT',
      body: JSON.stringify(options),
    })
  },

  getApiSettings(): Promise<ApiSettings> {
    if (USE_MOCK) return mockApi.getApiSettings()
    return http<ApiSettings>('/api/settings/api')
  },

  saveApiSettings(settings: ApiSettingsUpdate): Promise<ApiSettings> {
    if (USE_MOCK) return mockApi.saveApiSettings(settings)
    return http<ApiSettings>('/api/settings/api', {
      method: 'PUT',
      body: JSON.stringify(settings),
    })
  },

  testApiSettings(settings: ApiSettingsUpdate): Promise<ApiConnectionTestResult> {
    if (USE_MOCK) return mockApi.testApiSettings(settings)
    return http<ApiConnectionTestResult>('/api/settings/api/test', {
      method: 'POST',
      body: JSON.stringify(settings),
    })
  },

  getSyncSettings(): Promise<SyncSettings> {
    if (USE_MOCK) return mockApi.getSyncSettings()
    return http<SyncSettings>('/api/sync/settings')
  },

  saveSyncSettings(settings: SyncSettingsUpdate): Promise<SyncSettings> {
    if (USE_MOCK) return mockApi.saveSyncSettings(settings)
    return http<SyncSettings>('/api/sync/settings', {
      method: 'PUT',
      body: JSON.stringify(settings),
    })
  },

  testSyncSettings(settings: SyncSettingsUpdate): Promise<SyncSettingsTestResult> {
    if (USE_MOCK) return mockApi.testSyncSettings(settings)
    return http<SyncSettingsTestResult>('/api/sync/settings/test', {
      method: 'POST',
      body: JSON.stringify(settings),
    })
  },

  testConfiguredSyncProviderLive(): Promise<SyncSettingsTestResult> {
    if (USE_MOCK) return mockApi.testConfiguredSyncProviderLive()
    return http<SyncSettingsTestResult>('/api/sync/provider/test-live', { method: 'POST' })
  },

  scanRedFlags(projectId: string, limit = 20): Promise<AnalysisScanResponse> {
    if (USE_MOCK) return mockApi.scanRedFlags(projectId, limit)
    return http<AnalysisScanResponse>('/api/analysis/red-flags', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, limit }),
    })
  },

  scanFinancialConsistency(projectId: string, limit = 20): Promise<AnalysisScanResponse> {
    if (USE_MOCK) return mockApi.scanFinancialConsistency(projectId, limit)
    return http<AnalysisScanResponse>('/api/analysis/financial-consistency', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, limit }),
    })
  },

  scanContractClauses(projectId: string, limit = 20): Promise<AnalysisScanResponse> {
    if (USE_MOCK) return mockApi.scanContractClauses(projectId, limit)
    return http<AnalysisScanResponse>('/api/analysis/contract-clauses', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, limit }),
    })
  },

  /** 后端 /api/documents/{id} 已内嵌 pages（Agent B 对齐）；需要 project_id 查询参数 */
  getDocument(id: string, projectId: string): Promise<DocumentMeta> {
    if (USE_MOCK) return mockApi.getDocument(id)
    return http<DocumentMeta>(`/api/documents/${encodeURIComponent(id)}${q({ project_id: projectId })}`)
  },

  async search(projectId: string, query: string, options: SearchOptions = {}): Promise<SearchResponse> {
    if (USE_MOCK) return mockApi.search(projectId, query, options)
    // 后端 /api/search 返回裸数组，这里包成 { results } 以统一前端使用
    const results = await http<Chunk[]>('/api/search', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, query, ...options }),
    })
    return { results }
  },

  /** 抽取式 source-grounded memo 生成：后端用 JSON body，输出会经过 verify gate。 */
  generateMemo(projectId: string, query: string): Promise<GenerateMemoResponse> {
    if (USE_MOCK) return mockApi.generateMemo(projectId, query)
    return http<GenerateMemoResponse>('/api/generate/memo', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, query, top_n: 5 }),
    })
  },

  /** 校验：后端要 { project_id, claims }，返回 { run_id, claims }（比原契约的 {run_id} 更合理，已采纳） */
  verifyRun(projectId: string, claims: unknown[]) {
    if (USE_MOCK) return mockApi.verifyRun('run_mock')
    return http<{ run_id: string; claims: Claim[] }>('/api/verify/run', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, claims }),
    })
  },

  reviewCitation(projectId: string, citationId: string, action: 'approve' | 'reject'): Promise<Claim> {
    if (USE_MOCK) {
      throw new Error('Mock citation review is handled locally')
    }
    return http<Claim>(`/api/citations/${encodeURIComponent(citationId)}/review`, {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, action }),
    })
  },

  replaceCitation(projectId: string, citationId: string, chunkId: string, quote: string): Promise<Claim> {
    if (USE_MOCK) {
      throw new Error('Mock citation replacement is handled locally')
    }
    return http<Claim>(`/api/citations/${encodeURIComponent(citationId)}/replace`, {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, chunk_id: chunkId, quote }),
    })
  },

  correctClaim(projectId: string, claimId: string, correction: ClaimCorrectionInput): Promise<Claim> {
    if (USE_MOCK) {
      throw new Error('Mock claim correction is handled locally')
    }
    return http<Claim>(`/api/claims/${encodeURIComponent(claimId)}/correct`, {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, ...correction }),
    })
  },

  getCitationTarget(projectId: string, citationId: string): Promise<CitationTarget> {
    if (USE_MOCK) return mockApi.getCitationTarget(projectId, citationId)
    return http<CitationTarget>(`/api/citations/${encodeURIComponent(citationId)}/target${q({ project_id: projectId })}`)
  },

  judgeClaimSupport(projectId: string, claimId: string): Promise<SupportJudgeResponse> {
    if (USE_MOCK) return mockApi.judgeClaimSupport(projectId, claimId)
    return http<SupportJudgeResponse>(`/api/claims/${encodeURIComponent(claimId)}/judge-support`, {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId }),
    })
  },

  listReviewTasks(projectId: string, status?: ReviewTaskStatus): Promise<ReviewTask[]> {
    if (USE_MOCK) return mockApi.listReviewTasks(projectId, status)
    return http<ReviewTask[]>(`/api/review/tasks${q({ project_id: projectId, status })}`)
  },

  createReviewTask(projectId: string, claimId: string, assignee?: string, priority: ReviewTaskPriority = 'normal'): Promise<ReviewTask> {
    if (USE_MOCK) return mockApi.createReviewTask(projectId, claimId, assignee, priority)
    return http<ReviewTask>('/api/review/tasks', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, claim_id: claimId, assignee, priority }),
    })
  },

  updateReviewTask(
    projectId: string,
    taskId: string,
    update: { status?: ReviewTaskStatus; assignee?: string; priority?: ReviewTaskPriority },
  ): Promise<ReviewTask> {
    if (USE_MOCK) return mockApi.updateReviewTask(projectId, taskId, update)
    return http<ReviewTask>(`/api/review/tasks/${encodeURIComponent(taskId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ project_id: projectId, ...update }),
    })
  },

  addReviewComment(projectId: string, taskId: string, author: string, body: string): Promise<ReviewTask> {
    if (USE_MOCK) return mockApi.addReviewComment(projectId, taskId, author, body)
    return http<ReviewTask>(`/api/review/tasks/${encodeURIComponent(taskId)}/comments`, {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, author, body }),
    })
  },

  generateSlides(projectId: string, title: string, claimIds?: string[]): Promise<GenerateSlidesResponse> {
    if (USE_MOCK) return mockApi.generateSlides(projectId, title, claimIds)
    return http<GenerateSlidesResponse>('/api/slides/generate', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, title, claim_ids: claimIds }),
    })
  },

  listSlideTemplates(): Promise<SlideTemplate[]> {
    if (USE_MOCK) return mockApi.listSlideTemplates()
    return http<SlideTemplate[]>('/api/templates/slides')
  },

  generateTemplateSlides(projectId: string, templateId: string, title?: string, claimIds?: string[]): Promise<GenerateSlidesResponse> {
    if (USE_MOCK) return mockApi.generateTemplateSlides(projectId, templateId, title, claimIds)
    return http<GenerateSlidesResponse>('/api/slides/from-template', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, template_id: templateId, title, claim_ids: claimIds }),
    })
  },

  getSlides(projectId: string, deckId: string): Promise<Deck> {
    if (USE_MOCK) return mockApi.getSlides(projectId, deckId)
    return http<Deck>(`/api/slides/${encodeURIComponent(deckId)}${q({ project_id: projectId })}`)
  },

  exportPptx(projectId: string, deckId: string): Promise<ExportPptxResponse> {
    if (USE_MOCK) return mockApi.exportPptx(projectId, deckId)
    return http<ExportPptxResponse>('/api/export/pptx', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, deck_id: deckId }),
    })
  },

  exportResearchPackage(projectId: string, deckId?: string | null): Promise<ExportResearchPackageResponse> {
    if (USE_MOCK) return mockApi.exportResearchPackage(projectId, deckId)
    return http<ExportResearchPackageResponse>('/api/export/research-package', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, deck_id: deckId }),
    })
  },

  exportProjectSnapshot(projectId: string, includeIndex = true): Promise<ExportProjectSnapshotResponse> {
    if (USE_MOCK) return mockApi.exportProjectSnapshot(projectId, includeIndex)
    return http<ExportProjectSnapshotResponse>('/api/export/project-snapshot', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, include_index: includeIndex }),
    })
  },

  importProjectSnapshot(archivePath: string, projectId?: string, overwrite = false): Promise<ImportProjectSnapshotResponse> {
    if (USE_MOCK) return mockApi.importProjectSnapshot(archivePath, projectId, overwrite)
    return http<ImportProjectSnapshotResponse>('/api/import/project-snapshot', {
      method: 'POST',
      body: JSON.stringify({ archive_path: archivePath, project_id: projectId || null, overwrite }),
    })
  },

  pushProjectSnapshot(projectId: string, targetDir: string, includeIndex = true): Promise<PushProjectSnapshotResponse> {
    if (USE_MOCK) return mockApi.pushProjectSnapshot(projectId, targetDir, includeIndex)
    return http<PushProjectSnapshotResponse>('/api/sync/push-snapshot', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, target_dir: targetDir, include_index: includeIndex }),
    })
  },

  listSyncedSnapshots(targetDir: string, projectId?: string): Promise<SyncSnapshot[]> {
    if (USE_MOCK) return mockApi.listSyncedSnapshots(targetDir, projectId)
    return http<SyncSnapshot[]>(`/api/sync/snapshots${q({ target_dir: targetDir, project_id: projectId })}`)
  },

  pullProjectSnapshot(targetDir: string, snapshotId: string, projectId?: string, overwrite = false): Promise<PullProjectSnapshotResponse> {
    if (USE_MOCK) return mockApi.pullProjectSnapshot(targetDir, snapshotId, projectId, overwrite)
    return http<PullProjectSnapshotResponse>('/api/sync/pull-snapshot', {
      method: 'POST',
      body: JSON.stringify({ target_dir: targetDir, snapshot_id: snapshotId, project_id: projectId || null, overwrite }),
    })
  },

  deleteSyncedSnapshot(targetDir: string, snapshotId: string): Promise<SyncSnapshot & { deleted: boolean }> {
    if (USE_MOCK) return mockApi.deleteSyncedSnapshot(targetDir, snapshotId)
    return http<SyncSnapshot & { deleted: boolean }>('/api/sync/delete-snapshot', {
      method: 'POST',
      body: JSON.stringify({ target_dir: targetDir, snapshot_id: snapshotId }),
    })
  },

  pushProviderProjectSnapshot(projectId: string, includeIndex = true): Promise<PushProjectSnapshotResponse> {
    if (USE_MOCK) return mockApi.pushProviderProjectSnapshot(projectId, includeIndex)
    return http<PushProjectSnapshotResponse>('/api/sync/provider/push-snapshot', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, include_index: includeIndex }),
    })
  },

  listProviderSyncedSnapshots(projectId?: string): Promise<SyncSnapshot[]> {
    if (USE_MOCK) return mockApi.listProviderSyncedSnapshots(projectId)
    return http<SyncSnapshot[]>(`/api/sync/provider/snapshots${q({ project_id: projectId })}`)
  },

  pullProviderProjectSnapshot(snapshotId: string, projectId?: string, overwrite = false): Promise<PullProjectSnapshotResponse> {
    if (USE_MOCK) return mockApi.pullProviderProjectSnapshot(snapshotId, projectId, overwrite)
    return http<PullProjectSnapshotResponse>('/api/sync/provider/pull-snapshot', {
      method: 'POST',
      body: JSON.stringify({ snapshot_id: snapshotId, project_id: projectId || null, overwrite }),
    })
  },

  deleteProviderSyncedSnapshot(snapshotId: string): Promise<SyncSnapshot & { deleted: boolean }> {
    if (USE_MOCK) return mockApi.deleteProviderSyncedSnapshot(snapshotId)
    return http<SyncSnapshot & { deleted: boolean }>('/api/sync/provider/delete-snapshot', {
      method: 'POST',
      body: JSON.stringify({ snapshot_id: snapshotId }),
    })
  },

  listExportArtifacts(projectId: string): Promise<ExportArtifact[]> {
    if (USE_MOCK) return mockApi.listExportArtifacts(projectId)
    return http<ExportArtifact[]>(`/api/export/artifacts${q({ project_id: projectId })}`)
  },

  listAudit(projectId: string, limit = 30): Promise<AuditEvent[]> {
    if (USE_MOCK) return mockApi.listAudit(projectId, limit)
    return http<AuditEvent[]>(`/api/audit${q({ project_id: projectId, limit })}`)
  },

  /** GET /api/memo/{project_id} 返回 { markdown, path, claims }。 */
  async getMemo(projectId: string): Promise<MemoResponse> {
    if (USE_MOCK) return mockApi.getMemo(projectId)
    const r = await http<{ markdown: string; path?: string; claims?: Claim[] }>(
      `/api/memo/${encodeURIComponent(projectId)}`,
    )
    return { markdown: r.markdown, claims: r.claims ?? [] }
  },

  /** 全量 claim 列表（含 citations），用于 claim 审核台。后端 GET /api/claims */
  listClaims(projectId: string): Promise<Claim[]> {
    if (USE_MOCK) return mockApi.listClaims(projectId)
    return http<Claim[]>(`/api/claims${q({ project_id: projectId })}`)
  },

  /** 页面渲染图 URL（PDF 高亮底图）。后端路由是 .../pages/{n}/render */
  pageRenderUrl(documentId: string, pageNumber: number, projectId: string): string {
    return apiUrl(
      `/api/documents/${encodeURIComponent(documentId)}/pages/${pageNumber}/render${q({ project_id: projectId })}`,
    )
  },
}

function normalizeColumnWidths(widths: UiPreferences['column_widths']): UiPreferences['column_widths'] {
  return {
    sidebar: clampInt(widths.sidebar, 160, 460),
    memo: clampInt(widths.memo, 260, 760),
    viewer: clampInt(widths.viewer, 320, 1100),
  }
}

function clampInt(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min
  return Math.max(min, Math.min(max, Math.round(value)))
}
