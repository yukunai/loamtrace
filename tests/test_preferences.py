from loamtrace import config
from loamtrace.db import connect
from loamtrace.services.paths import project_db_path
from loamtrace.services.preferences import get_ui_preferences, save_ui_preferences
from loamtrace.services.retrieval_preferences import (
    DEFAULT_RETRIEVAL_PREFERENCES,
    get_retrieval_preferences,
    save_retrieval_preferences,
)


RETRIEVAL_PAYLOAD = {
    "top_n": 4,
    "rrf_k": 42,
    "fts_top_n": 8,
    "vector_top_n": 9,
    "keyword_boost": 1.6,
    "vector_boost": 0.4,
}


def test_retrieval_preferences_defaults_and_save(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")

    defaults = get_retrieval_preferences("p1")
    assert defaults["project_id"] == "p1"
    assert defaults["updated_at"] is None
    assert defaults["top_n"] == DEFAULT_RETRIEVAL_PREFERENCES["top_n"]
    assert defaults["rrf_k"] == DEFAULT_RETRIEVAL_PREFERENCES["rrf_k"]

    saved = save_retrieval_preferences("p1", RETRIEVAL_PAYLOAD)
    assert saved["updated_at"]
    assert saved["rrf_k"] == RETRIEVAL_PAYLOAD["rrf_k"]
    assert saved["keyword_boost"] == RETRIEVAL_PAYLOAD["keyword_boost"]

    loaded = get_retrieval_preferences("p1")
    assert loaded["top_n"] == RETRIEVAL_PAYLOAD["top_n"]
    assert loaded["vector_boost"] == RETRIEVAL_PAYLOAD["vector_boost"]


def test_ui_preferences_defaults_and_save(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")

    defaults = get_ui_preferences("p1")
    assert defaults["column_widths"] == {"sidebar": 230, "memo": 380, "viewer": 560}
    assert defaults["updated_at"] is None

    saved = save_ui_preferences(
        "p1",
        {"sidebar": 300, "memo": 500, "viewer": 700},
    )
    assert saved["updated_at"]
    assert saved["column_widths"] == {"sidebar": 300, "memo": 500, "viewer": 700}

    loaded = get_ui_preferences("p1")
    assert loaded["column_widths"] == saved["column_widths"]


def test_ui_preferences_api_enforces_server_mode_write_guard(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    project_id = "ui_prefs_guard"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}
    payload = {"column_widths": {"sidebar": 300, "memo": 500, "viewer": 700}}

    denied = client.put(f"/api/projects/{project_id}/ui-preferences", json=payload, headers=headers)
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    allowed = client.put(f"/api/projects/{project_id}/ui-preferences", json=payload, headers=headers)
    assert allowed.status_code == 200
    assert allowed.json()["column_widths"] == payload["column_widths"]

    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    assert len(rows) == 2


def test_ui_preferences_guard_allows_legacy_project_without_owner_acl(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    project_id = "ui_prefs_legacy"
    client = TestClient(main.app)

    response = client.put(
        f"/api/projects/{project_id}/ui-preferences",
        json={"column_widths": {"sidebar": 300, "memo": 500, "viewer": 700}},
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )

    assert response.status_code == 200


def test_retrieval_preferences_api_enforces_server_mode_write_guard(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    project_id = "retrieval_prefs_guard"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    denied = client.put(f"/api/projects/{project_id}/retrieval-preferences", json=RETRIEVAL_PAYLOAD, headers=headers)
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    allowed = client.put(f"/api/projects/{project_id}/retrieval-preferences", json=RETRIEVAL_PAYLOAD, headers=headers)
    assert allowed.status_code == 200
    assert allowed.json()["rrf_k"] == RETRIEVAL_PAYLOAD["rrf_k"]

    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    assert len(rows) == 2


def test_retrieval_preferences_guard_allows_legacy_project_without_owner_acl(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    project_id = "retrieval_prefs_legacy"
    client = TestClient(main.app)

    response = client.put(
        f"/api/projects/{project_id}/retrieval-preferences",
        json=RETRIEVAL_PAYLOAD,
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )

    assert response.status_code == 200
    assert response.json()["top_n"] == RETRIEVAL_PAYLOAD["top_n"]
