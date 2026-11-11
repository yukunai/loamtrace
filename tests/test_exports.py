import json
import zipfile
from pathlib import Path

import pytest

from loamtrace import config
from loamtrace.db import connect
from loamtrace.models import CitationInput, ClaimInput
from loamtrace.services.documents import import_document
from loamtrace.services.exports import export_project_snapshot, export_research_package, import_project_snapshot, list_export_artifacts
from loamtrace.services.paths import ensure_project, project_db_path, project_root
from loamtrace.services.slides import export_pptx, generate_slide_deck
from loamtrace.services.verifier import review_citation, verify_claims


@pytest.fixture
def export_project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "exports"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk_good",
                "doc_1",
                "text",
                "Revenue increased by 24% year over year in 2025.",
                "pdf://doc_1#page=1",
                "[]",
            ),
        )
    return project_id


def test_export_research_package_writes_markdown_json_and_manifest(export_project):
    verified = verify_claims(
        export_project,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_good",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]
    deck_result = generate_slide_deck(export_project, "Diligence Deck", [verified["id"]])

    result = export_research_package(export_project, deck_result["deck_id"])
    export_dir = Path(result["path"])
    archive_path = Path(result["archive_path"])
    run_dir = Path(result["run_dir"])

    assert export_dir.exists()
    assert archive_path.exists()
    assert run_dir.exists()
    assert (export_dir / "memo.md").read_text(encoding="utf-8").startswith("# Verified Memo")
    assert json.loads((export_dir / "claims.json").read_text(encoding="utf-8"))[0]["id"] == verified["id"]
    assert json.loads((export_dir / "citations.json").read_text(encoding="utf-8"))[0]["source_uri"] == "pdf://doc_1#page=1"
    targets = json.loads((export_dir / "citation_targets.json").read_text(encoding="utf-8"))
    assert targets[0]["citation_id"] == verified["citations"][0]["id"]
    assert targets[0]["scheme"] == "pdf"
    assert targets[0]["precision"] == "page"
    workflow = json.loads((export_dir / "workflow_status.json").read_text(encoding="utf-8"))
    assert workflow["project_id"] == export_project
    assert workflow["counts"]["citations"] == 1
    assert json.loads((export_dir / "deck.slide.json").read_text(encoding="utf-8"))["deck_id"] == deck_result["deck_id"]
    assert json.loads((export_dir / "source_files.json").read_text(encoding="utf-8")) == []

    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["package_id"] == result["package_id"]
    assert manifest["counts"]["verified_claims"] == 1
    assert manifest["counts"]["citation_targets"] == 1
    assert manifest["counts"]["source_files"] == 0
    assert "memo.md" in manifest["files"]
    assert "claims.json" in manifest["files"]
    assert "citation_targets.json" in manifest["files"]
    assert "workflow_status.json" in manifest["files"]
    assert "source_files.json" in manifest["files"]
    assert "deck.slide.json" in manifest["files"]
    assert json.loads((run_dir / "input.json").read_text(encoding="utf-8"))["deck_id"] == deck_result["deck_id"]
    assert json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["package_id"] == result["package_id"]
    assert json.loads((run_dir / "workflow_status.json").read_text(encoding="utf-8"))["project_id"] == export_project
    run_output = json.loads((run_dir / "output.json").read_text(encoding="utf-8"))
    assert run_output["path"] == result["path"]
    assert run_output["archive_path"] == result["archive_path"]
    assert "research_package_exported" in (run_dir / "logs.jsonl").read_text(encoding="utf-8")

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert {
            "memo.md",
            "claims.json",
            "citations.json",
            "citation_targets.json",
            "documents.json",
            "source_files.json",
            "workflow_status.json",
            "deck.slide.json",
            "manifest.json",
        }.issubset(names)
        archived_manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    assert archived_manifest["package_id"] == result["package_id"]

    with connect(project_db_path(export_project)) as conn:
        row = conn.execute(
            "select * from audit_log where type = ?",
            ("research_package_exported",),
        ).fetchone()
    assert row is not None


def test_export_research_package_copies_imported_source_files(export_project, tmp_path):
    source = tmp_path / "source-note.txt"
    source.write_text("Original source file for the export package.", encoding="utf-8")
    imported = import_document(export_project, str(source))

    result = export_research_package(export_project)
    export_dir = Path(result["path"])

    source_files = json.loads((export_dir / "source_files.json").read_text(encoding="utf-8"))
    assert source_files == [
        {
            "document_id": imported["id"],
            "filename": "source-note.txt",
            "sha256": imported["sha256"],
            "source_path": imported["source_path"],
            "relative_path": f"sources/original/{imported['id']}_source-note.txt",
            "copied": True,
            "error": None,
        }
    ]
    copied = export_dir / source_files[0]["relative_path"]
    assert copied.read_text(encoding="utf-8") == "Original source file for the export package."
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["source_files"] == 1
    assert source_files[0]["relative_path"] in manifest["files"]

    with zipfile.ZipFile(Path(result["archive_path"])) as archive:
        assert source_files[0]["relative_path"] in archive.namelist()
        assert archive.read(source_files[0]["relative_path"]).decode("utf-8") == "Original source file for the export package."


def test_export_project_snapshot_writes_private_sync_zip(export_project, tmp_path):
    source = tmp_path / "snapshot-source.txt"
    source.write_text("Snapshot source file.", encoding="utf-8")
    imported = import_document(export_project, str(source))
    notes_dir = project_root(export_project) / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "memo.md").write_text("# Memo\n", encoding="utf-8")

    result = export_project_snapshot(export_project)
    snapshot_dir = Path(result["path"])
    archive_path = Path(result["archive_path"])
    manifest = result["manifest"]

    assert snapshot_dir.exists()
    assert archive_path.exists()
    assert manifest["format"] == "loamtrace-project-snapshot-v1"
    assert manifest["include_index"] is True
    assert "project.json" in manifest["files"]
    assert "notes/memo.md" in manifest["files"]
    assert f"sources/original/{imported['id']}_snapshot-source.txt" in manifest["files"]
    assert "index/project.sqlite" in manifest["files"]
    assert json.loads((snapshot_dir / "snapshot_manifest.json").read_text(encoding="utf-8"))["snapshot_id"] == result["snapshot_id"]

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "snapshot_manifest.json" in names
        assert "project.json" in names
        assert "notes/memo.md" in names
        assert "index/project.sqlite" in names
        assert f"sources/original/{imported['id']}_snapshot-source.txt" in names

    artifacts = list_export_artifacts(export_project)
    assert any(item["type"] == "project_snapshot_zip" and item["package_id"] == result["snapshot_id"] for item in artifacts)

    with connect(project_db_path(export_project)) as conn:
        row = conn.execute(
            "select * from audit_log where type = ?",
            ("project_snapshot_exported",),
        ).fetchone()
    assert row is not None


def test_import_project_snapshot_restores_project_files(export_project, tmp_path):
    source = tmp_path / "restore-source.txt"
    source.write_text("Restorable source file.", encoding="utf-8")
    imported = import_document(export_project, str(source))
    notes_dir = project_root(export_project) / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "memo.md").write_text("# Restored Memo\n", encoding="utf-8")
    snapshot = export_project_snapshot(export_project)

    restored = import_project_snapshot(snapshot["archive_path"], "restored_exports")
    restored_root = project_root("restored_exports")

    assert restored["project_id"] == "restored_exports"
    assert restored["source_project_id"] == export_project
    assert restored["snapshot_id"] == snapshot["snapshot_id"]
    assert (restored_root / "project.json").exists()
    assert (restored_root / "notes" / "memo.md").read_text(encoding="utf-8") == "# Restored Memo\n"
    assert (restored_root / "sources" / "original" / f"{imported['id']}_restore-source.txt").read_text(encoding="utf-8") == "Restorable source file."
    assert (restored_root / "index" / "project.sqlite").exists()
    assert (restored_root / "snapshot_manifest.json").exists()
    with connect(project_db_path("restored_exports")) as conn:
        row = conn.execute(
            "select * from audit_log where type = ?",
            ("project_snapshot_imported",),
        ).fetchone()
    assert row is not None


def test_import_project_snapshot_rejects_unsafe_paths(export_project, tmp_path):
    archive_path = tmp_path / "unsafe_snapshot.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "snapshot_manifest.json",
            json.dumps(
                {
                    "snapshot_id": "snapshot_unsafe",
                    "project_id": "unsafe",
                    "format": "loamtrace-project-snapshot-v1",
                    "files": ["../escape.txt"],
                }
            ),
        )
        archive.writestr("../escape.txt", "escape")

    with pytest.raises(ValueError, match="snapshot_path_unsafe"):
        import_project_snapshot(str(archive_path), "unsafe_restore")


def test_list_export_artifacts_includes_pptx_package_directory_and_zip(export_project):
    verified = verify_claims(
        export_project,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_good",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]
    deck_result = generate_slide_deck(export_project, "Diligence Deck", [verified["id"]])
    pptx = export_pptx(export_project, deck_result["deck_id"])
    package = export_research_package(export_project, deck_result["deck_id"])

    artifacts = list_export_artifacts(export_project)
    by_type = {artifact["type"]: artifact for artifact in artifacts}

    assert by_type["pptx"]["path"] == pptx["path"]
    assert by_type["pptx"]["deck_id"] == deck_result["deck_id"]
    assert by_type["research_package"]["path"] == package["path"]
    assert by_type["research_package"]["package_id"] == package["package_id"]
    assert by_type["research_package"]["open_kind"] == "directory"
    assert by_type["research_package_zip"]["path"] == package["archive_path"]
    assert by_type["research_package_zip"]["package_id"] == package["package_id"]
    assert by_type["research_package_zip"]["size_bytes"] > 0


def test_list_export_artifacts_tolerates_missing_manifest(export_project):
    exports_dir = project_root(export_project) / "exports"
    orphan_dir = exports_dir / "export_orphan"
    orphan_dir.mkdir(parents=True)
    orphan_zip = exports_dir / "export_orphan.zip"
    orphan_zip.write_bytes(b"not a real zip but still an artifact")

    artifacts = list_export_artifacts(export_project)
    by_path = {artifact["path"]: artifact for artifact in artifacts}

    assert by_path[str(orphan_dir)]["package_id"] == "export_orphan"
    assert by_path[str(orphan_zip)]["package_id"] == "export_orphan"


def test_export_research_package_records_missing_source_files(export_project, tmp_path):
    source = tmp_path / "missing-source.txt"
    source.write_text("This source will be removed before export.", encoding="utf-8")
    imported = import_document(export_project, str(source))
    Path(imported["source_path"]).unlink()

    result = export_research_package(export_project)
    export_dir = Path(result["path"])

    source_files = json.loads((export_dir / "source_files.json").read_text(encoding="utf-8"))
    assert source_files == [
        {
            "document_id": imported["id"],
            "filename": "missing-source.txt",
            "sha256": imported["sha256"],
            "source_path": imported["source_path"],
            "relative_path": None,
            "copied": False,
            "error": "source_file_missing",
        }
    ]
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["source_files"] == 0
    assert "sources/original" not in "\n".join(manifest["files"])


def test_export_research_package_rechecks_deck_claim_status(export_project):
    verified = verify_claims(
        export_project,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_good",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]
    deck_result = generate_slide_deck(export_project, "Stale Deck", [verified["id"]])

    review_citation(export_project, verified["citations"][0]["id"], "reject")

    with pytest.raises(ValueError, match="blocked_claims_in_deck"):
        export_research_package(export_project, deck_result["deck_id"])


def test_export_research_package_records_citation_target_errors(export_project):
    with connect(project_db_path(export_project)) as conn:
        conn.execute(
            """
            insert into claims(id, project_id, run_id, claim_text, status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "claim_bad_target",
                export_project,
                "run_1",
                "Bad target citation",
                "verified",
                "2026-06-09T00:00:00Z",
            ),
        )
        conn.execute(
            """
            insert into citations(id, claim_id, chunk_id, document_id, quote, source_uri, verified)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "citation_bad_target",
                "claim_bad_target",
                "chunk_missing",
                "doc_missing",
                "Bad target citation",
                "not-a-source-uri",
                1,
            ),
        )

    result = export_research_package(export_project)
    targets = json.loads((Path(result["path"]) / "citation_targets.json").read_text(encoding="utf-8"))

    assert targets[0]["citation_id"] == "citation_bad_target"
    assert targets[0]["error"] == "source_uri_invalid"
