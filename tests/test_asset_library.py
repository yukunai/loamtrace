import tempfile
from pathlib import Path

import pytest

from loamtrace import config
from loamtrace.db import connect
from loamtrace.services.asset_library import add_document_asset, delete_asset, import_asset_to_project, list_assets, update_asset_tags
from loamtrace.services.documents import import_document, list_documents
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


def test_add_document_asset_reuses_sha_and_merges_tags(tmp_workspace):
    source_path = _write_temp_file("Asset content")
    doc = import_document("source_project", str(source_path))

    first = add_document_asset("source_project", doc["id"], tags=["Market Map", "Finance"])
    second = add_document_asset("source_project", doc["id"], tags=["finance", "Diligence"])

    assert second["id"] == first["id"]
    assert second["tags"] == ["diligence", "finance", "market-map"]
    assert second["source_refs"] == [{"project_id": "source_project", "document_id": doc["id"]}]
    assert Path(second["storage_path"]).exists()

    assets = list_assets(tag="market map")
    assert [asset["id"] for asset in assets] == [first["id"]]
    with connect(project_db_path("source_project")) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("asset_registered",)).fetchall()
    assert len(audit) == 2


def test_import_asset_to_another_project(tmp_workspace):
    source_path = _write_temp_file("Reusable market evidence")
    source_doc = import_document("p_source", str(source_path))
    asset = add_document_asset("p_source", source_doc["id"], tags=["market"])

    result = import_asset_to_project("p_target", asset["id"])

    imported = result["document"]
    assert result["asset"]["id"] == asset["id"]
    assert imported["project_id"] == "p_target"
    assert imported["sha256"] == asset["sha256"]
    assert list_documents("p_target")[0]["id"] == imported["id"]
    assert Path(imported["source_path"]).exists()
    assert Path(imported["source_path"]).read_text(encoding="utf-8") == "Reusable market evidence"
    with connect(project_db_path("p_target")) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("asset_imported",)).fetchone()
    assert audit is not None


def test_delete_asset_removes_catalog_entry_and_file(tmp_workspace):
    source_path = _write_temp_file("Disposable asset")
    doc = import_document("asset_delete_source", str(source_path))
    asset = add_document_asset("asset_delete_source", doc["id"], tags=["cleanup"])
    storage_path = Path(asset["storage_path"])

    result = delete_asset(asset["id"])

    assert result == {"asset_id": asset["id"], "deleted": True, "file_deleted": True}
    assert list_assets() == []
    assert not storage_path.exists()
    with connect(project_db_path("asset_delete_source")) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("asset_deleted",)).fetchone()
    assert audit is not None


def test_update_asset_tags_replaces_tags_and_updates_search(tmp_workspace):
    source_path = _write_temp_file("Retaggable asset")
    doc = import_document("asset_tags_source", str(source_path))
    asset = add_document_asset("asset_tags_source", doc["id"], tags=["old tag"])

    updated = update_asset_tags(asset["id"], ["New Tag", "finance", "new tag"])

    assert updated["tags"] == ["finance", "new-tag"]
    assert [item["id"] for item in list_assets(tag="new tag")] == [asset["id"]]
    assert list_assets(tag="old tag") == []
    with connect(project_db_path("asset_tags_source")) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("asset_tags_updated",)).fetchone()
    assert audit is not None


def test_asset_library_api(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")

    source_path = _write_temp_file("Reusable API asset")
    doc = import_document("api_source", str(source_path))
    client = TestClient(main.app)

    created = client.post(
        "/api/assets/from-document",
        json={"project_id": "api_source", "document_id": doc["id"], "tags": ["Legal"]},
    )
    assert created.status_code == 200
    asset_id = created.json()["id"]

    listed = client.get("/api/assets?tag=legal")
    assert listed.status_code == 200
    assert [asset["id"] for asset in listed.json()] == [asset_id]

    updated = client.put(f"/api/assets/{asset_id}/tags", json={"tags": ["Diligence", "Market Map"]})
    assert updated.status_code == 200
    assert updated.json()["tags"] == ["diligence", "market-map"]
    assert client.get("/api/assets?tag=legal").json() == []
    assert [asset["id"] for asset in client.get("/api/assets?tag=market map").json()] == [asset_id]

    imported = client.post(
        "/api/assets/import",
        json={"project_id": "api_target", "asset_id": asset_id},
    )
    assert imported.status_code == 200
    assert imported.json()["document"]["project_id"] == "api_target"

    deleted = client.delete(f"/api/assets/{asset_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get("/api/assets?tag=legal").json() == []

    deleted_again = client.delete(f"/api/assets/{asset_id}")
    assert deleted_again.status_code == 404

    missing_update = client.put(f"/api/assets/{asset_id}/tags", json={"tags": ["missing"]})
    assert missing_update.status_code == 404


def test_asset_library_apis_enforce_server_mode_route_guards(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    source_doc = import_document("asset_guard_source", str(_write_temp_file("Guarded reusable asset")))
    bootstrap_local_admin("asset_guard_source", "owner@example.test", "Owner")
    bootstrap_local_admin("asset_guard_target", "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    created_denied = client.post(
        "/api/assets/from-document",
        json={"project_id": "asset_guard_source", "document_id": source_doc["id"], "tags": ["Legal"]},
        headers=headers,
    )
    assert created_denied.status_code == 403

    upsert_user("asset_guard_source", "user_1", "user@example.test", "User One")
    set_project_acl("asset_guard_source", "user", "user_1", "editor")
    created = client.post(
        "/api/assets/from-document",
        json={"project_id": "asset_guard_source", "document_id": source_doc["id"], "tags": ["Legal"]},
        headers=headers,
    )
    assert created.status_code == 200
    asset_id = created.json()["id"]

    imported_denied = client.post(
        "/api/assets/import",
        json={"project_id": "asset_guard_target", "asset_id": asset_id},
        headers=headers,
    )
    assert imported_denied.status_code == 403

    upsert_user("asset_guard_target", "user_1", "user@example.test", "User One")
    set_project_acl("asset_guard_target", "user", "user_1", "editor")
    imported = client.post(
        "/api/assets/import",
        json={"project_id": "asset_guard_target", "asset_id": asset_id},
        headers=headers,
    )
    assert imported.status_code == 200
    assert imported.json()["document"]["project_id"] == "asset_guard_target"

    updated = client.put(f"/api/assets/{asset_id}/tags", json={"tags": ["Diligence"]}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["tags"] == ["diligence"]

    delete_denied = client.delete(f"/api/assets/{asset_id}", headers=headers)
    assert delete_denied.status_code == 403

    set_project_acl("asset_guard_source", "user", "user_1", "owner")
    deleted = client.delete(f"/api/assets/{asset_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_asset_library_guards_allow_legacy_project_without_owner_acl(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    source_doc = import_document("asset_guard_legacy", str(_write_temp_file("Legacy reusable asset")))
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    created = client.post(
        "/api/assets/from-document",
        json={"project_id": "asset_guard_legacy", "document_id": source_doc["id"], "tags": ["Legacy"]},
        headers=headers,
    )
    assert created.status_code == 200
    asset_id = created.json()["id"]

    updated = client.put(f"/api/assets/{asset_id}/tags", json={"tags": ["Updated"]}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["tags"] == ["updated"]

    deleted = client.delete(f"/api/assets/{asset_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def _write_temp_file(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    try:
        handle.write(text.encode("utf-8"))
        return Path(handle.name)
    finally:
        handle.close()
