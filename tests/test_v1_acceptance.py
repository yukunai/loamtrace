from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.main import app


def test_v1_api_acceptance_docx_to_memo_slides_and_exports(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")

    source = tmp_path / "acceptance_memo.docx"
    docx = Document()
    docx.add_heading("Financial Highlights", level=1)
    docx.add_paragraph("Revenue increased by 24% year over year in 2025.")
    docx.save(source)

    client = TestClient(app)
    project_id = "acceptance_v1"

    created = client.post("/api/projects", json={"project_id": project_id, "name": "Acceptance V1"})
    assert created.status_code == 200
    assert created.json()["id"] == project_id

    imported = client.post(
        "/api/documents/import",
        json={"project_id": project_id, "file_path": str(source)},
    )
    assert imported.status_code == 200
    document_id = imported.json()["id"]

    parsed = client.post(f"/api/documents/{document_id}/parse", json={"project_id": project_id})
    assert parsed.status_code == 200
    assert parsed.json()["status"] == "parsed"

    search = client.post("/api/search", json={"project_id": project_id, "query": "Revenue 2025", "top_n": 12})
    assert search.status_code == 200
    results = search.json()
    assert any(result["source_uri"].startswith("docx://") for result in results)

    memo = client.post("/api/generate/memo", json={"project_id": project_id, "query": "Revenue 2025", "top_n": 5})
    assert memo.status_code == 200
    memo_body = memo.json()
    verified_claim_ids = [claim["id"] for claim in memo_body["claims"] if claim["status"] == "verified"]
    assert verified_claim_ids
    assert "Revenue increased by 24%" in memo_body["answer"]

    deck = client.post(
        "/api/slides/generate",
        json={"project_id": project_id, "title": "Acceptance Deck", "claim_ids": verified_claim_ids},
    )
    assert deck.status_code == 200
    deck_body = deck.json()
    assert deck_body["deck"]["slides"][1]["main_claim_id"] == verified_claim_ids[0]

    pptx = client.post("/api/export/pptx", json={"project_id": project_id, "deck_id": deck_body["deck_id"]})
    assert pptx.status_code == 200
    assert Path(pptx.json()["path"]).exists()

    package = client.post(
        "/api/export/research-package",
        json={"project_id": project_id, "deck_id": deck_body["deck_id"]},
    )
    assert package.status_code == 200
    manifest = package.json()["manifest"]
    assert manifest["counts"]["verified_claims"] >= 1
    assert "memo.md" in manifest["files"]
    assert "deck.slide.json" in manifest["files"]

    audit = client.get("/api/audit", params={"project_id": project_id, "limit": 20})
    assert audit.status_code == 200
    audit_types = {event["type"] for event in audit.json()}
    assert {
        "search_completed",
        "generate_memo_completed",
        "slide_deck_generated",
        "pptx_exported",
        "research_package_exported",
    }.issubset(audit_types)
