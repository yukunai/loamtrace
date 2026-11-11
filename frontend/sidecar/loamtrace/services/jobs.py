from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from loamtrace.db import connect
from loamtrace.services.access_control import actor_audit_fields
from loamtrace.services.audit import write_audit
from loamtrace.services.exports import export_project_snapshot, export_research_package
from loamtrace.services.generator import generate_memo
from loamtrace.services.parse import parse_document
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.slides import export_pptx
from loamtrace.services.time import now_iso

JOB_TYPES = {
    "parse_document",
    "ocr_document",
    "generate_memo",
    "export_pptx",
    "export_research_package",
    "export_project_snapshot",
}
JOB_STATUSES = {"queued", "running", "succeeded", "failed", "canceled"}
JOB_TYPE_ORDER = [
    "parse_document",
    "ocr_document",
    "generate_memo",
    "export_pptx",
    "export_research_package",
    "export_project_snapshot",
]
JOB_STATUS_ORDER = ["queued", "running", "succeeded", "failed", "canceled"]
TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}
EXECUTABLE_JOB_TYPES = {
    "parse_document",
    "ocr_document",
    "generate_memo",
    "export_pptx",
    "export_research_package",
    "export_project_snapshot",
}
EXECUTABLE_JOB_TYPE_ORDER = [
    "parse_document",
    "ocr_document",
    "generate_memo",
    "export_pptx",
    "export_research_package",
    "export_project_snapshot",
]
ALLOWED_TRANSITIONS = {
    "queued": {"running", "canceled"},
    "running": {"succeeded", "failed", "canceled"},
    "succeeded": set(),
    "failed": set(),
    "canceled": set(),
}


def enqueue_job(
    project_id: str,
    job_type: str,
    input_payload: Optional[dict] = None,
    actor: Optional[dict] = None,
) -> dict:
    _validate(job_type, JOB_TYPES, "job_type")
    payload = input_payload or {}
    job_id = f"job_{uuid.uuid4().hex}"
    now = now_iso()
    actor_fields = actor_audit_fields(actor)
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into background_jobs(
              id, project_id, job_type, status, input_json,
              actor_user_id, actor_email, request_id,
              created_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                project_id,
                job_type,
                "queued",
                json.dumps(payload, ensure_ascii=False),
                actor_fields["actor_user_id"],
                actor_fields["actor_email"],
                actor_fields["request_id"],
                now,
                now,
            ),
        )
    write_audit(project_id, "background_job_enqueued", {"job_id": job_id, "job_type": job_type, **actor_fields})
    return get_job(project_id, job_id)


def list_jobs(project_id: str, status: Optional[str] = None, limit: int = 100) -> list[dict]:
    ensure_project(project_id)
    params: list = []
    where = ""
    if status:
        _validate(status, JOB_STATUSES, "status")
        where = "where status = ?"
        params.append(status)
    params.append(max(1, min(limit, 500)))
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            f"""
            select *
            from background_jobs
            {where}
            order by created_at desc, id desc
            limit ?
            """,
            params,
        ).fetchall()
    return [_job_from_row(row) for row in rows]


def queue_depth(project_id: str) -> dict:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            """
            select job_type, status, count(*) as count
            from background_jobs
            group by job_type, status
            order by job_type asc, status asc
            """
        ).fetchall()

    by_type: dict[str, dict[str, int]] = {job_type: {status: 0 for status in JOB_STATUS_ORDER} for job_type in JOB_TYPE_ORDER}
    by_status = {status: 0 for status in JOB_STATUS_ORDER}
    total = 0
    for row in rows:
        job_type = row["job_type"]
        status = row["status"]
        count = int(row["count"])
        by_type.setdefault(job_type, {item: 0 for item in JOB_STATUS_ORDER})[status] = count
        by_status[status] = by_status.get(status, 0) + count
        total += count

    return {
        "project_id": project_id,
        "total": total,
        "by_status": by_status,
        "by_type": by_type,
    }


def list_stale_running_jobs(project_id: str, older_than_seconds: int = 3600, limit: int = 100) -> list[dict]:
    if older_than_seconds < 1 or older_than_seconds > 604800:
        raise ValueError("older_than_seconds_out_of_range")
    ensure_project(project_id)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    items = []
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            """
            select *
            from background_jobs
            where status = ?
            order by updated_at asc, id asc
            limit ?
            """,
            ("running", max(1, min(limit, 500))),
        ).fetchall()
    for row in rows:
        job = _job_from_row(row)
        reference = _parse_iso(job["updated_at"] or job["started_at"] or job["created_at"])
        if reference and reference <= cutoff:
            items.append(job)
    return items


def recover_stale_running_jobs(
    project_id: str,
    older_than_seconds: int = 3600,
    limit: int = 100,
    actor: Optional[dict] = None,
) -> dict:
    stale_jobs = list_stale_running_jobs(project_id, older_than_seconds, limit)
    recovered = []
    error = f"stale_running_recovered_after_{older_than_seconds}s"
    for job in stale_jobs:
        recovered.append(update_job_status(project_id, job["id"], "failed", error=error, actor=actor))
    write_audit(
        project_id,
        "background_stale_running_jobs_recovered",
        {
            "older_than_seconds": older_than_seconds,
            "limit": limit,
            "recovered_count": len(recovered),
            "job_ids": [job["id"] for job in recovered],
            **actor_audit_fields(actor),
        },
    )
    return {
        "project_id": project_id,
        "older_than_seconds": older_than_seconds,
        "recovered_count": len(recovered),
        "jobs": recovered,
    }


def get_job(project_id: str, job_id: str) -> dict:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute(
            "select * from background_jobs where id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        raise KeyError("job_not_found")
    return _job_from_row(row)


def update_job_status(
    project_id: str,
    job_id: str,
    status: str,
    output: Optional[dict] = None,
    error: Optional[str] = None,
    actor: Optional[dict] = None,
) -> dict:
    _validate(status, JOB_STATUSES, "status")
    existing = get_job(project_id, job_id)
    if status not in ALLOWED_TRANSITIONS[existing["status"]]:
        raise ValueError("invalid_job_status_transition")

    now = now_iso()
    started_at = existing["started_at"]
    finished_at = existing["finished_at"]
    if status == "running" and started_at is None:
        started_at = now
    if status in TERMINAL_STATUSES:
        finished_at = now

    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            update background_jobs
            set status = ?, output_json = ?, error = ?, updated_at = ?, started_at = ?, finished_at = ?
            where id = ?
            """,
            (
                status,
                json.dumps(output, ensure_ascii=False) if output is not None else existing["output_json_raw"],
                error,
                now,
                started_at,
                finished_at,
                job_id,
            ),
        )
    write_audit(
        project_id,
        "background_job_status_updated",
        {"job_id": job_id, "status": status, "error": error, **actor_audit_fields(actor)},
    )
    return get_job(project_id, job_id)


def cancel_job(project_id: str, job_id: str, actor: Optional[dict] = None) -> dict:
    return update_job_status(project_id, job_id, "canceled", actor=actor)


def run_next_job(project_id: str, job_type: str = "parse_document", actor: Optional[dict] = None) -> Optional[dict]:
    _validate(job_type, EXECUTABLE_JOB_TYPES, "job_type")
    job = _next_queued_job(project_id, job_type)
    if job is None:
        return None

    update_job_status(project_id, job["id"], "running", actor=actor)
    try:
        output = _execute_job(project_id, job)
    except Exception as exc:
        return update_job_status(project_id, job["id"], "failed", error=str(exc), actor=actor)
    return update_job_status(project_id, job["id"], "succeeded", output=output, actor=actor)


def run_worker_loop(
    project_id: str,
    job_type: Optional[str] = None,
    max_jobs: int = 10,
    idle_rounds: int = 1,
    poll_interval_seconds: float = 0.0,
    actor: Optional[dict] = None,
) -> dict:
    if job_type is not None:
        _validate(job_type, EXECUTABLE_JOB_TYPES, "job_type")
    if max_jobs < 1 or max_jobs > 100:
        raise ValueError("max_jobs_out_of_range")
    if idle_rounds < 1 or idle_rounds > 100:
        raise ValueError("idle_rounds_out_of_range")
    if poll_interval_seconds < 0 or poll_interval_seconds > 10:
        raise ValueError("poll_interval_seconds_out_of_range")

    types = [job_type] if job_type else EXECUTABLE_JOB_TYPE_ORDER
    jobs = []
    idle_count = 0
    while len(jobs) < max_jobs and idle_count < idle_rounds:
        ran = None
        for current_type in types:
            ran = run_next_job(project_id, current_type, actor)
            if ran is not None:
                break
        if ran is None:
            idle_count += 1
            if idle_count < idle_rounds and poll_interval_seconds:
                time.sleep(poll_interval_seconds)
            continue
        jobs.append(ran)
        idle_count = 0

    reason = "max_jobs_reached" if len(jobs) >= max_jobs else "idle_rounds_exhausted"
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for job in jobs:
        status_counts[job["status"]] = status_counts.get(job["status"], 0) + 1
        type_counts[job["job_type"]] = type_counts.get(job["job_type"], 0) + 1
    write_audit(
        project_id,
        "background_worker_loop_completed",
        {
            "job_type": job_type,
            "max_jobs": max_jobs,
            "idle_rounds_configured": idle_rounds,
            "idle_rounds_observed": idle_count,
            "poll_interval_seconds": poll_interval_seconds,
            "ran_count": len(jobs),
            "stopped_reason": reason,
            "job_ids": [job["id"] for job in jobs],
            "status_counts": status_counts,
            "job_type_counts": type_counts,
            **actor_audit_fields(actor),
        },
    )
    return {
        "project_id": project_id,
        "job_type": job_type,
        "ran_count": len(jobs),
        "idle_rounds": idle_count,
        "stopped_reason": reason,
        "jobs": jobs,
    }


def _validate(value: str, allowed: set[str], field: str) -> None:
    if value not in allowed:
        raise ValueError(f"invalid_{field}")


def _next_queued_job(project_id: str, job_type: str) -> Optional[dict]:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute(
            """
            select *
            from background_jobs
            where status = ? and job_type = ?
            order by created_at asc, id asc
            limit 1
            """,
            ("queued", job_type),
        ).fetchone()
    return _job_from_row(row) if row else None


def _execute_job(project_id: str, job: dict) -> dict:
    if job["job_type"] == "parse_document":
        document_id = job["input"].get("document_id")
        if not document_id:
            raise ValueError("document_id_required")
        return parse_document(project_id, document_id)
    if job["job_type"] == "ocr_document":
        document_id = job["input"].get("document_id")
        if not document_id:
            raise ValueError("document_id_required")
        return parse_document(project_id, document_id)
    if job["job_type"] == "generate_memo":
        query = job["input"].get("query")
        if not query:
            raise ValueError("query_required")
        top_n = int(job["input"].get("top_n") or 5)
        if top_n < 1 or top_n > 12:
            raise ValueError("top_n_out_of_range")
        return generate_memo(project_id, query, top_n)
    if job["job_type"] == "export_pptx":
        deck_id = job["input"].get("deck_id")
        if not deck_id:
            raise ValueError("deck_id_required")
        return export_pptx(project_id, deck_id)
    if job["job_type"] == "export_research_package":
        deck_id = job["input"].get("deck_id")
        return export_research_package(project_id, deck_id)
    if job["job_type"] == "export_project_snapshot":
        include_index = _input_bool(job["input"], "include_index", True)
        return export_project_snapshot(project_id, include_index)
    raise ValueError("unsupported_job_type")


def _input_bool(input_payload: dict, key: str, default: bool) -> bool:
    value = input_payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise ValueError(f"{key}_must_be_boolean")


def _job_from_row(row) -> dict:
    item = dict(row)
    input_json = item.pop("input_json")
    output_json = item.pop("output_json")
    item["input"] = json.loads(input_json) if input_json else {}
    item["output"] = json.loads(output_json) if output_json else None
    item["output_json_raw"] = output_json
    return item


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
