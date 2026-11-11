import json

from fastapi.testclient import TestClient

from loamtrace.db import connect
from loamtrace.services.paths import project_db_path


def test_generate_memo_api_enforces_server_mode_write_guard(tmp_path, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    monkeypatch.setattr(main, "generate_memo", _fake_generate_memo)

    project_id = "generate_memo_guard"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}
    payload = {"project_id": project_id, "query": "revenue", "top_n": 2}

    denied = client.post("/api/generate/memo", json=payload, headers=headers)
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    allowed = client.post("/api/generate/memo", json=payload, headers=headers)
    assert allowed.status_code == 200
    assert allowed.json() == {
        "project_id": project_id,
        "query": "revenue",
        "top_n": 2,
        "answer": "# Verified Memo\n\nFake memo.\n",
        "claims": [],
        "retrieved_chunks": [],
    }

    query_allowed = client.post(
        "/api/generate/memo",
        params={"project_id": project_id, "query": "margin", "top_n": 1},
        headers=headers,
    )
    assert query_allowed.status_code == 200
    assert query_allowed.json()["query"] == "margin"

    payloads = _route_guard_payloads(project_id)
    assert [payload["route"] for payload in payloads] == [
        "POST /api/generate/memo",
        "POST /api/generate/memo",
        "POST /api/generate/memo",
    ]
    assert [payload["would_block"] for payload in payloads] == [True, False, False]


def test_memo_render_api_enforces_server_mode_write_guard(tmp_path, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "memo_render_guard"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}
    payload = {"project_id": project_id}

    denied = client.post("/api/memo/render", json=payload, headers=headers)
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    allowed = client.post("/api/memo/render", json=payload, headers=headers)
    assert allowed.status_code == 200
    assert allowed.json()["claims"] == []
    assert allowed.json()["markdown"].startswith("# Verified Memo")

    payloads = _route_guard_payloads(project_id)
    assert [payload["route"] for payload in payloads] == [
        "POST /api/memo/render",
        "POST /api/memo/render",
    ]
    assert [payload["would_block"] for payload in payloads] == [True, False]


def test_generation_guards_allow_legacy_project_without_owner_acl(tmp_path, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    monkeypatch.setattr(main, "generate_memo", _fake_generate_memo)

    project_id = "generation_guard_legacy"
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    generated = client.post(
        "/api/generate/memo",
        json={"project_id": project_id, "query": "revenue", "top_n": 1},
        headers=headers,
    )
    rendered = client.post("/api/memo/render", json={"project_id": project_id}, headers=headers)

    assert generated.status_code == 200
    assert rendered.status_code == 200


def _fake_generate_memo(project_id: str, query: str, top_n: int = 5) -> dict:
    return {
        "project_id": project_id,
        "query": query,
        "top_n": top_n,
        "answer": "# Verified Memo\n\nFake memo.\n",
        "claims": [],
        "retrieved_chunks": [],
    }


def _route_guard_payloads(project_id: str) -> list[dict]:
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]
