import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.db import connect
from loamtrace.main import app
from loamtrace.services.documents import import_document
from loamtrace.services.paths import ensure_project, project_db_path, project_root
from loamtrace.services.sync import delete_synced_snapshot, list_synced_snapshots, pull_project_snapshot, push_project_snapshot


def test_push_list_and_pull_project_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "workspace" / "projects")
    project_id = "sync_source"
    ensure_project(project_id, "Sync Source")
    source = tmp_path / "source.txt"
    source.write_text("Synced source file.", encoding="utf-8")
    imported = import_document(project_id, str(source))
    notes = project_root(project_id) / "notes" / "memo.md"
    notes.write_text("# Synced Memo\n", encoding="utf-8")

    target_dir = tmp_path / "sync-target"
    pushed = push_project_snapshot(project_id, str(target_dir))

    archive_path = Path(pushed["archive_path"])
    metadata_path = Path(pushed["metadata_path"])
    assert archive_path.exists()
    assert metadata_path.exists()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["snapshot_id"] == pushed["snapshot_id"]
    assert metadata["project_id"] == project_id
    assert metadata["archive_sha256"] == pushed["archive_sha256"]
    assert len(metadata["archive_sha256"]) == 64

    snapshots = list_synced_snapshots(str(target_dir))
    assert len(snapshots) == 1
    assert snapshots[0]["snapshot_id"] == pushed["snapshot_id"]
    assert snapshots[0]["available"] is True
    assert snapshots[0]["integrity_status"] == "ok"
    assert snapshots[0]["archive_sha256"] == pushed["archive_sha256"]

    restored = pull_project_snapshot(str(target_dir), pushed["snapshot_id"], "sync_restored")
    restored_root = project_root("sync_restored")
    assert restored["project_id"] == "sync_restored"
    assert (restored_root / "notes" / "memo.md").read_text(encoding="utf-8") == "# Synced Memo\n"
    assert (restored_root / "sources" / "original" / f"{imported['id']}_source.txt").read_text(encoding="utf-8") == "Synced source file."

    with connect(project_db_path(project_id)) as conn:
        assert conn.execute("select 1 from audit_log where type = ?", ("project_snapshot_synced",)).fetchone()
    with connect(project_db_path("sync_restored")) as conn:
        assert conn.execute("select 1 from audit_log where type = ?", ("project_snapshot_pulled",)).fetchone()


def test_sync_api_push_list_pull_and_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "workspace" / "projects")
    project_id = "sync_api_source"
    ensure_project(project_id, "Sync API Source")
    (project_root(project_id) / "notes" / "memo.md").write_text("# API Sync\n", encoding="utf-8")
    target_dir = tmp_path / "sync-target"
    client = TestClient(app)

    pushed = client.post(
        "/api/sync/push-snapshot",
        json={"project_id": project_id, "target_dir": str(target_dir), "include_index": True},
    )
    assert pushed.status_code == 200
    snapshot_id = pushed.json()["snapshot_id"]

    listed = client.get("/api/sync/snapshots", params={"target_dir": str(target_dir), "project_id": project_id})
    assert listed.status_code == 200
    assert [item["snapshot_id"] for item in listed.json()] == [snapshot_id]

    pulled = client.post(
        "/api/sync/pull-snapshot",
        json={"target_dir": str(target_dir), "snapshot_id": snapshot_id, "project_id": "sync_api_restored"},
    )
    assert pulled.status_code == 200
    assert pulled.json()["project_id"] == "sync_api_restored"

    conflict = client.post(
        "/api/sync/pull-snapshot",
        json={"target_dir": str(target_dir), "snapshot_id": snapshot_id, "project_id": "sync_api_restored"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "project_already_exists"

    overwritten = client.post(
        "/api/sync/pull-snapshot",
        json={
            "target_dir": str(target_dir),
            "snapshot_id": snapshot_id,
            "project_id": "sync_api_restored",
            "overwrite": True,
        },
    )
    assert overwritten.status_code == 200
    assert overwritten.json()["project_id"] == "sync_api_restored"

    deleted = client.post(
        "/api/sync/delete-snapshot",
        json={"target_dir": str(target_dir), "snapshot_id": snapshot_id},
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get("/api/sync/snapshots", params={"target_dir": str(target_dir)}).json() == []

    missing_delete = client.post(
        "/api/sync/delete-snapshot",
        json={"target_dir": str(target_dir), "snapshot_id": snapshot_id},
    )
    assert missing_delete.status_code == 404
    assert missing_delete.json()["detail"] == "synced_snapshot_not_found"


def test_sync_snapshot_project_id_is_sanitized_as_path_segment(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "workspace" / "projects")
    project_id = "../unsafe"
    ensure_project(project_id, "Unsafe Sync Source")
    target_dir = tmp_path / "sync-target"

    pushed = push_project_snapshot(project_id, str(target_dir))

    archive_path = Path(pushed["archive_path"])
    assert archive_path.exists()
    assert target_dir.resolve() in archive_path.resolve().parents
    assert archive_path.parent.name == "_unsafe"
    assert not (target_dir / "loamtrace-sync" / "unsafe").exists()


def test_delete_synced_snapshot_removes_archive_and_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "workspace" / "projects")
    project_id = "sync_delete_source"
    ensure_project(project_id, "Sync Delete Source")
    target_dir = tmp_path / "sync-target"
    pushed = push_project_snapshot(project_id, str(target_dir))

    deleted = delete_synced_snapshot(str(target_dir), pushed["snapshot_id"])

    assert deleted["deleted"] is True
    assert not Path(pushed["archive_path"]).exists()
    assert not Path(pushed["metadata_path"]).exists()
    assert list_synced_snapshots(str(target_dir)) == []
    with connect(project_db_path(project_id)) as conn:
        assert conn.execute("select 1 from audit_log where type = ?", ("project_snapshot_sync_deleted",)).fetchone()


def test_sync_pull_rejects_tampered_snapshot_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "workspace" / "projects")
    project_id = "sync_tamper_source"
    ensure_project(project_id, "Sync Tamper Source")
    (project_root(project_id) / "notes" / "memo.md").write_text("# Tamper\n", encoding="utf-8")
    target_dir = tmp_path / "sync-target"

    pushed = push_project_snapshot(project_id, str(target_dir))
    archive_path = Path(pushed["archive_path"])
    archive_path.write_bytes(b"not the original snapshot")

    listed = list_synced_snapshots(str(target_dir), project_id)
    assert listed[0]["available"] is False
    assert listed[0]["integrity_status"] == "size_mismatch"
    with pytest.raises(ValueError, match="synced_snapshot_size_mismatch"):
        pull_project_snapshot(str(target_dir), pushed["snapshot_id"], "sync_tampered_restore")

    response = TestClient(app).post(
        "/api/sync/pull-snapshot",
        json={"target_dir": str(target_dir), "snapshot_id": pushed["snapshot_id"], "project_id": "sync_tampered_api"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "synced_snapshot_size_mismatch"
