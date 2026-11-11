// 后端未就绪时的内置假数据，用于独立开发前端。
// 通过 VITE_USE_MOCK=1 启用（见 client.ts）。
import type {
  AssetItem,
  Chunk,
  Claim,
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
  ApiConnectionTestResult,
  ApiSettings,
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
  WorkflowStatus,
} from '../types'

const project: Project = {
  id: 'project_001',
  name: 'Demo · 某公司尽调',
  created_at: '2026-06-08T14:00:00Z',
}
let mockProjects: Project[] = [project]
let mockSyncedSnapshots: SyncSnapshot[] = []

const doc: DocumentMeta = {
  id: 'doc_abc',
  project_id: 'project_001',
  filename: 'company_overview.pdf',
  mime_type: 'application/pdf',
  status: 'parsed',
  ocr_used: false,
  pages: [
    { page_number: 1, width: 612, height: 792, text_layer_available: true },
    { page_number: 8, width: 612, height: 792, text_layer_available: true },
  ],
}

// DOCX 文档：无页面渲染、无 bbox，用于演示诚实降级的文本视图
const docDocx: DocumentMeta = {
  id: 'doc_risk',
  project_id: 'project_001',
  filename: 'risk_memo.docx',
  mime_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  status: 'parsed',
  ocr_used: false,
  pages: [],
}

const docXlsx: DocumentMeta = {
  id: 'doc_model',
  project_id: 'project_001',
  filename: 'operating_model.xlsx',
  mime_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  status: 'parsed',
  ocr_used: false,
  pages: [],
}

const docScanned: DocumentMeta = {
  id: 'doc_scan',
  project_id: 'project_001',
  filename: 'scanned_appendix.pdf',
  mime_type: 'application/pdf',
  status: 'failed',
  ocr_used: false,
  ocr_required: true,
  pages: [
    { page_number: 1, width: 612, height: 792, text_layer_available: false },
  ],
}

const chunks: Chunk[] = [
  {
    id: 'chunk_123',
    document_id: 'doc_abc',
    text:
      'In fiscal year 2025, the company delivered strong results. Revenue increased by 24% year over year in 2025, driven by enterprise expansion. Gross margin held steady at 61%.',
    source_uri: 'pdf://doc_abc#page=8&chunk=chunk_123',
    page_start: 8,
    page_end: 8,
    heading_path: 'Financial Highlights',
    bbox_json: { page: 8, x0: 0.142, y0: 0.218, x1: 0.681, y1: 0.262 },
    score: 0.91,
  },
  {
    id: 'chunk_077',
    document_id: 'doc_abc',
    text:
      'Key risks include customer concentration: the top three customers represented 41% of total revenue in 2025, exposing the business to churn risk.',
    source_uri: 'pdf://doc_abc#page=8&chunk=chunk_077',
    page_start: 8,
    page_end: 8,
    heading_path: 'Risk Factors',
    bbox_json: { page: 8, x0: 0.142, y0: 0.42, x1: 0.7, y1: 0.47 },
    score: 0.73,
  },
  {
    id: 'chunk_125',
    document_id: 'doc_abc',
    text:
      'Revenue growth was computed from 100 in 2024 and 125 in 2025, using the prior-year revenue as the denominator.',
    source_uri: 'pdf://doc_abc#page=8&chunk=chunk_125',
    page_start: 8,
    page_end: 8,
    heading_path: 'Financial Highlights',
    bbox_json: { page: 8, x0: 0.142, y0: 0.31, x1: 0.72, y1: 0.35 },
    score: 0.79,
  },
  {
    id: 'chunk_docx_12',
    document_id: 'doc_risk',
    text:
      'Risk Factors: The company depends on a single cloud provider for substantially all of its infrastructure, and any prolonged outage could materially harm operations.',
    source_uri: 'docx://doc_risk#paragraph=12',
    heading_path: 'Risk Factors',
    bbox_json: null,
    score: 0.68,
  },
  {
    id: 'chunk_xlsx_b3',
    document_id: 'doc_model',
    text: 'Revenue row 3: A3: 2025 | B3: 148',
    source_uri: 'xlsx://doc_model#sheet=Revenue&cell=B3',
    heading_path: 'Revenue',
    bbox_json: null,
    score: 0.82,
  },
]

let mockDocuments: DocumentMeta[] = [doc, docDocx, docXlsx, docScanned]
const mockTables: TableMeta[] = [
  {
    id: 'table_financials_001',
    document_id: 'doc_abc',
    page_id: 'page_8',
    bbox_json: { page: 8, x0: 0.12, y0: 0.5, x1: 0.76, y1: 0.68 },
    caption: 'Revenue table',
    parser: 'mock-table-parser',
    document_filename: 'company_overview.pdf',
    document_mime_type: 'application/pdf',
    cell_count: 6,
    row_count: 3,
    col_count: 2,
    sheet_name: null,
    preview: [
      ['Year', 'Revenue'],
      ['2024', '120'],
      ['2025', '148'],
    ],
  },
  {
    id: 'table_model_revenue',
    document_id: 'doc_model',
    page_id: null,
    bbox_json: null,
    caption: 'Revenue',
    parser: 'mock-xlsx-parser',
    document_filename: 'operating_model.xlsx',
    document_mime_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    cell_count: 6,
    row_count: 3,
    col_count: 2,
    sheet_name: 'Revenue',
    preview: [
      ['Year', 'Revenue'],
      ['2024', '120'],
      ['2025', '148'],
    ],
  },
]
let mockAssets: AssetItem[] = [
  {
    id: 'asset_mock_001',
    sha256: 'mock_sha_market',
    filename: 'market_landscape.pdf',
    mime_type: 'application/pdf',
    storage_path: '/mock/assets/market_landscape.pdf',
    tags: ['market', 'diligence'],
    source_refs: [{ project_id: 'project_001', document_id: 'doc_abc' }],
    created_at: '2026-06-08T09:00:00Z',
    updated_at: '2026-06-08T09:00:00Z',
  },
]
let mockApiSettings: ApiSettings = {
  provider: 'openai-compatible',
  base_url: 'https://api.openai.com/v1',
  model: '',
  api_key_configured: false,
  settings_path: '/mock/api_settings.json',
}
let mockSyncSettings: SyncSettings = {
  provider: 'local',
  target_dir: '/mock/sync-target',
  endpoint_url: '',
  bucket: '',
  region: '',
  prefix: 'loamtrace-sync',
  access_key_configured: false,
  secret_key_configured: false,
  settings_path: '/mock/sync_settings.json',
}
const defaultRetrievalPreferences = {
  top_n: 12,
  rrf_k: 60,
  fts_top_n: 50,
  vector_top_n: 50,
  keyword_boost: 1,
  vector_boost: 1,
}
let mockRetrievalPreferences: Record<string, RetrievalPreferences> = {}
let mockReviewTasks: ReviewTask[] = []

const slideTemplates: SlideTemplate[] = [
  {
    id: 'investment_committee',
    name: 'Investment Committee Memo',
    description: 'Verified investment narrative with metrics, risks, comparison, timeline, and evidence appendix.',
    recommended_claims: 3,
    layouts: ['title', 'executive_summary', 'metric_table', 'red_flag_table', 'comparison_matrix', 'timeline', 'claim_with_evidence', 'evidence_appendix'],
  },
  {
    id: 'market_diligence',
    name: 'Market Diligence Brief',
    description: 'Evidence-led market brief focused on key claims, metrics, comparisons, and source appendix.',
    recommended_claims: 2,
    layouts: ['title', 'executive_summary', 'metric_table', 'comparison_matrix', 'claim_with_evidence', 'evidence_appendix'],
  },
  {
    id: 'risk_review',
    name: 'Risk Review',
    description: 'Review-oriented deck that foregrounds red flags, timeline, and claim-level evidence.',
    recommended_claims: 2,
    layouts: ['title', 'executive_summary', 'red_flag_table', 'timeline', 'claim_with_evidence', 'evidence_appendix'],
  },
]

const claims: Claim[] = [
  {
    id: 'claim_001',
    text: 'Company revenue grew 24% year over year in 2025.',
    type: 'financial_metric',
    status: 'verified',
    citations: [
      {
        id: 'citation_001',
        claim_id: 'claim_001',
        chunk_id: 'chunk_123',
        document_id: 'doc_abc',
        quote: 'Revenue increased by 24% year over year in 2025.',
        source_uri: 'pdf://doc_abc#page=8&chunk=chunk_123',
        bbox_json: { page: 8, x0: 0.142, y0: 0.224, x1: 0.55, y1: 0.238 },
        verified: true,
        verification_method: 'normalized_exact',
        verification_score: 1.0,
        failure_reason: null,
        support_level: 'direct',
        support_reason: 'quote directly covers the claim numbers',
      },
    ],
  },
  {
    id: 'claim_003',
    text: 'Revenue growth was 25% computed from 100 in 2024 and 125 in 2025.',
    type: 'computed',
    calculation_formula: '(125 - 100) / 100 = 25%',
    source_numbers: ['100', '2024', '125', '2025'],
    status: 'verified',
    citations: [
      {
        id: 'citation_003',
        claim_id: 'claim_003',
        chunk_id: 'chunk_125',
        document_id: 'doc_abc',
        quote: 'Revenue growth was computed from 100 in 2024 and 125 in 2025',
        source_uri: 'pdf://doc_abc#page=8&chunk=chunk_125',
        bbox_json: { page: 8, x0: 0.142, y0: 0.31, x1: 0.72, y1: 0.35 },
        verified: true,
        verification_method: 'normalized_exact',
        verification_score: 1.0,
        failure_reason: null,
        support_level: 'direct',
        support_reason: 'source numbers are present in the quote',
      },
    ],
  },
  {
    id: 'claim_002',
    text: 'The top three customers represented 38% of revenue in 2025.',
    type: 'financial_metric',
    status: 'blocked',
    citations: [
      {
        id: 'citation_002',
        claim_id: 'claim_002',
        chunk_id: 'chunk_077',
        document_id: 'doc_abc',
        quote: 'the top three customers represented 41% of total revenue in 2025',
        source_uri: 'pdf://doc_abc#page=8&chunk=chunk_077',
        bbox_json: { page: 8, x0: 0.142, y0: 0.42, x1: 0.7, y1: 0.47 },
        verified: false,
        verification_method: null,
        // claim 写 38%，原文是 41% —— 数字不一致，应被阻断
        failure_reason: 'number_mismatch',
        support_level: 'weak',
        support_reason: 'number mismatch blocks support',
      },
    ],
  },
  {
    id: 'claim_004',
    text: 'The company depends on a single cloud provider for substantially all infrastructure.',
    type: 'risk_factor',
    status: 'verified',
    citations: [
      {
        id: 'citation_004',
        claim_id: 'claim_004',
        chunk_id: 'chunk_docx_12',
        document_id: 'doc_risk',
        quote: 'The company depends on a single cloud provider for substantially all of its infrastructure',
        source_uri: 'docx://doc_risk#paragraph=12',
        bbox_json: null,
        verified: true,
        verification_method: 'normalized_exact',
        verification_score: 1.0,
        failure_reason: null,
        support_level: 'direct',
        support_reason: 'DOCX paragraph directly supports the risk claim',
      },
    ],
  },
  {
    id: 'claim_005',
    text: 'Revenue was 148 in 2025.',
    type: 'financial_metric',
    status: 'verified',
    citations: [
      {
        id: 'citation_005',
        claim_id: 'claim_005',
        chunk_id: 'chunk_xlsx_b3',
        document_id: 'doc_model',
        quote: 'B3: 148',
        source_uri: 'xlsx://doc_model#sheet=Revenue&cell=B3',
        bbox_json: null,
        verified: true,
        verification_method: 'normalized_exact',
        verification_score: 1.0,
        failure_reason: null,
        support_level: 'direct',
        support_reason: 'XLSX cell value directly supports the metric claim',
      },
    ],
  },
]

const memoMarkdown = `# 投研 Memo（草稿）

## 财务表现

Revenue grew 24% year over year in 2025. [E:claim_001]

> 下面这条因数字与原文不一致被校验闸门阻断，不会进入正式正文：
> ~~The top three customers represented 38% of revenue in 2025.~~ [E:claim_002 · blocked]
`

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

const makeMockDeck = (title: string, claimIds?: string[]): Deck => {
  const allowedClaims = claims.filter((claim) => claim.status === 'verified' || claim.status === 'approved')
  const selected = claimIds?.length
    ? allowedClaims.filter((claim) => claimIds.includes(claim.id))
    : allowedClaims
  return {
    deck_id: 'deck_mock_001',
    title,
    slides: [
      {
        id: 'slide_001',
        layout: 'title',
        title,
        main_claim_id: null,
        elements: [{ type: 'text', role: 'title', text: title, claim_id: null }],
        speaker_notes: [],
      },
      ...selected.map((claim, i) => ({
        id: `slide_${String(i + 2).padStart(3, '0')}`,
        layout: 'claim_with_evidence',
        title: claim.text,
        main_claim_id: claim.id,
        elements: [
          { type: 'text', role: 'headline', text: claim.text, claim_id: claim.id },
          { type: 'text', role: 'evidence', text: claim.citations[0]?.quote ?? '', claim_id: claim.id },
        ],
        speaker_notes: [
          {
            claim_id: claim.id,
            quote: claim.citations[0]?.quote ?? '',
            source_uri: claim.citations[0]?.source_uri ?? '',
          },
        ],
      })),
    ],
  }
}

export const mockApi = {
  async health(): Promise<HealthStatus> {
    await delay(80)
    return {
      status: 'ok',
      vector: { backend: 'mock', sqlite_vec_available: true },
      ocr: { backend: 'mock', available: true },
    }
  },
  async listProjects(): Promise<Project[]> {
    await delay(120)
    return mockProjects
  },
  async createProject(projectId: string, name: string): Promise<Project> {
    await delay(160)
    const created: Project = {
      id: projectId,
      name,
      created_at: new Date().toISOString(),
    }
    mockProjects = [created, ...mockProjects.filter((p) => p.id !== projectId)]
    return created
  },
  async workflowStatus(projectId: string): Promise<WorkflowStatus> {
    await delay(80)
    const documents = mockDocuments.length
    const parsedDocuments = mockDocuments.filter((doc) => doc.status === 'parsed').length
    const verifiedClaims = claims.filter((claim) => claim.status === 'verified' || claim.status === 'approved').length
    const reviewClaims = claims.filter((claim) => ['needs_review', 'blocked', 'rejected'].includes(claim.status)).length
    return {
      project_id: projectId,
      overall_status: reviewClaims ? 'needs_review' : 'in_progress',
      counts: {
        documents,
        parsed_documents: parsedDocuments,
        failed_documents: 0,
        chunks: chunks.length,
        claims: claims.length,
        verified_claims: verifiedClaims,
        review_claims: reviewClaims,
        decks: 1,
        pptx_exports: 1,
        research_packages: 1,
        research_package_archives: 1,
      },
      steps: [
        { key: 'project', label: 'Project', status: 'complete', detail: 'Project workspace is ready.', counts: {} },
        { key: 'import', label: 'Import', status: documents ? 'complete' : 'not_started', detail: `${documents} document(s) imported.`, counts: { documents } },
        { key: 'parse', label: 'Parse / OCR', status: parsedDocuments === documents ? 'complete' : 'in_progress', detail: `${parsedDocuments}/${documents} document(s) parsed.`, counts: { documents, parsed_documents: parsedDocuments } },
        { key: 'evidence', label: 'Evidence Index', status: chunks.length ? 'complete' : 'not_started', detail: `${chunks.length} evidence chunk(s) indexed.`, counts: { chunks: chunks.length } },
        { key: 'memo', label: 'Memo', status: claims.length ? 'complete' : 'ready', detail: `${claims.length} claim(s), ${verifiedClaims} verified.`, counts: { claims: claims.length, verified_claims: verifiedClaims } },
        { key: 'review', label: 'Claim Review', status: reviewClaims ? 'needs_review' : 'complete', detail: `${reviewClaims} claim(s) need review.`, counts: { review_claims: reviewClaims } },
        { key: 'slides', label: 'Slides', status: 'complete', detail: '1 deck(s) generated.', counts: { decks: 1 } },
        {
          key: 'export',
          label: 'Export',
          status: 'complete',
          detail: '1 PPTX export(s), 1 research package(s), 1 ZIP archive(s).',
          counts: { pptx_exports: 1, research_packages: 1, research_package_archives: 1 },
        },
      ],
      blockers: reviewClaims
        ? [{ key: 'review_pending', severity: 'needs_review', message: `${reviewClaims} 条 claim 待复核` }]
        : [],
      next_actions: reviewClaims
        ? [{ key: 'review_claims', label: '复核待处理 claim', step: 'review' }]
        : [{ key: 'export_pptx', label: '导出 PPTX', step: 'export' }],
      latest_audit: null,
    }
  },
  async listDocuments(_projectId: string): Promise<DocumentMeta[]> {
    await delay(120)
    return mockDocuments
  },
  async getDocument(id: string): Promise<DocumentMeta> {
    await delay(80)
    return mockDocuments.find((d) => d.id === id) ?? doc
  },
  async importDocument(projectId: string, filePath: string): Promise<DocumentMeta> {
    await delay(160)
    const imported: DocumentMeta = {
      id: `doc_mock_${Date.now()}`,
      project_id: projectId,
      filename: filePath.split('/').pop() || filePath,
      mime_type: filePath.endsWith('.docx')
        ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        : filePath.endsWith('.xlsx')
          ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
          : 'application/pdf',
      status: 'imported',
      ocr_used: false,
      pages: [],
    }
    mockDocuments = [imported, ...mockDocuments]
    return imported
  },
  async parseDocument(_projectId: string, documentId: string): Promise<DocumentMeta> {
    await delay(260)
    mockDocuments = mockDocuments.map((d) => (d.id === documentId ? { ...d, status: 'parsed' } : d))
    return mockDocuments.find((d) => d.id === documentId) ?? doc
  },
  async listAssets(query?: string, tag?: string): Promise<AssetItem[]> {
    await delay(100)
    const q = (query ?? '').trim().toLowerCase()
    const t = (tag ?? '').trim().toLowerCase().replace(/\s+/g, '-')
    return mockAssets.filter((asset) => {
      const matchesQuery = !q || asset.filename.toLowerCase().includes(q) || asset.tags.some((item) => item.includes(q))
      const matchesTag = !t || asset.tags.includes(t)
      return matchesQuery && matchesTag
    })
  },
  async addDocumentAsset(projectId: string, documentId: string, tags: string[]): Promise<AssetItem> {
    await delay(160)
    const document = mockDocuments.find((item) => item.id === documentId) ?? doc
    const normalizedTags = normalizeTags(tags)
    const existing = mockAssets.find((asset) => asset.filename === document.filename)
    if (existing) {
      existing.tags = Array.from(new Set([...existing.tags, ...normalizedTags])).sort()
      existing.updated_at = new Date().toISOString()
      if (!existing.source_refs.some((ref) => ref.project_id === projectId && ref.document_id === documentId)) {
        existing.source_refs.push({ project_id: projectId, document_id: documentId })
      }
      return existing
    }
    const asset: AssetItem = {
      id: `asset_mock_${Date.now()}`,
      sha256: `mock_sha_${document.id}`,
      filename: document.filename,
      mime_type: document.mime_type ?? 'application/octet-stream',
      storage_path: `/mock/assets/${document.filename}`,
      tags: normalizedTags,
      source_refs: [{ project_id: projectId, document_id: documentId }],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    mockAssets = [asset, ...mockAssets]
    return asset
  },
  async importAsset(projectId: string, assetId: string): Promise<ImportAssetResponse> {
    await delay(180)
    const asset = mockAssets.find((item) => item.id === assetId) ?? mockAssets[0]
    const imported: DocumentMeta = {
      id: `doc_asset_${Date.now()}`,
      project_id: projectId,
      filename: asset.filename,
      mime_type: asset.mime_type,
      status: 'imported',
      ocr_used: false,
      pages: [],
    }
    mockDocuments = [imported, ...mockDocuments]
    return { asset, document: imported }
  },
  async deleteAsset(assetId: string): Promise<{ asset_id: string; deleted: boolean; file_deleted: boolean }> {
    await delay(120)
    const before = mockAssets.length
    mockAssets = mockAssets.filter((asset) => asset.id !== assetId)
    if (mockAssets.length === before) {
      throw new Error('asset_not_found')
    }
    return { asset_id: assetId, deleted: true, file_deleted: true }
  },
  async updateAssetTags(assetId: string, tags: string[]): Promise<AssetItem> {
    await delay(120)
    const asset = mockAssets.find((item) => item.id === assetId)
    if (!asset) {
      throw new Error('asset_not_found')
    }
    asset.tags = normalizeTags(tags)
    asset.updated_at = new Date().toISOString()
    return asset
  },
  async listTables(_projectId: string, documentId?: string): Promise<TableMeta[]> {
    await delay(100)
    return documentId ? mockTables.filter((table) => table.document_id === documentId) : mockTables
  },
  async generateChartData(
    _projectId: string,
    tableId: string,
    _labelColumn = 0,
    valueColumns: number[] | null = null,
    chartType: 'line' | 'bar' = 'line',
  ): Promise<GenerateChartDataResponse> {
    await delay(180)
    const table = mockTables.find((item) => item.id === tableId) ?? mockTables[0]
    const valueColumn = valueColumns?.[0] ?? 1
    const header = table.preview[0]?.[valueColumn] ?? 'Revenue'
    return {
      run_id: 'run_mock_chart_data',
      run_dir: '/mock/runs/run_mock_chart_data',
      chart: {
        type: 'chart',
        chart_type: chartType,
        review_status: 'verified',
        data_source: {
          table_id: table.id,
          cell_ids: ['cell_mock_r2c2', 'cell_mock_r3c2'],
        },
        series: [
          {
            name: header,
            points: [
              { label: '2024', value: 120, cell_id: 'cell_mock_r2c2' },
              { label: '2025', value: 148, cell_id: 'cell_mock_r3c2' },
            ],
          },
        ],
      },
    }
  },
  async generateChartDeck(_projectId: string, title: string, chart: unknown): Promise<GenerateSlidesResponse> {
    await delay(180)
    const chartElement = chart && typeof chart === 'object' ? chart : { type: 'chart', chart_type: 'line' }
    const deck: Deck = {
      deck_id: 'deck_mock_chart_001',
      title,
      slides: [
        {
          id: 'slide_001',
          layout: 'title',
          title,
          main_claim_id: null,
          elements: [{ type: 'text', role: 'title', text: title, claim_id: null }],
          speaker_notes: [],
        },
        {
          id: 'slide_002',
          layout: 'source_table_chart',
          title,
          main_claim_id: null,
          elements: [
            { type: 'text', role: 'headline', text: title, claim_id: null },
            chartElement as Deck['slides'][number]['elements'][number],
          ],
          speaker_notes: [
            { claim_id: null, source_uri: 'table:table_financials_001', quote: 'Chart data generated from parsed source table cells.' },
          ],
        },
      ],
    }
    return {
      deck_id: deck.deck_id,
      path: '/mock/slides/deck_mock_chart_001.slide.json',
      deck,
      run_id: 'run_mock_chart_deck',
      run_dir: '/mock/runs/run_mock_chart_deck',
    }
  },
  async generateTableDeck(
    _projectId: string,
    tableId: string,
    title: string,
    maxRows = 8,
    maxCols = 6,
  ): Promise<GenerateSlidesResponse> {
    await delay(180)
    const table = mockTables.find((item) => item.id === tableId) ?? mockTables[0]
    const rows = table.preview.slice(0, maxRows).map((row) => row.slice(0, maxCols))
    const deck: Deck = {
      deck_id: 'deck_mock_table_001',
      title,
      slides: [
        {
          id: 'slide_001',
          layout: 'title',
          title,
          main_claim_id: null,
          elements: [{ type: 'text', role: 'title', text: title, claim_id: null }],
          speaker_notes: [],
        },
        {
          id: 'slide_002',
          layout: 'source_table',
          title: table.caption ?? table.sheet_name ?? 'Source table',
          main_claim_id: null,
          elements: [
            { type: 'text', role: 'headline', text: table.caption ?? table.sheet_name ?? 'Source table', claim_id: null },
            {
              type: 'table',
              role: 'source_table',
              rows,
              review_status: 'verified',
              data_source: {
                table_id: table.id,
                cell_ids: ['cell_mock_r1c1', 'cell_mock_r1c2', 'cell_mock_r2c1', 'cell_mock_r2c2'],
              },
            },
          ],
          speaker_notes: [
            { claim_id: null, source_uri: `table:${table.id}`, quote: 'Table slide generated from parsed source table cells.' },
          ],
        },
      ],
    }
    return {
      deck_id: deck.deck_id,
      path: '/mock/slides/deck_mock_table_001.slide.json',
      deck,
      run_id: 'run_mock_table_deck',
      run_dir: '/mock/runs/run_mock_table_deck',
    }
  },
  async applyManualText(_projectId: string, documentId: string, _text: string, _heading = 'Manual correction'): Promise<DocumentMeta> {
    await delay(180)
    mockDocuments = mockDocuments.map((d) =>
      d.id === documentId ? { ...d, status: 'parsed', ocr_required: false, ocr_used: false } : d,
    )
    return mockDocuments.find((d) => d.id === documentId) ?? doc
  },
  async previewDeleteDocument(projectId: string, documentId: string): Promise<DeleteDocumentPreview> {
    await delay(80)
    const target = mockDocuments.find((d) => d.id === documentId)
    if (!target) throw new Error(`Document not found: ${documentId}`)
    return {
      document_id: documentId,
      project_id: projectId,
      filename: target.filename,
      deleted: false,
      removed_claim_ids: [],
      retained_claim_ids: [],
      removed_citation_ids: [],
      removed_claims: [],
      retained_claims: [],
      removed_citations: [],
      file_impacts: [
        {
          kind: 'source_file',
          path: `/mock/sources/${target.filename}`,
          exists: true,
          is_dir: false,
        },
        {
          kind: 'rendered_pages',
          path: `/mock/sources/rendered_pages/${target.id}`,
          exists: Boolean(target.pages?.length),
          is_dir: Boolean(target.pages?.length),
        },
      ],
    }
  },
  async deleteDocument(projectId: string, documentId: string): Promise<DeleteDocumentResult> {
    await delay(120)
    const preview = await mockApi.previewDeleteDocument(projectId, documentId)
    mockDocuments = mockDocuments.filter((d) => d.id !== documentId)
    const { file_impacts, ...result } = preview
    void file_impacts
    return {
      ...result,
      deleted: true,
      removed_files: preview.file_impacts.filter((item) => item.exists).map((item) => item.path),
    }
  },
  async getApiSettings(): Promise<ApiSettings> {
    await delay(80)
    return mockApiSettings
  },
  async saveApiSettings(settings: ApiSettingsUpdate): Promise<ApiSettings> {
    await delay(120)
    mockApiSettings = {
      ...mockApiSettings,
      provider: settings.provider,
      base_url: settings.base_url,
      model: settings.model,
      api_key_configured: settings.clear_api_key ? false : Boolean(settings.api_key) || mockApiSettings.api_key_configured,
    }
    return mockApiSettings
  },
  async testApiSettings(settings: ApiSettingsUpdate): Promise<ApiConnectionTestResult> {
    await delay(180)
    const hasBaseUrl = Boolean(settings.base_url.trim() || mockApiSettings.base_url)
    const hasKey = Boolean(settings.api_key) || mockApiSettings.api_key_configured
    return {
      ok: hasBaseUrl && hasKey,
      provider: settings.provider,
      base_url: settings.base_url,
      model: settings.model,
      status: hasBaseUrl ? (hasKey ? 'connected' : 'missing_api_key') : 'missing_base_url',
      checked_url: hasBaseUrl ? `${settings.base_url.replace(/\/$/, '')}/models` : null,
      http_status: hasBaseUrl && hasKey ? 200 : null,
      model_status: settings.model ? 'unknown' : 'not_checked',
      available_models: hasBaseUrl && hasKey ? ['deepseek-chat', 'deepseek-reasoner'] : [],
      detail: null,
    }
  },
  async getSyncSettings(): Promise<SyncSettings> {
    await delay(80)
    return mockSyncSettings
  },
  async saveSyncSettings(settings: SyncSettingsUpdate): Promise<SyncSettings> {
    await delay(120)
    mockSyncSettings = {
      ...mockSyncSettings,
      provider: settings.provider,
      target_dir: settings.target_dir,
      endpoint_url: settings.endpoint_url,
      bucket: settings.bucket,
      region: settings.region,
      prefix: settings.prefix || 'loamtrace-sync',
      access_key_configured: settings.clear_secret ? false : Boolean(settings.access_key_id) || mockSyncSettings.access_key_configured,
      secret_key_configured: settings.clear_secret ? false : Boolean(settings.secret_access_key) || mockSyncSettings.secret_key_configured,
    }
    return mockSyncSettings
  },
  async testSyncSettings(settings: SyncSettingsUpdate): Promise<SyncSettingsTestResult> {
    await delay(120)
    if (settings.provider === 'local') {
      return {
        ok: Boolean(settings.target_dir.trim() || mockSyncSettings.target_dir),
        provider: settings.provider,
        status: settings.target_dir.trim() || mockSyncSettings.target_dir ? 'ready' : 'missing_target_dir',
        target_dir: settings.target_dir || mockSyncSettings.target_dir,
        missing_fields: [],
        detail: null,
      }
    }
    const missing = ['endpoint_url', 'bucket'].filter((field) => !String(settings[field as keyof SyncSettingsUpdate] || '').trim())
    if (!settings.access_key_id && !mockSyncSettings.access_key_configured) missing.push('access_key_id')
    if (!settings.secret_access_key && !mockSyncSettings.secret_key_configured) missing.push('secret_access_key')
    return {
      ok: missing.length === 0,
      provider: settings.provider,
      status: missing.length === 0 ? 'configuration_valid' : 'missing_required_fields',
      target_dir: null,
      missing_fields: missing,
      detail: missing.length === 0 ? 'S3/R2 provider config saved; upload provider is not enabled in this build.' : null,
    }
  },
  async testConfiguredSyncProviderLive(): Promise<SyncSettingsTestResult> {
    await delay(160)
    if (mockSyncSettings.provider === 'local') {
      return {
        ok: Boolean(mockSyncSettings.target_dir),
        provider: mockSyncSettings.provider,
        status: mockSyncSettings.target_dir ? 'ready' : 'missing_target_dir',
        target_dir: mockSyncSettings.target_dir,
        missing_fields: mockSyncSettings.target_dir ? [] : ['target_dir'],
        detail: null,
      }
    }
    const missing = []
    if (!mockSyncSettings.endpoint_url) missing.push('endpoint_url')
    if (!mockSyncSettings.bucket) missing.push('bucket')
    if (!mockSyncSettings.access_key_configured) missing.push('access_key_id')
    if (!mockSyncSettings.secret_key_configured) missing.push('secret_access_key')
    return {
      ok: missing.length === 0,
      provider: mockSyncSettings.provider,
      status: missing.length === 0 ? 'live_ready' : 'missing_required_fields',
      target_dir: null,
      missing_fields: missing,
      detail: missing.length === 0 ? `Provider list check succeeded with ${mockSyncedSnapshots.length} snapshot(s).` : null,
    }
  },
  async scanRedFlags(_projectId: string, _limit = 20): Promise<AnalysisScanResponse> {
    await delay(180)
    return {
      run_id: 'run_mock_red_flags',
      run_dir: '/mock/runs/run_mock_red_flags',
      findings: [
        {
          id: 'flag_mock_001',
          category: 'customer_concentration',
          severity: 'high',
          chunk_id: 'chunk_077',
          document_id: 'doc_abc',
          source_uri: 'pdf://doc_abc#page=8&chunk=chunk_077',
          quote: 'the top three customers represented 41% of total revenue in 2025',
          reason: 'Matched red flag signal: top three customers',
        },
      ],
    }
  },
  async scanFinancialConsistency(_projectId: string, _limit = 20): Promise<AnalysisScanResponse> {
    await delay(180)
    return {
      run_id: 'run_mock_financial',
      run_dir: '/mock/runs/run_mock_financial',
      findings: [
        {
          id: 'fin_mock_001',
          category: 'financial_inconsistency',
          severity: 'high',
          metric: 'revenue',
          period: '2025',
          values: ['$120million', '$135million'],
          reason: 'Conflicting revenue values found for 2025.',
          observations: [
            {
              id: 'obs_mock_001',
              metric: 'revenue',
              period: '2025',
              value: '$120million',
              value_text: '$120 million',
              chunk_id: 'chunk_123',
              document_id: 'doc_abc',
              source_uri: 'pdf://doc_abc#page=8&chunk=chunk_123',
              quote: 'Revenue was $120 million in 2025.',
            },
            {
              id: 'obs_mock_002',
              metric: 'revenue',
              period: '2025',
              value: '$135million',
              value_text: '$135 million',
              chunk_id: 'chunk_125',
              document_id: 'doc_abc',
              source_uri: 'pdf://doc_abc#page=8&chunk=chunk_125',
              quote: 'Revenue was $135 million in 2025.',
            },
          ],
        },
      ],
      observations: [
        {
          id: 'obs_mock_003',
          metric: 'gross_margin',
          period: '2025',
          value: '61%',
          value_text: '61%',
          chunk_id: 'chunk_123',
          document_id: 'doc_abc',
          source_uri: 'pdf://doc_abc#page=8&chunk=chunk_123',
          quote: 'Gross margin held steady at 61%.',
        },
      ],
    }
  },
  async scanContractClauses(_projectId: string, _limit = 20): Promise<AnalysisScanResponse> {
    await delay(180)
    return {
      run_id: 'run_mock_contract',
      run_dir: '/mock/runs/run_mock_contract',
      findings: [
        {
          id: 'clause_mock_001',
          category: 'contract_clause_mismatch',
          severity: 'medium',
          clause_type: 'termination',
          variants: ['cause_only', 'convenience'],
          reason: 'Conflicting termination variants found across documents.',
          observations: [
            {
              id: 'clause_obs_001',
              clause_type: 'termination',
              variant: 'convenience',
              chunk_id: 'chunk_docx_12',
              document_id: 'doc_risk',
              source_uri: 'docx://doc_risk#paragraph=12',
              quote: 'The agreement may be terminated for convenience.',
            },
            {
              id: 'clause_obs_002',
              clause_type: 'termination',
              variant: 'cause_only',
              chunk_id: 'chunk_077',
              document_id: 'doc_abc',
              source_uri: 'pdf://doc_abc#page=8&chunk=chunk_077',
              quote: 'The agreement may be terminated only for cause.',
            },
          ],
        },
      ],
      observations: [],
    }
  },
  async getRetrievalPreferences(projectId: string): Promise<RetrievalPreferences> {
    await delay(80)
    return mockRetrievalPreferences[projectId] ?? {
      project_id: projectId,
      ...defaultRetrievalPreferences,
      updated_at: null,
    }
  },
  async saveRetrievalPreferences(projectId: string, options: SearchOptions): Promise<RetrievalPreferences> {
    await delay(120)
    const saved = {
      project_id: projectId,
      top_n: options.top_n ?? defaultRetrievalPreferences.top_n,
      rrf_k: options.rrf_k ?? defaultRetrievalPreferences.rrf_k,
      fts_top_n: options.fts_top_n ?? defaultRetrievalPreferences.fts_top_n,
      vector_top_n: options.vector_top_n ?? defaultRetrievalPreferences.vector_top_n,
      keyword_boost: options.keyword_boost ?? defaultRetrievalPreferences.keyword_boost,
      vector_boost: options.vector_boost ?? defaultRetrievalPreferences.vector_boost,
      updated_at: new Date().toISOString(),
    }
    mockRetrievalPreferences = { ...mockRetrievalPreferences, [projectId]: saved }
    return saved
  },
  async getCitationTarget(_projectId: string, citationId: string): Promise<CitationTarget> {
    await delay(80)
    const claim = claims.find((item) => item.citations.some((citation) => citation.id === citationId)) ?? claims[0]
    const citation = claim.citations.find((item) => item.id === citationId) ?? claim.citations[0]
    const chunk = chunks.find((item) => item.id === citation.chunk_id) ?? null
    const document = mockDocuments.find((item) => item.id === citation.document_id)
    if (citation.source_uri.startsWith('docx://')) {
      return {
        citation_id: citation.id,
        claim_id: claim.id,
        claim_status: claim.status,
        claim_text: claim.text,
        document_id: citation.document_id,
        filename: document?.filename,
        mime_type: document?.mime_type,
        ocr_used: false,
        ocr_confidence: null,
        source_uri: citation.source_uri,
        quote: citation.quote,
        scheme: 'docx',
        locator: { paragraph: '12' },
        bbox: null,
        precision: 'paragraph',
        renderable: false,
        location_label: 'paragraph 12',
        chunk,
        paragraph: {
          id: 'block_12',
          block_type: 'paragraph',
          text: chunk?.text ?? citation.quote,
          reading_order: 12,
          heading_path: 'Risk Factors',
        },
      }
    }
    if (citation.source_uri.startsWith('xlsx://')) {
      return {
        citation_id: citation.id,
        claim_id: claim.id,
        claim_status: claim.status,
        claim_text: claim.text,
        document_id: citation.document_id,
        filename: document?.filename,
        mime_type: document?.mime_type,
        ocr_used: false,
        ocr_confidence: null,
        source_uri: citation.source_uri,
        quote: citation.quote,
        scheme: 'xlsx',
        locator: { sheet: 'Revenue', cell: 'B3' },
        bbox: null,
        precision: 'cell',
        renderable: false,
        location_label: 'sheet Revenue, cell B3',
        chunk,
        cells: [
          {
            id: 'cell_mock_b3',
            sheet_name: 'Revenue',
            cell_ref: 'B3',
            row_index: 3,
            col_index: 2,
            text: '148',
            value: { text: '148' },
          },
        ],
      }
    }
    return {
      citation_id: citation.id,
      claim_id: claim.id,
      claim_status: claim.status,
      claim_text: claim.text,
      document_id: citation.document_id,
      filename: document?.filename,
      mime_type: document?.mime_type,
      ocr_used: false,
      ocr_confidence: null,
      source_uri: citation.source_uri,
      quote: citation.quote,
      scheme: 'pdf',
      locator: { page: '8', chunk: citation.chunk_id },
      bbox: citation.bbox_json ?? null,
      precision: citation.bbox_json ? 'bbox' : 'page',
      renderable: true,
      location_label: 'page 8',
      chunk,
      page: { page_number: 8, width: 612, height: 792 },
    }
  },
  async judgeClaimSupport(_projectId: string, claimId: string): Promise<SupportJudgeResponse> {
    await delay(180)
    const claim = claims.find((item) => item.id === claimId) ?? claims[0]
    const judged: Claim = {
      ...claim,
      citations: claim.citations.map((citation) => ({
        ...citation,
        support_judge_label: citation.verified ? 'direct' : 'weak',
        support_judge_reason: citation.verified
          ? 'Mock judge: the quote supports the claim.'
          : 'Mock judge: failed citations remain insufficient.',
      })),
    }
    return {
      judge_status: 'used',
      claim: judged,
      model_error: null,
      applied_count: judged.citations.length,
    }
  },
  async listReviewTasks(_projectId: string, status?: ReviewTaskStatus): Promise<ReviewTask[]> {
    await delay(100)
    return status ? mockReviewTasks.filter((task) => task.status === status) : mockReviewTasks
  },
  async createReviewTask(projectId: string, claimId: string, assignee?: string, priority: ReviewTaskPriority = 'normal'): Promise<ReviewTask> {
    await delay(120)
    const existing = mockReviewTasks.find((task) => task.claim_id === claimId && ['open', 'in_review'].includes(task.status))
    if (existing) {
      existing.assignee = assignee || existing.assignee
      existing.priority = priority
      existing.updated_at = new Date().toISOString()
      return existing
    }
    const claim = claims.find((item) => item.id === claimId)
    const task: ReviewTask = {
      id: `review_mock_${mockReviewTasks.length + 1}`,
      project_id: projectId,
      claim_id: claimId,
      claim_text: claim?.text,
      claim_status: claim?.status,
      status: 'open',
      assignee: assignee || null,
      priority,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      resolved_at: null,
      comment_count: 0,
      comments: [],
    }
    mockReviewTasks = [task, ...mockReviewTasks]
    return task
  },
  async updateReviewTask(_projectId: string, taskId: string, update: { status?: ReviewTaskStatus; assignee?: string; priority?: ReviewTaskPriority }): Promise<ReviewTask> {
    await delay(120)
    const task = mockReviewTasks.find((item) => item.id === taskId)
    if (!task) throw new Error('review_task_not_found')
    if (update.status) task.status = update.status
    if (update.assignee !== undefined) task.assignee = update.assignee
    if (update.priority) task.priority = update.priority
    task.updated_at = new Date().toISOString()
    if (task.status === 'resolved' || task.status === 'dismissed') task.resolved_at = task.updated_at
    return task
  },
  async addReviewComment(_projectId: string, taskId: string, author: string, body: string): Promise<ReviewTask> {
    await delay(120)
    const task = mockReviewTasks.find((item) => item.id === taskId)
    if (!task) throw new Error('review_task_not_found')
    const comment = {
      id: `comment_mock_${(task.comments?.length ?? 0) + 1}`,
      task_id: taskId,
      author,
      body,
      created_at: new Date().toISOString(),
    }
    task.comments = [...(task.comments ?? []), comment]
    task.comment_count = task.comments.length
    task.updated_at = comment.created_at
    return task
  },
  async search(_projectId: string, query: string, options: SearchOptions = {}): Promise<SearchResponse> {
    await delay(200)
    const q = query.trim().toLowerCase()
    if (!q) return { results: chunks.slice(0, options.top_n ?? 12) }
    return {
      results: chunks.filter((c) => c.text.toLowerCase().includes(q)).slice(0, options.top_n ?? 12),
    }
  },
  async generateMemo(_projectId: string, _query: string): Promise<GenerateMemoResponse> {
    await delay(300)
    return { run_id: 'run_001', answer: memoMarkdown, claims, model_status: 'mock' }
  },
  async verifyRun(_runId: string): Promise<{ claims: Claim[] }> {
    await delay(200)
    return { claims }
  },
  async getMemo(_projectId: string): Promise<MemoResponse> {
    await delay(120)
    return { markdown: memoMarkdown, claims }
  },
  async listClaims(_projectId: string): Promise<Claim[]> {
    await delay(120)
    return claims
  },
  async generateSlides(_projectId: string, title: string, claimIds?: string[]): Promise<GenerateSlidesResponse> {
    await delay(220)
    const deck = makeMockDeck(title, claimIds)
    return {
      deck_id: deck.deck_id,
      path: '/mock/slides/deck_mock_001.slide.json',
      deck,
      run_id: 'run_mock_generate_slides',
      run_dir: '/mock/runs/run_mock_generate_slides',
    }
  },
  async listSlideTemplates(): Promise<SlideTemplate[]> {
    await delay(80)
    return slideTemplates
  },
  async generateTemplateSlides(_projectId: string, templateId: string, title?: string, claimIds?: string[]): Promise<GenerateSlidesResponse> {
    await delay(240)
    const template = slideTemplates.find((item) => item.id === templateId) ?? slideTemplates[0]
    const deck = makeMockDeck(title || template.name, claimIds)
    deck.template_id = template.id
    deck.template_name = template.name
    deck.slides = deck.slides.filter((slide) => template.layouts.includes(slide.layout) || slide.layout === 'claim_with_evidence')
    return {
      deck_id: deck.deck_id,
      path: '/mock/slides/deck_mock_template.slide.json',
      deck,
      run_id: 'run_mock_generate_template_slides',
      run_dir: '/mock/runs/run_mock_generate_template_slides',
    }
  },
  async getSlides(_projectId: string, _deckId: string): Promise<Deck> {
    await delay(100)
    return makeMockDeck('Evidence Deck')
  },
  async exportPptx(_projectId: string, deckId: string): Promise<ExportPptxResponse> {
    await delay(180)
    return { deck_id: deckId, path: '/mock/slides/deck_mock_001.pptx', status: 'exported' }
  },
  async exportResearchPackage(_projectId: string, deckId?: string | null): Promise<ExportResearchPackageResponse> {
    await delay(180)
    return {
      package_id: 'export_mock_001',
      path: '/mock/exports/export_mock_001',
      archive_path: '/mock/exports/export_mock_001.zip',
      manifest: {
        package_id: 'export_mock_001',
        project_id: project.id,
        created_at: '2026-06-08T00:00:00Z',
        deck_id: deckId ?? null,
        counts: { documents: 3, source_files: 3, claims: claims.length, verified_claims: 2, citations: 3, citation_targets: 3, slides: deckId ? 2 : 0 },
        files: [
          'claims.json',
          'citations.json',
          'citation_targets.json',
          'deck.slide.json',
          'documents.json',
          'manifest.json',
          'memo.md',
          'source_files.json',
          'sources/original/doc_pdf_annual-report.pdf',
          'workflow_status.json',
        ],
      },
    }
  },
  async exportProjectSnapshot(_projectId: string, includeIndex = true): Promise<ExportProjectSnapshotResponse> {
    await delay(180)
    return {
      snapshot_id: 'snapshot_mock_001',
      path: '/mock/exports/snapshot_mock_001',
      archive_path: '/mock/exports/snapshot_mock_001.zip',
      manifest: {
        snapshot_id: 'snapshot_mock_001',
        project_id: project.id,
        created_at: '2026-06-09T00:00:00Z',
        format: 'loamtrace-project-snapshot-v1',
        include_index: includeIndex,
        source_root: '/mock/projects/project_001',
        counts: { files: 8, bytes: 42000 },
        files: ['project.json', 'notes/memo.md', 'slides/deck_mock_001.slide.json', 'index/project.sqlite'],
      },
    }
  },
  async importProjectSnapshot(_archivePath: string, projectId?: string, overwrite = false): Promise<ImportProjectSnapshotResponse> {
    await delay(180)
    const restoredId = projectId?.trim() || 'restored_project_001'
    if (!overwrite && mockProjects.some((item) => item.id === restoredId)) {
      throw new Error('project_already_exists')
    }
    mockProjects = [
      {
        id: restoredId,
        name: restoredId,
        created_at: new Date().toISOString(),
      },
      ...mockProjects.filter((item) => item.id !== restoredId),
    ]
    return {
      project_id: restoredId,
      root: `/mock/projects/${restoredId}`,
      source_project_id: project.id,
      snapshot_id: 'snapshot_mock_001',
      file_count: 8,
      name: restoredId,
      manifest: {
        snapshot_id: 'snapshot_mock_001',
        project_id: project.id,
        created_at: '2026-06-09T00:00:00Z',
        format: 'loamtrace-project-snapshot-v1',
        include_index: true,
        source_root: '/mock/projects/project_001',
        counts: { files: 8, bytes: 42000 },
        files: ['project.json', 'notes/memo.md', 'slides/deck_mock_001.slide.json', 'index/project.sqlite'],
      },
    }
  },
  async pushProjectSnapshot(projectId: string, targetDir: string, includeIndex = true): Promise<PushProjectSnapshotResponse> {
    await delay(160)
    const snapshotId = `snapshot_mock_${mockSyncedSnapshots.length + 1}`
    const archivePath = `${targetDir}/loamtrace-sync/snapshots/${projectId}/${snapshotId}.zip`
    const metadataPath = `${targetDir}/loamtrace-sync/snapshots/${projectId}/${snapshotId}.json`
    const manifest: ExportProjectSnapshotResponse['manifest'] = {
      snapshot_id: snapshotId,
      project_id: projectId,
      created_at: new Date().toISOString(),
      format: 'loamtrace-project-snapshot-v1',
      include_index: includeIndex,
      source_root: `/mock/projects/${projectId}`,
      counts: { files: 8, bytes: 42000 },
      files: ['project.json', 'notes/memo.md', 'slides/deck_mock_001.slide.json', 'index/project.sqlite'],
    }
    const synced: SyncSnapshot = {
      snapshot_id: snapshotId,
      project_id: projectId,
      source_project_id: projectId,
      created_at: manifest.created_at,
      format: manifest.format,
      archive_path: archivePath,
      metadata_path: metadataPath,
      size_bytes: 42000,
      archive_sha256: `mock_sha256_${snapshotId}`,
      integrity_status: 'ok',
      available: true,
      manifest,
    }
    mockSyncedSnapshots = [synced, ...mockSyncedSnapshots.filter((item) => item.snapshot_id !== snapshotId)]
    return {
      snapshot_id: snapshotId,
      project_id: projectId,
      target_dir: targetDir,
      archive_path: archivePath,
      metadata_path: metadataPath,
      size_bytes: 42000,
      archive_sha256: synced.archive_sha256,
      manifest,
    }
  },
  async listSyncedSnapshots(_targetDir: string, projectId?: string): Promise<SyncSnapshot[]> {
    await delay(100)
    return projectId ? mockSyncedSnapshots.filter((item) => item.project_id === projectId) : mockSyncedSnapshots
  },
  async pullProjectSnapshot(_targetDir: string, snapshotId: string, projectId?: string, overwrite = false): Promise<PullProjectSnapshotResponse> {
    await delay(160)
    const snapshot = mockSyncedSnapshots.find((item) => item.snapshot_id === snapshotId)
    if (!snapshot) throw new Error('synced_snapshot_not_found')
    const restored = await this.importProjectSnapshot(snapshot.archive_path, projectId || snapshot.project_id, overwrite)
    return { ...restored, sync_snapshot: snapshot }
  },
  async deleteSyncedSnapshot(_targetDir: string, snapshotId: string): Promise<SyncSnapshot & { deleted: boolean }> {
    await delay(120)
    const snapshot = mockSyncedSnapshots.find((item) => item.snapshot_id === snapshotId)
    if (!snapshot) throw new Error('synced_snapshot_not_found')
    mockSyncedSnapshots = mockSyncedSnapshots.filter((item) => item.snapshot_id !== snapshotId)
    return { ...snapshot, deleted: true }
  },
  async pushProviderProjectSnapshot(projectId: string, includeIndex = true): Promise<PushProjectSnapshotResponse> {
    const target = mockSyncSettings.provider === 'local' ? mockSyncSettings.target_dir || '/mock/sync-target' : `s3://${mockSyncSettings.bucket || 'mock-bucket'}`
    const response = await this.pushProjectSnapshot(projectId, target, includeIndex)
    if (mockSyncSettings.provider === 's3-compatible') {
      const snapshot = mockSyncedSnapshots.find((item) => item.snapshot_id === response.snapshot_id)
      if (snapshot) {
        snapshot.archive_path = `${target}/loamtrace-sync/snapshots/${projectId}/${response.snapshot_id}.zip`
        snapshot.metadata_path = `${target}/loamtrace-sync/snapshots/${projectId}/${response.snapshot_id}.json`
      }
      return {
        ...response,
        archive_path: `${target}/loamtrace-sync/snapshots/${projectId}/${response.snapshot_id}.zip`,
        metadata_path: `${target}/loamtrace-sync/snapshots/${projectId}/${response.snapshot_id}.json`,
        object_key: `loamtrace-sync/snapshots/${projectId}/${response.snapshot_id}.zip`,
        metadata_key: `loamtrace-sync/snapshots/${projectId}/${response.snapshot_id}.json`,
      }
    }
    return response
  },
  async listProviderSyncedSnapshots(projectId?: string): Promise<SyncSnapshot[]> {
    await delay(100)
    return projectId ? mockSyncedSnapshots.filter((item) => item.project_id === projectId) : mockSyncedSnapshots
  },
  async pullProviderProjectSnapshot(snapshotId: string, projectId?: string, overwrite = false): Promise<PullProjectSnapshotResponse> {
    await delay(160)
    return this.pullProjectSnapshot(mockSyncSettings.target_dir || '/mock/sync-target', snapshotId, projectId, overwrite)
  },
  async deleteProviderSyncedSnapshot(snapshotId: string): Promise<SyncSnapshot & { deleted: boolean }> {
    await delay(120)
    return this.deleteSyncedSnapshot(mockSyncSettings.target_dir || '/mock/sync-target', snapshotId)
  },
  async listExportArtifacts(_projectId: string): Promise<ExportArtifact[]> {
    await delay(100)
    return [
      {
        id: 'pptx:deck_mock_001.pptx',
        type: 'pptx',
        label: 'PPTX',
        name: 'deck_mock_001.pptx',
        path: '/mock/slides/deck_mock_001.pptx',
        deck_id: 'deck_mock_001',
        package_id: null,
        created_at: '2026-06-08T00:03:00Z',
        modified_at: '2026-06-08T00:03:00Z',
        size_bytes: 120000,
        open_kind: 'file',
      },
      {
        id: 'research_package_zip:export_mock_001.zip',
        type: 'research_package_zip',
        label: '研究包 ZIP',
        name: 'export_mock_001.zip',
        path: '/mock/exports/export_mock_001.zip',
        package_id: 'export_mock_001',
        deck_id: 'deck_mock_001',
        created_at: '2026-06-08T00:04:00Z',
        modified_at: '2026-06-08T00:04:00Z',
        size_bytes: 98000,
        open_kind: 'file',
      },
      {
        id: 'project_snapshot_zip:snapshot_mock_001.zip',
        type: 'project_snapshot_zip',
        label: '项目快照 ZIP',
        name: 'snapshot_mock_001.zip',
        path: '/mock/exports/snapshot_mock_001.zip',
        package_id: 'snapshot_mock_001',
        deck_id: null,
        created_at: '2026-06-09T00:00:00Z',
        modified_at: '2026-06-09T00:00:00Z',
        size_bytes: 42000,
        open_kind: 'file',
      },
      {
        id: 'research_package:export_mock_001',
        type: 'research_package',
        label: '研究包目录',
        name: 'export_mock_001',
        path: '/mock/exports/export_mock_001',
        package_id: 'export_mock_001',
        deck_id: 'deck_mock_001',
        created_at: '2026-06-08T00:04:00Z',
        modified_at: '2026-06-08T00:04:00Z',
        size_bytes: null,
        open_kind: 'directory',
      },
    ]
  },
  async listAudit(_projectId: string, limit: number): Promise<AuditEvent[]> {
    await delay(80)
    return [
      {
        id: 'audit_mock_003',
        ts: '2026-06-08T09:35:00Z',
        type: 'citation_replaced',
        payload_json: JSON.stringify({ claim_id: 'claim_002', citation_id: 'citation_002', chunk_id: 'chunk_077' }),
      },
      {
        id: 'audit_mock_002',
        ts: '2026-06-08T09:32:00Z',
        type: 'claim_blocked',
        payload_json: JSON.stringify({ claim_id: 'claim_002', reason: 'number_mismatch' }),
      },
      {
        id: 'audit_mock_001',
        ts: '2026-06-08T09:30:00Z',
        type: 'memo_generated',
        payload_json: JSON.stringify({ run_id: 'run_001', query: 'revenue growth' }),
      },
    ].slice(0, limit)
  },
}

function normalizeTags(tags: string[]): string[] {
  return Array.from(
    new Set(
      tags
        .map((tag) => tag.trim().toLowerCase().replace(/\s+/g, '-'))
        .filter(Boolean),
    ),
  ).sort()
}
