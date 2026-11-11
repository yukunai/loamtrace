import json

from fastapi.testclient import TestClient

from loamtrace import config
from loamtrace.db import connect
from loamtrace.main import app
from loamtrace.services.chunk_store import insert_chunk
from loamtrace.services.paths import ensure_project, project_db_path, project_root


def test_search_api_writes_run_artifacts_and_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "api_search"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        insert_chunk(
            conn,
            {
                "id": "chunk_revenue",
                "document_id": "doc_1",
                "chunk_type": "text",
                "text": "Revenue increased by 24% year over year in 2025.",
                "token_count": 8,
                "source_uri": "pdf://doc_1#page=1",
                "word_ids_json": "[]",
                "cell_ids_json": None,
                "bbox_json": None,
            },
        )

    response = TestClient(app).post(
        "/api/search",
        json={"project_id": project_id, "query": "Revenue 2025", "top_n": 5},
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == "chunk_revenue"
    runs_root = project_root(project_id) / "runs"
    run_dirs = [path for path in runs_root.iterdir() if path.is_dir() and "_search_" in path.name]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert json.loads((run_dir / "input.json").read_text(encoding="utf-8"))["query"] == "Revenue 2025"
    assert json.loads((run_dir / "results.json").read_text(encoding="utf-8"))[0]["id"] == "chunk_revenue"
    assert "search_completed" in (run_dir / "logs.jsonl").read_text(encoding="utf-8")
    assert "search_completed" in (runs_root / "decision_log.jsonl").read_text(encoding="utf-8")
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute("select * from audit_log where type = ?", ("search_completed",)).fetchone()
    assert row is not None


def test_search_api_accepts_custom_retrieval_parameters(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "api_search_custom"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        insert_chunk(
            conn,
            {
                "id": "chunk_revenue",
                "document_id": "doc_1",
                "chunk_type": "text",
                "text": "Revenue increased by 24% year over year in 2025.",
                "token_count": 8,
                "source_uri": "pdf://doc_1#page=1",
                "word_ids_json": "[]",
                "cell_ids_json": None,
                "bbox_json": None,
            },
        )

    response = TestClient(app).post(
        "/api/search",
        json={
            "project_id": project_id,
            "query": "Revenue 2025",
            "top_n": 5,
            "rrf_k": 30,
            "fts_top_n": 7,
            "vector_top_n": 9,
            "keyword_boost": 2.0,
            "vector_boost": 0.5,
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == "chunk_revenue"
    runs_root = project_root(project_id) / "runs"
    run_dir = next(path for path in runs_root.iterdir() if path.is_dir() and "_search_" in path.name)
    input_json = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
    assert input_json["rrf_k"] == 30
    assert input_json["fts_top_n"] == 7
    assert input_json["vector_top_n"] == 9
    assert input_json["keyword_boost"] == 2.0
    assert input_json["vector_boost"] == 0.5


def test_search_api_uses_project_retrieval_preferences_when_request_omits_params(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "api_search_project_prefs"
    ensure_project(project_id)
    client = TestClient(app)
    with connect(project_db_path(project_id)) as conn:
        insert_chunk(
            conn,
            {
                "id": "chunk_revenue",
                "document_id": "doc_1",
                "chunk_type": "text",
                "text": "Revenue increased by 24% year over year in 2025.",
                "token_count": 8,
                "source_uri": "pdf://doc_1#page=1",
                "word_ids_json": "[]",
                "cell_ids_json": None,
                "bbox_json": None,
            },
        )

    saved = client.put(
        f"/api/projects/{project_id}/retrieval-preferences",
        json={
            "top_n": 4,
            "rrf_k": 42,
            "fts_top_n": 8,
            "vector_top_n": 9,
            "keyword_boost": 1.6,
            "vector_boost": 0.4,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["rrf_k"] == 42

    fetched = client.get(f"/api/projects/{project_id}/retrieval-preferences")
    assert fetched.status_code == 200
    assert fetched.json()["keyword_boost"] == 1.6

    response = client.post(
        "/api/search",
        json={"project_id": project_id, "query": "Revenue 2025"},
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == "chunk_revenue"
    runs_root = project_root(project_id) / "runs"
    run_dir = next(path for path in runs_root.iterdir() if path.is_dir() and "_search_" in path.name)
    input_json = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
    assert input_json["top_n"] == 4
    assert input_json["rrf_k"] == 42
    assert input_json["fts_top_n"] == 8
    assert input_json["vector_top_n"] == 9
    assert input_json["keyword_boost"] == 1.6
    assert input_json["vector_boost"] == 0.4


def test_search_api_enforces_server_mode_read_guard(tmp_path, monkeypatch):
    from loamtrace import main
    from loamtrace.services.team_admin import bootstrap_local_admin, set_project_acl, upsert_user

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "api_search_guard"
    bootstrap_local_admin(project_id, "owner@example.test", "Owner")
    client = TestClient(app)
    headers = {"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"}

    denied = client.post("/api/search", json={"project_id": project_id, "query": "Revenue"}, headers=headers)
    assert denied.status_code == 403

    upsert_user(project_id, "user_1", "user@example.test", "User One")
    set_project_acl(project_id, "user", "user_1", "viewer")
    allowed = client.post("/api/search", json={"project_id": project_id, "query": "Revenue"}, headers=headers)
    assert allowed.status_code == 200
    assert allowed.json() == []


def test_search_guard_allows_legacy_project_without_owner_acl(tmp_path, monkeypatch):
    from loamtrace import main

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(main.loamtrace.config, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(main.loamtrace.config, "SERVER_MODE", True)

    project_id = "api_search_legacy"
    ensure_project(project_id)
    response = TestClient(app).post(
        "/api/search",
        json={"project_id": project_id, "query": "Revenue"},
        headers={"x-loamtrace-actor-id": "user_1", "x-loamtrace-actor-email": "user@example.test"},
    )
    assert response.status_code == 200
    assert response.json() == []
