from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loamtrace.services.audit import write_audit, write_run_artifacts
from loamtrace.services.documents import list_documents
from loamtrace.services.paths import ensure_project, project_root
from loamtrace.services.slides import assert_deck_claims_allowed, load_slide_deck
from loamtrace.services.source_targets import resolve_citation_target
from loamtrace.services.time import now_iso
from loamtrace.services.verifier import list_claims, render_memo
from loamtrace.services.workflow import workflow_status


def list_export_artifacts(project_id: str) -> list[dict]:
    root = ensure_project(project_id)
    artifacts = []
    slides_dir = root / "slides"
    exports_dir = root / "exports"

    for pptx_path in sorted(slides_dir.glob("*.pptx")):
        artifacts.append(_artifact(pptx_path, "pptx", "PPTX", deck_id=pptx_path.stem))

    for export_dir in sorted(path for path in exports_dir.iterdir() if path.is_dir()):
        if export_dir.name.startswith("snapshot_"):
            continue
        manifest = _read_manifest(export_dir / "manifest.json")
        artifacts.append(
            _artifact(
                export_dir,
                "research_package",
                "研究包目录",
                package_id=manifest.get("package_id") or export_dir.name,
                deck_id=manifest.get("deck_id"),
                created_at=manifest.get("created_at"),
            )
        )

    for archive_path in sorted(exports_dir.glob("*.zip")):
        manifest = _read_manifest(exports_dir / archive_path.stem / "manifest.json")
        if archive_path.name.startswith("snapshot_"):
            manifest = _read_manifest(exports_dir / archive_path.stem / "snapshot_manifest.json")
            artifacts.append(
                _artifact(
                    archive_path,
                    "project_snapshot_zip",
                    "项目快照 ZIP",
                    package_id=manifest.get("snapshot_id") or archive_path.stem,
                    created_at=manifest.get("created_at"),
                )
            )
            continue
        artifacts.append(
            _artifact(
                archive_path,
                "research_package_zip",
                "研究包 ZIP",
                package_id=manifest.get("package_id") or archive_path.stem,
                deck_id=manifest.get("deck_id"),
                created_at=manifest.get("created_at"),
            )
        )

    artifacts.sort(key=lambda item: item["modified_at"], reverse=True)
    return artifacts


def export_project_snapshot(project_id: str, include_index: bool = True) -> dict:
    root = ensure_project(project_id)
    snapshot_id = f"snapshot_{uuid.uuid4().hex}"
    run_id = f"run_{uuid.uuid4().hex}"
    snapshot_dir = root / "exports" / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    copied_files = _copy_snapshot_files(root, snapshot_dir, include_index)
    manifest = {
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "created_at": now_iso(),
        "format": "loamtrace-project-snapshot-v1",
        "include_index": include_index,
        "source_root": str(root),
        "counts": {
            "files": len(copied_files),
            "bytes": sum(item["size_bytes"] for item in copied_files),
        },
        "files": [item["relative_path"] for item in copied_files],
    }
    _write_export_file(snapshot_dir / "snapshot_manifest.json", manifest)
    archive_path = _write_zip_archive(snapshot_dir, snapshot_id)
    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "export_project_snapshot",
        {
            "input.json": {"project_id": project_id, "include_index": include_index},
            "snapshot_manifest.json": manifest,
            "output.json": {"snapshot_id": snapshot_id, "path": str(snapshot_dir), "archive_path": str(archive_path)},
        },
        logs=[
            {
                "type": "project_snapshot_exported",
                "snapshot_id": snapshot_id,
                "file_count": len(copied_files),
                "path": str(snapshot_dir),
                "archive_path": str(archive_path),
            }
        ],
    )
    write_audit(
        project_id,
        "project_snapshot_exported",
        {
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "file_count": len(copied_files),
            "path": str(snapshot_dir),
            "archive_path": str(archive_path),
            "run_dir": str(run_dir),
        },
    )
    return {
        "snapshot_id": snapshot_id,
        "path": str(snapshot_dir),
        "archive_path": str(archive_path),
        "manifest": manifest,
        "run_id": run_id,
        "run_dir": str(run_dir),
    }


def import_project_snapshot(archive_path: str, project_id: Optional[str] = None, overwrite: bool = False) -> dict:
    archive = Path(archive_path).expanduser()
    if not archive.exists() or not archive.is_file():
        raise FileNotFoundError("snapshot_archive_not_found")
    if not zipfile.is_zipfile(archive):
        raise ValueError("snapshot_archive_invalid")

    with zipfile.ZipFile(archive) as zip_archive:
        manifest = _read_snapshot_manifest(zip_archive)
        source_project_id = str(manifest.get("project_id") or "").strip()
        target_project_id = _snapshot_target_project_id(project_id, source_project_id)
        root = project_root(target_project_id)
        if root.exists() and any(root.iterdir()) and not overwrite:
            raise FileExistsError("project_already_exists")
        _extract_snapshot(zip_archive, manifest, root, overwrite)

    ensure_project(target_project_id, _snapshot_project_name(root, target_project_id))
    restored_files = manifest.get("files") or []
    write_audit(
        target_project_id,
        "project_snapshot_imported",
        {
            "archive_path": str(archive),
            "source_project_id": source_project_id,
            "file_count": len(restored_files),
            "snapshot_id": manifest.get("snapshot_id"),
        },
    )
    metadata = _read_manifest(root / "project.json")
    return {
        "project_id": target_project_id,
        "root": str(root),
        "source_project_id": source_project_id,
        "snapshot_id": manifest.get("snapshot_id"),
        "manifest": manifest,
        "file_count": len(restored_files),
        "name": metadata.get("name") or target_project_id,
    }


def resolve_import_project_snapshot_target(archive_path: str, project_id: Optional[str] = None) -> str:
    archive = Path(archive_path).expanduser()
    if not archive.exists() or not archive.is_file():
        raise FileNotFoundError("snapshot_archive_not_found")
    if not zipfile.is_zipfile(archive):
        raise ValueError("snapshot_archive_invalid")

    with zipfile.ZipFile(archive) as zip_archive:
        manifest = _read_snapshot_manifest(zip_archive)
    source_project_id = str(manifest.get("project_id") or "").strip()
    return _snapshot_target_project_id(project_id, source_project_id)


def export_research_package(project_id: str, deck_id: Optional[str] = None) -> dict:
    ensure_project(project_id)
    package_id = f"export_{uuid.uuid4().hex}"
    run_id = f"run_{uuid.uuid4().hex}"
    export_dir = project_root(project_id) / "exports" / package_id
    export_dir.mkdir(parents=True, exist_ok=True)

    memo = render_memo(project_id)
    claims = list_claims(project_id)
    citations = [
        {**citation, "claim_text": claim["text"], "claim_status": claim["status"]}
        for claim in claims
        for citation in claim["citations"]
    ]
    citation_targets = [_citation_target_for_export(project_id, citation) for citation in citations]
    documents = list_documents(project_id)
    deck = load_slide_deck(project_id, deck_id) if deck_id else None
    if deck:
        assert_deck_claims_allowed(project_id, deck)
    workflow = workflow_status(project_id)
    source_files = _copy_source_files(export_dir, documents)

    files = {
        "memo.md": memo["markdown"],
        "claims.json": claims,
        "citations.json": citations,
        "citation_targets.json": citation_targets,
        "documents.json": documents,
        "source_files.json": source_files,
        "workflow_status.json": workflow,
    }
    if deck:
        files["deck.slide.json"] = deck

    manifest = {
        "package_id": package_id,
        "project_id": project_id,
        "created_at": now_iso(),
        "memo_path": memo["path"],
        "deck_id": deck_id,
        "counts": {
            "documents": len(documents),
            "source_files": len([item for item in source_files if item.get("copied")]),
            "claims": len(claims),
            "verified_claims": len([c for c in claims if c["status"] in {"verified", "approved"}]),
            "citations": len(citations),
            "citation_targets": len(citation_targets),
            "slides": len(deck["slides"]) if deck else 0,
        },
        "files": sorted([*files.keys(), "manifest.json", *[item["relative_path"] for item in source_files if item.get("relative_path")]]),
    }

    for filename, value in files.items():
        _write_export_file(export_dir / filename, value)
    _write_export_file(export_dir / "manifest.json", manifest)
    archive_path = _write_zip_archive(export_dir, package_id)
    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "export_research_package",
        {
            "input.json": {"project_id": project_id, "deck_id": deck_id},
            "manifest.json": manifest,
            "workflow_status.json": workflow,
            "output.json": {"package_id": package_id, "path": str(export_dir), "archive_path": str(archive_path)},
        },
        logs=[
            {
                "type": "research_package_exported",
                "package_id": package_id,
                "deck_id": deck_id,
                "path": str(export_dir),
                "archive_path": str(archive_path),
            }
        ],
    )

    write_audit(
        project_id,
        "research_package_exported",
        {
            "run_id": run_id,
            "package_id": package_id,
            "deck_id": deck_id,
            "path": str(export_dir),
            "archive_path": str(archive_path),
            "run_dir": str(run_dir),
        },
    )
    return {
        "package_id": package_id,
        "path": str(export_dir),
        "archive_path": str(archive_path),
        "manifest": manifest,
        "run_id": run_id,
        "run_dir": str(run_dir),
    }


def _citation_target_for_export(project_id: str, citation: dict) -> dict:
    try:
        return resolve_citation_target(project_id, citation["id"])
    except (KeyError, ValueError) as exc:
        return {
            "citation_id": citation.get("id"),
            "claim_id": citation.get("claim_id"),
            "source_uri": citation.get("source_uri"),
            "quote": citation.get("quote"),
            "error": str(exc),
        }


def _copy_source_files(export_dir: Path, documents: list[dict]) -> list[dict]:
    source_dir = export_dir / "sources" / "original"
    source_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for document in documents:
        source_path = Path(str(document.get("source_path") or ""))
        filename = document.get("filename") or source_path.name or f"{document.get('id', 'document')}.bin"
        target_name = f"{document.get('id', 'doc')}_{Path(filename).name}"
        target = source_dir / target_name
        item = {
            "document_id": document.get("id"),
            "filename": filename,
            "sha256": document.get("sha256"),
            "source_path": str(source_path) if str(source_path) else None,
            "relative_path": str(target.relative_to(export_dir)),
            "copied": False,
            "error": None,
        }
        try:
            if not source_path.exists() or not source_path.is_file():
                raise FileNotFoundError("source_file_missing")
            shutil.copy2(source_path, target)
            item["copied"] = True
        except OSError as exc:
            item["relative_path"] = None
            item["error"] = str(exc)
        results.append(item)
    return results


def _copy_snapshot_files(project_root_path: Path, snapshot_dir: Path, include_index: bool) -> list[dict]:
    selected_roots = ["project.json", "sources/original", "notes", "slides", "runs"]
    if include_index:
        selected_roots.append("index/project.sqlite")
    copied = []
    for relative in selected_roots:
        source = project_root_path / relative
        if not source.exists():
            continue
        if source.is_dir():
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    copied.append(_copy_snapshot_file(project_root_path, snapshot_dir, path))
        elif source.is_file():
            copied.append(_copy_snapshot_file(project_root_path, snapshot_dir, source))
    return copied


def _copy_snapshot_file(project_root_path: Path, snapshot_dir: Path, source: Path) -> dict:
    relative = source.relative_to(project_root_path)
    target = snapshot_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {"relative_path": str(relative), "size_bytes": target.stat().st_size}


def _read_snapshot_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        manifest = json.loads(archive.read("snapshot_manifest.json").decode("utf-8"))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("snapshot_manifest_invalid") from exc
    if manifest.get("format") != "loamtrace-project-snapshot-v1":
        raise ValueError("snapshot_format_unsupported")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("snapshot_manifest_invalid")
    for relative in files:
        _safe_snapshot_relative_path(str(relative))
    return manifest


def _snapshot_target_project_id(project_id: Optional[str], source_project_id: str) -> str:
    candidate = (project_id or source_project_id or f"restored_{uuid.uuid4().hex[:8]}").strip()
    safe = candidate.replace("/", "_").replace("\\", "_").strip(". ")
    return safe or f"restored_{uuid.uuid4().hex[:8]}"


def _snapshot_project_name(root: Path, project_id: str) -> str:
    metadata = _read_manifest(root / "project.json")
    return metadata.get("name") or project_id


def _extract_snapshot(archive: zipfile.ZipFile, manifest: dict, root: Path, overwrite: bool) -> None:
    if root.exists() and overwrite:
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for member in ["snapshot_manifest.json", *(str(item) for item in manifest.get("files", []))]:
        relative = _safe_snapshot_relative_path(member)
        try:
            info = archive.getinfo(member)
        except KeyError:
            if member == "snapshot_manifest.json":
                raise ValueError("snapshot_manifest_invalid")
            raise ValueError(f"snapshot_file_missing:{member}")
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def _safe_snapshot_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("snapshot_path_unsafe")
    return path


def _write_export_file(path: Path, value: object) -> None:
    if path.suffix == ".md":
        path.write_text(str(value), encoding="utf-8")
        return
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_zip_archive(export_dir: Path, package_id: str) -> Path:
    archive_path = export_dir.parent / f"{package_id}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(export_dir.rglob("*")):
            if path.is_file():
                archive.write(path, str(path.relative_to(export_dir)))
    return archive_path


def _artifact(
    path: Path,
    artifact_type: str,
    label: str,
    package_id: Optional[str] = None,
    deck_id: Optional[str] = None,
    created_at: Optional[str] = None,
) -> dict:
    stat = path.stat()
    modified_at = _timestamp(stat.st_mtime)
    return {
        "id": f"{artifact_type}:{path.name}",
        "type": artifact_type,
        "label": label,
        "name": path.name,
        "path": str(path),
        "package_id": package_id,
        "deck_id": deck_id,
        "created_at": created_at or modified_at,
        "modified_at": modified_at,
        "size_bytes": stat.st_size if path.is_file() else None,
        "open_kind": "file" if path.is_file() else "directory",
    }


def _read_manifest(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
