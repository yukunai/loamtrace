import json

from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.main import app
from loamtrace.services.paths import ensure_project, project_root


def test_research_package_api_returns_400_for_chart_needing_review(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "api_chart_gate"
    ensure_project(project_id)
    slides_dir = project_root(project_id) / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    (slides_dir / "deck_chart.slide.json").write_text(
        json.dumps(
            {
                "deck_id": "deck_chart",
                "title": "Chart Gate",
                "slides": [
                    {
                        "id": "slide_chart",
                        "layout": "claim_with_chart",
                        "title": "Revenue trend",
                        "main_claim_id": None,
                        "elements": [
                            {
                                "type": "chart",
                                "chart_type": "line",
                                "data_source": {},
                            }
                        ],
                        "speaker_notes": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    client = TestClient(app)
    response = client.post(
        "/api/export/research-package",
        json={"project_id": project_id, "deck_id": "deck_chart"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "chart_needs_review:slide_chart"


def test_export_artifacts_api_lists_existing_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "api_export_artifacts"
    ensure_project(project_id)
    root = project_root(project_id)
    (root / "slides" / "deck_1.pptx").write_bytes(b"pptx")
    package_dir = root / "exports" / "export_1"
    package_dir.mkdir(parents=True)
    (package_dir / "manifest.json").write_text(
        json.dumps({"package_id": "export_1", "deck_id": "deck_1", "created_at": "2026-06-09T00:00:00Z"}),
        encoding="utf-8",
    )
    (root / "exports" / "export_1.zip").write_bytes(b"zip")

    response = TestClient(app).get("/api/export/artifacts", params={"project_id": project_id})

    assert response.status_code == 200
    artifacts = response.json()
    assert {artifact["type"] for artifact in artifacts} == {"pptx", "research_package", "research_package_zip"}
    assert any(artifact["package_id"] == "export_1" for artifact in artifacts)
