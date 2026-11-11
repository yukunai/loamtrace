// 与后端契约对齐的类型（TEAM_NOTES §契约 / 计划书 §7）。
// 后端如改字段名，请先在 TEAM_NOTES 协商，再同步这里。

/** 归一化到 [0,1] 的坐标框（计划书 §7.2） */
export interface BBox {
  page: number
  x0: number
  y0: number
  x1: number
  y1: number
}

export interface Project {
  id: string
  name: string
  created_at?: string
  root?: string
}

export type DocStatus = 'imported' | 'parsing' | 'parsed' | 'failed'

export interface Page {
  page_number: number
  width: number
  height: number
  render_path?: string
  text_layer_available?: boolean
}

export interface DocumentMeta {
  id: string
  project_id: string
  filename: string
  mime_type?: string
  status: DocStatus
  ocr_used?: boolean
  ocr_confidence?: number | null
  ocr_required?: boolean
  parser_version?: string | null
  pages?: Page[]
}

export interface DeleteFileImpact {
  kind: 'source_file' | 'rendered_pages' | string
  path: string
  exists: boolean
  is_dir: boolean
}

export interface DeleteClaimImpact {
  id: string
  text: string
  status: ClaimStatus | string
}

export interface DeleteDocumentPreview {
  document_id: string
  project_id: string
  filename: string
  deleted: false
  removed_claim_ids: string[]
  retained_claim_ids: string[]
  removed_citation_ids: string[]
  removed_claims: DeleteClaimImpact[]
  retained_claims: DeleteClaimImpact[]
  removed_citations: Citation[]
  file_impacts: DeleteFileImpact[]
}

export interface DeleteDocumentResult extends Omit<DeleteDocumentPreview, 'deleted' | 'file_impacts'> {
  deleted: true
  removed_files: string[]
}

export interface AssetItem {
  id: string
  sha256: string
  filename: string
  mime_type: string
  storage_path: string
  tags: string[]
  source_refs: Array<{ project_id: string; document_id: string }>
  created_at: string
  updated_at: string
}

export interface ImportAssetResponse {
  asset: AssetItem
  document: DocumentMeta
}

export interface TableMeta {
  id: string
  document_id: string
  page_id?: string | null
  bbox_json?: BBox | string | null
  caption?: string | null
  parser?: string | null
  document_filename?: string | null
  document_mime_type?: string | null
  cell_count: number
  row_count: number
  col_count: number
  sheet_name?: string | null
  preview: string[][]
}

export interface Chunk {
  id: string
  document_id: string
  text: string
  source_uri: string
  page_start?: number
  page_end?: number
  /** bbox union；后端可能返回 JSON 字符串或对象，前端两者都兼容 */
  bbox_json?: BBox | string | null
  heading_path?: string
  score?: number
  retrieval_sources?: string[]
}

export type ClaimStatus =
  | 'draft'
  | 'verified'
  | 'needs_review'
  | 'blocked'
  | 'approved'
  | 'rejected'

export type CitationStatus =
  | 'unverified'
  | 'verified'
  | 'fuzzy_verified'
  | 'failed'
  | 'manual_approved'

export type VerificationMethod =
  | 'normalized_exact'
  | 'fuzzy_quote_match'
  | 'manual_approved'
  | null

export interface Citation {
  id: string
  claim_id: string
  chunk_id: string
  document_id: string
  quote: string
  source_uri: string
  bbox_json?: BBox | string | null
  verified: boolean
  verification_method?: VerificationMethod
  verification_score?: number | null
  failure_reason?: string | null
  support_level?: 'direct' | 'partial' | 'weak' | string | null
  support_reason?: string | null
  support_judge_label?: 'direct' | 'partial' | 'weak' | string | null
  support_judge_reason?: string | null
  reviewer?: string | null
  review_note?: string | null
  reviewed_at?: string | null
}

export interface CitationTarget {
  citation_id: string
  claim_id: string
  claim_status: ClaimStatus | string
  claim_text: string
  document_id: string
  filename?: string | null
  mime_type?: string | null
  ocr_used?: boolean
  ocr_confidence?: number | null
  source_uri: string
  quote: string
  scheme: 'pdf' | 'docx' | 'xlsx' | 'md' | 'html' | 'text' | string
  locator: Record<string, string>
  bbox?: BBox | string | null
  precision: string
  renderable: boolean
  location_label: string
  chunk?: Chunk | null
  page?: Page | { page_number: number }
  paragraph?: {
    id?: string
    block_type?: string
    text?: string
    reading_order?: number
    heading_path?: string | null
  }
  block?: {
    id?: string
    block_type?: string
    text?: string
    reading_order?: number
    heading_path?: string | null
  }
  table?: Record<string, unknown>
  cells?: Array<{
    id: string
    sheet_name?: string | null
    cell_ref?: string | null
    row_index?: number | null
    col_index?: number | null
    text?: string | null
    value?: unknown
  }>
}

export interface Claim {
  id: string
  text: string
  type?: string
  calculation_formula?: string | null
  source_numbers?: string[]
  status: ClaimStatus
  citations: Citation[]
}

export interface ClaimCorrectionInput {
  text?: string
  citation_id?: string
  chunk_id?: string
  quote?: string
  reviewer?: string
  note?: string
}

export type ReviewTaskStatus = 'open' | 'in_review' | 'resolved' | 'dismissed'
export type ReviewTaskPriority = 'low' | 'normal' | 'high'

export interface ReviewComment {
  id: string
  task_id: string
  author: string
  body: string
  created_at: string
}

export interface ReviewTask {
  id: string
  project_id: string
  claim_id: string
  claim_text?: string
  claim_status?: ClaimStatus | string
  status: ReviewTaskStatus
  assignee?: string | null
  priority: ReviewTaskPriority
  created_at: string
  updated_at: string
  resolved_at?: string | null
  comment_count: number
  comments?: ReviewComment[]
}

export interface SearchResponse {
  results: Chunk[]
}

export interface SearchOptions {
  top_n?: number
  rrf_k?: number
  fts_top_n?: number
  vector_top_n?: number
  keyword_boost?: number
  vector_boost?: number
}

export interface RetrievalPreferences {
  project_id: string
  top_n: number
  rrf_k: number
  fts_top_n: number
  vector_top_n: number
  keyword_boost: number
  vector_boost: number
  updated_at?: string | null
}

export interface GenerateMemoResponse {
  run_id: string
  answer: string
  claims: Claim[]
  model_status?: string
  model_error?: string | null
}

export interface MemoResponse {
  markdown: string
  claims: Claim[]
}

export interface SupportJudgeResponse {
  judge_status:
    | 'used'
    | 'failed'
    | 'not_configured'
    | 'no_verified_citations'
    | 'no_applicable_judgements'
    | string
  claim: Claim
  model_error?: string | null
  applied_count?: number
}

export interface AnalysisObservation {
  id?: string
  metric?: string
  period?: string
  value?: string
  value_text?: string
  clause_type?: string
  variant?: string
  chunk_id: string
  document_id: string
  source_uri: string
  quote: string
}

export interface AnalysisFinding {
  id: string
  category: string
  severity: 'high' | 'medium' | 'low' | string
  reason: string
  chunk_id?: string
  document_id?: string
  source_uri?: string
  quote?: string
  metric?: string
  period?: string
  values?: string[]
  clause_type?: string
  variants?: string[]
  observations?: AnalysisObservation[]
}

export interface AnalysisScanResponse {
  run_id: string
  run_dir?: string
  findings: AnalysisFinding[]
  observations?: AnalysisObservation[]
}

export interface UiPreferences {
  project_id: string
  column_widths: {
    sidebar: number
    memo: number
    viewer: number
  }
  updated_at?: string | null
}

export interface ApiSettings {
  provider: string
  base_url: string
  model: string
  api_key_configured: boolean
  settings_path?: string
}

export interface ApiSettingsUpdate {
  provider: string
  base_url: string
  model: string
  api_key?: string
  clear_api_key?: boolean
}

export interface ApiConnectionTestResult {
  ok: boolean
  provider: string
  base_url: string
  model: string
  status: string
  checked_url?: string | null
  http_status?: number | null
  model_status: 'not_checked' | 'found' | 'not_found' | 'unknown'
  available_models: string[]
  detail?: string | null
}

export interface SyncSettings {
  provider: 'local' | 's3-compatible' | string
  target_dir: string
  endpoint_url: string
  bucket: string
  region: string
  prefix: string
  access_key_configured: boolean
  secret_key_configured: boolean
  settings_path?: string
}

export interface SyncSettingsUpdate {
  provider: 'local' | 's3-compatible' | string
  target_dir: string
  endpoint_url: string
  bucket: string
  region: string
  prefix: string
  access_key_id?: string
  secret_access_key?: string
  clear_secret?: boolean
}

export interface SyncSettingsTestResult {
  ok: boolean
  provider: string
  status: string
  target_dir?: string | null
  missing_fields: string[]
  detail?: string | null
}

export interface BackendCapabilityStatus {
  backend?: string
  available?: boolean
  sqlite_vec_available?: boolean
  reason?: string
  [key: string]: unknown
}

export interface HealthStatus {
  status: string
  vector?: BackendCapabilityStatus
  ocr?: BackendCapabilityStatus
}

export type WorkflowStepStatus =
  | 'not_started'
  | 'ready'
  | 'in_progress'
  | 'needs_review'
  | 'blocked'
  | 'complete'

export interface WorkflowStep {
  key: string
  label: string
  status: WorkflowStepStatus
  detail: string
  counts: Record<string, number>
}

export interface WorkflowStatus {
  project_id: string
  overall_status: WorkflowStepStatus
  steps: WorkflowStep[]
  counts: Record<string, number>
  blockers?: Array<{ key: string; severity: WorkflowStepStatus | string; message: string }>
  next_actions?: Array<{ key: string; label: string; step: string }>
  latest_audit?: AuditEvent | null
}

export interface ChartDataSource {
  cell_ids?: string[]
  table_id?: string
  table_ids?: string[]
}

export interface ChartPoint {
  label: string
  value: number | string
  cell_id?: string
}

export interface ChartSeries {
  name: string
  points: ChartPoint[]
}

export interface GenerateChartDataResponse {
  run_id: string
  run_dir?: string
  chart: SlideElement
}

export interface SlideElement {
  type: string
  role?: string
  text?: string
  claim_id?: string | null
  rows?: string[][]
  data?: {
    rows?: string[][]
    series?: ChartSeries[]
  }
  chart_type?: string
  data_source?: ChartDataSource | null
  series?: ChartSeries[]
  review_status?: string
  failure_reason?: string | null
}

export interface SlideSpeakerNote {
  claim_id?: string | null
  source_uri?: string
  quote?: string
}

export interface Slide {
  id: string
  layout: string
  title: string
  main_claim_id?: string | null
  elements: SlideElement[]
  speaker_notes: SlideSpeakerNote[]
}

export interface Deck {
  deck_id: string
  title: string
  slides: Slide[]
  template_id?: string
  template_name?: string
}

export interface GenerateSlidesResponse {
  deck_id: string
  path: string
  deck: Deck
  run_id?: string
  run_dir?: string
}

export interface SlideTemplate {
  id: string
  name: string
  description: string
  recommended_claims: number
  layouts: string[]
}

export interface ExportPptxResponse {
  deck_id: string
  path: string
  status: 'exported'
  run_id?: string
  run_dir?: string
}

export interface ExportResearchPackageResponse {
  package_id: string
  path: string
  archive_path?: string
  run_id?: string
  run_dir?: string
  manifest: {
    package_id: string
    project_id: string
    created_at: string
    deck_id?: string | null
    counts: Record<string, number>
    files: string[]
  }
}

export interface ExportProjectSnapshotResponse {
  snapshot_id: string
  path: string
  archive_path: string
  run_id?: string
  run_dir?: string
  manifest: {
    snapshot_id: string
    project_id: string
    created_at: string
    format: string
    include_index: boolean
    source_root: string
    counts: Record<string, number>
    files: string[]
  }
}

export interface ImportProjectSnapshotResponse {
  project_id: string
  root: string
  source_project_id: string
  snapshot_id?: string | null
  file_count: number
  name: string
  manifest: {
    snapshot_id?: string | null
    project_id: string
    created_at?: string
    format: string
    include_index?: boolean
    source_root?: string
    counts?: Record<string, number>
    files: string[]
  }
}

export interface SyncSnapshot {
  snapshot_id: string
  project_id: string
  source_project_id: string
  created_at?: string
  format?: string
  archive_path: string
  metadata_path: string
  size_bytes?: number | null
  expected_size_bytes?: number | null
  actual_size_bytes?: number | null
  archive_sha256?: string | null
  integrity_status?: 'ok' | 'unchecked' | 'unknown' | 'missing' | 'size_mismatch' | 'checksum_mismatch' | string
  available: boolean
  manifest: ExportProjectSnapshotResponse['manifest'] | Record<string, unknown>
}

export interface PushProjectSnapshotResponse {
  snapshot_id: string
  project_id: string
  target_dir?: string
  archive_path: string
  metadata_path: string
  object_key?: string | null
  metadata_key?: string | null
  size_bytes: number
  archive_sha256?: string | null
  manifest: ExportProjectSnapshotResponse['manifest']
}

export interface PullProjectSnapshotResponse extends ImportProjectSnapshotResponse {
  sync_snapshot: SyncSnapshot
}

export interface ExportArtifact {
  id: string
  type: 'pptx' | 'research_package' | 'research_package_zip' | 'project_snapshot_zip' | string
  label: string
  name: string
  path: string
  package_id?: string | null
  deck_id?: string | null
  created_at: string
  modified_at: string
  size_bytes?: number | null
  open_kind: 'file' | 'directory' | string
}

export interface AuditEvent {
  id?: string
  ts: string
  type: string
  payload_json?: string
  [key: string]: unknown
}

/** 把 bbox_json 兼容性解析为 BBox|null */
export function parseBBox(b: BBox | string | null | undefined): BBox | null {
  if (!b) return null
  if (typeof b === 'string') {
    try {
      const o = JSON.parse(b)
      return isBBox(o) ? o : null
    } catch {
      return null
    }
  }
  return isBBox(b) ? b : null
}

function isBBox(o: unknown): o is BBox {
  if (!o || typeof o !== 'object') return false
  const b = o as Record<string, unknown>
  return (
    typeof b.x0 === 'number' &&
    typeof b.y0 === 'number' &&
    typeof b.x1 === 'number' &&
    typeof b.y1 === 'number'
  )
}
