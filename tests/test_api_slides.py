import json

from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.db import connect
from loamtrace.main import app
from loamtrace.models import CitationInput, ClaimInput
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.verifier import verify_claims


def test_table_deck_api_generates_source_table_deck(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "api_table_deck"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into documents(id, project_id, sha256, filename, mime_type, source_path, created_at, status)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ( "doc_table", project_id, "sha_table", "metrics.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "/tmp/metrics.xlsx", "2026-06-09T00:00:00Z", "parsed"),
        )
        conn.execute(
            """
            insert into tables(id, document_id, page_id, bbox_json, caption, parser)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("table_metrics", "doc_table", None, None, "Operating metrics", "test-parser"),
        )
        for cell_id, row_index, col_index, text in [
            ("cell_metric", 1, 1, "Metric"),
            ("cell_value", 1, 2, "2025"),
            ("cell_revenue", 2, 1, "Revenue"),
            ("cell_amount", 2, 2, "148"),
        ]:
            conn.execute(
                """
                insert into cells(
                  id, table_id, document_id, page_id, sheet_name, cell_ref,
                  row_index, col_index, text, value_json, bbox_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cell_id,
                    "table_metrics",
                    "doc_table",
                    None,
                    "Revenue",
                    f"R{row_index}C{col_index}",
                    row_index,
                    col_index,
                    text,
                    json.dumps({"text": text}),
                    None,
                ),
            )

    response = TestClient(app).post(
        "/api/slides/table-deck",
        json={"project_id": project_id, "table_id": "table_metrics", "title": "Operating Table"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["deck_id"].startswith("deck_")
    assert body["deck"]["slides"][1]["layout"] == "source_table"
    table = next(element for element in body["deck"]["slides"][1]["elements"] if element["type"] == "table")
    assert table["review_status"] == "verified"
    assert table["rows"] == [["Metric", "2025"], ["Revenue", "148"]]
    assert table["data_source"]["table_id"] == "table_metrics"


def test_slide_template_api_lists_and_generates_deck(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "api_template_deck"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk_revenue",
                "doc_1",
                "text",
                "Revenue increased by 24% year over year in 2025.",
                "pdf://doc_1#page=1",
                "[]",
            ),
        )
    claim = verify_claims(
        project_id,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_revenue",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]

    client = TestClient(app)
    templates = client.get("/api/templates/slides")
    assert templates.status_code == 200
    assert any(template["id"] == "investment_committee" for template in templates.json())

    response = client.post(
        "/api/slides/from-template",
        json={
            "project_id": project_id,
            "template_id": "risk_review",
            "title": "Risk Review",
            "claim_ids": [claim["id"]],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["deck"]["template_id"] == "risk_review"
    assert body["deck"]["slides"][0]["layout"] == "title"
    assert body["deck"]["slides"][-1]["layout"] == "evidence_appendix"
