from __future__ import annotations

import hashlib
import mimetypes
import shutil
import uuid
from pathlib import Path

from loamtrace.db import connect
from loamtrace.services.audit import write_audit
from loamtrace.services.chunk_store import clear_existing_parse, insert_chunk
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.time import now_iso


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_document(project_id: str, file_path: str) -> dict:
    root = ensure_project(project_id)
    source = Path(file_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source file does not exist: {source}")
    if not source.is_file():
        raise ValueError(f"Source path is not a file: {source}")

    digest = sha256_file(source)
    mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    document_id = f"doc_{uuid.uuid4().hex}"
    target = root / "sources" / "original" / f"{document_id}_{source.name}"
    shutil.copy2(source, target)

    with connect(project_db_path(project_id)) as conn:
        existing = conn.execute(
            "select * from documents where project_id = ? and sha256 = ?",
            (project_id, digest),
        ).fetchone()
        if existing:
            return dict(existing)
        conn.execute(
            """
            insert into documents(
              id, project_id, sha256, filename, mime_type, source_path, created_at, status
            )
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                project_id,
                digest,
                source.name,
                mime_type,
                str(target),
                now_iso(),
                "imported",
            ),
        )
    return {
        "id": document_id,
        "project_id": project_id,
        "sha256": digest,
        "filename": source.name,
        "mime_type": mime_type,
        "source_path": str(target),
        "status": "imported",
    }


def list_documents(project_id: str) -> list[dict]:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select * from documents where project_id = ? order by created_at desc",
            (project_id,),
        ).fetchall()
        return [_with_parse_flags(conn, dict(row)) for row in rows]


def get_document(project_id: str, document_id: str) -> dict:
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute("select * from documents where id = ?", (document_id,)).fetchone()
        if not row:
            raise KeyError(f"Document not found: {document_id}")
        return _with_parse_flags(conn, dict(row))


def preview_delete_document(project_id: str, document_id: str) -> dict:
    root = ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        document = _get_document_for_project(conn, project_id, document_id)
        impact = _document_delete_impact(conn, document)

    return {
        "document_id": document_id,
        "project_id": project_id,
        "filename": document["filename"],
        "deleted": False,
        **impact,
        "file_impacts": _delete_file_impacts(root, document),
    }


def delete_document(project_id: str, document_id: str) -> dict:
    root = ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        document = _get_document_for_project(conn, project_id, document_id)
        impact = _document_delete_impact(conn, document)

        for claim_id in impact["removed_claim_ids"]:
            conn.execute("delete from citations where claim_id = ?", (claim_id,))
            conn.execute("delete from claims where id = ?", (claim_id,))
        for claim_id in impact["retained_claim_ids"]:
            conn.execute(
                "delete from citations where claim_id = ? and document_id = ?",
                (claim_id, document_id),
            )
            conn.execute(
                "update claims set status = ? where id = ?",
                ("needs_review", claim_id),
            )

        clear_existing_parse(conn, document_id)
        conn.execute("delete from documents where id = ?", (document_id,))

    removed_files = []
    for item in _delete_file_impacts(root, document):
        path = Path(item["path"])
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed_files.append(str(path))

    result = {
        "document_id": document_id,
        "project_id": project_id,
        "filename": document["filename"],
        "deleted": True,
        **impact,
        "removed_files": removed_files,
    }
    write_audit(project_id, "document_deleted", result)
    return result


def _get_document_for_project(conn, project_id: str, document_id: str) -> dict:
    row = conn.execute(
        "select * from documents where id = ? and project_id = ?",
        (document_id, project_id),
    ).fetchone()
    if not row:
        raise KeyError(f"Document not found: {document_id}")
    return dict(row)


def _document_delete_impact(conn, document: dict) -> dict:
    document_id = document["id"]
    citation_rows = conn.execute(
        """
        select *
        from citations
        where document_id = ?
        order by id asc
        """,
        (document_id,),
    ).fetchall()
    removed_citations = [dict(row) for row in citation_rows]
    affected_claim_ids = sorted({row["claim_id"] for row in citation_rows})
    removed_claim_ids = []
    retained_claim_ids = []

    for claim_id in affected_claim_ids:
        total_citations = conn.execute(
            "select count(*) from citations where claim_id = ?",
            (claim_id,),
        ).fetchone()[0]
        citations_for_deleted_doc = conn.execute(
            "select count(*) from citations where claim_id = ? and document_id = ?",
            (claim_id, document_id),
        ).fetchone()[0]
        if total_citations <= citations_for_deleted_doc:
            removed_claim_ids.append(claim_id)
        else:
            retained_claim_ids.append(claim_id)

    claim_rows = []
    if affected_claim_ids:
        placeholders = ",".join("?" for _ in affected_claim_ids)
        claim_rows = conn.execute(
            f"select * from claims where id in ({placeholders}) order by id asc",
            affected_claim_ids,
        ).fetchall()
    claims_by_id = {row["id"]: dict(row) for row in claim_rows}

    return {
        "removed_claim_ids": removed_claim_ids,
        "retained_claim_ids": retained_claim_ids,
        "removed_citation_ids": [citation["id"] for citation in removed_citations],
        "removed_claims": [_claim_delete_item(claims_by_id[claim_id]) for claim_id in removed_claim_ids if claim_id in claims_by_id],
        "retained_claims": [_claim_delete_item(claims_by_id[claim_id]) for claim_id in retained_claim_ids if claim_id in claims_by_id],
        "removed_citations": removed_citations,
    }


def _claim_delete_item(row: dict) -> dict:
    return {
        "id": row["id"],
        "text": row["claim_text"],
        "status": row["status"],
    }


def _delete_file_impacts(root: Path, document: dict) -> list[dict]:
    document_id = document["id"]
    paths = []
    if document.get("source_path"):
        paths.append(("source_file", Path(document["source_path"])))
    paths.append(("rendered_pages", root / "sources" / "rendered_pages" / document_id))
    return [
        {
            "kind": kind,
            "path": str(path),
            "exists": path.exists(),
            "is_dir": path.is_dir() if path.exists() else False,
        }
        for kind, path in paths
    ]


def apply_manual_text(project_id: str, document_id: str, text: str, heading: str = "Manual correction") -> dict:
    normalized = _normalize_manual_text(text)
    if not normalized:
        raise ValueError("manual_text_empty")

    ensure_project(project_id)
    now = now_iso()
    block_id = f"manual_{uuid.uuid4().hex}"
    chunk_id = f"chunk_{uuid.uuid4().hex}"
    source_uri = f"text://{document_id}#block={block_id}"
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute(
            "select * from documents where id = ? and project_id = ?",
            (document_id, project_id),
        ).fetchone()
        if not row:
            raise KeyError(f"Document not found: {document_id}")
        clear_existing_parse(conn, document_id)
        conn.execute(
            """
            insert into blocks(id, document_id, block_type, text, reading_order, heading_path)
            values (?, ?, ?, ?, ?, ?)
            """,
            (block_id, document_id, "manual_text", normalized, 0, heading),
        )
        insert_chunk(
            conn,
            {
                "id": chunk_id,
                "document_id": document_id,
                "chunk_type": "manual_text",
                "text": normalized,
                "token_count": len(normalized.split()),
                "heading_path": heading,
                "word_ids_json": "[]",
                "cell_ids_json": None,
                "bbox_json": None,
                "source_uri": source_uri,
            },
        )
        conn.execute(
            """
            update documents
            set parsed_at = ?,
                parser_version = ?,
                ocr_used = 0,
                ocr_confidence = null,
                status = ?
            where id = ? and project_id = ?
            """,
            (now, "manual-text-v1", "parsed", document_id, project_id),
        )

    result = {
        "document_id": document_id,
        "status": "parsed",
        "parser_version": "manual-text-v1",
        "chunks": 1,
        "chunk_id": chunk_id,
        "source_uri": source_uri,
        "manual_text_length": len(normalized),
    }
    write_audit(project_id, "manual_text_applied", result)
    return {**get_document(project_id, document_id), **result}


def _with_parse_flags(conn, document: dict) -> dict:
    is_pdf = document.get("mime_type") == "application/pdf" or document.get("filename", "").lower().endswith(".pdf")
    document["ocr_required"] = False
    if not is_pdf or document.get("status") != "failed":
        return document

    row = conn.execute(
        """
        select
          count(*) as page_count,
          sum(case when text_layer_available = 0 then 1 else 0 end) as missing_text_pages
        from pages
        where document_id = ?
        """,
        (document["id"],),
    ).fetchone()
    page_count = row["page_count"] if row else 0
    missing_text_pages = row["missing_text_pages"] or 0 if row else 0
    document["ocr_required"] = page_count > 0 and missing_text_pages == page_count
    return document


def _normalize_manual_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()
