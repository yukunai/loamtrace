import pytest
import tempfile
import json
from pathlib import Path
from loamtrace.services import paths
from loamtrace import config, main

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

def test_list_projects_with_names(tmp_workspace):
    # Use ensure_project to create projects with names
    paths.ensure_project("p1", "Project One")
    paths.ensure_project("p2", "Project Two")
    
    projects = main.list_projects()
    assert len(projects) == 2
    
    # Sort by id to be sure
    projects.sort(key=lambda x: x["id"])
    assert projects[0]["id"] == "p1"
    assert projects[0]["name"] == "Project One"
    assert projects[1]["id"] == "p2"
    assert projects[1]["name"] == "Project Two"

def test_create_project_api(tmp_workspace):
    from loamtrace.models import CreateProjectRequest
    req = CreateProjectRequest(project_id="p3", name="Project Three")
    res = main.create_project(req)
    assert res["id"] == "p3"
    assert res["name"] == "Project Three"
    
    projects = main.list_projects()
    assert any(p["id"] == "p3" and p["name"] == "Project Three" for p in projects)


def test_create_project_api_enforces_server_mode_creation_guard(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "SERVER_MODE", True)
    client = TestClient(main.app)

    denied = client.post(
        "/api/projects",
        json={"project_id": "team_denied_project", "name": "Denied"},
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )
    assert denied.status_code == 403
    assert not (config.PROJECTS_ROOT / "team_denied_project").exists()

    editor_denied = client.post(
        "/api/projects",
        json={"project_id": "team_editor_denied_project", "name": "Editor Denied"},
        headers={
            "x-loamtrace-actor-id": "user_1",
            "x-loamtrace-actor-email": "user@example.test",
            "x-loamtrace-project-role": "editor",
        },
    )
    assert editor_denied.status_code == 403
    assert not (config.PROJECTS_ROOT / "team_editor_denied_project").exists()

    allowed = client.post(
        "/api/projects",
        json={"project_id": "team_owner_project", "name": "Owner Project"},
        headers={
            "x-loamtrace-actor-id": "user_1",
            "x-loamtrace-actor-email": "user@example.test",
            "x-loamtrace-project-role": "owner",
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["id"] == "team_owner_project"


def test_create_project_api_remains_open_in_desktop_mode(tmp_workspace, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "SERVER_MODE", False)
    response = TestClient(main.app).post(
        "/api/projects",
        json={"project_id": "desktop_project", "name": "Desktop Project"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "desktop_project"


def test_health_reports_vector_backend():
    status = main.health()
    assert status["status"] == "ok"
    assert status["vector"]["backend"] in {"sqlite-vec", "json-fallback"}
    assert "sqlite_vec_available" in status["vector"]
    assert status["ocr"]["backend"] in {"tesseract", "unavailable"}
    assert "available" in status["ocr"]


def test_api_settings_save_hides_secret(tmp_workspace, monkeypatch):
    from loamtrace.models import ApiSettingsRequest
    from loamtrace.services import api_settings

    monkeypatch.setattr(api_settings, "SETTINGS_PATH", tmp_workspace / "api_settings.json")

    initial = main.api_get_api_settings()
    assert initial["api_key_configured"] is False

    saved = main.api_save_api_settings(
        ApiSettingsRequest(
            provider="openai-compatible",
            base_url="https://api.example.test/v1",
            model="model-test",
            api_key="secret-key",
        )
    )

    assert saved == {
        "provider": "openai-compatible",
        "base_url": "https://api.example.test/v1",
        "model": "model-test",
        "api_key_configured": True,
        "settings_path": str(tmp_workspace / "api_settings.json"),
    }
    assert "api_key" not in saved
    assert api_settings.get_configured_api_secret()["api_key"] == "secret-key"

    cleared = main.api_save_api_settings(ApiSettingsRequest(clear_api_key=True))
    assert cleared["api_key_configured"] is False
    assert "api_key" not in api_settings.get_configured_api_secret()


def test_api_settings_connection_test_validates_required_fields(tmp_workspace, monkeypatch):
    from loamtrace.models import ApiSettingsRequest
    from loamtrace.services import api_settings

    monkeypatch.setattr(api_settings, "SETTINGS_PATH", tmp_workspace / "api_settings.json")

    missing_base = main.api_test_api_settings(ApiSettingsRequest(api_key="secret"))
    assert missing_base["ok"] is False
    assert missing_base["status"] == "missing_base_url"
    assert "api_key" not in missing_base

    missing_key = main.api_test_api_settings(
        ApiSettingsRequest(provider="openai", base_url="https://api.example.test/v1")
    )
    assert missing_key["ok"] is False
    assert missing_key["status"] == "missing_api_key"
    assert "api_key" not in missing_key


def test_api_settings_connection_test_reports_success_without_exposing_key(tmp_workspace, monkeypatch):
    from loamtrace.models import ApiSettingsRequest
    from loamtrace.services import api_settings

    monkeypatch.setattr(api_settings, "SETTINGS_PATH", tmp_workspace / "api_settings.json")

    def fake_send(url, headers):
        assert url == "https://api.example.test/v1/models"
        assert headers["Authorization"] == "Bearer secret-key"
        return 200, b'{"data":[{"id":"model-a"},{"id":"model-b"}]}'

    monkeypatch.setattr(api_settings, "_send_test_request", fake_send)

    result = main.api_test_api_settings(
        ApiSettingsRequest(
            provider="openai-compatible",
            base_url="https://api.example.test/v1",
            model="model-b",
            api_key="secret-key",
        )
    )

    assert result["ok"] is True
    assert result["status"] == "connected"
    assert result["http_status"] == 200
    assert result["model_status"] == "found"
    assert result["available_models"] == ["model-a", "model-b"]
    assert result["checked_url"] == "https://api.example.test/v1/models"
    assert "api_key" not in result


def test_api_settings_connection_test_redacts_network_error_secrets(tmp_workspace, monkeypatch):
    from urllib.error import URLError

    from loamtrace.models import ApiSettingsRequest
    from loamtrace.services import api_settings

    monkeypatch.setattr(api_settings, "SETTINGS_PATH", tmp_workspace / "api_settings.json")

    def fake_send(url, _headers):
        raise URLError(f"failed {url}")

    monkeypatch.setattr(api_settings, "_send_test_request", fake_send)

    result = main.api_test_api_settings(
        ApiSettingsRequest(
            provider="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-test",
            api_key="secret/key",
        )
    )

    assert result["ok"] is False
    assert result["status"] == "network_error"
    assert result["checked_url"].endswith("/models?key=%2A%2A%2A")
    assert "secret/key" not in result["detail"]
    assert "secret%2Fkey" not in result["detail"]
    assert "key=***" in result["detail"]
