import json

from fastapi.testclient import TestClient

from loamtrace.db import connect
from loamtrace.services.paths import project_db_path


def test_sync_apis_enforce_server_mode_route_guards(tmp_path, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    _patch_sync_handlers(main, monkeypatch)

    project_id = "sync_guard"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    for route, payload in _payloads(project_id):
        denied = client.post(route, json=payload, headers=headers)
        assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    for route, payload in _export_payloads(project_id):
        allowed = client.post(route, json=payload, headers=headers)
        assert allowed.status_code == 200

    for route, payload in _admin_delete_payloads(project_id):
        denied = client.post(route, json=payload, headers=headers)
        assert denied.status_code == 403

    set_project_acl(project_id, "user", "user_1", "owner")
    for route, payload in _admin_delete_payloads(project_id):
        allowed = client.post(route, json=payload, headers=headers)
        assert allowed.status_code == 200

    payloads = _route_guard_payloads(project_id)
    assert [payload["permission"] for payload in payloads] == [
        "export",
        "export",
        "admin",
        "delete",
        "admin",
        "delete",
        "export",
        "export",
        "admin",
        "delete",
        "admin",
        "delete",
        "admin",
        "delete",
        "admin",
        "delete",
    ]
    assert [payload["would_block"] for payload in payloads] == [
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    ]


def test_sync_guards_allow_legacy_project_without_owner_acl(tmp_path, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    _patch_sync_handlers(main, monkeypatch)

    project_id = "sync_guard_legacy"
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    for route, payload in _payloads(project_id):
        response = client.post(route, json=payload, headers=headers)
        assert response.status_code == 200


def _patch_sync_handlers(main, monkeypatch) -> None:
    monkeypatch.setattr(main, "push_project_snapshot", lambda project_id, target_dir, include_index=True: {"route": "local_push"})
    monkeypatch.setattr(
        main,
        "resolve_pull_project_snapshot_target",
        lambda target_dir, snapshot_id, project_id=None: project_id or "sync_guard",
    )
    monkeypatch.setattr(
        main,
        "pull_project_snapshot",
        lambda target_dir, snapshot_id, project_id=None, overwrite=False: {"route": "local_pull"},
    )
    monkeypatch.setattr(
        main,
        "resolve_delete_synced_snapshot_project",
        lambda target_dir, snapshot_id: "sync_guard" if "legacy" not in target_dir else "sync_guard_legacy",
    )
    monkeypatch.setattr(main, "delete_synced_snapshot", lambda target_dir, snapshot_id: {"route": "local_delete"})
    monkeypatch.setattr(
        main,
        "push_project_snapshot_to_configured_provider",
        lambda project_id, include_index=True: {"route": "provider_push"},
    )
    monkeypatch.setattr(
        main,
        "resolve_provider_pull_project_snapshot_target",
        lambda snapshot_id, project_id=None: project_id or "sync_guard",
    )
    monkeypatch.setattr(
        main,
        "pull_project_snapshot_from_configured_provider",
        lambda snapshot_id, project_id=None, overwrite=False: {"route": "provider_pull"},
    )
    monkeypatch.setattr(
        main,
        "resolve_provider_delete_synced_snapshot_project",
        lambda snapshot_id: "sync_guard_legacy" if "legacy" in snapshot_id else "sync_guard",
    )
    monkeypatch.setattr(main, "delete_provider_synced_snapshot", lambda snapshot_id: {"route": "provider_delete"})


def _payloads(project_id: str) -> list[tuple[str, dict]]:
    return _export_payloads(project_id) + _admin_delete_payloads(project_id)


def _export_payloads(project_id: str) -> list[tuple[str, dict]]:
    return [
        ("/api/sync/push-snapshot", {"project_id": project_id, "target_dir": f"/tmp/{project_id}", "include_index": True}),
        ("/api/sync/provider/push-snapshot", {"project_id": project_id, "include_index": True}),
    ]


def _admin_delete_payloads(project_id: str) -> list[tuple[str, dict]]:
    return [
        (
            "/api/sync/pull-snapshot",
            {"target_dir": f"/tmp/{project_id}", "snapshot_id": "snapshot_1", "project_id": project_id},
        ),
        ("/api/sync/delete-snapshot", {"target_dir": f"/tmp/{project_id}", "snapshot_id": "snapshot_1"}),
        ("/api/sync/provider/pull-snapshot", {"snapshot_id": "snapshot_1", "project_id": project_id}),
        ("/api/sync/provider/delete-snapshot", {"snapshot_id": f"snapshot_{project_id}"}),
    ]


def _route_guard_payloads(project_id: str) -> list[dict]:
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]
