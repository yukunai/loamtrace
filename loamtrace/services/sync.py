from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Optional

from loamtrace.services.sync_providers import configured_sync_provider
from loamtrace.services.audit import write_audit
from loamtrace.services.exports import export_project_snapshot, import_project_snapshot
from loamtrace.services.paths import safe_project_id
from loamtrace.services.time import now_iso

SYNC_ROOT_NAME = "loamtrace-sync"


def push_project_snapshot(project_id: str, target_dir: str, include_index: bool = True) -> dict:
    target_root = _sync_root(target_dir)
    snapshot = export_project_snapshot(project_id, include_index)
    manifest = snapshot["manifest"]
    snapshot_id = snapshot["snapshot_id"]
    source_archive = Path(snapshot["archive_path"])
    safe_id = safe_project_id(project_id)
    project_dir = target_root / "snapshots" / safe_id
    project_dir.mkdir(parents=True, exist_ok=True)

    archive_path = project_dir / f"{snapshot_id}.zip"
    metadata_path = project_dir / f"{snapshot_id}.json"
    shutil.copy2(source_archive, archive_path)
    archive_sha256 = _sha256_file(archive_path)
    metadata = {
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "source_project_id": manifest.get("project_id") or project_id,
        "created_at": manifest.get("created_at") or now_iso(),
        "format": manifest.get("format"),
        "archive_path": str(archive_path),
        "metadata_path": str(metadata_path),
        "size_bytes": archive_path.stat().st_size,
        "archive_sha256": archive_sha256,
        "manifest": manifest,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    write_audit(
        project_id,
        "project_snapshot_synced",
        {
            "snapshot_id": snapshot_id,
            "target_dir": str(Path(target_dir).expanduser()),
            "archive_path": str(archive_path),
            "metadata_path": str(metadata_path),
        },
    )
    return {
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "target_dir": str(Path(target_dir).expanduser()),
        "archive_path": str(archive_path),
        "metadata_path": str(metadata_path),
        "manifest": manifest,
        "size_bytes": metadata["size_bytes"],
        "archive_sha256": archive_sha256,
    }


def push_project_snapshot_to_configured_provider(project_id: str, include_index: bool = True) -> dict:
    snapshot = export_project_snapshot(project_id, include_index)
    manifest = snapshot["manifest"]
    snapshot_id = snapshot["snapshot_id"]
    source_archive = Path(snapshot["archive_path"])
    archive_sha256 = _sha256_file(source_archive)
    metadata = {
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "source_project_id": manifest.get("project_id") or project_id,
        "created_at": manifest.get("created_at") or now_iso(),
        "format": manifest.get("format"),
        "size_bytes": source_archive.stat().st_size,
        "archive_sha256": archive_sha256,
        "manifest": manifest,
    }
    stored = configured_sync_provider().put_snapshot(project_id, snapshot_id, source_archive, metadata)
    write_audit(
        project_id,
        "project_snapshot_provider_synced",
        {
            "snapshot_id": snapshot_id,
            "archive_path": stored.get("archive_path"),
            "metadata_path": stored.get("metadata_path"),
            "object_key": stored.get("object_key"),
            "metadata_key": stored.get("metadata_key"),
        },
    )
    return {
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "archive_path": stored.get("archive_path"),
        "metadata_path": stored.get("metadata_path"),
        "object_key": stored.get("object_key"),
        "metadata_key": stored.get("metadata_key"),
        "manifest": manifest,
        "size_bytes": metadata["size_bytes"],
        "archive_sha256": archive_sha256,
    }


def list_synced_snapshots(target_dir: str, project_id: Optional[str] = None) -> list[dict]:
    snapshots_root = _sync_root(target_dir, create=False) / "snapshots"
    if not snapshots_root.exists():
        return []

    project_dirs = [snapshots_root / safe_project_id(project_id)] if project_id else sorted(path for path in snapshots_root.iterdir() if path.is_dir())
    snapshots: list[dict] = []
    for project_dir in project_dirs:
        if not project_dir.exists() or not project_dir.is_dir():
            continue
        for metadata_path in sorted(project_dir.glob("*.json")):
            metadata = _read_sync_metadata(metadata_path)
            archive_path = Path(str(metadata.get("archive_path") or metadata_path.with_suffix(".zip")))
            integrity_status = _snapshot_integrity_status(metadata, archive_path)
            item = {
                "snapshot_id": metadata.get("snapshot_id") or metadata_path.stem,
                "project_id": metadata.get("project_id") or project_dir.name,
                "source_project_id": metadata.get("source_project_id") or metadata.get("project_id") or project_dir.name,
                "created_at": metadata.get("created_at"),
                "format": metadata.get("format"),
                "archive_path": str(archive_path),
                "metadata_path": str(metadata_path),
                "size_bytes": archive_path.stat().st_size if archive_path.exists() else metadata.get("size_bytes"),
                "expected_size_bytes": metadata.get("size_bytes"),
                "actual_size_bytes": archive_path.stat().st_size if archive_path.exists() else None,
                "archive_sha256": metadata.get("archive_sha256"),
                "integrity_status": integrity_status,
                "available": archive_path.exists() and integrity_status in {"ok", "unchecked"},
                "manifest": metadata.get("manifest") or {},
            }
            snapshots.append(item)
    snapshots.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return snapshots


def list_provider_synced_snapshots(project_id: Optional[str] = None) -> list[dict]:
    return configured_sync_provider().list_snapshots(project_id)


def resolve_pull_project_snapshot_target(target_dir: str, snapshot_id: str, project_id: Optional[str] = None) -> str:
    snapshot = _find_synced_snapshot(target_dir, snapshot_id)
    return _sync_target_project_id(snapshot, project_id)


def resolve_provider_pull_project_snapshot_target(snapshot_id: str, project_id: Optional[str] = None) -> str:
    snapshot = _find_provider_synced_snapshot(snapshot_id)
    return _sync_target_project_id(snapshot, project_id)


def resolve_delete_synced_snapshot_project(target_dir: str, snapshot_id: str) -> str:
    snapshot = _find_synced_snapshot(target_dir, snapshot_id)
    return _sync_snapshot_project_id(snapshot)


def resolve_provider_delete_synced_snapshot_project(snapshot_id: str) -> str:
    snapshot = _find_provider_synced_snapshot(snapshot_id)
    return _sync_snapshot_project_id(snapshot)


def delete_synced_snapshot(target_dir: str, snapshot_id: str) -> dict:
    snapshot = _find_synced_snapshot(target_dir, snapshot_id)
    deleted_paths = []
    for key in ("archive_path", "metadata_path"):
        path = Path(snapshot[key])
        if path.exists():
            path.unlink()
            deleted_paths.append(str(path))
    result = {**snapshot, "deleted": True, "deleted_paths": deleted_paths}
    write_audit(
        str(snapshot.get("project_id") or snapshot.get("source_project_id") or "default"),
        "project_snapshot_sync_deleted",
        {
            "snapshot_id": snapshot_id,
            "target_dir": str(Path(target_dir).expanduser()),
            "archive_path": snapshot.get("archive_path"),
            "metadata_path": snapshot.get("metadata_path"),
            "deleted_paths": deleted_paths,
        },
    )
    return result


def delete_provider_synced_snapshot(snapshot_id: str) -> dict:
    provider = configured_sync_provider()
    deleted = provider.delete_snapshot(snapshot_id)
    write_audit(
        str(deleted.get("project_id") or deleted.get("source_project_id") or "default"),
        "project_snapshot_provider_deleted",
        {
            "snapshot_id": snapshot_id,
            "archive_path": deleted.get("archive_path"),
            "metadata_path": deleted.get("metadata_path"),
            "object_key": deleted.get("object_key"),
            "metadata_key": deleted.get("metadata_key"),
            "deleted_keys": deleted.get("deleted_keys") or [],
            "deleted_paths": deleted.get("deleted_paths") or [],
        },
    )
    return deleted


def pull_project_snapshot(
    target_dir: str,
    snapshot_id: str,
    project_id: Optional[str] = None,
    overwrite: bool = False,
) -> dict:
    snapshot = _find_synced_snapshot(target_dir, snapshot_id)
    archive_path = Path(snapshot["archive_path"])
    if not archive_path.exists() or not archive_path.is_file():
        raise FileNotFoundError("synced_snapshot_archive_not_found")
    _assert_snapshot_integrity(snapshot, archive_path)
    restored = import_project_snapshot(str(archive_path), project_id, overwrite)
    write_audit(
        restored["project_id"],
        "project_snapshot_pulled",
        {
            "snapshot_id": snapshot_id,
            "target_dir": str(Path(target_dir).expanduser()),
            "archive_path": str(archive_path),
            "source_project_id": snapshot.get("source_project_id"),
        },
    )
    return {**restored, "sync_snapshot": snapshot}


def pull_project_snapshot_from_configured_provider(
    snapshot_id: str,
    project_id: Optional[str] = None,
    overwrite: bool = False,
) -> dict:
    provider = configured_sync_provider()
    archive_path = provider.get_snapshot_archive(snapshot_id)
    snapshots = provider.list_snapshots()
    snapshot = next((item for item in snapshots if item["snapshot_id"] == snapshot_id), {})
    _assert_snapshot_integrity(snapshot, archive_path)
    restored = import_project_snapshot(str(archive_path), project_id, overwrite)
    write_audit(
        restored["project_id"],
        "project_snapshot_provider_pulled",
        {
            "snapshot_id": snapshot_id,
            "archive_path": snapshot.get("archive_path"),
            "source_project_id": snapshot.get("source_project_id"),
            "object_key": snapshot.get("object_key"),
        },
    )
    return {**restored, "sync_snapshot": snapshot}


def _sync_root(target_dir: str, create: bool = True) -> Path:
    if not target_dir or not str(target_dir).strip():
        raise ValueError("sync_target_dir_required")
    root = Path(target_dir).expanduser()
    if root.exists() and not root.is_dir():
        raise ValueError("sync_target_not_directory")
    sync_root = root / SYNC_ROOT_NAME
    if create:
        sync_root.mkdir(parents=True, exist_ok=True)
    return sync_root


def _read_sync_metadata(metadata_path: Path) -> dict:
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("sync_metadata_invalid") from exc


def _find_synced_snapshot(target_dir: str, snapshot_id: str) -> dict:
    if not snapshot_id or not snapshot_id.strip():
        raise ValueError("sync_snapshot_id_required")
    matches = [item for item in list_synced_snapshots(target_dir) if item["snapshot_id"] == snapshot_id]
    if not matches:
        raise FileNotFoundError("synced_snapshot_not_found")
    return matches[0]


def _find_provider_synced_snapshot(snapshot_id: str) -> dict:
    if not snapshot_id or not snapshot_id.strip():
        raise ValueError("sync_snapshot_id_required")
    matches = [item for item in list_provider_synced_snapshots() if item["snapshot_id"] == snapshot_id]
    if not matches:
        raise FileNotFoundError("synced_snapshot_not_found")
    return matches[0]


def _sync_target_project_id(snapshot: dict, project_id: Optional[str] = None) -> str:
    candidate = (
        project_id
        or snapshot.get("source_project_id")
        or snapshot.get("project_id")
        or (snapshot.get("manifest") or {}).get("project_id")
        or "default"
    )
    safe = str(candidate).replace("/", "_").replace("\\", "_").strip(". ")
    return safe or "default"


def _sync_snapshot_project_id(snapshot: dict) -> str:
    return str(snapshot.get("project_id") or snapshot.get("source_project_id") or "default")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_integrity_status(metadata: dict, archive_path: Path) -> str:
    if not archive_path.exists() or not archive_path.is_file():
        return "missing"
    expected_size = metadata.get("expected_size_bytes", metadata.get("size_bytes"))
    if expected_size is not None and archive_path.stat().st_size != int(expected_size):
        return "size_mismatch"
    expected_sha = str(metadata.get("archive_sha256") or "").strip()
    if not expected_sha:
        return "unchecked"
    return "ok" if _sha256_file(archive_path) == expected_sha else "checksum_mismatch"


def _assert_snapshot_integrity(snapshot: dict, archive_path: Path) -> None:
    status = _snapshot_integrity_status(snapshot, archive_path)
    if status == "missing":
        raise FileNotFoundError("synced_snapshot_archive_not_found")
    if status == "size_mismatch":
        raise ValueError("synced_snapshot_size_mismatch")
    if status == "checksum_mismatch":
        raise ValueError("synced_snapshot_checksum_mismatch")
