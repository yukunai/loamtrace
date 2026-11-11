import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.db import connect
from loamtrace.services.documents import import_document
from loamtrace.services.paths import project_db_path


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


def test_document_delete_api_enforces_server_mode_route_guard(tmp_workspace, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "source_deletion_guard"
    document = import_document(project_id, str(_write_temp_file("Delete guarded document")))
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            "insert into chunks(id, document_id, chunk_type, text, source_uri) values (?, ?, ?, ?, ?)",
            ("chunk_delete", document["id"], "text", "Delete guarded document", f"txt://{document['id']}#chunk=chunk_delete"),
        )
        conn.execute(
            """
            insert into claims(id, project_id, run_id, claim_text, status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "claim_delete",
                project_id,
                "run_delete",
                "Delete guarded document",
                "verified",
                "2026-06-22T00:00:00Z",
            ),
        )
        conn.execute(
            """
            insert into citations(id, claim_id, chunk_id, document_id, quote, source_uri, verified)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "citation_delete",
                "claim_delete",
                "chunk_delete",
                document["id"],
                "Delete guarded document",
                f"txt://{document['id']}#chunk=chunk_delete",
                1,
            ),
        )
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    denied = client.delete(f"/api/projects/{project_id}/documents/{document['id']}", headers=headers)
    assert denied.status_code == 403

    preview_denied = client.get(
        f"/api/projects/{project_id}/documents/{document['id']}/delete-preview",
        headers=headers,
    )
    assert preview_denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    editor_denied = client.delete(f"/api/projects/{project_id}/documents/{document['id']}", headers=headers)
    assert editor_denied.status_code == 403

    editor_preview_denied = client.get(
        f"/api/projects/{project_id}/documents/{document['id']}/delete-preview",
        headers=headers,
    )
    assert editor_preview_denied.status_code == 403

    set_project_acl(project_id, "user", "user_1", "owner")
    preview_allowed = client.get(
        f"/api/projects/{project_id}/documents/{document['id']}/delete-preview",
        headers=headers,
    )
    assert preview_allowed.status_code == 200
    preview_body = preview_allowed.json()
    assert preview_body["deleted"] is False
    assert preview_body["document_id"] == document["id"]
    assert preview_body["removed_claim_ids"] == ["claim_delete"]
    assert preview_body["retained_claim_ids"] == []
    assert preview_body["removed_citation_ids"] == ["citation_delete"]
    assert preview_body["removed_claims"] == [
        {"id": "claim_delete", "text": "Delete guarded document", "status": "verified"}
    ]
    assert [item["kind"] for item in preview_body["file_impacts"]] == ["source_file", "rendered_pages"]
    with connect(project_db_path(project_id)) as conn:
        assert conn.execute("select count(*) from documents where id = ?", (document["id"],)).fetchone()[0] == 1
        assert conn.execute("select status from claims where id = ?", ("claim_delete",)).fetchone()["status"] == "verified"

    allowed = client.delete(f"/api/projects/{project_id}/documents/{document['id']}", headers=headers)
    assert allowed.status_code == 200
    delete_body = allowed.json()
    assert delete_body["deleted"] is True
    assert delete_body["removed_claim_ids"] == ["claim_delete"]


def test_document_delete_guard_allows_legacy_project_without_owner_acl(tmp_workspace, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "source_deletion_legacy"
    document = import_document(project_id, str(_write_temp_file("Legacy delete document")))
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    allowed = client.delete(f"/api/projects/{project_id}/documents/{document['id']}", headers=headers)
    assert allowed.status_code == 200
    assert allowed.json()["deleted"] is True


def _write_temp_file(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    try:
        handle.write(text.encode("utf-8"))
        return Path(handle.name)
    finally:
        handle.close()
