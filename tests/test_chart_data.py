import json
import tempfile
from pathlib import Path

import pytest

from loamtrace import config
from loamtrace.db import connect
from loamtrace.services.chart_data import generate_chart_data
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.slides import annotate_chart_review_status
from loamtrace.services.tables import list_tables


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


def test_generate_chart_data_from_table_cells_with_traceability(tmp_workspace):
    project_id = "chart_project"
    ensure_project(project_id)
    _insert_table(project_id)

    result = generate_chart_data(project_id, "table_1", chart_type="bar")

    assert result["run_id"].startswith("run_")
    chart = result["chart"]
    assert chart["type"] == "chart"
    assert chart["chart_type"] == "bar"
    assert chart["review_status"] == "verified"
    assert chart["data_source"]["table_id"] == "table_1"
    assert chart["data_source"]["cell_ids"] == ["cell_r2c2", "cell_r3c2"]
    assert chart["series"] == [
        {
            "name": "Revenue",
            "points": [
                {"label": "2024", "value": 120.0, "cell_id": "cell_r2c2"},
                {"label": "2025", "value": 148.0, "cell_id": "cell_r3c2"},
            ],
        }
    ]

    deck = {
        "slides": [
            {
                "id": "slide_1",
                "elements": [chart],
            }
        ]
    }
    annotate_chart_review_status(project_id, deck)
    assert deck["slides"][0]["elements"][0]["review_status"] == "verified"
    with connect(project_db_path(project_id)) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("chart_data_generated",)).fetchone()
    assert audit is not None


def test_generate_chart_data_rejects_table_without_numeric_values(tmp_workspace):
    project_id = "chart_no_values"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            "insert into tables(id, document_id, parser) values (?, ?, ?)",
            ("table_1", "doc_1", "test"),
        )
        for row, values in enumerate([["Year", "Segment"], ["2024", "SMB"], ["2025", "Enterprise"]]):
            for col, text in enumerate(values):
                conn.execute(
                    """
                    insert into cells(id, table_id, document_id, row_index, col_index, text, value_json)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (f"cell_{row}_{col}", "table_1", "doc_1", row, col, text, f'"{text}"'),
                )

    with pytest.raises(ValueError, match="no_numeric_value_columns"):
        generate_chart_data(project_id, "table_1")


def test_chart_data_api(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")

    project_id = "chart_api"
    ensure_project(project_id)
    _insert_table(project_id)
    client = TestClient(main.app)

    response = client.post(
        "/api/charts/generate-data",
        json={"project_id": project_id, "table_id": "table_1", "chart_type": "line"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["chart"]["chart_type"] == "line"
    assert data["chart"]["series"][0]["points"][0]["cell_id"] == "cell_r2c2"


def test_chart_data_api_enforces_server_mode_write_guard(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "chart_guard"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    _insert_table(project_id)
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}
    payload = {"project_id": project_id, "table_id": "table_1", "chart_type": "bar"}

    denied = client.post("/api/charts/generate-data", json=payload, headers=headers)
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    allowed = client.post("/api/charts/generate-data", json=payload, headers=headers)
    assert allowed.status_code == 200
    assert allowed.json()["chart"]["review_status"] == "verified"

    payloads = _route_guard_payloads(project_id)
    assert [payload["route"] for payload in payloads] == [
        "POST /api/charts/generate-data",
        "POST /api/charts/generate-data",
    ]
    assert [payload["would_block"] for payload in payloads] == [True, False]


def test_chart_data_guard_allows_legacy_project_without_owner_acl(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "chart_guard_legacy"
    ensure_project(project_id)
    _insert_table(project_id)
    client = TestClient(main.app)

    response = client.post(
        "/api/charts/generate-data",
        json={"project_id": project_id, "table_id": "table_1", "chart_type": "bar"},
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )

    assert response.status_code == 200


def test_list_tables_returns_document_metadata_and_preview(tmp_workspace):
    project_id = "table_catalog"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into documents(id, project_id, sha256, filename, mime_type, source_path, created_at, status)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("doc_1", project_id, "sha", "model.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "/tmp/model.xlsx", "2026-06-09T00:00:00Z", "parsed"),
        )
    _insert_table(project_id)

    tables = list_tables(project_id)

    assert len(tables) == 1
    assert tables[0]["id"] == "table_1"
    assert tables[0]["document_filename"] == "model.xlsx"
    assert tables[0]["row_count"] == 3
    assert tables[0]["col_count"] == 2
    assert tables[0]["cell_count"] == 6
    assert tables[0]["preview"] == [["Year", "Revenue"], ["2024", "120"], ["2025", "148"]]


def test_list_tables_api_supports_document_filter(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")

    project_id = "table_catalog_api"
    ensure_project(project_id)
    _insert_table(project_id)
    client = TestClient(main.app)

    response = client.get("/api/tables", params={"project_id": project_id, "document_id": "doc_1"})

    assert response.status_code == 200
    data = response.json()
    assert data[0]["id"] == "table_1"
    assert data[0]["preview"][0] == ["Year", "Revenue"]


def _insert_table(project_id: str) -> None:
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            "insert into tables(id, document_id, parser) values (?, ?, ?)",
            ("table_1", "doc_1", "test"),
        )
        rows = [
            [("cell_r1c1", "Year", '"Year"'), ("cell_r1c2", "Revenue", '"Revenue"')],
            [("cell_r2c1", "2024", '"2024"'), ("cell_r2c2", "120", "120")],
            [("cell_r3c1", "2025", '"2025"'), ("cell_r3c2", "148", "148")],
        ]
        for row_index, row in enumerate(rows):
            for col_index, (cell_id, text, value_json) in enumerate(row):
                conn.execute(
                    """
                    insert into cells(id, table_id, document_id, row_index, col_index, text, value_json)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cell_id, "table_1", "doc_1", row_index, col_index, text, value_json),
                )


def _route_guard_payloads(project_id: str) -> list[dict]:
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]
