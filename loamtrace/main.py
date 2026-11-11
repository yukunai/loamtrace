from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from typing import Optional

import loamtrace.config
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from loamtrace.db import connect
from loamtrace.models import (
    AddReviewCommentRequest,
    BootstrapAdminRequest,
    CancelJobRequest,
    CreateProjectRequest,
    CreateAssetFromDocumentRequest,
    CreateReviewTaskRequest,
    ClaimSupportJudgeRequest,
    ClaimCorrectionRequest,
    ContractClauseScanRequest,
    CitationReplaceRequest,
    CitationReviewRequest,
    DeleteSyncedSnapshotRequest,
    EnqueueJobRequest,
    ExportPptxRequest,
    ExportProjectSnapshotRequest,
    ExportResearchPackageRequest,
    FinancialConsistencyScanRequest,
    GenerateMemoRequest,
    GenerateChartDataRequest,
    GenerateChartDeckRequest,
    GenerateSlidesRequest,
    GenerateTableDeckRequest,
    GenerateTemplateSlidesRequest,
    ImportAssetRequest,
    ImportDocumentRequest,
    ImportProjectSnapshotRequest,
    ManualTextRequest,
    ParseDocumentRequest,
    ProviderDeleteSyncedSnapshotRequest,
    ProviderPullProjectSnapshotRequest,
    ProviderPushProjectSnapshotRequest,
    PullProjectSnapshotRequest,
    PushProjectSnapshotRequest,
    RecoverStaleRunningJobsRequest,
    RedFlagScanRequest,
    RetrievalPreferencesRequest,
    RenderMemoRequest,
    RunNextJobRequest,
    RunWorkerLoopRequest,
    SearchRequest,
    SetProjectAclRequest,
    SetTeamMemberRequest,
    ApiSettingsRequest,
    SyncSettingsRequest,
    UpsertTeamRequest,
    UpsertUserRequest,
    UiPreferencesRequest,
    UpdateAssetTagsRequest,
    UpdateJobStatusRequest,
    UpdateReviewTaskRequest,
    VerifyRunRequest,
)
from loamtrace.services.audit import write_audit, write_run_artifacts
from loamtrace.services.access_control import (
    actor_from_headers,
    check_project_access,
    dry_run_route_guard,
    get_current_actor,
    guarded_project_access,
    preview_project_access,
    reset_current_actor,
    set_current_actor,
)
from loamtrace.services.analysis import scan_contract_clauses, scan_financial_consistency, scan_red_flags
from loamtrace.services.asset_library import add_document_asset, delete_asset, get_asset, import_asset_to_project, list_assets, update_asset_tags
from loamtrace.services.chart_data import generate_chart_data
from loamtrace.services.documents import apply_manual_text, delete_document, get_document, import_document, list_documents, preview_delete_document
from loamtrace.services.exports import (
    export_project_snapshot,
    export_research_package,
    import_project_snapshot,
    list_export_artifacts,
    resolve_import_project_snapshot_target,
)
from loamtrace.services.generator import generate_memo
from loamtrace.services.jobs import (
    cancel_job,
    enqueue_job,
    get_job,
    list_jobs,
    list_stale_running_jobs,
    queue_depth,
    recover_stale_running_jobs,
    run_next_job,
    run_worker_loop,
    update_job_status,
)
from loamtrace.services.mutation_risk import (
    claim_citation_review_plan,
    list_mutation_route_risks,
    mutation_route_risk_summary,
)
from loamtrace.services.ocr_backend import ocr_backend_status
from loamtrace.services.parse import parse_document
from loamtrace.services.paths import ensure_project, project_db_path, project_root
from loamtrace.services.api_settings import get_api_settings, save_api_settings, test_api_connection
from loamtrace.services.preferences import get_ui_preferences, save_ui_preferences
from loamtrace.services.retrieval_preferences import get_retrieval_preferences, save_retrieval_preferences
from loamtrace.services.review_flow import add_review_comment, create_review_task, list_review_tasks, update_review_task
from loamtrace.services.search import get_chunk, search_chunks
from loamtrace.services.slides import (
    export_pptx,
    generate_chart_deck,
    generate_slide_deck,
    generate_table_deck,
    generate_template_slide_deck,
    list_slide_templates,
    load_slide_deck,
)
from loamtrace.services.source_targets import resolve_citation_target
from loamtrace.services.support_judge import judge_claim_support
from loamtrace.services.sync import (
    delete_provider_synced_snapshot,
    delete_synced_snapshot,
    list_provider_synced_snapshots,
    list_synced_snapshots,
    pull_project_snapshot,
    pull_project_snapshot_from_configured_provider,
    push_project_snapshot,
    push_project_snapshot_to_configured_provider,
    resolve_delete_synced_snapshot_project,
    resolve_provider_delete_synced_snapshot_project,
    resolve_provider_pull_project_snapshot_target,
    resolve_pull_project_snapshot_target,
)
from loamtrace.services.sync_settings import get_sync_settings, save_sync_settings, test_configured_sync_provider_live, test_sync_settings
from loamtrace.services.tables import list_tables
from loamtrace.services.team_admin import (
    bootstrap_local_admin,
    acl_migration_diagnostics,
    delete_project_acl,
    delete_team_member,
    list_project_acl,
    list_team_members,
    list_teams,
    list_users,
    set_project_acl,
    set_team_member,
    upsert_team,
    upsert_user,
)
from loamtrace.services.verifier import correct_claim, list_claims, render_memo, replace_citation, review_citation, verify_claims
from loamtrace.services.vector_backend import vector_backend_status
from loamtrace.services.workflow import workflow_status



@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_project("default", "Default Project")
    yield


app = FastAPI(title="LoamTrace", version="0.5.42", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def actor_context_middleware(request: Request, call_next):
    token = set_current_actor(actor_from_headers(request.headers))
    try:
        return await call_next(request)
    finally:
        reset_current_actor(token)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "vector": vector_backend_status(), "ocr": ocr_backend_status()}


@app.get("/api/session/actor")
def api_session_actor(project_id: str = "default") -> dict:
    actor = get_current_actor()
    return {
        "actor": actor,
        "authorization": check_project_access(project_id, "read", actor),
        "acl_preview": preview_project_access(project_id, "read", actor),
    }


@app.post("/api/projects")
def create_project(request: CreateProjectRequest) -> dict:
    _enforce_project_creation_guard(request.project_id, "POST /api/projects")
    root = ensure_project(request.project_id, request.name)
    _audit_project_creation_guard(request.project_id, "POST /api/projects")
    return {"id": request.project_id, "name": request.name, "root": str(root)}


@app.get("/api/projects")
def list_projects() -> list[dict]:
    loamtrace.config.PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    projects = []
    for root in sorted(loamtrace.config.PROJECTS_ROOT.iterdir()):
        if root.is_dir():
            metadata_path = root / "project.json"
            name = root.name
            if metadata_path.exists():
                try:
                    name = json.loads(metadata_path.read_text(encoding="utf-8")).get("name") or name
                except json.JSONDecodeError:
                    pass
            projects.append({"id": root.name, "name": name, "root": str(root)})
    return projects


@app.post("/api/documents/import")
def api_import_document(request: ImportDocumentRequest) -> dict:
    try:
        _enforce_project_mutation_guard(request.project_id, "write", "POST /api/documents/import")
        return import_document(request.project_id, request.file_path)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _guard_project_read(project_id: str) -> None:
    try:
        guarded_project_access(project_id, "read")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _audit_project_mutation_guard(project_id: str, permission: str, route: str) -> dict:
    decision = dry_run_route_guard(project_id, permission)
    if not decision["server_mode"] and decision["mode"] == "desktop":
        return {**decision, "audit_recorded": False}

    payload = {
        "route": route,
        "audit_only": True,
        "project_id": project_id,
        "permission": permission,
        "actor_id": decision["actor_id"],
        "mode": decision["mode"],
        "server_mode": decision["server_mode"],
        "would_block": decision["would_block"],
        "guard_reason": decision["guard_reason"],
        "required_role": decision["required_role"],
        "matched_role": decision["matched_role"],
        "matched_principal_type": decision["matched_principal_type"],
        "matched_principal_id": decision["matched_principal_id"],
    }
    try:
        write_audit(project_id, "route_guard_dry_run", payload)
    except Exception as exc:
        return {**decision, "audit_recorded": False, "audit_error": str(exc)}
    return {**decision, "audit_recorded": True}


def _enforce_project_mutation_guard(project_id: str, permission: str, route: str) -> None:
    _audit_project_mutation_guard(project_id, permission, route)
    try:
        guarded_project_access(project_id, permission)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _enforce_project_creation_guard(project_id: str, route: str) -> None:
    actor = get_current_actor()
    if not loamtrace.config.SERVER_MODE or actor["mode"] == "desktop":
        return
    if actor.get("project_role") != "owner":
        raise HTTPException(status_code=403, detail=f"admin access denied for project creation {project_id}")


def _audit_project_creation_guard(project_id: str, route: str) -> None:
    actor = get_current_actor()
    if not loamtrace.config.SERVER_MODE or actor["mode"] == "desktop":
        return
    payload = {
        "route": route,
        "audit_only": True,
        "project_id": project_id,
        "permission": "admin",
        "actor_id": actor["id"],
        "mode": actor["mode"],
        "server_mode": True,
        "would_block": actor.get("project_role") != "owner",
        "guard_reason": "server_mode_would_allow" if actor.get("project_role") == "owner" else "server_mode_would_block",
        "required_role": "owner",
        "matched_role": actor.get("project_role"),
        "matched_principal_type": "actor_project_role",
        "matched_principal_id": actor["id"],
    }
    try:
        write_audit(project_id, "route_guard_dry_run", payload)
    except Exception:
        return


def _enforce_asset_ref_guards(asset_id: str, permission: str, route: str) -> None:
    asset = get_asset(asset_id)
    project_ids = []
    for ref in asset.get("source_refs", []):
        project_id = ref.get("project_id")
        if project_id and project_id not in project_ids:
            project_ids.append(project_id)
    if not project_ids:
        raise HTTPException(status_code=400, detail="asset_has_no_source_project")
    for project_id in project_ids:
        _enforce_project_mutation_guard(project_id, permission, route)


@app.get("/api/projects/{project_id}/documents")
def api_list_documents(project_id: str) -> list[dict]:
    _guard_project_read(project_id)
    return list_documents(project_id)


@app.get("/api/assets")
def api_list_assets(query: Optional[str] = None, tag: Optional[str] = None) -> list[dict]:
    return list_assets(query, tag)


@app.post("/api/assets/from-document")
def api_add_document_asset(request: CreateAssetFromDocumentRequest) -> dict:
    try:
        _enforce_project_mutation_guard(request.project_id, "write", "POST /api/assets/from-document")
        return add_document_asset(request.project_id, request.document_id, request.tags)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/assets/import")
def api_import_asset(request: ImportAssetRequest) -> dict:
    try:
        _enforce_project_mutation_guard(request.project_id, "write", "POST /api/assets/import")
        return import_asset_to_project(request.project_id, request.asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/assets/{asset_id}")
def api_delete_asset(asset_id: str) -> dict:
    try:
        _enforce_asset_ref_guards(asset_id, "delete", "DELETE /api/assets/{asset_id}")
        return delete_asset(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/team/bootstrap-admin")
def api_bootstrap_admin(request: BootstrapAdminRequest) -> dict:
    try:
        return bootstrap_local_admin(request.project_id, request.email, request.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/team/acl/diagnostics")
def api_acl_diagnostics(project_id: str = "default") -> dict:
    return acl_migration_diagnostics(project_id)


@app.get("/api/team/acl/guard-check")
def api_acl_guard_check(project_id: str = "default", permission: str = "read") -> dict:
    return dry_run_route_guard(project_id, permission, get_current_actor())


@app.get("/api/team/acl/mutation-risk")
def api_mutation_route_risk(category: Optional[str] = None, guard_status: Optional[str] = None) -> dict:
    return {
        "summary": mutation_route_risk_summary(),
        "routes": list_mutation_route_risks(category, guard_status),
    }


@app.get("/api/team/acl/review-mutation-plan")
def api_review_mutation_plan() -> dict:
    return claim_citation_review_plan()


@app.get("/api/jobs")
def api_list_jobs(project_id: str = "default", status: Optional[str] = None, limit: int = 100) -> list[dict]:
    _guard_project_read(project_id)
    try:
        return _public_jobs(list_jobs(project_id, status, limit))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/queue-depth")
def api_queue_depth(project_id: str = "default") -> dict:
    _guard_project_read(project_id)
    return queue_depth(project_id)


@app.get("/api/jobs/stale-running")
def api_stale_running_jobs(
    project_id: str = "default",
    older_than_seconds: int = 3600,
    limit: int = 100,
) -> dict:
    _guard_project_read(project_id)
    try:
        jobs = list_stale_running_jobs(project_id, older_than_seconds, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "project_id": project_id,
        "older_than_seconds": older_than_seconds,
        "stale_count": len(jobs),
        "jobs": _public_jobs(jobs),
    }


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str, project_id: str = "default") -> dict:
    _guard_project_read(project_id)
    try:
        return _public_job(get_job(project_id, job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_error_detail(exc)) from exc


@app.post("/api/jobs")
def api_enqueue_job(request: EnqueueJobRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "write", "POST /api/jobs")
    try:
        return _public_job(enqueue_job(request.project_id, request.job_type, request.input, get_current_actor()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/jobs/{job_id}")
def api_update_job_status(job_id: str, request: UpdateJobStatusRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "admin", "PATCH /api/jobs/{job_id}")
    try:
        return _public_job(update_job_status(request.project_id, job_id, request.status, request.output, request.error, get_current_actor()))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_error_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc


@app.post("/api/jobs/{job_id}/cancel")
def api_cancel_job(job_id: str, request: CancelJobRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "write", "POST /api/jobs/{job_id}/cancel")
    try:
        return _public_job(cancel_job(request.project_id, job_id, get_current_actor()))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_error_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc


@app.post("/api/jobs/run-next")
def api_run_next_job(request: RunNextJobRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "admin", "POST /api/jobs/run-next")
    try:
        job = run_next_job(request.project_id, request.job_type, get_current_actor())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if job is None:
        return {"ran": False, "job": None}
    return {"ran": True, "job": _public_job(job)}


@app.post("/api/jobs/run-worker")
def api_run_worker_loop(request: RunWorkerLoopRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "admin", "POST /api/jobs/run-worker")
    try:
        result = run_worker_loop(
            request.project_id,
            request.job_type,
            request.max_jobs,
            request.idle_rounds,
            request.poll_interval_seconds,
            get_current_actor(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "jobs": _public_jobs(result["jobs"])}


@app.post("/api/jobs/recover-stale-running")
def api_recover_stale_running_jobs(request: RecoverStaleRunningJobsRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "admin", "POST /api/jobs/recover-stale-running")
    try:
        result = recover_stale_running_jobs(
            request.project_id,
            request.older_than_seconds,
            request.limit,
            get_current_actor(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "jobs": _public_jobs(result["jobs"])}


def _public_jobs(jobs: list[dict]) -> list[dict]:
    return [_public_job(job) for job in jobs]


def _public_job(job: dict) -> dict:
    cleaned = dict(job)
    cleaned.pop("output_json_raw", None)
    return cleaned


def _error_detail(exc: Exception) -> str:
    return str(exc.args[0]) if exc.args else str(exc)


@app.get("/api/team/users")
def api_list_team_users(project_id: str = "default") -> list[dict]:
    return list_users(project_id)


@app.post("/api/team/users")
def api_upsert_team_user(request: UpsertUserRequest) -> dict:
    try:
        _enforce_project_mutation_guard(request.project_id, "admin", "POST /api/team/users")
        return upsert_user(request.project_id, request.user_id, request.email, request.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/team/teams")
def api_list_teams(project_id: str = "default") -> list[dict]:
    return list_teams(project_id)


@app.post("/api/team/teams")
def api_upsert_team(request: UpsertTeamRequest) -> dict:
    try:
        _enforce_project_mutation_guard(request.project_id, "admin", "POST /api/team/teams")
        return upsert_team(request.project_id, request.team_id, request.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/team/members")
def api_list_team_members(project_id: str = "default", team_id: Optional[str] = None) -> list[dict]:
    return list_team_members(project_id, team_id)


@app.put("/api/team/members")
def api_set_team_member(request: SetTeamMemberRequest) -> dict:
    try:
        _enforce_project_mutation_guard(request.project_id, "admin", "PUT /api/team/members")
        return set_team_member(request.project_id, request.team_id, request.user_id, request.role)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/team/members/{team_id}/{user_id}")
def api_delete_team_member(team_id: str, user_id: str, project_id: str = "default") -> dict:
    try:
        _enforce_project_mutation_guard(project_id, "admin", "DELETE /api/team/members/{team_id}/{user_id}")
        return delete_team_member(project_id, team_id, user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/team/acl")
def api_list_project_acl(project_id: str = "default") -> list[dict]:
    return list_project_acl(project_id)


@app.put("/api/team/acl")
def api_set_project_acl(request: SetProjectAclRequest) -> dict:
    try:
        _enforce_project_mutation_guard(request.project_id, "admin", "PUT /api/team/acl")
        return set_project_acl(request.project_id, request.principal_type, request.principal_id, request.role)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/team/acl")
def api_delete_project_acl(project_id: str, principal_type: str, principal_id: str) -> dict:
    try:
        _enforce_project_mutation_guard(project_id, "admin", "DELETE /api/team/acl")
        return delete_project_acl(project_id, principal_type, principal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/assets/{asset_id}/tags")
def api_update_asset_tags(asset_id: str, request: UpdateAssetTagsRequest) -> dict:
    try:
        _enforce_asset_ref_guards(asset_id, "write", "PUT /api/assets/{asset_id}/tags")
        return update_asset_tags(asset_id, request.tags)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/documents/{document_id}/delete-preview")
def api_preview_delete_document(project_id: str, document_id: str) -> dict:
    try:
        _enforce_project_mutation_guard(
            project_id,
            "delete",
            "GET /api/projects/{project_id}/documents/{document_id}/delete-preview",
        )
        return preview_delete_document(project_id, document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/projects/{project_id}/documents/{document_id}")
def api_delete_document(project_id: str, document_id: str) -> dict:
    try:
        _enforce_project_mutation_guard(project_id, "delete", "DELETE /api/projects/{project_id}/documents/{document_id}")
        return delete_document(project_id, document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/ui-preferences")
def api_get_ui_preferences(project_id: str) -> dict:
    return get_ui_preferences(project_id)


@app.put("/api/projects/{project_id}/ui-preferences")
def api_save_ui_preferences(project_id: str, request: UiPreferencesRequest) -> dict:
    _enforce_project_mutation_guard(project_id, "write", "PUT /api/projects/{project_id}/ui-preferences")
    return save_ui_preferences(project_id, request.column_widths.model_dump())


@app.get("/api/projects/{project_id}/retrieval-preferences")
def api_get_retrieval_preferences(project_id: str) -> dict:
    return get_retrieval_preferences(project_id)


@app.put("/api/projects/{project_id}/retrieval-preferences")
def api_save_retrieval_preferences(project_id: str, request: RetrievalPreferencesRequest) -> dict:
    _enforce_project_mutation_guard(project_id, "write", "PUT /api/projects/{project_id}/retrieval-preferences")
    return save_retrieval_preferences(project_id, request.model_dump())


@app.get("/api/settings/api")
def api_get_api_settings() -> dict:
    return get_api_settings()


@app.put("/api/settings/api")
def api_save_api_settings(request: ApiSettingsRequest) -> dict:
    return save_api_settings(request)


@app.post("/api/settings/api/test")
def api_test_api_settings(request: ApiSettingsRequest) -> dict:
    return test_api_connection(request)


@app.post("/api/documents/{document_id}/parse")
def api_parse_document(document_id: str, request: ParseDocumentRequest) -> dict:
    try:
        _enforce_project_mutation_guard(request.project_id, "write", "POST /api/documents/{document_id}/parse")
        return parse_document(request.project_id, document_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/documents/{document_id}/manual-text")
def api_apply_manual_text(document_id: str, request: ManualTextRequest) -> dict:
    try:
        _enforce_project_mutation_guard(request.project_id, "write", "POST /api/documents/{document_id}/manual-text")
        return apply_manual_text(request.project_id, document_id, request.text, request.heading or "Manual correction")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/documents/{document_id}")
def api_get_document(document_id: str, project_id: str = "default") -> dict:
    try:
        doc = get_document(project_id, document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select * from pages where document_id = ? order by page_number asc",
            (document_id,),
        ).fetchall()
    doc["pages"] = [dict(row) for row in rows]
    return doc


@app.get("/api/documents/{document_id}/pages/{page_number}/render")
def api_page_render(document_id: str, page_number: int, project_id: str = "default") -> FileResponse:
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute(
            """
            select render_path from pages
            where document_id = ? and page_number = ?
            """,
            (document_id, page_number),
        ).fetchone()
    if not row or not row["render_path"]:
        raise HTTPException(status_code=404, detail="Rendered page image not found")
    path = Path(row["render_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Rendered page image missing on disk")
    return FileResponse(path)


@app.post("/api/search")
def api_search(request: SearchRequest) -> list[dict]:
    _enforce_project_mutation_guard(request.project_id, "read", "POST /api/search")
    try:
        retrieval_preferences = get_retrieval_preferences(request.project_id)
        search_input = {
            "project_id": request.project_id,
            "query": request.query,
            "top_n": request.top_n if request.top_n is not None else retrieval_preferences["top_n"],
            "rrf_k": request.rrf_k if request.rrf_k is not None else retrieval_preferences["rrf_k"],
            "fts_top_n": request.fts_top_n if request.fts_top_n is not None else retrieval_preferences["fts_top_n"],
            "vector_top_n": (
                request.vector_top_n if request.vector_top_n is not None else retrieval_preferences["vector_top_n"]
            ),
            "keyword_boost": (
                request.keyword_boost if request.keyword_boost is not None else retrieval_preferences["keyword_boost"]
            ),
            "vector_boost": request.vector_boost if request.vector_boost is not None else retrieval_preferences["vector_boost"],
        }
        results = search_chunks(
            search_input["project_id"],
            search_input["query"],
            search_input["top_n"],
            search_input["rrf_k"],
            search_input["fts_top_n"],
            search_input["vector_top_n"],
            search_input["keyword_boost"],
            search_input["vector_boost"],
        )
        run_id = f"run_{uuid.uuid4().hex}"
        run_dir = write_run_artifacts(
            request.project_id,
            run_id,
            "search",
            {
                "input.json": search_input,
                "results.json": results,
            },
            logs=[
                {
                    "type": "search_completed",
                    "query": search_input["query"],
                    "top_n": search_input["top_n"],
                    "rrf_k": search_input["rrf_k"],
                    "fts_top_n": search_input["fts_top_n"],
                    "vector_top_n": search_input["vector_top_n"],
                    "keyword_boost": search_input["keyword_boost"],
                    "vector_boost": search_input["vector_boost"],
                    "result_count": len(results),
                }
            ],
        )
        write_audit(
            request.project_id,
            "search_completed",
            {
                "run_id": run_id,
                "query": search_input["query"],
                "top_n": search_input["top_n"],
                "rrf_k": search_input["rrf_k"],
                "fts_top_n": search_input["fts_top_n"],
                "vector_top_n": search_input["vector_top_n"],
                "keyword_boost": search_input["keyword_boost"],
                "vector_boost": search_input["vector_boost"],
                "result_count": len(results),
                "run_dir": str(run_dir),
            },
        )
        return results
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/chunks/{chunk_id}")
def api_get_chunk(chunk_id: str, project_id: str = "default") -> dict:
    try:
        return get_chunk(project_id, chunk_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/verify/run")
def api_verify(request: VerifyRunRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "write", "POST /api/verify/run")
    return verify_claims(request.project_id, request.claims)


@app.post("/api/generate/memo")
def api_generate_memo(
    request: Optional[GenerateMemoRequest] = Body(default=None),
    project_id: Optional[str] = None,
    query: Optional[str] = None,
    top_n: int = 5,
) -> dict:
    if request is not None:
        _enforce_project_mutation_guard(request.project_id, "write", "POST /api/generate/memo")
        return generate_memo(request.project_id, request.query, request.top_n)
    if project_id and query:
        _enforce_project_mutation_guard(project_id, "write", "POST /api/generate/memo")
        return generate_memo(project_id, query, top_n)
    raise HTTPException(status_code=422, detail="project_id and query are required")


@app.get("/api/memo/{project_id}")
def api_get_memo(project_id: str) -> dict:
    return render_memo(project_id)


@app.post("/api/memo/render")
def api_render_memo(request: RenderMemoRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "write", "POST /api/memo/render")
    return render_memo(request.project_id, request.claim_ids)


@app.get("/api/claims")
def api_claims(project_id: str = "default") -> list[dict]:
    _guard_project_read(project_id)
    return list_claims(project_id)


@app.post("/api/claims/{claim_id}/correct")
def api_correct_claim(claim_id: str, request: ClaimCorrectionRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "review", "POST /api/claims/{claim_id}/correct")
    try:
        return correct_claim(
            request.project_id,
            claim_id,
            request.text,
            request.citation_id,
            request.chunk_id,
            request.quote,
            request.reviewer,
            request.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/review/tasks")
def api_list_review_tasks(project_id: str = "default", status: Optional[str] = None) -> list[dict]:
    _guard_project_read(project_id)
    return list_review_tasks(project_id, status)


@app.post("/api/review/tasks")
def api_create_review_task(request: CreateReviewTaskRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "review", "POST /api/review/tasks")
    try:
        return create_review_task(request.project_id, request.claim_id, request.assignee, request.priority)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/review/tasks/{task_id}")
def api_update_review_task(task_id: str, request: UpdateReviewTaskRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "review", "PATCH /api/review/tasks/{task_id}")
    try:
        return update_review_task(request.project_id, task_id, request.status, request.assignee, request.priority)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/review/tasks/{task_id}/comments")
def api_add_review_comment(task_id: str, request: AddReviewCommentRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "review", "POST /api/review/tasks/{task_id}/comments")
    try:
        return add_review_comment(request.project_id, task_id, request.author, request.body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/claims/{claim_id}/judge-support")
def api_judge_claim_support(claim_id: str, request: ClaimSupportJudgeRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "review", "POST /api/claims/{claim_id}/judge-support")
    try:
        return judge_claim_support(request.project_id, claim_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/analysis/red-flags")
def api_scan_red_flags(request: RedFlagScanRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "write", "POST /api/analysis/red-flags")
    return scan_red_flags(request.project_id, request.limit)


@app.post("/api/analysis/financial-consistency")
def api_scan_financial_consistency(request: FinancialConsistencyScanRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "write", "POST /api/analysis/financial-consistency")
    return scan_financial_consistency(request.project_id, request.limit)


@app.post("/api/analysis/contract-clauses")
def api_scan_contract_clauses(request: ContractClauseScanRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "write", "POST /api/analysis/contract-clauses")
    return scan_contract_clauses(request.project_id, request.limit)


@app.post("/api/charts/generate-data")
def api_generate_chart_data(request: GenerateChartDataRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "write", "POST /api/charts/generate-data")
    try:
        return generate_chart_data(
            request.project_id,
            request.table_id,
            request.label_column,
            request.value_columns,
            request.chart_type,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/tables")
def api_list_tables(project_id: str = "default", document_id: Optional[str] = None) -> list[dict]:
    return list_tables(project_id, document_id)


@app.post("/api/slides/generate")
def api_generate_slides(request: GenerateSlidesRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "export", "POST /api/slides/generate")
    try:
        return generate_slide_deck(request.project_id, request.title, request.claim_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/templates/slides")
def api_list_slide_templates() -> list[dict]:
    return list_slide_templates()


@app.post("/api/slides/from-template")
def api_generate_template_slides(request: GenerateTemplateSlidesRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "export", "POST /api/slides/from-template")
    try:
        return generate_template_slide_deck(request.project_id, request.template_id, request.title, request.claim_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/slides/chart-deck")
def api_generate_chart_deck(request: GenerateChartDeckRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "export", "POST /api/slides/chart-deck")
    try:
        return generate_chart_deck(request.project_id, request.title, request.chart)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/slides/table-deck")
def api_generate_table_deck(request: GenerateTableDeckRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "export", "POST /api/slides/table-deck")
    try:
        return generate_table_deck(request.project_id, request.table_id, request.title, request.max_rows, request.max_cols)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/slides/{deck_id}")
def api_get_slides(deck_id: str, project_id: str = "default") -> dict:
    try:
        return load_slide_deck(project_id, deck_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/export/pptx")
def api_export_pptx(request: ExportPptxRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "export", "POST /api/export/pptx")
    try:
        return export_pptx(request.project_id, request.deck_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/export/research-package")
def api_export_research_package(request: ExportResearchPackageRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "export", "POST /api/export/research-package")
    try:
        return export_research_package(request.project_id, request.deck_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/export/project-snapshot")
def api_export_project_snapshot(request: ExportProjectSnapshotRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "export", "POST /api/export/project-snapshot")
    return export_project_snapshot(request.project_id, request.include_index)


@app.post("/api/import/project-snapshot")
def api_import_project_snapshot(request: ImportProjectSnapshotRequest) -> dict:
    try:
        target_project_id = resolve_import_project_snapshot_target(request.archive_path, request.project_id)
        _enforce_project_mutation_guard(target_project_id, "admin", "POST /api/import/project-snapshot")
        return import_project_snapshot(request.archive_path, request.project_id, request.overwrite)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sync/push-snapshot")
def api_sync_push_snapshot(request: PushProjectSnapshotRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "export", "POST /api/sync/push-snapshot")
    try:
        return push_project_snapshot(request.project_id, request.target_dir, request.include_index)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sync/snapshots")
def api_sync_snapshots(target_dir: str, project_id: Optional[str] = None) -> list[dict]:
    try:
        return list_synced_snapshots(target_dir, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sync/pull-snapshot")
def api_sync_pull_snapshot(request: PullProjectSnapshotRequest) -> dict:
    try:
        target_project_id = resolve_pull_project_snapshot_target(
            request.target_dir,
            request.snapshot_id,
            request.project_id,
        )
        _enforce_project_mutation_guard(target_project_id, "admin", "POST /api/sync/pull-snapshot")
        return pull_project_snapshot(
            request.target_dir,
            request.snapshot_id,
            request.project_id,
            request.overwrite,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sync/delete-snapshot")
def api_sync_delete_snapshot(request: DeleteSyncedSnapshotRequest) -> dict:
    try:
        project_id = resolve_delete_synced_snapshot_project(request.target_dir, request.snapshot_id)
        _enforce_project_mutation_guard(project_id, "delete", "POST /api/sync/delete-snapshot")
        return delete_synced_snapshot(request.target_dir, request.snapshot_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sync/provider/push-snapshot")
def api_sync_provider_push_snapshot(request: ProviderPushProjectSnapshotRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "export", "POST /api/sync/provider/push-snapshot")
    try:
        return push_project_snapshot_to_configured_provider(request.project_id, request.include_index)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sync/provider/snapshots")
def api_sync_provider_snapshots(project_id: Optional[str] = None) -> list[dict]:
    try:
        return list_provider_synced_snapshots(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sync/provider/pull-snapshot")
def api_sync_provider_pull_snapshot(request: ProviderPullProjectSnapshotRequest) -> dict:
    try:
        target_project_id = resolve_provider_pull_project_snapshot_target(request.snapshot_id, request.project_id)
        _enforce_project_mutation_guard(target_project_id, "admin", "POST /api/sync/provider/pull-snapshot")
        return pull_project_snapshot_from_configured_provider(
            request.snapshot_id,
            request.project_id,
            request.overwrite,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sync/provider/delete-snapshot")
def api_sync_provider_delete_snapshot(request: ProviderDeleteSyncedSnapshotRequest) -> dict:
    try:
        project_id = resolve_provider_delete_synced_snapshot_project(request.snapshot_id)
        _enforce_project_mutation_guard(project_id, "delete", "POST /api/sync/provider/delete-snapshot")
        return delete_provider_synced_snapshot(request.snapshot_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sync/settings")
def api_get_sync_settings() -> dict:
    return get_sync_settings()


@app.put("/api/sync/settings")
def api_save_sync_settings(request: SyncSettingsRequest) -> dict:
    try:
        return save_sync_settings(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sync/settings/test")
def api_test_sync_settings(request: SyncSettingsRequest) -> dict:
    try:
        return test_sync_settings(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sync/provider/test-live")
def api_test_configured_sync_provider_live(project_id: Optional[str] = None) -> dict:
    return test_configured_sync_provider_live(project_id)


@app.get("/api/export/artifacts")
def api_export_artifacts(project_id: str = "default") -> list[dict]:
    _guard_project_read(project_id)
    return list_export_artifacts(project_id)


@app.post("/api/citations/{citation_id}/review")
def api_review_citation(citation_id: str, request: CitationReviewRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "review", "POST /api/citations/{citation_id}/review")
    try:
        return review_citation(request.project_id, citation_id, request.action, request.reviewer, request.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/citations/{citation_id}/replace")
def api_replace_citation(citation_id: str, request: CitationReplaceRequest) -> dict:
    _enforce_project_mutation_guard(request.project_id, "review", "POST /api/citations/{citation_id}/replace")
    try:
        return replace_citation(request.project_id, citation_id, request.chunk_id, request.quote)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/citations/{citation_id}/target")
def api_citation_target(citation_id: str, project_id: str = "default") -> dict:
    try:
        return resolve_citation_target(project_id, citation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/audit")
def api_audit(project_id: str = "default", limit: int = 100) -> list[dict]:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select * from audit_log order by ts desc limit ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/project-root")
def api_project_root(project_id: str = "default") -> dict:
    return {"root": str(project_root(project_id))}


@app.get("/api/workflow/status")
def api_workflow_status(project_id: str = "default") -> dict:
    return workflow_status(project_id)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
