from fastapi.testclient import TestClient

from loamtrace.main import app
from loamtrace.services.access_control import (
    actor_audit_fields,
    actor_from_headers,
    check_project_access,
    dry_run_route_guard,
    get_current_actor,
    guarded_project_access,
    require_project_access,
    reset_current_actor,
    set_current_actor,
    preview_project_access,
)
from loamtrace.services.team_admin import set_project_acl, upsert_team, upsert_user


def test_default_actor_keeps_desktop_noop_access():
    actor = get_current_actor()

    assert actor["id"] == "local"
    decision = require_project_access("default", "read")
    assert decision["allowed"] is True
    assert decision["mode"] == "desktop"
    assert decision["reason"] == "desktop_noop"


def test_actor_from_headers_sets_team_context_without_enforcing_acl():
    actor = actor_from_headers(
        {
            "x-loamtrace-actor-id": "user_1",
            "x-loamtrace-actor-email": "user@example.test",
            "x-loamtrace-actor-name": "User One",
            "x-loamtrace-team-id": "team_1",
            "x-loamtrace-project-role": "reviewer",
            "x-request-id": "req_1",
        }
    )

    assert actor["mode"] == "team"
    assert actor["project_role"] == "reviewer"
    decision = check_project_access("project_1", "review", actor)
    assert decision["allowed"] is True
    assert decision["reason"] == "team_acl_not_enforced_s1"
    assert actor_audit_fields(actor) == {
        "actor_user_id": "user_1",
        "actor_email": "user@example.test",
        "team_id": "team_1",
        "project_role": "reviewer",
        "request_id": "req_1",
    }


def test_team_actor_without_explicit_project_role_defaults_to_viewer():
    actor = actor_from_headers(
        {
            "x-loamtrace-actor-id": "user_1",
            "x-loamtrace-actor-email": "user@example.test",
        }
    )

    assert actor["mode"] == "team"
    assert actor["project_role"] == "viewer"


def test_actor_context_resets_after_token_reset():
    original = get_current_actor()
    token = set_current_actor({"id": "temporary", "mode": "team", "project_role": "editor"})
    try:
        assert get_current_actor()["id"] == "temporary"
    finally:
        reset_current_actor(token)

    assert get_current_actor() == original


def test_session_actor_endpoint_uses_request_headers_and_resets():
    client = TestClient(app)

    team_response = client.get(
        "/api/session/actor",
        params={"project_id": "project_1"},
        headers={
            "x-loamtrace-actor-id": "user_1",
            "x-loamtrace-actor-email": "user@example.test",
            "x-loamtrace-team-id": "team_1",
            "x-loamtrace-project-role": "editor",
        },
    )
    assert team_response.status_code == 200
    body = team_response.json()
    assert body["actor"]["id"] == "user_1"
    assert body["actor"]["mode"] == "team"
    assert body["authorization"]["project_id"] == "project_1"
    assert body["authorization"]["reason"] == "team_acl_not_enforced_s1"

    local_response = client.get("/api/session/actor")
    assert local_response.status_code == 200
    assert local_response.json()["actor"]["id"] == "local"
    assert local_response.json()["authorization"]["reason"] == "desktop_noop"
    assert local_response.json()["acl_preview"]["reason"] == "desktop_owner_preview"


def test_acl_preview_uses_matching_user_acl(tmp_path, monkeypatch):
    from loamtrace import config

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "acl_user_preview"
    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")

    actor = {"id": "user_1", "mode": "team", "project_role": "viewer"}
    preview = preview_project_access(project_id, "export", actor)

    assert preview["allowed"] is True
    assert preview["enforced"] is False
    assert preview["reason"] == "acl_preview_allowed"
    assert preview["required_role"] == "editor"
    assert preview["matched_role"] == "editor"
    assert preview["matched_principal_type"] == "user"


def test_acl_preview_uses_team_acl_and_reports_insufficient_role(tmp_path, monkeypatch):
    from loamtrace import config

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "acl_team_preview"
    upsert_team(project_id, "team_1", "Team One")
    set_project_acl(project_id, "team", "team_1", "reviewer")

    actor = {"id": "user_1", "team_id": "team_1", "mode": "team", "project_role": "viewer"}
    preview = preview_project_access(project_id, "write", actor)

    assert preview["allowed"] is False
    assert preview["enforced"] is False
    assert preview["reason"] == "acl_preview_insufficient_role"
    assert preview["required_role"] == "editor"
    assert preview["matched_role"] == "reviewer"
    assert preview["matched_principal_type"] == "team"


def test_session_actor_endpoint_exposes_acl_preview_from_headers(tmp_path, monkeypatch):
    from loamtrace import config

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "acl_api_preview"
    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "viewer")

    response = TestClient(app).get(
        "/api/session/actor",
        params={"project_id": project_id},
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["authorization"]["allowed"] is True
    assert body["authorization"]["reason"] == "team_acl_not_enforced_s1"
    assert body["acl_preview"]["allowed"] is True
    assert body["acl_preview"]["enforced"] is False
    assert body["acl_preview"]["matched_role"] == "viewer"


def test_dry_run_guard_is_disabled_by_default(tmp_path, monkeypatch):
    from loamtrace import config

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(config, "SERVER_MODE", False)
    project_id = "guard_default"
    actor = {"id": "user_1", "mode": "team"}

    decision = dry_run_route_guard(project_id, "delete", actor)

    assert decision["allowed"] is True
    assert decision["enforced"] is False
    assert decision["would_block"] is False
    assert decision["server_mode"] is False
    assert decision["guard_reason"] == "server_mode_disabled"


def test_dry_run_guard_reports_would_block_when_server_mode_enabled(tmp_path, monkeypatch):
    from loamtrace import config

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(config, "SERVER_MODE", True)
    project_id = "guard_enabled"
    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "viewer")

    decision = dry_run_route_guard(project_id, "delete", {"id": "user_1", "mode": "team"})

    assert decision["allowed"] is False
    assert decision["enforced"] is True
    assert decision["would_block"] is True
    assert decision["server_mode"] is True
    assert decision["guard_reason"] == "server_mode_would_block"
    assert decision["matched_role"] == "viewer"
    assert decision["required_role"] == "owner"


def test_guard_check_api_respects_server_mode_flag(tmp_path, monkeypatch):
    from loamtrace import config

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(config, "SERVER_MODE", True)
    project_id = "guard_api"
    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "viewer")

    response = TestClient(app).get(
        "/api/team/acl/guard-check",
        params={"project_id": project_id, "permission": "read"},
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True
    assert response.json()["enforced"] is True
    assert response.json()["guard_reason"] == "server_mode_would_allow"


def test_guarded_access_allows_old_desktop_project_until_owner_bootstrap(tmp_path, monkeypatch):
    from loamtrace import config

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(config, "SERVER_MODE", True)

    decision = guarded_project_access("legacy_without_acl", "read", {"id": "user_1", "mode": "team"})

    assert decision["allowed"] is True
    assert decision["enforced"] is False
    assert decision["would_block"] is False
    assert decision["guard_reason"] == "owner_bootstrap_required"


def test_guarded_access_denies_unlisted_actor_after_owner_bootstrap(tmp_path, monkeypatch):
    from loamtrace import config
    from loamtrace.services.team_admin import bootstrap_local_admin

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(config, "SERVER_MODE", True)
    project_id = "guarded_after_bootstrap"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")

    try:
        guarded_project_access(project_id, "read", {"id": "user_1", "mode": "team"})
    except PermissionError as exc:
        assert "read access denied" in str(exc)
    else:
        raise AssertionError("guarded_project_access should deny unlisted actor after owner bootstrap")


def test_document_list_route_guard_default_and_server_mode(tmp_path, monkeypatch):
    from loamtrace import config
    from loamtrace.services.team_admin import bootstrap_local_admin

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "guarded_documents"
    client = TestClient(app)

    monkeypatch.setattr(config, "SERVER_MODE", False)
    default_response = client.get(f"/api/projects/{project_id}/documents")
    assert default_response.status_code == 200
    assert default_response.json() == []

    monkeypatch.setattr(config, "SERVER_MODE", True)
    legacy_response = client.get(
        f"/api/projects/{project_id}/documents",
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )
    assert legacy_response.status_code == 200

    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    denied_response = client.get(
        f"/api/projects/{project_id}/documents",
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )
    assert denied_response.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "viewer")
    allowed_response = client.get(
        f"/api/projects/{project_id}/documents",
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )
    assert allowed_response.status_code == 200


def test_low_risk_read_routes_share_guard_default_and_server_mode(tmp_path, monkeypatch):
    from loamtrace import config
    from loamtrace.services.team_admin import bootstrap_local_admin

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "guarded_read_routes"
    client = TestClient(app)
    routes = [
        ("/api/claims", {"project_id": project_id}),
        ("/api/review/tasks", {"project_id": project_id}),
        ("/api/export/artifacts", {"project_id": project_id}),
    ]

    monkeypatch.setattr(config, "SERVER_MODE", False)
    for route, params in routes:
        response = client.get(route, params=params)
        assert response.status_code == 200
        assert response.json() == []

    monkeypatch.setattr(config, "SERVER_MODE", True)
    for route, params in routes:
        legacy_response = client.get(
            route,
            params=params,
            headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
        )
        assert legacy_response.status_code == 200

    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    for route, params in routes:
        denied_response = client.get(
            route,
            params=params,
            headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
        )
        assert denied_response.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "viewer")
    for route, params in routes:
        allowed_response = client.get(
            route,
            params=params,
            headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
        )
        assert allowed_response.status_code == 200
