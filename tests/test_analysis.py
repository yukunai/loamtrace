import json
import tempfile
from pathlib import Path

import pytest

from loamtrace import config
from loamtrace.db import connect
from loamtrace.services.analysis import scan_contract_clauses, scan_financial_consistency, scan_red_flags
from loamtrace.services.paths import ensure_project, project_db_path


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


def test_scan_red_flags_returns_evidence_and_audit(tmp_workspace):
    project_id = "risk_scan"
    ensure_project(project_id)
    _insert_chunk(
        project_id,
        "c1",
        "Risk Factors: customer concentration is material because the top three customers represented 41% of revenue.",
    )
    _insert_chunk(project_id, "c2", "Revenue grew by 24% in 2025.")

    result = scan_red_flags(project_id, limit=10)

    assert result["run_id"].startswith("run_")
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["category"] == "customer_concentration"
    assert finding["severity"] == "high"
    assert finding["chunk_id"] == "c1"
    assert finding["source_uri"] == "docx://d1#paragraph=1"
    assert "top three customers" in finding["quote"]

    run_dir = Path(result["run_dir"])
    assert json.loads((run_dir / "findings.json").read_text(encoding="utf-8"))[0]["chunk_id"] == "c1"
    assert "red_flag_scan_completed" in (run_dir / "logs.jsonl").read_text(encoding="utf-8")
    with connect(project_db_path(project_id)) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("red_flag_scan_completed",)).fetchone()
    assert audit is not None


def test_scan_red_flags_respects_limit(tmp_workspace):
    project_id = "risk_limit"
    ensure_project(project_id)
    _insert_chunk(project_id, "c1", "The company reported a covenant default.")
    _insert_chunk(project_id, "c2", "The contract termination clause could trigger a breach.")

    result = scan_red_flags(project_id, limit=1)

    assert len(result["findings"]) == 1


def test_red_flag_api(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")

    project_id = "risk_api"
    ensure_project(project_id)
    _insert_chunk(project_id, "c1", "Liquidity risk increased after negative cash flow.")
    client = TestClient(main.app)

    response = client.post("/api/analysis/red-flags", json={"project_id": project_id, "limit": 5})

    assert response.status_code == 200
    data = response.json()
    assert data["findings"][0]["category"] in {"debt_or_default", "financial_decline"}
    assert data["findings"][0]["chunk_id"] == "c1"


def test_scan_financial_consistency_flags_conflicting_metric_values(tmp_workspace):
    project_id = "financial_conflict"
    ensure_project(project_id)
    _insert_chunk(project_id, "c1", "Revenue was $120 million in 2025.")
    _insert_chunk(project_id, "c2", "Revenue was $135 million in 2025.")
    _insert_chunk(project_id, "c3", "Gross margin was 42% in 2025.")

    result = scan_financial_consistency(project_id, limit=10)

    assert result["run_id"].startswith("run_")
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["category"] == "financial_inconsistency"
    assert finding["metric"] == "revenue"
    assert finding["period"] == "2025"
    assert finding["values"] == ["$120million", "$135million"]
    assert {item["chunk_id"] for item in finding["observations"]} == {"c1", "c2"}
    assert all(item["source_uri"] == "docx://d1#paragraph=1" for item in finding["observations"])

    run_dir = Path(result["run_dir"])
    assert json.loads((run_dir / "findings.json").read_text(encoding="utf-8"))[0]["metric"] == "revenue"
    assert "financial_consistency_scan_completed" in (run_dir / "logs.jsonl").read_text(encoding="utf-8")
    with connect(project_db_path(project_id)) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("financial_consistency_scan_completed",)).fetchone()
    assert audit is not None


def test_scan_financial_consistency_ignores_matching_values(tmp_workspace):
    project_id = "financial_match"
    ensure_project(project_id)
    _insert_chunk(project_id, "c1", "Revenue was $120 million in 2025.")
    _insert_chunk(project_id, "c2", "2025 revenue was $120 million.")

    result = scan_financial_consistency(project_id, limit=10)

    assert result["findings"] == []
    assert len(result["observations"]) == 2


def test_financial_consistency_api(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")

    project_id = "financial_api"
    ensure_project(project_id)
    _insert_chunk(project_id, "c1", "ARR was $10 million in 2025.")
    _insert_chunk(project_id, "c2", "ARR was $12 million in 2025.")
    client = TestClient(main.app)

    response = client.post("/api/analysis/financial-consistency", json={"project_id": project_id, "limit": 5})

    assert response.status_code == 200
    data = response.json()
    assert data["findings"][0]["metric"] == "arr"
    assert data["findings"][0]["period"] == "2025"


def test_scan_contract_clauses_flags_conflicting_clause_variants(tmp_workspace):
    project_id = "contract_conflict"
    ensure_project(project_id)
    _insert_chunk(
        project_id,
        "c1",
        "The agreement may be terminated for convenience by either party with 30 days notice.",
        document_id="msa_2024",
        source_uri="docx://msa_2024#paragraph=4",
    )
    _insert_chunk(
        project_id,
        "c2",
        "The agreement may be terminated only for cause after a material breach.",
        document_id="msa_2025",
        source_uri="docx://msa_2025#paragraph=9",
    )

    result = scan_contract_clauses(project_id, limit=10)

    assert result["run_id"].startswith("run_")
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["category"] == "contract_clause_mismatch"
    assert finding["clause_type"] == "termination"
    assert finding["variants"] == ["cause_only", "convenience"]
    assert {item["document_id"] for item in finding["observations"]} == {"msa_2024", "msa_2025"}
    assert all("terminated" in item["quote"] for item in finding["observations"])

    run_dir = Path(result["run_dir"])
    assert json.loads((run_dir / "findings.json").read_text(encoding="utf-8"))[0]["clause_type"] == "termination"
    assert "contract_clause_scan_completed" in (run_dir / "logs.jsonl").read_text(encoding="utf-8")
    with connect(project_db_path(project_id)) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("contract_clause_scan_completed",)).fetchone()
    assert audit is not None


def test_scan_contract_clauses_ignores_matching_clause_variants(tmp_workspace):
    project_id = "contract_match"
    ensure_project(project_id)
    _insert_chunk(project_id, "c1", "Payment is due net 30 from receipt of invoice.")
    _insert_chunk(project_id, "c2", "Fees are payable on net 30 terms.")

    result = scan_contract_clauses(project_id, limit=10)

    assert result["findings"] == []
    assert len(result["observations"]) == 2


def test_contract_clause_api(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")

    project_id = "contract_api"
    ensure_project(project_id)
    _insert_chunk(project_id, "c1", "This agreement will automatically renew for one year.")
    _insert_chunk(project_id, "c2", "This agreement will not automatically renew after the initial term.")
    client = TestClient(main.app)

    response = client.post("/api/analysis/contract-clauses", json={"project_id": project_id, "limit": 5})

    assert response.status_code == 200
    data = response.json()
    assert data["findings"][0]["clause_type"] == "auto_renewal"
    assert data["findings"][0]["variants"] == ["auto_renewal", "no_auto_renewal"]


def test_analysis_apis_enforce_server_mode_write_guard(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "analysis_guard"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}
    routes = [
        "/api/analysis/red-flags",
        "/api/analysis/financial-consistency",
        "/api/analysis/contract-clauses",
    ]

    for route in routes:
        denied = client.post(route, json={"project_id": project_id, "limit": 5}, headers=headers)
        assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    for route in routes:
        allowed = client.post(route, json={"project_id": project_id, "limit": 5}, headers=headers)
        assert allowed.status_code == 200
        assert allowed.json()["findings"] == []

    payloads = _route_guard_payloads(project_id)
    assert [payload["route"] for payload in payloads] == [
        "POST /api/analysis/red-flags",
        "POST /api/analysis/financial-consistency",
        "POST /api/analysis/contract-clauses",
        "POST /api/analysis/red-flags",
        "POST /api/analysis/financial-consistency",
        "POST /api/analysis/contract-clauses",
    ]
    assert [payload["would_block"] for payload in payloads] == [True, True, True, False, False, False]


def test_analysis_guards_allow_legacy_project_without_owner_acl(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "analysis_guard_legacy"
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    for route in [
        "/api/analysis/red-flags",
        "/api/analysis/financial-consistency",
        "/api/analysis/contract-clauses",
    ]:
        response = client.post(route, json={"project_id": project_id, "limit": 5}, headers=headers)
        assert response.status_code == 200


def _insert_chunk(
    project_id: str,
    chunk_id: str,
    text: str,
    document_id: str = "d1",
    source_uri: str = "docx://d1#paragraph=1",
) -> None:
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (chunk_id, document_id, "text", text, source_uri, "[]"),
        )


def _route_guard_payloads(project_id: str) -> list[dict]:
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]
