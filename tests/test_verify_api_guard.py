import json

from fastapi.testclient import TestClient

from loamtrace.db import connect
from loamtrace.services.paths import ensure_project, project_db_path


def test_verify_run_api_enforces_server_mode_write_guard(tmp_path, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "verify_guard"
    _insert_source_chunk(project_id)
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}
    payload = _verify_payload(project_id)

    denied = client.post("/api/verify/run", json=payload, headers=headers)
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    allowed = client.post("/api/verify/run", json=payload, headers=headers)
    assert allowed.status_code == 200
    assert allowed.json()["claims"][0]["status"] == "verified"

    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    payloads = [json.loads(row["payload_json"]) for row in rows]
    assert [payload["route"] for payload in payloads] == [
        "POST /api/verify/run",
        "POST /api/verify/run",
    ]
    assert [payload["would_block"] for payload in payloads] == [True, False]


def test_verify_run_guard_allows_legacy_project_without_owner_acl(tmp_path, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "verify_guard_legacy"
    _insert_source_chunk(project_id)
    client = TestClient(main.app)

    response = client.post(
        "/api/verify/run",
        json=_verify_payload(project_id),
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )

    assert response.status_code == 200
    assert response.json()["claims"][0]["status"] == "verified"


def _insert_source_chunk(project_id: str) -> None:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "source",
                "doc_1",
                "text",
                "Revenue grew 24% in 2025.",
                "pdf://doc_1#page=1",
                "[]",
            ),
        )


def _verify_payload(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "claims": [
            {
                "text": "Revenue grew 24% in 2025.",
                "citations": [{"chunk_id": "source", "quote": "Revenue grew 24% in 2025."}],
            }
        ],
    }
