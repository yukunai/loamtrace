import tempfile
from pathlib import Path

import pytest

from loamtrace import config
from loamtrace.db import connect
from loamtrace.services import documents, paths, workflow


@pytest.fixture
def tmp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_root = config.WORKSPACE_ROOT
        orig_projects = config.PROJECTS_ROOT
        config.WORKSPACE_ROOT = Path(tmpdir)
        config.PROJECTS_ROOT = config.WORKSPACE_ROOT / "projects"
        yield Path(tmpdir)
        config.WORKSPACE_ROOT = orig_root
        config.PROJECTS_ROOT = orig_projects


def test_workflow_status_empty_project(tmp_workspace):
    result = workflow.workflow_status("empty")

    assert result["overall_status"] == "in_progress"
    assert result["counts"]["documents"] == 0
    assert result["next_actions"][0]["key"] == "import_document"
    assert result["blockers"] == []
    assert _status(result, "project") == "complete"
    assert _status(result, "import") == "not_started"
    assert _status(result, "memo") == "not_started"


def test_workflow_status_after_parse_and_verified_claim(tmp_workspace):
    project_id = "wf"
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
        tf.write(b"Revenue grew by 24% in 2025.")
        source_path = tf.name
    doc = documents.import_document(project_id, source_path)

    with connect(paths.project_db_path(project_id)) as conn:
        conn.execute("update documents set status = ? where id = ?", ("parsed", doc["id"]))
        conn.execute(
            "insert into chunks(id, document_id, chunk_type, text, source_uri) values (?, ?, ?, ?, ?)",
            ("chunk_1", doc["id"], "text", "Revenue grew by 24% in 2025.", f"txt://{doc['id']}#chunk=chunk_1"),
        )
        conn.execute(
            """
            insert into claims(id, project_id, run_id, claim_text, status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("claim_1", project_id, "run_1", "Revenue grew by 24% in 2025.", "verified", "2026-06-09T00:00:00Z"),
        )

    result = workflow.workflow_status(project_id)

    assert _status(result, "import") == "complete"
    assert _status(result, "parse") == "complete"
    assert _status(result, "evidence") == "complete"
    assert _status(result, "memo") == "complete"
    assert _status(result, "review") == "complete"
    assert _status(result, "slides") == "ready"
    assert result["next_actions"][0]["key"] == "generate_slides"


def test_workflow_status_flags_review_claims_and_exports(tmp_workspace):
    project_id = "wf_review"
    paths.ensure_project(project_id)
    root = paths.project_root(project_id)
    (root / "slides" / "deck_1.slide.json").write_text("{}", encoding="utf-8")
    (root / "slides" / "deck_1.pptx").write_bytes(b"pptx")
    (root / "exports" / "export_1").mkdir(parents=True)
    (root / "exports" / "export_1.zip").write_bytes(b"zip")
    with connect(paths.project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into claims(id, project_id, run_id, claim_text, status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("claim_review", project_id, "run_1", "Needs review", "needs_review", "2026-06-09T00:00:00Z"),
        )
        conn.execute(
            """
            insert into citations(id, claim_id, chunk_id, document_id, quote, source_uri, verified, failure_reason)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "citation_failed",
                "claim_review",
                "chunk_missing",
                "doc_missing",
                "Needs review",
                "pdf://doc_missing#page=1",
                0,
                "chunk_not_found",
            ),
        )
        conn.execute(
            """
            insert into review_tasks(
              id, project_id, claim_id, status, priority, created_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "review_1",
                project_id,
                "claim_review",
                "open",
                "high",
                "2026-06-09T00:00:00Z",
                "2026-06-09T00:00:00Z",
            ),
        )

    result = workflow.workflow_status(project_id)

    assert result["overall_status"] == "needs_review"
    assert _status(result, "review") == "needs_review"
    assert _status(result, "slides") == "complete"
    assert _status(result, "export") == "complete"
    assert result["counts"]["failed_citations"] == 1
    assert result["counts"]["active_review_tasks"] == 1
    assert result["counts"]["research_package_archives"] == 1
    assert _step_counts(result, "export")["research_package_archives"] == 1
    assert {blocker["key"] for blocker in result["blockers"]} == {
        "failed_citations",
        "review_claims",
        "active_review_tasks",
    }
    assert result["next_actions"][0]["key"] == "review_claims"


def test_workflow_status_reports_latest_audit_and_export_next_action(tmp_workspace):
    project_id = "wf_audit"
    paths.ensure_project(project_id)
    root = paths.project_root(project_id)
    (root / "slides" / "deck_1.slide.json").write_text("{}", encoding="utf-8")
    with connect(paths.project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into claims(id, project_id, run_id, claim_text, status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("claim_1", project_id, "run_1", "Verified", "verified", "2026-06-09T00:00:00Z"),
        )
        conn.execute(
            """
            insert into audit_log(id, ts, type, payload_json)
            values (?, ?, ?, ?)
            """,
            ("audit_1", "2026-06-09T00:00:01Z", "slide_deck_generated", '{"deck_id":"deck_1"}'),
        )

    result = workflow.workflow_status(project_id)

    assert result["latest_audit"]["type"] == "slide_deck_generated"
    assert result["next_actions"][0]["key"] == "export_package"


def test_workflow_status_counts_zip_archive_as_completed_export(tmp_workspace):
    project_id = "wf_zip_export"
    paths.ensure_project(project_id)
    root = paths.project_root(project_id)
    (root / "slides" / "deck_1.slide.json").write_text("{}", encoding="utf-8")
    (root / "exports" / "export_only_zip.zip").write_bytes(b"zip")
    with connect(paths.project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into claims(id, project_id, run_id, claim_text, status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("claim_1", project_id, "run_1", "Verified", "verified", "2026-06-09T00:00:00Z"),
        )

    result = workflow.workflow_status(project_id)

    assert _status(result, "export") == "complete"
    assert result["counts"]["research_packages"] == 0
    assert result["counts"]["research_package_archives"] == 1
    assert result["next_actions"] == []


def _status(result: dict, key: str) -> str:
    return next(step["status"] for step in result["steps"] if step["key"] == key)


def _step_counts(result: dict, key: str) -> dict:
    return next(step["counts"] for step in result["steps"] if step["key"] == key)
