from __future__ import annotations

import json

from loamtrace.db import connect
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.time import now_iso

DEFAULT_RETRIEVAL_PREFERENCES = {
    "top_n": 12,
    "rrf_k": 60,
    "fts_top_n": 50,
    "vector_top_n": 50,
    "keyword_boost": 1.0,
    "vector_boost": 1.0,
}


def get_retrieval_preferences(project_id: str) -> dict:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute(
            "select preferences_json, updated_at from retrieval_preferences where project_id = ?",
            (project_id,),
        ).fetchone()
    if not row:
        return {
            "project_id": project_id,
            **dict(DEFAULT_RETRIEVAL_PREFERENCES),
            "updated_at": None,
        }
    return {
        "project_id": project_id,
        **{**DEFAULT_RETRIEVAL_PREFERENCES, **json.loads(row["preferences_json"])},
        "updated_at": row["updated_at"],
    }


def save_retrieval_preferences(project_id: str, preferences: dict) -> dict:
    ensure_project(project_id)
    normalized = {
        "top_n": int(preferences["top_n"]),
        "rrf_k": int(preferences["rrf_k"]),
        "fts_top_n": int(preferences["fts_top_n"]),
        "vector_top_n": int(preferences["vector_top_n"]),
        "keyword_boost": float(preferences["keyword_boost"]),
        "vector_boost": float(preferences["vector_boost"]),
    }
    updated_at = now_iso()
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into retrieval_preferences(project_id, preferences_json, updated_at)
            values (?, ?, ?)
            on conflict(project_id) do update set
              preferences_json = excluded.preferences_json,
              updated_at = excluded.updated_at
            """,
            (project_id, json.dumps(normalized), updated_at),
        )
    return {
        "project_id": project_id,
        **normalized,
        "updated_at": updated_at,
    }
