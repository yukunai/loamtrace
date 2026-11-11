from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

import loamtrace.config
from loamtrace.services.audit import write_audit
from loamtrace.services.documents import get_document, import_document
from loamtrace.services.time import now_iso


def add_document_asset(project_id: str, document_id: str, tags: Optional[list[str]] = None) -> dict:
    document = get_document(project_id, document_id)
    source_path = Path(document["source_path"])
    if not source_path.exists():
        raise FileNotFoundError(f"Document source missing: {source_path}")

    root = _asset_root()
    catalog = _load_catalog()
    normalized_tags = _normalize_tags(tags or [])
    existing = _find_by_sha(catalog, document["sha256"])
    now = now_iso()
    if existing:
        existing["tags"] = sorted(set(existing.get("tags", [])) | set(normalized_tags))
        existing["updated_at"] = now
        _append_source_ref(existing, project_id, document_id)
        asset = existing
        reused = True
    else:
        asset_id = f"asset_{uuid.uuid4().hex}"
        target = root / "original" / f"{asset_id}_{document['filename']}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        asset = {
            "id": asset_id,
            "sha256": document["sha256"],
            "filename": document["filename"],
            "mime_type": document["mime_type"],
            "storage_path": str(target),
            "tags": normalized_tags,
            "source_refs": [{"project_id": project_id, "document_id": document_id}],
            "created_at": now,
            "updated_at": now,
        }
        catalog.append(asset)
        reused = False

    _save_catalog(catalog)
    write_audit(
        project_id,
        "asset_registered",
        {"asset_id": asset["id"], "document_id": document_id, "reused": reused, "tags": asset["tags"]},
    )
    return dict(asset)


def list_assets(query: Optional[str] = None, tag: Optional[str] = None) -> list[dict]:
    catalog = _load_catalog()
    query_text = (query or "").strip().lower()
    tag_text = _normalize_tag(tag) if tag else None
    assets = []
    for asset in catalog:
        if query_text and query_text not in asset["filename"].lower() and not any(query_text in item for item in asset.get("tags", [])):
            continue
        if tag_text and tag_text not in asset.get("tags", []):
            continue
        assets.append(dict(asset))
    return sorted(assets, key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)


def import_asset_to_project(project_id: str, asset_id: str) -> dict:
    asset = get_asset(asset_id)
    imported = import_document(project_id, asset["storage_path"])
    write_audit(
        project_id,
        "asset_imported",
        {"asset_id": asset_id, "document_id": imported["id"], "filename": asset["filename"]},
    )
    return {"asset": asset, "document": imported}


def delete_asset(asset_id: str) -> dict:
    catalog = _load_catalog()
    remaining = []
    deleted: Optional[dict] = None
    for asset in catalog:
        if asset.get("id") == asset_id:
            deleted = asset
        else:
            remaining.append(asset)
    if deleted is None:
        raise KeyError("asset_not_found")

    storage_path = Path(deleted.get("storage_path") or "")
    file_deleted = False
    if storage_path.exists() and storage_path.is_file():
        storage_path.unlink()
        file_deleted = True
    _save_catalog(remaining)

    for ref in deleted.get("source_refs", []):
        project_id = ref.get("project_id")
        if project_id:
            write_audit(
                project_id,
                "asset_deleted",
                {"asset_id": asset_id, "filename": deleted.get("filename"), "file_deleted": file_deleted},
            )
    return {"asset_id": asset_id, "deleted": True, "file_deleted": file_deleted}


def update_asset_tags(asset_id: str, tags: list[str]) -> dict:
    catalog = _load_catalog()
    normalized_tags = _normalize_tags(tags)
    now = now_iso()
    updated: Optional[dict] = None
    for asset in catalog:
        if asset.get("id") == asset_id:
            asset["tags"] = normalized_tags
            asset["updated_at"] = now
            updated = asset
            break
    if updated is None:
        raise KeyError("asset_not_found")

    _save_catalog(catalog)
    for ref in updated.get("source_refs", []):
        project_id = ref.get("project_id")
        if project_id:
            write_audit(
                project_id,
                "asset_tags_updated",
                {"asset_id": asset_id, "filename": updated.get("filename"), "tags": normalized_tags},
            )
    return dict(updated)


def get_asset(asset_id: str) -> dict:
    for asset in _load_catalog():
        if asset["id"] == asset_id:
            return dict(asset)
    raise KeyError("asset_not_found")


def _asset_root() -> Path:
    root = loamtrace.config.WORKSPACE_ROOT / "assets" / "library"
    root.mkdir(parents=True, exist_ok=True)
    (root / "original").mkdir(parents=True, exist_ok=True)
    return root


def _catalog_path() -> Path:
    return _asset_root() / "assets.json"


def _load_catalog() -> list[dict]:
    path = _catalog_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("id")]


def _save_catalog(catalog: list[dict]) -> None:
    path = _catalog_path()
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_by_sha(catalog: list[dict], sha256: str) -> Optional[dict]:
    for asset in catalog:
        if asset.get("sha256") == sha256:
            return asset
    return None


def _append_source_ref(asset: dict, project_id: str, document_id: str) -> None:
    refs = asset.setdefault("source_refs", [])
    ref = {"project_id": project_id, "document_id": document_id}
    if ref not in refs:
        refs.append(ref)


def _normalize_tags(tags: list[str]) -> list[str]:
    return sorted({tag for tag in (_normalize_tag(item) for item in tags) if tag})


def _normalize_tag(tag: Optional[str]) -> str:
    return (tag or "").strip().lower().replace(" ", "-")
