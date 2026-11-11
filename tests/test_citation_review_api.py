from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.db import connect
from loamtrace.main import app
from loamtrace.services.paths import ensure_project, project_db_path


def test_citation_review_api_records_manual_decision_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")

    project_id = "citation_review_api"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("bad", "doc_1", "text", "Revenue grew 24% in 2025.", "pdf://doc_1#page=1", "[]"),
        )
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("good", "doc_1", "text", "Revenue grew 25% in 2025.", "pdf://doc_1#page=2", "[]"),
        )

    client = TestClient(app)
    verified = client.post(
        "/api/verify/run",
        json={
            "project_id": project_id,
            "claims": [
                {
                    "text": "Revenue grew 25% in 2025.",
                    "citations": [{"chunk_id": "bad", "quote": "Revenue grew 24% in 2025."}],
                }
            ],
        },
    )
    assert verified.status_code == 200
    blocked = verified.json()["claims"][0]
    assert blocked["status"] == "blocked"
    citation_id = blocked["citations"][0]["id"]

    reviewed = client.post(
        f"/api/citations/{citation_id}/review",
        json={
            "project_id": project_id,
            "action": "approve",
            "reviewer": "qa",
            "note": "Approved with documented exception.",
        },
    )
    assert reviewed.status_code == 200
    approved = reviewed.json()
    assert approved["status"] == "blocked"
    citation = approved["citations"][0]
    assert citation["verified"] is False
    assert citation["verification_method"] is None
    assert citation["failure_reason"] == "number_not_found"
    assert citation["reviewer"] == "qa"
    assert citation["review_note"] == "Approved with documented exception."
    assert citation["reviewed_at"]

    replaced = client.post(
        f"/api/citations/{citation_id}/replace",
        json={
            "project_id": project_id,
            "chunk_id": "good",
            "quote": "Revenue grew 25% in 2025.",
        },
    )
    assert replaced.status_code == 200
    updated = replaced.json()
    assert updated["status"] == "verified"
    assert updated["citations"][0]["reviewer"] is None
    assert updated["citations"][0]["review_note"] is None
    assert updated["citations"][0]["reviewed_at"] is None

    audit = client.get("/api/audit", params={"project_id": project_id, "limit": 10})
    assert audit.status_code == 200
    audit_types = {event["type"] for event in audit.json()}
    assert "citation_manual_approved" in audit_types
    assert "citation_replaced" in audit_types


def test_citation_review_api_enforces_server_mode_review_guard(tmp_path, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "citation_review_guard"
    citation_id = _blocked_citation_id(project_id)
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    denied = client.post(
        f"/api/citations/{citation_id}/review",
        json={"project_id": project_id, "action": "approve", "reviewer": "qa"},
        headers=headers,
    )
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "reviewer")
    allowed = client.post(
        f"/api/citations/{citation_id}/review",
        json={"project_id": project_id, "action": "approve", "reviewer": "qa"},
        headers=headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["citations"][0]["reviewer"] == "qa"

    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    assert len(rows) >= 2


def test_citation_review_guard_allows_legacy_project_without_owner_acl(tmp_path, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "citation_review_guard_legacy"
    citation_id = _blocked_citation_id(project_id)
    client = TestClient(main.app)

    response = client.post(
        f"/api/citations/{citation_id}/review",
        json={"project_id": project_id, "action": "reject", "reviewer": "qa"},
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )

    assert response.status_code == 200
    assert response.json()["citations"][0]["reviewer"] == "qa"


def test_claim_correction_api_reverifies_and_audits_manual_fix(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")

    project_id = "claim_correction_api"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("source", "doc_1", "text", "Revenue grew 24% in 2025.", "pdf://doc_1#page=1", "[]"),
        )

    client = TestClient(app)
    verified = client.post(
        "/api/verify/run",
        json={
            "project_id": project_id,
            "claims": [
                {
                    "text": "Revenue grew 25% in 2025.",
                    "citations": [{"chunk_id": "source", "quote": "Revenue grew 24% in 2025."}],
                }
            ],
        },
    )
    assert verified.status_code == 200
    blocked = verified.json()["claims"][0]
    assert blocked["status"] == "blocked"
    assert blocked["citations"][0]["failure_reason"] == "number_not_found"

    corrected = client.post(
        f"/api/claims/{blocked['id']}/correct",
        json={
            "project_id": project_id,
            "text": "Revenue grew 24% in 2025.",
            "citation_id": blocked["citations"][0]["id"],
            "quote": "Revenue grew 24% in 2025.",
            "reviewer": "qa",
            "note": "Corrected the misstated percentage.",
        },
    )
    assert corrected.status_code == 200
    claim = corrected.json()
    assert claim["text"] == "Revenue grew 24% in 2025."
    assert claim["status"] == "verified"
    citation = claim["citations"][0]
    assert citation["verified"] is True
    assert citation["verification_method"] == "normalized_exact"
    assert citation["failure_reason"] is None
    assert citation["reviewer"] == "qa"
    assert citation["review_note"] == "Corrected the misstated percentage."
    assert citation["reviewed_at"]

    audit = client.get("/api/audit", params={"project_id": project_id, "limit": 20})
    assert audit.status_code == 200
    events = audit.json()
    assert any(event["type"] == "claim_corrected" for event in events)


def test_claim_correction_api_enforces_server_mode_review_guard(tmp_path, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "claim_correction_guard"
    claim = _blocked_claim(project_id)
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    denied = client.post(
        f"/api/claims/{claim['id']}/correct",
        json={
            "project_id": project_id,
            "text": "Revenue grew 24% in 2025.",
            "citation_id": claim["citations"][0]["id"],
            "quote": "Revenue grew 24% in 2025.",
            "reviewer": "qa",
        },
        headers=headers,
    )
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "reviewer")
    allowed = client.post(
        f"/api/claims/{claim['id']}/correct",
        json={
            "project_id": project_id,
            "text": "Revenue grew 24% in 2025.",
            "citation_id": claim["citations"][0]["id"],
            "quote": "Revenue grew 24% in 2025.",
            "reviewer": "qa",
        },
        headers=headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "verified"

    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    assert len(rows) >= 2


def test_claim_correction_guard_allows_legacy_project_without_owner_acl(tmp_path, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "claim_correction_guard_legacy"
    claim = _blocked_claim(project_id)
    client = TestClient(main.app)

    response = client.post(
        f"/api/claims/{claim['id']}/correct",
        json={
            "project_id": project_id,
            "text": "Revenue grew 24% in 2025.",
            "citation_id": claim["citations"][0]["id"],
            "quote": "Revenue grew 24% in 2025.",
            "reviewer": "qa",
        },
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "verified"


def test_citation_replacement_api_enforces_server_mode_review_guard(tmp_path, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "citation_replace_guard"
    claim = _blocked_claim(project_id)
    _insert_good_chunk(project_id)
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    denied = client.post(
        f"/api/citations/{claim['citations'][0]['id']}/replace",
        json={"project_id": project_id, "chunk_id": "good", "quote": "Revenue grew 25% in 2025."},
        headers=headers,
    )
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "reviewer")
    allowed = client.post(
        f"/api/citations/{claim['citations'][0]['id']}/replace",
        json={"project_id": project_id, "chunk_id": "good", "quote": "Revenue grew 25% in 2025."},
        headers=headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "verified"

    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    assert len(rows) >= 2


def test_citation_replacement_guard_allows_legacy_project_without_owner_acl(tmp_path, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "citation_replace_guard_legacy"
    claim = _blocked_claim(project_id)
    _insert_good_chunk(project_id)
    client = TestClient(main.app)

    response = client.post(
        f"/api/citations/{claim['citations'][0]['id']}/replace",
        json={"project_id": project_id, "chunk_id": "good", "quote": "Revenue grew 25% in 2025."},
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "verified"


def _blocked_citation_id(project_id: str) -> str:
    return _blocked_claim(project_id)["citations"][0]["id"]


def _blocked_claim(project_id: str) -> dict:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("bad", "doc_1", "text", "Revenue grew 24% in 2025.", "pdf://doc_1#page=1", "[]"),
        )

    client = TestClient(app)
    verified = client.post(
        "/api/verify/run",
        json={
            "project_id": project_id,
            "claims": [
                {
                    "text": "Revenue grew 25% in 2025.",
                    "citations": [{"chunk_id": "bad", "quote": "Revenue grew 24% in 2025."}],
                }
            ],
        },
    )
    assert verified.status_code == 200
    blocked = verified.json()["claims"][0]
    assert blocked["status"] == "blocked"
    return blocked


def _insert_good_chunk(project_id: str) -> None:
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("good", "doc_1", "text", "Revenue grew 25% in 2025.", "pdf://doc_1#page=2", "[]"),
        )
