import tempfile
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.main import app
from loamtrace.services.team_admin import (
    bootstrap_local_admin,
    set_project_acl,
    set_team_member,
    upsert_team,
    upsert_user,
)


@pytest.fixture
def tmp_workspace(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_root = config.WORKSPACE_ROOT
        orig_projects = config.PROJECTS_ROOT
        orig_server_mode = config.SERVER_MODE
        config.WORKSPACE_ROOT = Path(tmpdir)
        config.PROJECTS_ROOT = config.WORKSPACE_ROOT / "projects"
        monkeypatch.setattr(config, "SERVER_MODE", True)
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


def _bootstrap_project(project_id: str) -> dict:
    boot = bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    upsert_user(project_id, "user_2", "user2@example.test", "User Two")
    upsert_team(project_id, "team_1", "Team One")
    set_team_member(project_id, "team_1", "user_2", "member")
    set_project_acl(project_id, "user", "user_2", "viewer")
    return boot["user"]


def test_team_admin_routes_require_owner_after_bootstrap(tmp_workspace):
    client = TestClient(app)
    project_id = "team_admin_guard"
    owner = _bootstrap_project(project_id)
    unlisted_headers = _actor("intruder", "intruder@example.test")

    denied_cases = [
        client.post(
            "/api/team/users",
            headers=unlisted_headers,
            json={"project_id": project_id, "user_id": "user_3", "email": "user3@example.test"},
        ),
        client.post(
            "/api/team/teams",
            headers=unlisted_headers,
            json={"project_id": project_id, "team_id": "team_2", "name": "Team Two"},
        ),
        client.put(
            "/api/team/members",
            headers=unlisted_headers,
            json={"project_id": project_id, "team_id": "team_1", "user_id": "user_2", "role": "admin"},
        ),
        client.delete(
            "/api/team/members/team_1/user_2",
            headers=unlisted_headers,
            params={"project_id": project_id},
        ),
        client.put(
            "/api/team/acl",
            headers=unlisted_headers,
            json={"project_id": project_id, "principal_type": "user", "principal_id": "user_2", "role": "editor"},
        ),
        client.delete(
            "/api/team/acl",
            headers=unlisted_headers,
            params={"project_id": project_id, "principal_type": "user", "principal_id": "user_2"},
        ),
    ]

    assert [response.status_code for response in denied_cases] == [403, 403, 403, 403, 403, 403]

    owner_headers = _actor(owner["id"], owner["email"])
    assert client.post(
        "/api/team/users",
        headers=owner_headers,
        json={"project_id": project_id, "user_id": "user_3", "email": "user3@example.test"},
    ).status_code == 200
    assert client.post(
        "/api/team/teams",
        headers=owner_headers,
        json={"project_id": project_id, "team_id": "team_2", "name": "Team Two"},
    ).status_code == 200
    assert client.put(
        "/api/team/members",
        headers=owner_headers,
        json={"project_id": project_id, "team_id": "team_1", "user_id": "user_2", "role": "admin"},
    ).status_code == 200
    assert client.delete(
        "/api/team/members/team_1/user_2",
        headers=owner_headers,
        params={"project_id": project_id},
    ).status_code == 200
    assert client.put(
        "/api/team/acl",
        headers=owner_headers,
        json={"project_id": project_id, "principal_type": "user", "principal_id": "user_2", "role": "editor"},
    ).status_code == 200
    assert client.delete(
        "/api/team/acl",
        headers=owner_headers,
        params={"project_id": project_id, "principal_type": "user", "principal_id": "user_2"},
    ).status_code == 200


def test_team_admin_routes_reject_editor_acl(tmp_workspace):
    client = TestClient(app)
    project_id = "team_admin_editor_guard"
    _bootstrap_project(project_id)

    editor = upsert_user(project_id, "editor_user", "editor@example.test", "Editor")
    set_project_acl(project_id, "user", editor["id"], "editor")

    response = client.post(
        "/api/team/users",
        headers=_actor(editor["id"], editor["email"]),
        json={"project_id": project_id, "user_id": "blocked_user", "email": "blocked@example.test"},
    )

    assert response.status_code == 403


def test_team_admin_routes_keep_legacy_no_owner_project_compatible(tmp_workspace):
    client = TestClient(app)
    project_id = "team_admin_legacy"

    assert client.post(
        "/api/team/users",
        headers=_actor("legacy_actor"),
        json={"project_id": project_id, "user_id": "user_1", "email": "user1@example.test"},
    ).status_code == 200
    assert client.post(
        "/api/team/teams",
        headers=_actor("legacy_actor"),
        json={"project_id": project_id, "team_id": "team_1", "name": "Team One"},
    ).status_code == 200
    assert client.put(
        "/api/team/members",
        headers=_actor("legacy_actor"),
        json={"project_id": project_id, "team_id": "team_1", "user_id": "user_1", "role": "member"},
    ).status_code == 200
