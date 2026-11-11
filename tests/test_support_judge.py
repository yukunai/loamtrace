import tempfile
from pathlib import Path

import pytest

from loamtrace import config
from loamtrace.db import connect
from loamtrace.models import CitationInput, ClaimInput
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.support_judge import judge_claim_support
from loamtrace.services.verifier import verify_claims


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


def test_support_judge_persists_review_signal_without_changing_claim_status(tmp_workspace, monkeypatch):
    project_id = "judge_test"
    claim = _verified_claim(project_id)
    citation_id = claim["citations"][0]["id"]

    def fake_chat_json(system_prompt, user_prompt):
        assert "must not change verification status" in system_prompt
        assert citation_id in user_prompt
        return {
            "citations": [
                {
                    "citation_id": citation_id,
                    "support_label": "partial",
                    "reason": "The quote supports revenue but not retention.",
                }
            ]
        }

    monkeypatch.setattr("loamtrace.services.support_judge.chat_json", fake_chat_json)

    result = judge_claim_support(project_id, claim["id"])

    assert result["judge_status"] == "used"
    assert result["applied_count"] == 1
    assert result["claim"]["status"] == "verified"
    citation = result["claim"]["citations"][0]
    assert citation["support_judge_label"] == "partial"
    assert citation["support_judge_reason"] == "The quote supports revenue but not retention."

    with connect(project_db_path(project_id)) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("support_judge_completed",)).fetchone()
    assert audit is not None


def test_support_judge_reports_not_configured(tmp_workspace, monkeypatch):
    project_id = "judge_not_configured"
    claim = _verified_claim(project_id)
    monkeypatch.setattr("loamtrace.services.support_judge.chat_json", lambda _system, _user: None)

    result = judge_claim_support(project_id, claim["id"])

    assert result["judge_status"] == "not_configured"
    assert result["claim"]["id"] == claim["id"]
    assert result["model_error"] is None


def test_support_judge_accepts_single_citation_top_level_label(tmp_workspace, monkeypatch):
    project_id = "judge_single_shape"
    claim = _verified_claim(project_id)
    monkeypatch.setattr(
        "loamtrace.services.support_judge.chat_json",
        lambda _system, _user: {"support_level": "direct", "explanation": "The quote directly supports the claim."},
    )

    result = judge_claim_support(project_id, claim["id"])

    citation = result["claim"]["citations"][0]
    assert result["judge_status"] == "used"
    assert citation["support_judge_label"] == "direct"
    assert citation["support_judge_reason"] == "The quote directly supports the claim."


def test_support_judge_reports_no_applicable_judgements(tmp_workspace, monkeypatch):
    project_id = "judge_unusable_shape"
    claim = _verified_claim(project_id)
    monkeypatch.setattr(
        "loamtrace.services.support_judge.chat_json",
        lambda _system, _user: {"citations": [{"citation_id": "missing", "support_label": "direct"}]},
    )

    result = judge_claim_support(project_id, claim["id"])

    assert result["judge_status"] == "no_applicable_judgements"
    assert result["applied_count"] == 0


def test_support_judge_api_returns_updated_claim(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace.main import app

    project_id = "judge_api"
    claim = _verified_claim(project_id)
    citation_id = claim["citations"][0]["id"]
    monkeypatch.setattr(
        "loamtrace.services.support_judge.chat_json",
        lambda _system, _user: {
            "citations": [
                {
                    "citation_id": citation_id,
                    "support_label": "weak",
                    "reason": "The quote is related but not enough.",
                }
            ]
        },
    )

    response = TestClient(app).post(
        f"/api/claims/{claim['id']}/judge-support",
        json={"project_id": project_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["judge_status"] == "used"
    assert payload["claim"]["status"] == "verified"
    citation = payload["claim"]["citations"][0]
    assert citation["support_judge_label"] == "weak"
    assert citation["support_judge_reason"] == "The quote is related but not enough."


def test_support_judge_api_enforces_server_mode_review_guard(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "judge_api_guard"
    claim = _verified_claim(project_id)
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    monkeypatch.setattr("loamtrace.services.support_judge.chat_json", lambda _system, _user: None)
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    denied = client.post(
        f"/api/claims/{claim['id']}/judge-support",
        json={"project_id": project_id},
        headers=headers,
    )
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "reviewer")
    allowed = client.post(
        f"/api/claims/{claim['id']}/judge-support",
        json={"project_id": project_id},
        headers=headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["judge_status"] == "not_configured"

    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    assert len(rows) == 2


def test_support_judge_guard_allows_legacy_project_without_owner_acl(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_workspace)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_workspace / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "judge_api_guard_legacy"
    claim = _verified_claim(project_id)
    monkeypatch.setattr("loamtrace.services.support_judge.chat_json", lambda _system, _user: None)
    client = TestClient(main.app)

    response = client.post(
        f"/api/claims/{claim['id']}/judge-support",
        json={"project_id": project_id},
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )

    assert response.status_code == 200
    assert response.json()["judge_status"] == "not_configured"


def _verified_claim(project_id: str) -> dict:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "c1",
                "d1",
                "text",
                "Revenue grew by 24% in 2025.",
                "pdf://d1#page=1",
                "[]",
            ),
        )
    result = verify_claims(
        project_id,
        [
            ClaimInput(
                text="Revenue grew by 24% in 2025.",
                citations=[CitationInput(chunk_id="c1", quote="Revenue grew by 24% in 2025.")],
            )
        ],
    )
    return result["claims"][0]
