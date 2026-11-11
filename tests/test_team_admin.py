import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.main import app
from loamtrace.services.team_admin import (
    acl_migration_diagnostics,
    bootstrap_local_admin,
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


def test_bootstrap_local_admin_is_idempotent(tmp_workspace):
    first = bootstrap_local_admin("team_admin_project", "Admin@Example.Test", "Admin One")
    second = bootstrap_local_admin("team_admin_project", "admin@example.test", "Admin Two")

    assert first["user"]["id"] == second["user"]["id"]
    assert second["user"]["email"] == "admin@example.test"
    assert second["user"]["display_name"] == "Admin Two"
    assert second["acl"]["principal_type"] == "user"
    assert second["acl"]["role"] == "owner"
    assert len(list_users("team_admin_project")) == 1
    assert len(list_project_acl("team_admin_project")) == 1


def test_acl_migration_diagnostics_keeps_empty_desktop_project_safe(tmp_workspace):
    diagnostics = acl_migration_diagnostics("diagnostics_empty")

    assert diagnostics["project_id"] == "diagnostics_empty"
    assert diagnostics["acl_entries"] == 0
    assert diagnostics["owner_acl_entries"] == 0
    assert diagnostics["desktop_compatible"] is True
    assert diagnostics["enforcement_ready"] is False
    assert diagnostics["enforcement_enabled"] is False
    assert diagnostics["recommended_action"] == "bootstrap_local_admin"


def test_acl_migration_diagnostics_reports_owner_ready_after_bootstrap(tmp_workspace):
    bootstrap_local_admin("diagnostics_bootstrap", "owner@example.test", "Owner")
    diagnostics = acl_migration_diagnostics("diagnostics_bootstrap")

    assert diagnostics["users"] == 1
    assert diagnostics["acl_entries"] == 1
    assert diagnostics["owner_acl_entries"] == 1
    assert diagnostics["enforcement_ready"] is True
    assert diagnostics["enforcement_enabled"] is False
    assert diagnostics["recommended_action"] == "none"


def test_team_admin_service_manages_members_and_acl(tmp_workspace):
    project_id = "team_admin_service"
    user = upsert_user(project_id, "user_1", "user@example.test", "User One")
    team = upsert_team(project_id, "team_1", "Team One")

    member = set_team_member(project_id, team["id"], user["id"], "admin")
    assert member["team_id"] == "team_1"
    assert member["user_id"] == "user_1"
    assert member["role"] == "admin"
    assert member["email"] == "user@example.test"

    acl = set_project_acl(project_id, "team", team["id"], "editor")
    assert acl["principal_type"] == "team"
    assert acl["principal_id"] == "team_1"
    assert acl["role"] == "editor"

    assert list_teams(project_id)[0]["name"] == "Team One"
    assert list_team_members(project_id, "team_1")[0]["display_name"] == "User One"
    assert list_project_acl(project_id)[0]["role"] == "editor"

    assert delete_team_member(project_id, "team_1", "user_1") == {
        "deleted": True,
        "team_id": "team_1",
        "user_id": "user_1",
    }
    assert delete_project_acl(project_id, "team", "team_1") == {
        "deleted": True,
        "project_id": project_id,
        "principal_type": "team",
        "principal_id": "team_1",
    }
    assert list_team_members(project_id) == []
    assert list_project_acl(project_id) == []


def test_team_admin_service_rejects_missing_entities_and_invalid_values(tmp_workspace):
    project_id = "team_admin_invalid"
    upsert_user(project_id, "user_1", "user@example.test", "User One")

    with pytest.raises(KeyError):
        set_team_member(project_id, "missing_team", "user_1", "viewer")
    with pytest.raises(ValueError):
        set_project_acl(project_id, "group", "user_1", "viewer")
    with pytest.raises(ValueError):
        upsert_user(project_id, "empty", "   ", None)


def test_team_admin_api_round_trip(tmp_workspace):
    client = TestClient(app)
    project_id = "team_admin_api"

    boot = client.post(
        "/api/team/bootstrap-admin",
        json={"project_id": project_id, "email": "admin@example.test", "display_name": "Admin"},
    )
    assert boot.status_code == 200
    assert boot.json()["acl"]["role"] == "owner"

    user = client.post(
        "/api/team/users",
        json={"project_id": project_id, "user_id": "user_2", "email": "user2@example.test", "display_name": "User Two"},
    )
    assert user.status_code == 200
    assert user.json()["id"] == "user_2"

    team = client.post(
        "/api/team/teams",
        json={"project_id": project_id, "team_id": "team_2", "name": "Team Two"},
    )
    assert team.status_code == 200
    assert team.json()["id"] == "team_2"

    member = client.put(
        "/api/team/members",
        json={"project_id": project_id, "team_id": "team_2", "user_id": "user_2", "role": "member"},
    )
    assert member.status_code == 200
    assert member.json()["email"] == "user2@example.test"

    acl = client.put(
        "/api/team/acl",
        json={"project_id": project_id, "principal_type": "team", "principal_id": "team_2", "role": "reviewer"},
    )
    assert acl.status_code == 200
    assert acl.json()["role"] == "reviewer"

    assert len(client.get("/api/team/users", params={"project_id": project_id}).json()) == 2
    assert len(client.get("/api/team/teams", params={"project_id": project_id}).json()) == 1
    assert len(client.get("/api/team/members", params={"project_id": project_id}).json()) == 1
    assert len(client.get("/api/team/acl", params={"project_id": project_id}).json()) == 2

    deleted_acl = client.delete(
        "/api/team/acl",
        params={"project_id": project_id, "principal_type": "team", "principal_id": "team_2"},
    )
    assert deleted_acl.status_code == 200
    assert deleted_acl.json()["deleted"] is True

    deleted_member = client.delete(
        "/api/team/members/team_2/user_2",
        params={"project_id": project_id},
    )
    assert deleted_member.status_code == 200
    assert deleted_member.json()["deleted"] is True


def test_acl_diagnostics_api_round_trip(tmp_workspace):
    client = TestClient(app)
    project_id = "diagnostics_api"

    initial = client.get("/api/team/acl/diagnostics", params={"project_id": project_id})
    assert initial.status_code == 200
    assert initial.json()["recommended_action"] == "bootstrap_local_admin"
    assert initial.json()["enforcement_enabled"] is False

    boot = client.post(
        "/api/team/bootstrap-admin",
        json={"project_id": project_id, "email": "owner@example.test", "display_name": "Owner"},
    )
    assert boot.status_code == 200

    ready = client.get("/api/team/acl/diagnostics", params={"project_id": project_id})
    assert ready.status_code == 200
    assert ready.json()["owner_acl_entries"] == 1
    assert ready.json()["enforcement_ready"] is True
    assert ready.json()["recommended_action"] == "none"
