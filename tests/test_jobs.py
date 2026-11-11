import json
import tempfile
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.db import connect
from loamtrace.main import app
from loamtrace.models import CitationInput, ClaimInput
from loamtrace.services.documents import import_document
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
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.slides import generate_slide_deck
from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user
from loamtrace.services.verifier import verify_claims


@pytest.fixture
def tmp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_root = config.WORKSPACE_ROOT
        orig_projects = config.PROJECTS_ROOT
        orig_server_mode = config.SERVER_MODE
        config.WORKSPACE_ROOT = Path(tmpdir)
        config.PROJECTS_ROOT = config.WORKSPACE_ROOT / "projects"
        config.SERVER_MODE = False
        yield Path(tmpdir)
        config.WORKSPACE_ROOT = orig_root
        config.PROJECTS_ROOT = orig_projects
        config.SERVER_MODE = orig_server_mode


def _actor(user_id: str, email: str = "actor@example.test", role: Optional[str] = None) -> dict:
    headers = {
        "x-loamtrace-actor-id": user_id,
        "x-loamtrace-actor-email": email,
    }
    if role:
        headers["x-loamtrace-project-role"] = role
    return headers


def _write_temp_file(text: str) -> str:
    handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    try:
        handle.write(text.encode("utf-8"))
        return handle.name
    finally:
        handle.close()


def _create_exportable_deck(project_id: str) -> str:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk_jobs_export",
                "doc_jobs_export",
                "text",
                "Revenue increased by 24% year over year in 2025.",
                "pdf://doc_jobs_export#page=1",
                "[]",
            ),
        )
    verified = verify_claims(
        project_id,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_jobs_export",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]
    return generate_slide_deck(project_id, "Worker Export Deck", [verified["id"]])["deck_id"]


def _age_job(project_id: str, job_id: str) -> None:
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            "update background_jobs set updated_at = ?, started_at = ? where id = ?",
            ("2000-01-01T00:00:00Z", "2000-01-01T00:00:00Z", job_id),
        )


def test_job_service_enqueues_lists_updates_and_cancels(tmp_workspace):
    queued = enqueue_job("jobs_service", "parse_document", {"document_id": "doc_1"})

    assert queued["status"] == "queued"
    assert queued["job_type"] == "parse_document"
    assert queued["input"] == {"document_id": "doc_1"}
    assert queued["output"] is None
    assert queued["output_json_raw"] is None
    assert list_jobs("jobs_service", "queued")[0]["id"] == queued["id"]

    running = update_job_status("jobs_service", queued["id"], "running")
    assert running["status"] == "running"
    assert running["started_at"] is not None

    succeeded = update_job_status("jobs_service", queued["id"], "succeeded", {"chunks": 3})
    assert succeeded["status"] == "succeeded"
    assert succeeded["output"] == {"chunks": 3}
    assert succeeded["finished_at"] is not None

    with pytest.raises(ValueError):
        update_job_status("jobs_service", queued["id"], "running")

    second = enqueue_job("jobs_service", "export_pptx", {"deck_id": "deck_1"})
    canceled = cancel_job("jobs_service", second["id"])
    assert canceled["status"] == "canceled"
    assert get_job("jobs_service", second["id"])["finished_at"] is not None


def test_job_service_reports_queue_depth(tmp_workspace):
    project_id = "jobs_queue_depth_service"
    first = enqueue_job(project_id, "generate_memo", {"query": "missing one"})
    second = enqueue_job(project_id, "export_pptx", {"deck_id": "deck_1"})
    update_job_status(project_id, second["id"], "running")
    update_job_status(project_id, second["id"], "failed", error="boom")

    depth = queue_depth(project_id)

    assert depth["project_id"] == project_id
    assert depth["total"] == 2
    assert depth["by_status"]["queued"] == 1
    assert depth["by_status"]["failed"] == 1
    assert depth["by_type"]["generate_memo"]["queued"] == 1
    assert depth["by_type"]["export_pptx"]["failed"] == 1
    assert depth["by_type"]["parse_document"]["queued"] == 0
    assert get_job(project_id, first["id"])["status"] == "queued"


def test_job_service_recovers_stale_running_jobs(tmp_workspace):
    project_id = "jobs_stale_recovery_service"
    first = enqueue_job(project_id, "generate_memo", {"query": "missing one"})
    second = enqueue_job(project_id, "generate_memo", {"query": "missing two"})
    update_job_status(project_id, first["id"], "running")
    update_job_status(project_id, second["id"], "running")
    _age_job(project_id, first["id"])

    stale = list_stale_running_jobs(project_id, older_than_seconds=60)
    result = recover_stale_running_jobs(project_id, older_than_seconds=60)

    assert [job["id"] for job in stale] == [first["id"]]
    assert result["recovered_count"] == 1
    assert result["jobs"][0]["id"] == first["id"]
    assert result["jobs"][0]["status"] == "failed"
    assert result["jobs"][0]["error"] == "stale_running_recovered_after_60s"
    assert get_job(project_id, second["id"])["status"] == "running"
    with connect(project_db_path(project_id)) as conn:
        audit = conn.execute(
            "select payload_json from audit_log where type = ? order by ts desc limit 1",
            ("background_stale_running_jobs_recovered",),
        ).fetchone()
    payload = json.loads(audit["payload_json"])
    assert payload["recovered_count"] == 1
    assert payload["job_ids"] == [first["id"]]


def test_job_service_runs_next_parse_document_job(tmp_workspace):
    project_id = "jobs_worker_service"
    document = import_document(project_id, _write_temp_file("Revenue grew from source evidence."))
    queued = enqueue_job(project_id, "parse_document", {"document_id": document["id"]})

    result = run_next_job(project_id)

    assert result is not None
    assert result["id"] == queued["id"]
    assert result["status"] == "succeeded"
    assert result["output"]["document_id"] == document["id"]
    assert result["output"]["status"] == "parsed"
    assert get_job(project_id, queued["id"])["finished_at"] is not None
    assert run_next_job(project_id) is None


def test_job_service_runs_next_generate_memo_job(tmp_workspace):
    project_id = "jobs_memo_worker_service"
    queued = enqueue_job(project_id, "generate_memo", {"query": "missing market", "top_n": 3})

    result = run_next_job(project_id, "generate_memo")

    assert result is not None
    assert result["id"] == queued["id"]
    assert result["status"] == "succeeded"
    assert result["output"]["claims"] == []
    assert result["output"]["retrieved_chunks"] == []
    assert "No matching evidence was found" in result["output"]["answer"]
    assert get_job(project_id, queued["id"])["finished_at"] is not None
    assert run_next_job(project_id, "generate_memo") is None


def test_job_service_fails_generate_memo_job_without_query(tmp_workspace):
    project_id = "jobs_memo_worker_missing_query"
    queued = enqueue_job(project_id, "generate_memo", {"top_n": 3})

    result = run_next_job(project_id, "generate_memo")

    assert result is not None
    assert result["id"] == queued["id"]
    assert result["status"] == "failed"
    assert result["error"] == "query_required"
    assert result["finished_at"] is not None


def test_job_service_runs_next_export_pptx_job(tmp_workspace):
    project_id = "jobs_pptx_worker_service"
    deck_id = _create_exportable_deck(project_id)
    queued = enqueue_job(project_id, "export_pptx", {"deck_id": deck_id})

    result = run_next_job(project_id, "export_pptx")

    assert result is not None
    assert result["id"] == queued["id"]
    assert result["status"] == "succeeded"
    assert result["output"]["deck_id"] == deck_id
    assert result["output"]["status"] == "exported"
    assert Path(result["output"]["path"]).exists()
    assert get_job(project_id, queued["id"])["finished_at"] is not None
    assert run_next_job(project_id, "export_pptx") is None


def test_job_service_fails_export_pptx_job_without_deck_id(tmp_workspace):
    project_id = "jobs_pptx_worker_missing_deck"
    queued = enqueue_job(project_id, "export_pptx", {})

    result = run_next_job(project_id, "export_pptx")

    assert result is not None
    assert result["id"] == queued["id"]
    assert result["status"] == "failed"
    assert result["error"] == "deck_id_required"
    assert result["finished_at"] is not None


def test_job_service_runs_next_export_research_package_job(tmp_workspace):
    project_id = "jobs_package_worker_service"
    deck_id = _create_exportable_deck(project_id)
    queued = enqueue_job(project_id, "export_research_package", {"deck_id": deck_id})

    result = run_next_job(project_id, "export_research_package")

    assert result is not None
    assert result["id"] == queued["id"]
    assert result["status"] == "succeeded"
    assert result["output"]["manifest"]["deck_id"] == deck_id
    assert Path(result["output"]["path"]).exists()
    assert Path(result["output"]["archive_path"]).exists()
    assert get_job(project_id, queued["id"])["finished_at"] is not None
    assert run_next_job(project_id, "export_research_package") is None


def test_job_service_fails_export_research_package_job_with_missing_deck(tmp_workspace):
    project_id = "jobs_package_worker_missing_deck"
    queued = enqueue_job(project_id, "export_research_package", {"deck_id": "missing_deck"})

    result = run_next_job(project_id, "export_research_package")

    assert result is not None
    assert result["id"] == queued["id"]
    assert result["status"] == "failed"
    assert "deck_not_found" in result["error"]
    assert result["finished_at"] is not None


def test_job_service_runs_next_export_project_snapshot_job(tmp_workspace):
    project_id = "jobs_snapshot_worker_service"
    imported = import_document(project_id, _write_temp_file("Snapshot worker source."))
    queued = enqueue_job(project_id, "export_project_snapshot", {"include_index": False})

    result = run_next_job(project_id, "export_project_snapshot")

    assert result is not None
    assert result["id"] == queued["id"]
    assert result["status"] == "succeeded"
    assert result["output"]["manifest"]["project_id"] == project_id
    assert result["output"]["manifest"]["include_index"] is False
    assert f"sources/original/{imported['id']}_{Path(imported['filename']).name}" in result["output"]["manifest"]["files"]
    assert "index/project.sqlite" not in result["output"]["manifest"]["files"]
    assert Path(result["output"]["path"]).exists()
    assert Path(result["output"]["archive_path"]).exists()
    assert get_job(project_id, queued["id"])["finished_at"] is not None
    assert run_next_job(project_id, "export_project_snapshot") is None


def test_job_service_fails_export_project_snapshot_job_with_invalid_include_index(tmp_workspace):
    project_id = "jobs_snapshot_worker_bad_flag"
    queued = enqueue_job(project_id, "export_project_snapshot", {"include_index": "sometimes"})

    result = run_next_job(project_id, "export_project_snapshot")

    assert result is not None
    assert result["id"] == queued["id"]
    assert result["status"] == "failed"
    assert result["error"] == "include_index_must_be_boolean"
    assert result["finished_at"] is not None


def test_job_service_worker_loop_runs_multiple_job_types(tmp_workspace):
    project_id = "jobs_worker_loop_service"
    document = import_document(project_id, _write_temp_file("Worker loop parse source text."))
    enqueue_job(project_id, "parse_document", {"document_id": document["id"]})
    enqueue_job(project_id, "generate_memo", {"query": "missing market"})

    result = run_worker_loop(project_id, max_jobs=10, idle_rounds=1)

    assert result["ran_count"] == 2
    assert result["stopped_reason"] == "idle_rounds_exhausted"
    assert [job["job_type"] for job in result["jobs"]] == ["parse_document", "generate_memo"]
    assert all(job["status"] == "succeeded" for job in result["jobs"])
    with connect(project_db_path(project_id)) as conn:
        audit = conn.execute(
            "select payload_json from audit_log where type = ? order by ts desc limit 1",
            ("background_worker_loop_completed",),
        ).fetchone()
    payload = json.loads(audit["payload_json"])
    assert payload["ran_count"] == 2
    assert payload["stopped_reason"] == "idle_rounds_exhausted"
    assert payload["job_type_counts"] == {"parse_document": 1, "generate_memo": 1}


def test_job_service_worker_loop_stops_at_max_jobs(tmp_workspace):
    project_id = "jobs_worker_loop_max"
    enqueue_job(project_id, "generate_memo", {"query": "missing one"})
    enqueue_job(project_id, "generate_memo", {"query": "missing two"})

    result = run_worker_loop(project_id, job_type="generate_memo", max_jobs=1, idle_rounds=1)

    assert result["ran_count"] == 1
    assert result["stopped_reason"] == "max_jobs_reached"
    assert len(list_jobs(project_id, "queued")) == 1


def test_jobs_api_desktop_round_trip(tmp_workspace):
    client = TestClient(app)
    project_id = "jobs_api"

    created = client.post(
        "/api/jobs",
        json={"project_id": project_id, "job_type": "generate_memo", "input": {"query": "market"}},
    )
    assert created.status_code == 200
    job = created.json()
    assert job["status"] == "queued"
    assert "output_json_raw" not in job

    listed = client.get("/api/jobs", params={"project_id": project_id, "status": "queued"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [job["id"]]

    running = client.patch(
        f"/api/jobs/{job['id']}",
        json={"project_id": project_id, "status": "running"},
    )
    assert running.status_code == 200
    assert running.json()["status"] == "running"

    failed = client.patch(
        f"/api/jobs/{job['id']}",
        json={"project_id": project_id, "status": "failed", "error": "provider_unavailable"},
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["error"] == "provider_unavailable"


def test_jobs_api_reports_queue_depth(tmp_workspace):
    client = TestClient(app)
    project_id = "jobs_api_queue_depth"
    enqueue_job(project_id, "generate_memo", {"query": "missing market"})

    response = client.get("/api/jobs/queue-depth", params={"project_id": project_id})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["by_status"]["queued"] == 1
    assert body["by_type"]["generate_memo"]["queued"] == 1
    assert body["by_type"]["export_research_package"]["queued"] == 0


def test_jobs_api_reports_and_recovers_stale_running_jobs(tmp_workspace):
    client = TestClient(app)
    project_id = "jobs_api_stale_recovery"
    job = enqueue_job(project_id, "generate_memo", {"query": "missing market"})
    update_job_status(project_id, job["id"], "running")
    _age_job(project_id, job["id"])

    stale = client.get(
        "/api/jobs/stale-running",
        params={"project_id": project_id, "older_than_seconds": 60},
    )
    recovered = client.post(
        "/api/jobs/recover-stale-running",
        json={"project_id": project_id, "older_than_seconds": 60},
    )

    assert stale.status_code == 200
    assert stale.json()["stale_count"] == 1
    assert stale.json()["jobs"][0]["id"] == job["id"]
    assert "output_json_raw" not in stale.json()["jobs"][0]
    assert recovered.status_code == 200
    assert recovered.json()["recovered_count"] == 1
    assert recovered.json()["jobs"][0]["status"] == "failed"


def test_jobs_api_runs_next_parse_document_job(tmp_workspace):
    client = TestClient(app)
    project_id = "jobs_api_worker"
    document = import_document(project_id, _write_temp_file("Worker parse source text."))

    created = client.post(
        "/api/jobs",
        json={"project_id": project_id, "job_type": "parse_document", "input": {"document_id": document["id"]}},
    )
    assert created.status_code == 200

    ran = client.post("/api/jobs/run-next", json={"project_id": project_id})
    assert ran.status_code == 200
    body = ran.json()
    assert body["ran"] is True
    assert body["job"]["status"] == "succeeded"
    assert body["job"]["output"]["document_id"] == document["id"]

    empty = client.post("/api/jobs/run-next", json={"project_id": project_id})
    assert empty.status_code == 200
    assert empty.json() == {"ran": False, "job": None}


def test_jobs_api_runs_next_generate_memo_job(tmp_workspace):
    client = TestClient(app)
    project_id = "jobs_api_memo_worker"

    created = client.post(
        "/api/jobs",
        json={"project_id": project_id, "job_type": "generate_memo", "input": {"query": "missing market", "top_n": 2}},
    )
    assert created.status_code == 200

    ran = client.post("/api/jobs/run-next", json={"project_id": project_id, "job_type": "generate_memo"})
    assert ran.status_code == 200
    body = ran.json()
    assert body["ran"] is True
    assert body["job"]["status"] == "succeeded"
    assert body["job"]["output"]["claims"] == []
    assert "No matching evidence was found" in body["job"]["output"]["answer"]

    empty = client.post("/api/jobs/run-next", json={"project_id": project_id, "job_type": "generate_memo"})
    assert empty.status_code == 200
    assert empty.json() == {"ran": False, "job": None}


def test_jobs_api_runs_next_export_pptx_job(tmp_workspace):
    client = TestClient(app)
    project_id = "jobs_api_pptx_worker"
    deck_id = _create_exportable_deck(project_id)

    created = client.post(
        "/api/jobs",
        json={"project_id": project_id, "job_type": "export_pptx", "input": {"deck_id": deck_id}},
    )
    assert created.status_code == 200

    ran = client.post("/api/jobs/run-next", json={"project_id": project_id, "job_type": "export_pptx"})
    assert ran.status_code == 200
    body = ran.json()
    assert body["ran"] is True
    assert body["job"]["status"] == "succeeded"
    assert body["job"]["output"]["deck_id"] == deck_id
    assert body["job"]["output"]["status"] == "exported"
    assert Path(body["job"]["output"]["path"]).exists()

    empty = client.post("/api/jobs/run-next", json={"project_id": project_id, "job_type": "export_pptx"})
    assert empty.status_code == 200
    assert empty.json() == {"ran": False, "job": None}


def test_jobs_api_runs_next_export_research_package_job(tmp_workspace):
    client = TestClient(app)
    project_id = "jobs_api_package_worker"
    deck_id = _create_exportable_deck(project_id)

    created = client.post(
        "/api/jobs",
        json={"project_id": project_id, "job_type": "export_research_package", "input": {"deck_id": deck_id}},
    )
    assert created.status_code == 200

    ran = client.post("/api/jobs/run-next", json={"project_id": project_id, "job_type": "export_research_package"})
    assert ran.status_code == 200
    body = ran.json()
    assert body["ran"] is True
    assert body["job"]["status"] == "succeeded"
    assert body["job"]["output"]["manifest"]["deck_id"] == deck_id
    assert Path(body["job"]["output"]["path"]).exists()
    assert Path(body["job"]["output"]["archive_path"]).exists()

    empty = client.post("/api/jobs/run-next", json={"project_id": project_id, "job_type": "export_research_package"})
    assert empty.status_code == 200
    assert empty.json() == {"ran": False, "job": None}


def test_jobs_api_runs_worker_loop(tmp_workspace):
    client = TestClient(app)
    project_id = "jobs_api_worker_loop"
    enqueue_job(project_id, "generate_memo", {"query": "missing one"})
    enqueue_job(project_id, "generate_memo", {"query": "missing two"})

    response = client.post(
        "/api/jobs/run-worker",
        json={"project_id": project_id, "job_type": "generate_memo", "max_jobs": 2, "idle_rounds": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ran_count"] == 2
    assert body["stopped_reason"] == "max_jobs_reached"
    assert [job["status"] for job in body["jobs"]] == ["succeeded", "succeeded"]
    assert all("output_json_raw" not in job for job in body["jobs"])


def test_jobs_api_worker_loop_empty_queue(tmp_workspace):
    client = TestClient(app)
    project_id = "jobs_api_worker_loop_empty"

    response = client.post("/api/jobs/run-worker", json={"project_id": project_id, "max_jobs": 2, "idle_rounds": 1})

    assert response.status_code == 200
    assert response.json()["ran_count"] == 0
    assert response.json()["stopped_reason"] == "idle_rounds_exhausted"
    assert response.json()["jobs"] == []


def test_jobs_api_enforces_server_mode_permissions(tmp_workspace, monkeypatch):
    monkeypatch.setattr(config, "SERVER_MODE", True)
    client = TestClient(app)
    project_id = "jobs_server_guard"
    owner = bootstrap_local_admin(project_id, "owner@example.test", "Owner")["user"]
    editor = upsert_user(project_id, "editor_user", "editor@example.test", "Editor")
    set_project_acl(project_id, "user", editor["id"], "editor")

    denied = client.post(
        "/api/jobs",
        headers=_actor("intruder", "intruder@example.test"),
        json={"project_id": project_id, "job_type": "parse_document", "input": {"document_id": "doc_1"}},
    )
    assert denied.status_code == 403

    allowed = client.post(
        "/api/jobs",
        headers=_actor(editor["id"], editor["email"]),
        json={"project_id": project_id, "job_type": "parse_document", "input": {"document_id": "doc_1"}},
    )
    assert allowed.status_code == 200
    job_id = allowed.json()["id"]

    editor_update = client.patch(
        f"/api/jobs/{job_id}",
        headers=_actor(editor["id"], editor["email"]),
        json={"project_id": project_id, "status": "running"},
    )
    assert editor_update.status_code == 403

    owner_update = client.patch(
        f"/api/jobs/{job_id}",
        headers=_actor(owner["id"], owner["email"]),
        json={"project_id": project_id, "status": "running"},
    )
    assert owner_update.status_code == 200

    cancel_denied = client.post(
        f"/api/jobs/{job_id}/cancel",
        headers=_actor("intruder", "intruder@example.test"),
        json={"project_id": project_id},
    )
    assert cancel_denied.status_code == 403

    cancel_allowed = client.post(
        f"/api/jobs/{job_id}/cancel",
        headers=_actor(owner["id"], owner["email"]),
        json={"project_id": project_id},
    )
    assert cancel_allowed.status_code == 200
    assert cancel_allowed.json()["status"] == "canceled"


def test_run_next_job_api_requires_owner_in_server_mode(tmp_workspace, monkeypatch):
    monkeypatch.setattr(config, "SERVER_MODE", True)
    client = TestClient(app)
    project_id = "jobs_worker_server_guard"
    owner = bootstrap_local_admin(project_id, "owner@example.test", "Owner")["user"]
    editor = upsert_user(project_id, "editor_user", "editor@example.test", "Editor")
    set_project_acl(project_id, "user", editor["id"], "editor")
    document = import_document(project_id, _write_temp_file("Server worker parse source."))

    created = client.post(
        "/api/jobs",
        headers=_actor(editor["id"], editor["email"]),
        json={"project_id": project_id, "job_type": "parse_document", "input": {"document_id": document["id"]}},
    )
    assert created.status_code == 200

    editor_run = client.post(
        "/api/jobs/run-next",
        headers=_actor(editor["id"], editor["email"]),
        json={"project_id": project_id},
    )
    assert editor_run.status_code == 403

    owner_run = client.post(
        "/api/jobs/run-next",
        headers=_actor(owner["id"], owner["email"]),
        json={"project_id": project_id},
    )
    assert owner_run.status_code == 200
    assert owner_run.json()["job"]["status"] == "succeeded"


def test_run_worker_loop_api_requires_owner_in_server_mode(tmp_workspace, monkeypatch):
    monkeypatch.setattr(config, "SERVER_MODE", True)
    client = TestClient(app)
    project_id = "jobs_loop_server_guard"
    owner = bootstrap_local_admin(project_id, "owner@example.test", "Owner")["user"]
    editor = upsert_user(project_id, "editor_user", "editor@example.test", "Editor")
    set_project_acl(project_id, "user", editor["id"], "editor")
    enqueue_job(project_id, "generate_memo", {"query": "missing market"})

    editor_run = client.post(
        "/api/jobs/run-worker",
        headers=_actor(editor["id"], editor["email"]),
        json={"project_id": project_id, "job_type": "generate_memo"},
    )
    assert editor_run.status_code == 403

    owner_run = client.post(
        "/api/jobs/run-worker",
        headers=_actor(owner["id"], owner["email"]),
        json={"project_id": project_id, "job_type": "generate_memo"},
    )
    assert owner_run.status_code == 200
    assert owner_run.json()["ran_count"] == 1
    assert owner_run.json()["jobs"][0]["status"] == "succeeded"


def test_ocr_document_job_is_worker_executable(tmp_workspace):
    project_id = "jobs_ocr_worker"
    document = import_document(project_id, _write_temp_file("OCR worker parse source."))
    queued = enqueue_job(project_id, "ocr_document", {"document_id": document["id"]})

    assert queued["status"] == "queued"
    assert queued["job_type"] == "ocr_document"

    result = run_next_job(project_id, "ocr_document")

    assert result is not None
    assert result["status"] == "succeeded"
    assert result["job_type"] == "ocr_document"
    assert result["output"]["status"] == "parsed"
    assert result["output"]["document_id"] == document["id"]
    assert get_job(project_id, queued["id"])["status"] == "succeeded"

    depth = queue_depth(project_id)
    assert depth["by_type"]["ocr_document"]["succeeded"] == 1
    assert depth["by_status"]["succeeded"] == 1

    second_document = import_document(project_id, _write_temp_file("Second OCR worker parse source."))
    second = enqueue_job(project_id, "ocr_document", {"document_id": second_document["id"]})
    loop = run_worker_loop(project_id, max_jobs=1, idle_rounds=1)

    assert loop["ran_count"] == 1
    assert loop["jobs"][0]["id"] == second["id"]
    assert loop["jobs"][0]["status"] == "succeeded"
    assert loop["jobs"][0]["job_type"] == "ocr_document"


def test_job_service_rejects_invalid_worker_job_type(tmp_workspace):
    with pytest.raises(ValueError, match="invalid_job_type"):
        run_next_job("jobs_invalid_type", "unknown_worker")

    with pytest.raises(ValueError, match="invalid_job_type"):
        run_worker_loop("jobs_invalid_type", job_type="unknown_worker")


def test_job_service_rejects_stale_running_out_of_range_threshold(tmp_workspace):
    with pytest.raises(ValueError, match="older_than_seconds_out_of_range"):
        list_stale_running_jobs("jobs_stale_bounds", older_than_seconds=0)

    with pytest.raises(ValueError, match="older_than_seconds_out_of_range"):
        recover_stale_running_jobs("jobs_stale_bounds", older_than_seconds=700000)


def test_job_service_worker_loop_rejects_invalid_parameters(tmp_workspace):
    with pytest.raises(ValueError, match="max_jobs_out_of_range"):
        run_worker_loop("jobs_loop_bounds", max_jobs=0)

    with pytest.raises(ValueError, match="idle_rounds_out_of_range"):
        run_worker_loop("jobs_loop_bounds", idle_rounds=0)

    with pytest.raises(ValueError, match="poll_interval_seconds_out_of_range"):
        run_worker_loop("jobs_loop_bounds", poll_interval_seconds=11)


def test_job_service_fails_generate_memo_job_when_top_n_out_of_range(tmp_workspace):
    project_id = "jobs_memo_top_n_bounds"
    queued = enqueue_job(project_id, "generate_memo", {"query": "market", "top_n": 13})

    result = run_next_job(project_id, "generate_memo")

    assert result is not None
    assert result["status"] == "failed"
    assert result["error"] == "top_n_out_of_range"


def test_get_job_raises_when_missing(tmp_workspace):
    with pytest.raises(KeyError, match="job_not_found"):
        get_job("jobs_missing", "job_does_not_exist")


def test_jobs_api_runs_ocr_document_with_run_next(tmp_workspace):
    client = TestClient(app)
    project_id = "jobs_api_ocr_worker"
    document = import_document(project_id, _write_temp_file("OCR API parse source."))

    created = client.post(
        "/api/jobs",
        json={"project_id": project_id, "job_type": "ocr_document", "input": {"document_id": document["id"]}},
    )
    assert created.status_code == 200
    assert created.json()["job_type"] == "ocr_document"

    ran = client.post(
        "/api/jobs/run-next",
        json={"project_id": project_id, "job_type": "ocr_document"},
    )
    assert ran.status_code == 200
    assert ran.json()["ran"] is True
    assert ran.json()["job"]["status"] == "succeeded"
    assert ran.json()["job"]["output"]["document_id"] == document["id"]

    assert get_job(project_id, created.json()["id"])["status"] == "succeeded"


def test_jobs_api_runs_export_project_snapshot_with_run_next(tmp_workspace):
    client = TestClient(app)
    project_id = "jobs_api_snapshot_worker"
    import_document(project_id, _write_temp_file("Snapshot API source."))

    created = client.post(
        "/api/jobs",
        json={"project_id": project_id, "job_type": "export_project_snapshot", "input": {"include_index": False}},
    )
    assert created.status_code == 200
    assert created.json()["job_type"] == "export_project_snapshot"

    ran = client.post(
        "/api/jobs/run-next",
        json={"project_id": project_id, "job_type": "export_project_snapshot"},
    )

    assert ran.status_code == 200
    payload = ran.json()
    assert payload["ran"] is True
    assert payload["job"]["status"] == "succeeded"
    assert payload["job"]["output"]["manifest"]["include_index"] is False
    assert Path(payload["job"]["output"]["archive_path"]).exists()


def test_jobs_api_returns_404_for_missing_job(tmp_workspace):
    client = TestClient(app)

    response = client.get("/api/jobs/job_missing", params={"project_id": "jobs_api_missing"})

    assert response.status_code == 404
    assert "job_not_found" in str(response.json()["detail"])


def test_recover_stale_running_jobs_api_requires_owner_in_server_mode(tmp_workspace, monkeypatch):
    monkeypatch.setattr(config, "SERVER_MODE", True)
    client = TestClient(app)
    project_id = "jobs_stale_server_guard"
    owner = bootstrap_local_admin(project_id, "owner@example.test", "Owner")["user"]
    editor = upsert_user(project_id, "editor_user", "editor@example.test", "Editor")
    set_project_acl(project_id, "user", editor["id"], "editor")
    job = enqueue_job(project_id, "generate_memo", {"query": "missing market"})
    update_job_status(project_id, job["id"], "running")
    _age_job(project_id, job["id"])

    editor_recover = client.post(
        "/api/jobs/recover-stale-running",
        headers=_actor(editor["id"], editor["email"]),
        json={"project_id": project_id, "older_than_seconds": 60},
    )
    assert editor_recover.status_code == 403

    owner_recover = client.post(
        "/api/jobs/recover-stale-running",
        headers=_actor(owner["id"], owner["email"]),
        json={"project_id": project_id, "older_than_seconds": 60},
    )
    assert owner_recover.status_code == 200
    assert owner_recover.json()["recovered_count"] == 1
