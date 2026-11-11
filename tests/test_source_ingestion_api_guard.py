import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loamtrace import config


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


def test_document_import_api_enforces_server_mode_route_guard(tmp_workspace, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "source_ingestion_guard"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    denied = client.post(
        "/api/documents/import",
        json={"project_id": project_id, "file_path": str(_write_temp_file("Denied import"))},
        headers=headers,
    )
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    allowed = client.post(
        "/api/documents/import",
        json={"project_id": project_id, "file_path": str(_write_temp_file("Allowed import"))},
        headers=headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["project_id"] == project_id


def test_document_import_guard_allows_legacy_project_without_owner_acl(tmp_workspace, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}
    allowed = client.post(
        "/api/documents/import",
        json={"project_id": "source_ingestion_legacy", "file_path": str(_write_temp_file("Legacy import"))},
        headers=headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["project_id"] == "source_ingestion_legacy"


def _write_temp_file(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    try:
        handle.write(text.encode("utf-8"))
        return Path(handle.name)
    finally:
        handle.close()
