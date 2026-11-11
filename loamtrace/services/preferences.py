from __future__ import annotations

import json

from loamtrace.db import connect
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.time import now_iso

DEFAULT_COLUMN_WIDTHS = {"sidebar": 230, "memo": 380, "viewer": 560}


def get_ui_preferences(project_id: str) -> dict:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute(
            "select column_widths_json, updated_at from ui_preferences where project_id = ?",
            (project_id,),
        ).fetchone()
    if not row:
        return {
            "project_id": project_id,
            "column_widths": dict(DEFAULT_COLUMN_WIDTHS),
            "updated_at": None,
        }
    return {
        "project_id": project_id,
        "column_widths": {**DEFAULT_COLUMN_WIDTHS, **json.loads(row["column_widths_json"])},
        "updated_at": row["updated_at"],
    }


def save_ui_preferences(project_id: str, column_widths: dict) -> dict:
    ensure_project(project_id)
    normalized = {key: int(column_widths[key]) for key in DEFAULT_COLUMN_WIDTHS}
    updated_at = now_iso()
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into ui_preferences(project_id, column_widths_json, updated_at)
            values (?, ?, ?)
            on conflict(project_id) do update set
              column_widths_json = excluded.column_widths_json,
              updated_at = excluded.updated_at
            """,
            (project_id, json.dumps(normalized), updated_at),
        )
    return {
        "project_id": project_id,
        "column_widths": normalized,
        "updated_at": updated_at,
    }
