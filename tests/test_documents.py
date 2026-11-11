import pytest
import tempfile
from pathlib import Path
from loamtrace.db import connect
from loamtrace.services import documents, paths
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

def test_import_document(tmp_workspace):
    # Create a dummy file to import
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
        tf.write(b"Hello world")
        tf_path = tf.name
    
    project_id = "p1"
    doc = documents.import_document(project_id, tf_path)
    
    assert doc["filename"] == Path(tf_path).name
    assert doc["status"] == "imported"
    
    docs = documents.list_documents(project_id)
    assert len(docs) == 1
    assert docs[0]["id"] == doc["id"]

def test_import_same_document_twice(tmp_workspace):
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
        tf.write(b"Same content")
        tf_path = tf.name
    
    project_id = "p1"
    doc1 = documents.import_document(project_id, tf_path)
    doc2 = documents.import_document(project_id, tf_path)
    
    assert doc1["id"] == doc2["id"]
    assert len(documents.list_documents(project_id)) == 1


def test_delete_document_removes_source_index_and_dependent_claims(tmp_workspace):
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
        tf.write(b"Delete me")
        tf_path = tf.name

    project_id = "p1"
    doc = documents.import_document(project_id, tf_path)
    source_path = Path(doc["source_path"])
    render_dir = paths.project_root(project_id) / "sources" / "rendered_pages" / doc["id"]
    render_dir.mkdir(parents=True)
    (render_dir / "page_1.png").write_bytes(b"png")

    db_path = paths.project_db_path(project_id)
    with connect(db_path) as conn:
        conn.execute(
            "insert into pages(id, document_id, page_number) values (?, ?, ?)",
            ("page_1", doc["id"], 1),
        )
        conn.execute(
            "insert into chunks(id, document_id, chunk_type, text, source_uri) values (?, ?, ?, ?, ?)",
            ("chunk_1", doc["id"], "text", "Delete me", f"txt://{doc['id']}#chunk=chunk_1"),
        )
        conn.execute(
            "insert into chunks_fts(id, document_id, text) values (?, ?, ?)",
            ("chunk_1", doc["id"], "Delete me"),
        )
        conn.execute(
            """
            insert into chunk_embeddings(chunk_id, document_id, embedding_json, updated_at)
            values (?, ?, ?, ?)
            """,
            ("chunk_1", doc["id"], "[]", "2026-06-09T00:00:00Z"),
        )
        conn.execute(
            """
            insert into claims(id, project_id, run_id, claim_text, status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("claim_1", project_id, "run_1", "Delete me", "verified", "2026-06-09T00:00:00Z"),
        )
        conn.execute(
            """
            insert into citations(id, claim_id, chunk_id, document_id, quote, source_uri, verified)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            ("citation_1", "claim_1", "chunk_1", doc["id"], "Delete me", f"txt://{doc['id']}#chunk=chunk_1", 1),
        )

    preview = documents.preview_delete_document(project_id, doc["id"])

    assert preview["deleted"] is False
    assert preview["filename"] == doc["filename"]
    assert preview["removed_claim_ids"] == ["claim_1"]
    assert preview["retained_claim_ids"] == []
    assert preview["removed_citation_ids"] == ["citation_1"]
    assert preview["removed_claims"] == [{"id": "claim_1", "text": "Delete me", "status": "verified"}]
    assert preview["retained_claims"] == []
    assert [item["id"] for item in preview["removed_citations"]] == ["citation_1"]
    assert {item["kind"] for item in preview["file_impacts"]} == {"source_file", "rendered_pages"}
    assert all(item["exists"] for item in preview["file_impacts"])
    assert documents.list_documents(project_id)[0]["id"] == doc["id"]

    result = documents.delete_document(project_id, doc["id"])

    assert result["deleted"] is True
    assert result["removed_claim_ids"] == ["claim_1"]
    assert result["retained_claim_ids"] == []
    assert result["removed_citation_ids"] == ["citation_1"]
    assert not source_path.exists()
    assert not render_dir.exists()
    assert documents.list_documents(project_id) == []
    with connect(db_path) as conn:
        for table in ["documents", "pages", "chunks", "chunk_embeddings", "claims", "citations"]:
            assert conn.execute(f"select count(*) from {table}").fetchone()[0] == 0
        assert conn.execute("select count(*) from chunks_fts").fetchone()[0] == 0
        audit = conn.execute("select * from audit_log where type = ?", ("document_deleted",)).fetchone()
    assert audit is not None


def test_delete_document_retains_multi_document_claim_for_review(tmp_workspace):
    project_id = "p1"
    docs = []
    for label in ["one", "two"]:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(f"Evidence {label}".encode("utf-8"))
            tf_path = tf.name
        docs.append(documents.import_document(project_id, tf_path))

    db_path = paths.project_db_path(project_id)
    with connect(db_path) as conn:
        for index, doc in enumerate(docs, start=1):
            conn.execute(
                "insert into chunks(id, document_id, chunk_type, text, source_uri) values (?, ?, ?, ?, ?)",
                (
                    f"chunk_{index}",
                    doc["id"],
                    "text",
                    f"Evidence {index}",
                    f"txt://{doc['id']}#chunk=chunk_{index}",
                ),
            )
            conn.execute(
                "insert into chunks_fts(id, document_id, text) values (?, ?, ?)",
                (f"chunk_{index}", doc["id"], f"Evidence {index}"),
            )
        conn.execute(
            """
            insert into claims(id, project_id, run_id, claim_text, status, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("claim_multi", project_id, "run_1", "Evidence requires two documents", "verified", "2026-06-09T00:00:00Z"),
        )
        for index, doc in enumerate(docs, start=1):
            conn.execute(
                """
                insert into citations(id, claim_id, chunk_id, document_id, quote, source_uri, verified)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"citation_{index}",
                    "claim_multi",
                    f"chunk_{index}",
                    doc["id"],
                    f"Evidence {index}",
                    f"txt://{doc['id']}#chunk=chunk_{index}",
                    1,
                ),
            )

    preview = documents.preview_delete_document(project_id, docs[0]["id"])

    assert preview["deleted"] is False
    assert preview["removed_claim_ids"] == []
    assert preview["retained_claim_ids"] == ["claim_multi"]
    assert preview["removed_citation_ids"] == ["citation_1"]
    assert preview["removed_claims"] == []
    assert preview["retained_claims"] == [
        {"id": "claim_multi", "text": "Evidence requires two documents", "status": "verified"}
    ]
    with connect(db_path) as conn:
        assert conn.execute("select count(*) from documents").fetchone()[0] == 2
        assert conn.execute("select status from claims where id = ?", ("claim_multi",)).fetchone()["status"] == "verified"
        assert conn.execute("select count(*) from citations where claim_id = ?", ("claim_multi",)).fetchone()[0] == 2

    result = documents.delete_document(project_id, docs[0]["id"])

    assert result["deleted"] is True
    assert result["removed_claim_ids"] == []
    assert result["retained_claim_ids"] == ["claim_multi"]
    assert result["removed_citation_ids"] == ["citation_1"]

    with connect(db_path) as conn:
        claim = conn.execute("select * from claims where id = ?", ("claim_multi",)).fetchone()
        assert claim["status"] == "needs_review"
        citations = conn.execute("select * from citations where claim_id = ? order by id", ("claim_multi",)).fetchall()
        assert [row["id"] for row in citations] == ["citation_2"]
        assert citations[0]["document_id"] == docs[1]["id"]
        assert conn.execute("select count(*) from documents").fetchone()[0] == 1
        assert conn.execute("select count(*) from chunks where document_id = ?", (docs[0]["id"],)).fetchone()[0] == 0
        assert conn.execute("select count(*) from chunks where document_id = ?", (docs[1]["id"],)).fetchone()[0] == 1


def test_apply_manual_text_replaces_parse_and_indexes_chunk(tmp_workspace):
    project_id = "manual_text"
    root = paths.ensure_project(project_id)
    source = root / "scan.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    document = documents.import_document(project_id, str(source))

    result = documents.apply_manual_text(
        project_id,
        document["id"],
        " Revenue increased by 24% in 2025.\n\n Gross margin was 61%. ",
        "Manual OCR correction",
    )

    assert result["status"] == "parsed"
    assert result["parser_version"] == "manual-text-v1"
    assert result["chunks"] == 1
    assert result["source_uri"].startswith(f"text://{document['id']}#block=manual_")
    with connect(paths.project_db_path(project_id)) as conn:
        doc_row = conn.execute("select * from documents where id = ?", (document["id"],)).fetchone()
        chunk_row = conn.execute("select * from chunks where document_id = ?", (document["id"],)).fetchone()
        fts_row = conn.execute(
            "select * from chunks_fts where chunks_fts match ?",
            ("Revenue",),
        ).fetchone()
        audit_row = conn.execute("select * from audit_log where type = ?", ("manual_text_applied",)).fetchone()

    assert doc_row["status"] == "parsed"
    assert doc_row["ocr_used"] == 0
    assert chunk_row["chunk_type"] == "manual_text"
    assert chunk_row["heading_path"] == "Manual OCR correction"
    assert "Revenue increased by 24% in 2025." in chunk_row["text"]
    assert fts_row["id"] == chunk_row["id"]
    assert audit_row is not None


def test_manual_text_api_returns_updated_document(tmp_workspace):
    from fastapi.testclient import TestClient
    from loamtrace.main import app

    project_id = "manual_text_api"
    root = paths.ensure_project(project_id)
    source = root / "scan.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    document = documents.import_document(project_id, str(source))

    response = TestClient(app).post(
        f"/api/documents/{document['id']}/manual-text",
        json={
            "project_id": project_id,
            "text": "Manual corrected source text with revenue 24%.",
            "heading": "Manual correction",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == document["id"]
    assert payload["status"] == "parsed"
    assert payload["parser_version"] == "manual-text-v1"
    assert payload["source_uri"].startswith(f"text://{document['id']}#block=manual_")
