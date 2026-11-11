import json
import tempfile
from pathlib import Path

import pytest

from loamtrace import config
from loamtrace.db import connect
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.review_flow import add_review_comment, create_review_task, list_review_tasks, update_review_task


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


def test_review_task_lifecycle_is_audited_without_changing_claim_status(tmp_workspace):
    project_id = "review_flow"
    ensure_project(project_id)
    _insert_claim(project_id, "claim_1", "Needs human review", "needs_review")

    task = create_review_task(project_id, "claim_1", assignee="alice", priority="high")

    assert task["id"].startswith("review_")
    assert task["status"] == "open"
    assert task["assignee"] == "alice"
    assert task["priority"] == "high"
    assert task["claim_status"] == "needs_review"
    assert task["comment_count"] == 0

    commented = add_review_comment(project_id, task["id"], "bob", "Quote supports revenue but not retention.")
    assert commented["comment_count"] == 1
    assert commented["comments"][0]["author"] == "bob"

    resolved = update_review_task(project_id, task["id"], status="resolved", assignee="carol")
    assert resolved["status"] == "resolved"
    assert resolved["assignee"] == "carol"
    assert resolved["resolved_at"] is not None

    with connect(project_db_path(project_id)) as conn:
        claim = conn.execute("select status from claims where id = ?", ("claim_1",)).fetchone()
        audit_types = [
            row["type"]
            for row in conn.execute("select type from audit_log order by ts asc").fetchall()
        ]
    assert claim["status"] == "needs_review"
    assert "review_task_created" in audit_types
    assert "review_comment_added" in audit_types
    assert "review_task_updated" in audit_types


def test_create_review_task_reuses_active_task(tmp_workspace):
    project_id = "review_reuse"
    ensure_project(project_id)
    _insert_claim(project_id, "claim_1", "Needs human review", "blocked")

    first = create_review_task(project_id, "claim_1", assignee="alice")
    second = create_review_task(project_id, "claim_1", assignee="bob", priority="high")

    assert second["id"] == first["id"]
    assert second["assignee"] == "bob"
    assert second["priority"] == "high"
    tasks = list_review_tasks(project_id)
    assert len(tasks) == 1


def test_review_task_api(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")

    project_id = "review_api"
    ensure_project(project_id)
    _insert_claim(project_id, "claim_1", "Needs human review", "needs_review")
    client = TestClient(main.app)

    created = client.post(
        "/api/review/tasks",
        json={"project_id": project_id, "claim_id": "claim_1", "assignee": "alice", "priority": "normal"},
    )
    assert created.status_code == 200
    task_id = created.json()["id"]

    commented = client.post(
        f"/api/review/tasks/{task_id}/comments",
        json={"project_id": project_id, "author": "bob", "body": "Please confirm support level."},
    )
    assert commented.status_code == 200
    assert commented.json()["comment_count"] == 1

    updated = client.patch(
        f"/api/review/tasks/{task_id}",
        json={"project_id": project_id, "status": "in_review", "assignee": "carol"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_review"
    assert updated.json()["assignee"] == "carol"

    listed = client.get(f"/api/review/tasks?project_id={project_id}&status=in_review")
    assert listed.status_code == 200
    assert [task["id"] for task in listed.json()] == [task_id]


def test_review_task_api_enforces_server_mode_mutation_guards(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "review_api_guard_dry_run"
    ensure_project(project_id)
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    _insert_claim(project_id, "claim_1", "Needs human review", "needs_review")
    task = create_review_task(project_id, "claim_1", assignee="seed")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    denied_create = client.post(
        "/api/review/tasks",
        json={"project_id": project_id, "claim_id": "claim_1", "assignee": "alice", "priority": "normal"},
        headers=headers,
    )
    assert denied_create.status_code == 403

    denied_comment = client.post(
        f"/api/review/tasks/{task['id']}/comments",
        json={"project_id": project_id, "author": "bob", "body": "Please confirm support level."},
        headers=headers,
    )
    assert denied_comment.status_code == 403

    denied_update = client.patch(
        f"/api/review/tasks/{task['id']}",
        json={"project_id": project_id, "status": "in_review", "assignee": "carol"},
        headers=headers,
    )
    assert denied_update.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "reviewer")
    allowed_create = client.post(
        "/api/review/tasks",
        json={"project_id": project_id, "claim_id": "claim_1", "assignee": "alice", "priority": "normal"},
        headers=headers,
    )
    assert allowed_create.status_code == 200
    task_id = allowed_create.json()["id"]

    allowed_comment = client.post(
        f"/api/review/tasks/{task_id}/comments",
        json={"project_id": project_id, "author": "bob", "body": "Please confirm support level."},
        headers=headers,
    )
    assert allowed_comment.status_code == 200

    allowed_update = client.patch(
        f"/api/review/tasks/{task_id}",
        json={"project_id": project_id, "status": "in_review", "assignee": "carol"},
        headers=headers,
    )
    assert allowed_update.status_code == 200
    assert allowed_update.json()["status"] == "in_review"

    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    payloads = [json.loads(row["payload_json"]) for row in rows]
    assert [payload["route"] for payload in payloads] == [
        "POST /api/review/tasks",
        "POST /api/review/tasks/{task_id}/comments",
        "PATCH /api/review/tasks/{task_id}",
        "POST /api/review/tasks",
        "POST /api/review/tasks/{task_id}/comments",
        "PATCH /api/review/tasks/{task_id}",
    ]
    assert all(payload["audit_only"] is True for payload in payloads)
    assert all(payload["server_mode"] is True for payload in payloads)
    assert [payload["would_block"] for payload in payloads] == [True, True, True, False, False, False]
    assert [payload["guard_reason"] for payload in payloads] == [
        "server_mode_would_block",
        "server_mode_would_block",
        "server_mode_would_block",
        "server_mode_would_allow",
        "server_mode_would_allow",
        "server_mode_would_allow",
    ]


def test_review_task_mutation_guards_allow_legacy_project_without_owner_acl(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "review_api_guard_legacy"
    ensure_project(project_id)
    _insert_claim(project_id, "claim_1", "Needs human review", "needs_review")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    created = client.post(
        "/api/review/tasks",
        json={"project_id": project_id, "claim_id": "claim_1", "assignee": "alice", "priority": "normal"},
        headers=headers,
    )
    assert created.status_code == 200
    task_id = created.json()["id"]

    commented = client.post(
        f"/api/review/tasks/{task_id}/comments",
        json={"project_id": project_id, "author": "bob", "body": "Please confirm support level."},
        headers=headers,
    )
    assert commented.status_code == 200

    updated = client.patch(
        f"/api/review/tasks/{task_id}",
        json={"project_id": project_id, "status": "in_review", "assignee": "carol"},
        headers=headers,
    )

    assert updated.status_code == 200
    assert updated.json()["status"] == "in_review"


def _insert_claim(project_id: str, claim_id: str, text: str, status: str) -> None:
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into claims(id, project_id, run_id, claim_text, claim_type, status, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (claim_id, project_id, "run_1", text, "memo", status, "2026-06-09T00:00:00Z"),
        )
