import json

from fastapi.testclient import TestClient

from loamtrace.db import connect
from loamtrace.services.paths import project_db_path


EXPORT_ROUTE_PAYLOADS = [
    ("/api/slides/generate", {"project_id": "PROJECT", "title": "Deck", "claim_ids": []}),
    (
        "/api/slides/from-template",
        {"project_id": "PROJECT", "template_id": "risk_review", "title": "Deck", "claim_ids": []},
    ),
    (
        "/api/slides/chart-deck",
        {
            "project_id": "PROJECT",
            "title": "Chart Deck",
            "chart": {"type": "chart", "chart_type": "line", "series": []},
        },
    ),
    ("/api/slides/table-deck", {"project_id": "PROJECT", "table_id": "table_1", "title": "Table Deck"}),
    ("/api/export/pptx", {"project_id": "PROJECT", "deck_id": "deck_1"}),
    ("/api/export/research-package", {"project_id": "PROJECT", "deck_id": "deck_1"}),
]


def test_export_apis_enforce_server_mode_export_guard(tmp_path, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    _patch_export_handlers(main, monkeypatch)

    project_id = "export_guard"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    for route, payload in _payloads(project_id):
        denied = client.post(route, json=payload, headers=headers)
        assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "editor")
    for route, payload in _payloads(project_id):
        allowed = client.post(route, json=payload, headers=headers)
        assert allowed.status_code == 200
        assert allowed.json()["route"] == route

    payloads = _route_guard_payloads(project_id)
    expected_routes = [route_label(route) for route, _payload in _payloads(project_id)]
    assert [payload["route"] for payload in payloads] == expected_routes + expected_routes
    assert [payload["would_block"] for payload in payloads] == [True] * 6 + [False] * 6
    assert {payload["permission"] for payload in payloads} == {"export"}


def test_export_guards_allow_legacy_project_without_owner_acl(tmp_path, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)
    _patch_export_handlers(main, monkeypatch)

    project_id = "export_guard_legacy"
    client = TestClient(main.app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    for route, payload in _payloads(project_id):
        response = client.post(route, json=payload, headers=headers)
        assert response.status_code == 200


def _patch_export_handlers(main, monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "generate_slide_deck",
        lambda project_id, title, claim_ids=None: _fake_response("/api/slides/generate"),
    )
    monkeypatch.setattr(
        main,
        "generate_template_slide_deck",
        lambda project_id, template_id, title, claim_ids=None: _fake_response("/api/slides/from-template"),
    )
    monkeypatch.setattr(
        main,
        "generate_chart_deck",
        lambda project_id, title, chart: _fake_response("/api/slides/chart-deck"),
    )
    monkeypatch.setattr(
        main,
        "generate_table_deck",
        lambda project_id, table_id, title=None, max_rows=8, max_cols=6: _fake_response("/api/slides/table-deck"),
    )
    monkeypatch.setattr(main, "export_pptx", lambda project_id, deck_id: _fake_response("/api/export/pptx"))
    monkeypatch.setattr(
        main,
        "export_research_package",
        lambda project_id, deck_id=None: _fake_response("/api/export/research-package"),
    )


def _fake_response(route: str) -> dict:
    return {"route": route, "ok": True}


def _payloads(project_id: str) -> list[tuple[str, dict]]:
    return [
        (route, {key: project_id if value == "PROJECT" else value for key, value in payload.items()})
        for route, payload in EXPORT_ROUTE_PAYLOADS
    ]


def route_label(route: str) -> str:
    return f"POST {route}"


def _route_guard_payloads(project_id: str) -> list[dict]:
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            "select payload_json from audit_log where type = ? order by ts asc",
            ("route_guard_dry_run",),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]
