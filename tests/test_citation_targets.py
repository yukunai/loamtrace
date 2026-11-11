import json

from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.db import connect
from loamtrace.main import app
from loamtrace.services.paths import ensure_project, project_db_path


def test_citation_target_resolves_pdf_page_and_bbox(tmp_path, monkeypatch):
    project_id = _setup_project(tmp_path, monkeypatch)
    with connect(project_db_path(project_id)) as conn:
        _insert_document(conn, project_id, "doc_pdf", "source.pdf", "application/pdf")
        conn.execute(
            """
            insert into pages(id, document_id, page_number, width, height, render_path, text_layer_available)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            ("page_1", "doc_pdf", 3, 612.0, 792.0, "/tmp/page-3.png", 1),
        )
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, page_start, page_end, bbox_json, word_ids_json, source_uri)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk_pdf",
                "doc_pdf",
                "text",
                "Revenue grew 24%.",
                3,
                3,
                json.dumps({"page": 3, "x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.25}),
                "[]",
                "pdf://doc_pdf#page=3&chunk=chunk_pdf",
            ),
        )
        _insert_claim_and_citation(
            conn,
            project_id,
            "claim_pdf",
            "cit_pdf",
            "chunk_pdf",
            "doc_pdf",
            "Revenue grew 24%.",
            "pdf://doc_pdf#page=3&chunk=chunk_pdf",
            json.dumps({"page": 3, "x0": 0.11, "y0": 0.21, "x1": 0.49, "y1": 0.24}),
        )

    response = TestClient(app).get("/api/citations/cit_pdf/target", params={"project_id": project_id})

    assert response.status_code == 200
    target = response.json()
    assert target["scheme"] == "pdf"
    assert target["precision"] == "bbox"
    assert target["renderable"] is True
    assert target["locator"]["page"] == "3"
    assert target["bbox"]["x0"] == 0.11
    assert target["page"]["page_number"] == 3


def test_citation_target_resolves_docx_paragraph_without_bbox(tmp_path, monkeypatch):
    project_id = _setup_project(tmp_path, monkeypatch)
    with connect(project_db_path(project_id)) as conn:
        _insert_document(conn, project_id, "doc_docx", "source.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        conn.execute(
            """
            insert into blocks(id, document_id, block_type, text, reading_order, heading_path)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("block_12", "doc_docx", "paragraph", "Risk factors increased.", 12, "Risk Factors"),
        )
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, word_ids_json, source_uri)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("chunk_docx", "doc_docx", "docx_paragraph", "Risk factors increased.", "[]", "docx://doc_docx#paragraph=12"),
        )
        _insert_claim_and_citation(
            conn,
            project_id,
            "claim_docx",
            "cit_docx",
            "chunk_docx",
            "doc_docx",
            "Risk factors increased.",
            "docx://doc_docx#paragraph=12",
            None,
        )

    response = TestClient(app).get("/api/citations/cit_docx/target", params={"project_id": project_id})

    assert response.status_code == 200
    target = response.json()
    assert target["scheme"] == "docx"
    assert target["precision"] == "paragraph"
    assert target["renderable"] is False
    assert target["bbox"] is None
    assert target["paragraph"]["id"] == "block_12"
    assert target["location_label"] == "paragraph 12"


def test_citation_target_resolves_xlsx_cell(tmp_path, monkeypatch):
    project_id = _setup_project(tmp_path, monkeypatch)
    with connect(project_db_path(project_id)) as conn:
        _insert_document(conn, project_id, "doc_xlsx", "source.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        conn.execute(
            """
            insert into cells(id, document_id, sheet_name, cell_ref, row_index, col_index, text, value_json)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("cell_b12", "doc_xlsx", "Revenue", "B12", 12, 2, "148", json.dumps({"number": 148})),
        )
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, word_ids_json, cell_ids_json, source_uri)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk_xlsx",
                "doc_xlsx",
                "xlsx_row",
                "Revenue row 12: B12: 148",
                "[]",
                json.dumps(["cell_b12"]),
                "xlsx://doc_xlsx#sheet=Revenue&cell=B12",
            ),
        )
        _insert_claim_and_citation(
            conn,
            project_id,
            "claim_xlsx",
            "cit_xlsx",
            "chunk_xlsx",
            "doc_xlsx",
            "Revenue was 148.",
            "xlsx://doc_xlsx#sheet=Revenue&cell=B12",
            None,
        )

    response = TestClient(app).get("/api/citations/cit_xlsx/target", params={"project_id": project_id})

    assert response.status_code == 200
    target = response.json()
    assert target["scheme"] == "xlsx"
    assert target["precision"] == "cell"
    assert target["location_label"] == "sheet Revenue, cell B12"
    assert target["cells"][0]["id"] == "cell_b12"
    assert target["cells"][0]["value"] == {"number": 148}


def test_citation_target_rejects_invalid_source_uri(tmp_path, monkeypatch):
    project_id = _setup_project(tmp_path, monkeypatch)
    with connect(project_db_path(project_id)) as conn:
        _insert_document(conn, project_id, "doc_bad", "source.txt", "text/plain")
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, word_ids_json, source_uri)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("chunk_bad", "doc_bad", "text", "Bad URI", "[]", "bad-uri"),
        )
        _insert_claim_and_citation(
            conn,
            project_id,
            "claim_bad",
            "cit_bad",
            "chunk_bad",
            "doc_bad",
            "Bad URI",
            "bad-uri",
            None,
        )

    response = TestClient(app).get("/api/citations/cit_bad/target", params={"project_id": project_id})

    assert response.status_code == 400
    assert "source_uri_invalid" in response.text


def _setup_project(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "citation_targets"
    ensure_project(project_id)
    return project_id


def _insert_document(conn, project_id: str, document_id: str, filename: str, mime_type: str) -> None:
    conn.execute(
        """
        insert into documents(
          id, project_id, sha256, filename, mime_type, source_path, created_at, status
        )
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (document_id, project_id, f"sha_{document_id}", filename, mime_type, f"/tmp/{filename}", "2026-06-09T00:00:00Z", "parsed"),
    )


def _insert_claim_and_citation(
    conn,
    project_id: str,
    claim_id: str,
    citation_id: str,
    chunk_id: str,
    document_id: str,
    quote: str,
    source_uri: str,
    bbox_json: str,
) -> None:
    conn.execute(
        """
        insert into claims(id, project_id, run_id, claim_text, claim_type, status, created_at)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (claim_id, project_id, "run_1", quote, "test", "verified", "2026-06-09T00:00:00Z"),
    )
    conn.execute(
        """
        insert into citations(
          id, claim_id, chunk_id, document_id, quote, source_uri, bbox_json, verified
        )
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (citation_id, claim_id, chunk_id, document_id, quote, source_uri, bbox_json, 1),
    )
