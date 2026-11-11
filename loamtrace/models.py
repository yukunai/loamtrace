from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    project_id: str = Field(default="default")
    name: str = Field(default="Default Project")


class ImportDocumentRequest(BaseModel):
    project_id: str
    file_path: str


class ParseDocumentRequest(BaseModel):
    project_id: str


class SearchRequest(BaseModel):
    project_id: str
    query: str
    top_n: Optional[int] = Field(default=None, ge=1, le=50)
    rrf_k: Optional[int] = Field(default=None, ge=1, le=500)
    fts_top_n: Optional[int] = Field(default=None, ge=1, le=200)
    vector_top_n: Optional[int] = Field(default=None, ge=1, le=200)
    keyword_boost: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    vector_boost: Optional[float] = Field(default=None, ge=0.0, le=10.0)


class RetrievalPreferencesRequest(BaseModel):
    top_n: int = Field(default=12, ge=1, le=50)
    rrf_k: int = Field(default=60, ge=1, le=500)
    fts_top_n: int = Field(default=50, ge=1, le=200)
    vector_top_n: int = Field(default=50, ge=1, le=200)
    keyword_boost: float = Field(default=1.0, ge=0.0, le=10.0)
    vector_boost: float = Field(default=1.0, ge=0.0, le=10.0)


class GenerateMemoRequest(BaseModel):
    project_id: str
    query: str
    top_n: int = Field(default=5, ge=1, le=12)


class CitationInput(BaseModel):
    chunk_id: str
    quote: str
    source_uri: Optional[str] = None


class ClaimInput(BaseModel):
    id: Optional[str] = None
    text: str
    type: Optional[str] = None
    calculation_formula: Optional[str] = Field(default=None, max_length=1000)
    source_numbers: list[str] = Field(default_factory=list)
    citations: list[CitationInput]


class VerifyRunRequest(BaseModel):
    project_id: str
    claims: list[ClaimInput]


class RenderMemoRequest(BaseModel):
    project_id: str
    claim_ids: Optional[list[str]] = None


class CitationReviewRequest(BaseModel):
    project_id: str
    action: str = Field(pattern="^(approve|reject)$")
    reviewer: str = Field(default="reviewer", max_length=120)
    note: Optional[str] = Field(default=None, max_length=2000)


class CitationReplaceRequest(BaseModel):
    project_id: str
    chunk_id: str
    quote: str


class ClaimCorrectionRequest(BaseModel):
    project_id: str
    text: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    citation_id: Optional[str] = None
    chunk_id: Optional[str] = None
    quote: Optional[str] = Field(default=None, min_length=1, max_length=20000)
    reviewer: str = Field(default="reviewer", max_length=120)
    note: Optional[str] = Field(default=None, max_length=2000)


class ClaimSupportJudgeRequest(BaseModel):
    project_id: str


class ManualTextRequest(BaseModel):
    project_id: str
    text: str = Field(min_length=1, max_length=200000)
    heading: Optional[str] = Field(default="Manual correction", max_length=200)


class CreateReviewTaskRequest(BaseModel):
    project_id: str
    claim_id: str
    assignee: Optional[str] = Field(default=None, max_length=120)
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")


class UpdateReviewTaskRequest(BaseModel):
    project_id: str
    status: Optional[str] = Field(default=None, pattern="^(open|in_review|resolved|dismissed)$")
    assignee: Optional[str] = Field(default=None, max_length=120)
    priority: Optional[str] = Field(default=None, pattern="^(low|normal|high)$")


class AddReviewCommentRequest(BaseModel):
    project_id: str
    author: str = Field(default="reviewer", max_length=120)
    body: str = Field(min_length=1, max_length=4000)


class CreateAssetFromDocumentRequest(BaseModel):
    project_id: str
    document_id: str
    tags: list[str] = Field(default_factory=list)


class ImportAssetRequest(BaseModel):
    project_id: str
    asset_id: str


class UpdateAssetTagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)


class BootstrapAdminRequest(BaseModel):
    project_id: str = Field(default="default", max_length=120)
    email: str = Field(default="local@loamtrace.local", max_length=320)
    display_name: str = Field(default="Local Admin", max_length=200)


class UpsertUserRequest(BaseModel):
    project_id: str = Field(default="default", max_length=120)
    user_id: Optional[str] = Field(default=None, max_length=120)
    email: str = Field(max_length=320)
    display_name: Optional[str] = Field(default=None, max_length=200)


class UpsertTeamRequest(BaseModel):
    project_id: str = Field(default="default", max_length=120)
    team_id: Optional[str] = Field(default=None, max_length=120)
    name: str = Field(max_length=200)


class SetTeamMemberRequest(BaseModel):
    project_id: str = Field(default="default", max_length=120)
    team_id: str = Field(max_length=120)
    user_id: str = Field(max_length=120)
    role: str = Field(pattern="^(owner|admin|member|viewer)$")


class SetProjectAclRequest(BaseModel):
    project_id: str = Field(default="default", max_length=120)
    principal_type: str = Field(pattern="^(team|user)$")
    principal_id: str = Field(max_length=120)
    role: str = Field(pattern="^(owner|editor|reviewer|viewer)$")


class EnqueueJobRequest(BaseModel):
    project_id: str = Field(default="default", max_length=120)
    job_type: str = Field(pattern="^(parse_document|ocr_document|generate_memo|export_pptx|export_research_package|export_project_snapshot)$")
    input: dict = Field(default_factory=dict)


class UpdateJobStatusRequest(BaseModel):
    project_id: str = Field(default="default", max_length=120)
    status: str = Field(pattern="^(running|succeeded|failed|canceled)$")
    output: Optional[dict] = None
    error: Optional[str] = Field(default=None, max_length=4000)


class CancelJobRequest(BaseModel):
    project_id: str = Field(default="default", max_length=120)


class RunNextJobRequest(BaseModel):
    project_id: str = Field(default="default", max_length=120)
    job_type: str = Field(default="parse_document", pattern="^(parse_document|ocr_document|generate_memo|export_pptx|export_research_package|export_project_snapshot)$")


class RunWorkerLoopRequest(BaseModel):
    project_id: str = Field(default="default", max_length=120)
    job_type: Optional[str] = Field(default=None, pattern="^(parse_document|ocr_document|generate_memo|export_pptx|export_research_package|export_project_snapshot)$")
    max_jobs: int = Field(default=10, ge=1, le=100)
    idle_rounds: int = Field(default=1, ge=1, le=100)
    poll_interval_seconds: float = Field(default=0.0, ge=0, le=10)


class RecoverStaleRunningJobsRequest(BaseModel):
    project_id: str = Field(default="default", max_length=120)
    older_than_seconds: int = Field(default=3600, ge=1, le=604800)
    limit: int = Field(default=100, ge=1, le=500)


class GenerateChartDataRequest(BaseModel):
    project_id: str
    table_id: str
    label_column: int = Field(default=0, ge=0)
    value_columns: Optional[list[int]] = None
    chart_type: str = Field(default="line", pattern="^(line|bar)$")


class RedFlagScanRequest(BaseModel):
    project_id: str
    limit: int = Field(default=20, ge=1, le=100)


class FinancialConsistencyScanRequest(BaseModel):
    project_id: str
    limit: int = Field(default=20, ge=1, le=100)


class ContractClauseScanRequest(BaseModel):
    project_id: str
    limit: int = Field(default=20, ge=1, le=100)


class ColumnWidths(BaseModel):
    sidebar: int = Field(ge=160, le=460)
    memo: int = Field(ge=260, le=760)
    viewer: int = Field(ge=320, le=1100)


class UiPreferencesRequest(BaseModel):
    column_widths: ColumnWidths


class ApiSettingsRequest(BaseModel):
    provider: str = Field(default="openai-compatible", max_length=80)
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    api_key: Optional[str] = Field(default=None, max_length=4096)
    clear_api_key: bool = Field(default=False)


class GenerateSlidesRequest(BaseModel):
    project_id: str
    title: str = Field(default="Research Evidence Deck")
    claim_ids: Optional[list[str]] = None


class GenerateTemplateSlidesRequest(BaseModel):
    project_id: str
    template_id: str
    title: Optional[str] = None
    claim_ids: Optional[list[str]] = None


class GenerateChartDeckRequest(BaseModel):
    project_id: str
    title: str = Field(default="Source Chart Deck")
    chart: dict


class GenerateTableDeckRequest(BaseModel):
    project_id: str
    table_id: str
    title: str = Field(default="Source Table Deck")
    max_rows: int = Field(default=8, ge=1, le=25)
    max_cols: int = Field(default=6, ge=1, le=12)


class ExportPptxRequest(BaseModel):
    project_id: str
    deck_id: str


class ExportResearchPackageRequest(BaseModel):
    project_id: str
    deck_id: Optional[str] = None


class ExportProjectSnapshotRequest(BaseModel):
    project_id: str
    include_index: bool = Field(default=True)


class ImportProjectSnapshotRequest(BaseModel):
    archive_path: str
    project_id: Optional[str] = Field(default=None, max_length=120)
    overwrite: bool = Field(default=False)


class PushProjectSnapshotRequest(BaseModel):
    project_id: str
    target_dir: str
    include_index: bool = Field(default=True)


class PullProjectSnapshotRequest(BaseModel):
    target_dir: str
    snapshot_id: str
    project_id: Optional[str] = Field(default=None, max_length=120)
    overwrite: bool = Field(default=False)


class DeleteSyncedSnapshotRequest(BaseModel):
    target_dir: str
    snapshot_id: str


class ProviderPushProjectSnapshotRequest(BaseModel):
    project_id: str
    include_index: bool = Field(default=True)


class ProviderPullProjectSnapshotRequest(BaseModel):
    snapshot_id: str
    project_id: Optional[str] = Field(default=None, max_length=120)
    overwrite: bool = Field(default=False)


class ProviderDeleteSyncedSnapshotRequest(BaseModel):
    snapshot_id: str


class SyncSettingsRequest(BaseModel):
    provider: str = Field(default="local", pattern="^(local|s3-compatible)$")
    target_dir: str = Field(default="", max_length=1000)
    endpoint_url: str = Field(default="", max_length=1000)
    bucket: str = Field(default="", max_length=300)
    region: str = Field(default="", max_length=120)
    prefix: str = Field(default="loamtrace-sync", max_length=300)
    access_key_id: Optional[str] = Field(default=None, max_length=4096)
    secret_access_key: Optional[str] = Field(default=None, max_length=4096)
    clear_secret: bool = Field(default=False)
