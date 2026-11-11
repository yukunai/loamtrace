import json
from pathlib import Path

from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.main import app
from loamtrace.models import SyncSettingsRequest
from loamtrace.services import sync_settings


def test_sync_settings_encrypts_secrets_and_hides_public_values(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(sync_settings, "SETTINGS_PATH", tmp_path / "sync_settings.json")
    monkeypatch.setattr(sync_settings, "KEY_PATH", tmp_path / "sync_settings.key")

    saved = sync_settings.save_sync_settings(
        SyncSettingsRequest(
            provider="s3-compatible",
            endpoint_url="https://example.r2.cloudflarestorage.com",
            bucket="loamtrace-private",
            region="auto",
            prefix="loamtrace-sync",
            access_key_id="access-secret",
            secret_access_key="secret-secret",
        )
    )

    assert saved["access_key_configured"] is True
    assert saved["secret_key_configured"] is True
    assert "access_key_id" not in saved
    assert "secret_access_key" not in saved

    raw = json.loads((tmp_path / "sync_settings.json").read_text(encoding="utf-8"))
    encoded = json.dumps(raw)
    assert "access-secret" not in encoded
    assert "secret-secret" not in encoded
    assert raw["secrets"]["access_key_id"]
    assert raw["secrets"]["secret_access_key"]
    assert (tmp_path / "sync_settings.key").exists()

    configured = sync_settings.get_configured_sync_secret()
    assert configured["access_key_id"] == "access-secret"
    assert configured["secret_access_key"] == "secret-secret"

    cleared = sync_settings.save_sync_settings(SyncSettingsRequest(clear_secret=True))
    assert cleared["access_key_configured"] is False
    assert cleared["secret_key_configured"] is False
    assert "secrets" not in json.loads((tmp_path / "sync_settings.json").read_text(encoding="utf-8"))


def test_sync_settings_test_local_and_s3_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_settings, "SETTINGS_PATH", tmp_path / "sync_settings.json")
    monkeypatch.setattr(sync_settings, "KEY_PATH", tmp_path / "sync_settings.key")

    local_target = tmp_path / "sync-target"
    local = sync_settings.test_sync_settings(SyncSettingsRequest(provider="local", target_dir=str(local_target)))
    assert local["ok"] is True
    assert local["status"] == "ready"
    assert Path(local["target_dir"]).exists()

    missing = sync_settings.test_sync_settings(
        SyncSettingsRequest(provider="s3-compatible", endpoint_url="https://r2.example", bucket="bucket")
    )
    assert missing["ok"] is False
    assert missing["status"] == "missing_required_fields"
    assert missing["missing_fields"] == ["access_key_id", "secret_access_key"]

    valid = sync_settings.test_sync_settings(
        SyncSettingsRequest(
            provider="s3-compatible",
            endpoint_url="https://r2.example",
            bucket="bucket",
            access_key_id="access",
            secret_access_key="secret",
        )
    )
    assert valid["ok"] is True
    assert valid["status"] == "configuration_valid"


def test_sync_settings_api_does_not_expose_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_settings, "SETTINGS_PATH", tmp_path / "sync_settings.json")
    monkeypatch.setattr(sync_settings, "KEY_PATH", tmp_path / "sync_settings.key")
    client = TestClient(app)

    saved = client.put(
        "/api/sync/settings",
        json={
            "provider": "s3-compatible",
            "endpoint_url": "https://r2.example",
            "bucket": "bucket",
            "access_key_id": "access",
            "secret_access_key": "secret",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["access_key_configured"] is True
    assert '"secret"' not in json.dumps(saved.json())
    assert '"access"' not in json.dumps(saved.json())

    fetched = client.get("/api/sync/settings")
    assert fetched.status_code == 200
    assert fetched.json()["secret_key_configured"] is True
    assert "access_key_id" not in fetched.json()
    assert "secret_access_key" not in fetched.json()


def test_configured_sync_provider_live_check_success(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_settings, "SETTINGS_PATH", tmp_path / "sync_settings.json")
    monkeypatch.setattr(sync_settings, "KEY_PATH", tmp_path / "sync_settings.key")
    sync_settings.save_sync_settings(
        SyncSettingsRequest(
            provider="s3-compatible",
            endpoint_url="https://r2.example",
            bucket="bucket",
            access_key_id="access",
            secret_access_key="secret",
        )
    )

    from loamtrace.services import sync_providers

    class FakeProvider:
        def list_snapshots(self, project_id=None):
            assert project_id == "p1"
            return [{"snapshot_id": "snap_1"}]

    monkeypatch.setattr(sync_providers, "configured_sync_provider", lambda: FakeProvider())

    result = sync_settings.test_configured_sync_provider_live("p1")

    assert result["ok"] is True
    assert result["status"] == "live_ready"
    assert "1 snapshot" in result["detail"]


def test_configured_sync_provider_live_check_redacts_secret_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_settings, "SETTINGS_PATH", tmp_path / "sync_settings.json")
    monkeypatch.setattr(sync_settings, "KEY_PATH", tmp_path / "sync_settings.key")
    sync_settings.save_sync_settings(
        SyncSettingsRequest(
            provider="s3-compatible",
            endpoint_url="https://r2.example",
            bucket="bucket",
            access_key_id="access-secret",
            secret_access_key="secret-secret",
        )
    )

    from loamtrace.services import sync_providers

    class FailingProvider:
        def list_snapshots(self, project_id=None):
            raise ValueError("bad access-secret and secret-secret")

    monkeypatch.setattr(sync_providers, "configured_sync_provider", lambda: FailingProvider())

    result = sync_settings.test_configured_sync_provider_live()

    assert result["ok"] is False
    assert result["status"] == "live_check_failed"
    assert "access-secret" not in result["detail"]
    assert "secret-secret" not in result["detail"]
    assert result["detail"].count("[redacted]") == 2


def test_sync_provider_live_check_api_reports_missing_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_settings, "SETTINGS_PATH", tmp_path / "sync_settings.json")
    monkeypatch.setattr(sync_settings, "KEY_PATH", tmp_path / "sync_settings.key")
    client = TestClient(app)

    saved = client.put(
        "/api/sync/settings",
        json={"provider": "s3-compatible", "endpoint_url": "https://r2.example", "bucket": "bucket"},
    )
    assert saved.status_code == 200

    result = client.post("/api/sync/provider/test-live")

    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["status"] == "missing_required_fields"
