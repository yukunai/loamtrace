import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import parse

from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.main import app
from loamtrace.models import SyncSettingsRequest
from loamtrace.services import sync_settings
from loamtrace.services.paths import ensure_project, project_root


class _S3MockHandler(BaseHTTPRequestHandler):
    objects: dict[str, bytes] = {}
    requests_seen: list[dict] = []

    def do_PUT(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        key = self.path.split("?", 1)[0].lstrip("/")
        self.objects[key] = body
        self.requests_seen.append({"method": "PUT", "path": self.path, "auth": self.headers.get("Authorization")})
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = parse.urlsplit(self.path)
        query = parse.parse_qs(parsed.query)
        key = parsed.path.lstrip("/")
        self.requests_seen.append({"method": "GET", "path": self.path, "auth": self.headers.get("Authorization")})
        if query.get("list-type") == ["2"]:
            prefix = query.get("prefix", [""])[0]
            keys = [item for item in sorted(self.objects) if item.startswith(f"bucket/{prefix}")]
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                + "".join(f"<Contents><Key>{item.removeprefix('bucket/')}</Key></Contents>" for item in keys)
                + "</ListBucketResult>"
            ).encode("utf-8")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
            return
        if key not in self.objects:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(self.objects[key])

    def do_DELETE(self):
        key = self.path.split("?", 1)[0].lstrip("/")
        self.requests_seen.append({"method": "DELETE", "path": self.path, "auth": self.headers.get("Authorization")})
        if key in self.objects:
            del self.objects[key]
            self.send_response(204)
        else:
            self.send_response(404)
        self.end_headers()

    def log_message(self, *_args):
        return


def test_provider_sync_s3_compatible_push_list_pull(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "workspace" / "projects")
    monkeypatch.setattr(sync_settings, "SETTINGS_PATH", tmp_path / "sync_settings.json")
    monkeypatch.setattr(sync_settings, "KEY_PATH", tmp_path / "sync_settings.key")
    _S3MockHandler.objects = {}
    _S3MockHandler.requests_seen = []
    server = HTTPServer(("127.0.0.1", 0), _S3MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        sync_settings.save_sync_settings(
            SyncSettingsRequest(
                provider="s3-compatible",
                endpoint_url=endpoint,
                bucket="bucket",
                region="auto",
                prefix="loamtrace-sync",
                access_key_id="access",
                secret_access_key="secret",
            )
        )
        project_id = "s3_provider_source"
        ensure_project(project_id, "S3 Provider Source")
        (project_root(project_id) / "notes" / "memo.md").write_text("# S3 Sync\n", encoding="utf-8")
        client = TestClient(app)

        pushed = client.post(
            "/api/sync/provider/push-snapshot",
            json={"project_id": project_id, "include_index": True},
        )
        assert pushed.status_code == 200
        snapshot_id = pushed.json()["snapshot_id"]
        assert pushed.json()["archive_path"].startswith("s3://bucket/loamtrace-sync/snapshots/")
        assert "/../" not in pushed.json()["archive_path"]
        assert any(item["auth"] and item["auth"].startswith("AWS4-HMAC-SHA256") for item in _S3MockHandler.requests_seen)

        listed = client.get("/api/sync/provider/snapshots", params={"project_id": project_id})
        assert listed.status_code == 200
        assert [item["snapshot_id"] for item in listed.json()] == [snapshot_id]
        assert listed.json()[0]["object_key"].endswith(f"{snapshot_id}.zip")
        assert listed.json()[0]["archive_sha256"] == pushed.json()["archive_sha256"]
        assert listed.json()[0]["integrity_status"] == "unchecked"

        pulled = client.post(
            "/api/sync/provider/pull-snapshot",
            json={"snapshot_id": snapshot_id, "project_id": "s3_provider_restored"},
        )
        assert pulled.status_code == 200
        restored_root = project_root("s3_provider_restored")
        assert (restored_root / "notes" / "memo.md").read_text(encoding="utf-8") == "# S3 Sync\n"

        metadata_keys = [key for key in _S3MockHandler.objects if key.endswith(".json")]
        assert metadata_keys
        metadata = json.loads(_S3MockHandler.objects[metadata_keys[0]].decode("utf-8"))
        assert metadata["snapshot_id"] == snapshot_id
        assert metadata["metadata_path"].startswith("s3://bucket/")
        assert metadata["archive_sha256"] == pushed.json()["archive_sha256"]

        zip_key = f"bucket/{metadata['object_key']}"
        original_zip = _S3MockHandler.objects[zip_key]
        _S3MockHandler.objects[zip_key] = b"0" * len(original_zip)
        tampered = client.post(
            "/api/sync/provider/pull-snapshot",
            json={"snapshot_id": snapshot_id, "project_id": "s3_provider_tampered"},
        )
        assert tampered.status_code == 400
        assert tampered.json()["detail"] == "synced_snapshot_checksum_mismatch"

        _S3MockHandler.objects[zip_key] = original_zip
        deleted = client.post(
            "/api/sync/provider/delete-snapshot",
            json={"snapshot_id": snapshot_id},
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert any(item["method"] == "DELETE" and item["auth"] for item in _S3MockHandler.requests_seen)
        assert not any(key.endswith(f"{snapshot_id}.zip") or key.endswith(f"{snapshot_id}.json") for key in _S3MockHandler.objects)

        missing_delete = client.post(
            "/api/sync/provider/delete-snapshot",
            json={"snapshot_id": snapshot_id},
        )
        assert missing_delete.status_code == 404
        assert missing_delete.json()["detail"] == "synced_snapshot_not_found"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_provider_sync_requires_configured_s3_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "workspace" / "projects")
    monkeypatch.setattr(sync_settings, "SETTINGS_PATH", tmp_path / "sync_settings.json")
    monkeypatch.setattr(sync_settings, "KEY_PATH", tmp_path / "sync_settings.key")
    sync_settings.save_sync_settings(
        SyncSettingsRequest(provider="s3-compatible", endpoint_url="http://127.0.0.1:9", bucket="bucket")
    )
    ensure_project("s3_missing_secret")

    response = TestClient(app).post(
        "/api/sync/provider/push-snapshot",
        json={"project_id": "s3_missing_secret", "include_index": True},
    )

    assert response.status_code == 400
    assert "sync_provider_missing_required" in response.json()["detail"]
