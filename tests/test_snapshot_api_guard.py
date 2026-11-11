import json

from fastapi.testclient import TestClient

from loamtrace.db import connect
from loamtrace.services.paths import project_db_path


def test_snapshot_apis_enforce_server_mode_export_and_admin_guards(tmp_path, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    monkeypatch.setattr(main, "export_project_snapshot", lambda project_id, include_index=True: {"route": "export", "ok": True})
    monkeypatch.setattr(
        main,
        "resolve_import_project_snapshot_target",
        lambda archive_path, project_id=None: project_id or "snapshot_guard",
    )
    monkeypatch.setattr(
        main,
        "import_project_snapshot",
        lambda archive_path, project_id=None, overwrite=False: {"route": "import", "ok": True},
    )

    project_id = "snapshot_guard"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    export_denied = client.post(
        "/api/export/project-snapshot",
        json={"project_id": project_id, "include_index": True},
        headers=headers,
    )
    import_denied = client.post(
        "/api/import/project-snapshot",
        json={"archive_path": "/tmp/snapshot.zip", "project_id": project_id, "overwrite": True},
        headers=headers,
    )
    assert export_denied.status_code == 403
    assert import_denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    export_allowed = client.post(
        "/api/export/project-snapshot",
        json={"project_id": project_id, "include_index": True},
        headers=headers,
    )
    assert export_allowed.status_code == 200

    import_editor_denied = client.post(
        "/api/import/project-snapshot",
        json={"archive_path": "/tmp/snapshot.zip", "project_id": project_id, "overwrite": True},
        headers=headers,
    )
    assert import_editor_denied.status_code == 403

    set_project_acl(project_id, "user", "user_1", "owner")
    import_owner_allowed = client.post(
        "/api/import/project-snapshot",
        json={"archive_path": "/tmp/snapshot.zip", "project_id": project_id, "overwrite": True},
        headers=headers,
    )
    assert import_owner_allowed.status_code == 200

    payloads = _route_guard_payloads(project_id)
    assert [payload["route"] for payload in payloads] == [
        "POST /api/export/project-snapshot",
        "POST /api/import/project-snapshot",
        "POST /api/export/project-snapshot",
        "POST /api/import/project-snapshot",
        "POST /api/import/project-snapshot",
    ]
    assert [payload["permission"] for payload in payloads] == ["export", "admin", "export", "admin", "admin"]
    assert [payload["would_block"] for payload in payloads] == [True, True, False, True, False]


def test_snapshot_guards_allow_legacy_project_without_owner_acl(tmp_path, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    monkeypatch.setattr(main, "export_project_snapshot", lambda project_id, include_index=True: {"route": "export", "ok": True})
    monkeypatch.setattr(
        main,
        "resolve_import_project_snapshot_target",
        lambda archive_path, project_id=None: project_id or "snapshot_guard_legacy",
    )
    monkeypatch.setattr(
        main,
        "import_project_snapshot",
        lambda archive_path, project_id=None, overwrite=False: {"route": "import", "ok": True},
    )

    project_id = "snapshot_guard_legacy"
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    exported = client.post(
        "/api/export/project-snapshot",
        json={"project_id": project_id, "include_index": True},
        headers=headers,
    )
    imported = client.post(
        "/api/import/project-snapshot",
        json={"archive_path": "/tmp/snapshot.zip", "project_id": project_id, "overwrite": True},
        headers=headers,
    )

    assert exported.status_code == 200
    assert imported.status_code == 200


def _route_guard_payloads(project_id: str) -> list[dict]:
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]
