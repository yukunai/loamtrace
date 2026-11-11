import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.services.documents import import_document


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


def test_source_processing_apis_enforce_server_mode_route_guards(tmp_workspace, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "source_processing_guard"
    document = import_document(project_id, str(_write_temp_file("Parse me")))
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    parse_denied = client.post(f"/api/documents/{document['id']}/parse", json={"project_id": project_id}, headers=headers)
    assert parse_denied.status_code == 403
    manual_denied = client.post(
        f"/api/documents/{document['id']}/manual-text",
        json={"project_id": project_id, "text": "Manual text"},
        headers=headers,
    )
    assert manual_denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")

    parsed = client.post(f"/api/documents/{document['id']}/parse", json={"project_id": project_id}, headers=headers)
    assert parsed.status_code == 200
    assert parsed.json()["status"] == "parsed"
    manual = client.post(
        f"/api/documents/{document['id']}/manual-text",
        json={"project_id": project_id, "text": "Manual replacement", "heading": "Manual"},
        headers=headers,
    )
    assert manual.status_code == 200
    assert manual.json()["parser_version"] == "manual-text-v1"


def test_source_processing_guards_allow_legacy_project_without_owner_acl(tmp_workspace, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "source_processing_legacy"
    document = import_document(project_id, str(_write_temp_file("Legacy parse me")))
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    parsed = client.post(f"/api/documents/{document['id']}/parse", json={"project_id": project_id}, headers=headers)
    assert parsed.status_code == 200
    manual = client.post(
        f"/api/documents/{document['id']}/manual-text",
        json={"project_id": project_id, "text": "Legacy manual text"},
        headers=headers,
    )
    assert manual.status_code == 200


def _write_temp_file(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    try:
        handle.write(text.encode("utf-8"))
        return Path(handle.name)
    finally:
        handle.close()
