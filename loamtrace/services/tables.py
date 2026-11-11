from __future__ import annotations

import json
from typing import Optional

from loamtrace.db import connect
from loamtrace.services.paths import ensure_project, project_db_path


def list_tables(project_id: str, document_id: Optional[str] = None) -> list[dict]:
    ensure_project(project_id)
    params: list[str] = []
    where = ""
    if document_id:
        where = "where t.document_id = ?"
        params.append(document_id)

    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            f"""
            select
              t.id,
              t.document_id,
              t.page_id,
              t.bbox_json,
              t.caption,
              t.parser,
              d.filename as document_filename,
              d.mime_type as document_mime_type,
              count(c.id) as cell_count,
              count(distinct c.row_index) as row_count,
              count(distinct c.col_index) as col_count,
              min(c.sheet_name) as sheet_name
            from tables t
            left join documents d on d.id = t.document_id
            left join cells c on c.table_id = t.id
            {where}
            group by t.id
            order by d.filename asc, t.caption asc, t.id asc
            """,
            params,
        ).fetchall()
        previews = _table_previews(conn, [row["id"] for row in rows])

    result = []
    for row in rows:
        item = dict(row)
        item["bbox_json"] = _parse_json(item.get("bbox_json"))
        item["preview"] = previews.get(item["id"], [])
        result.append(item)
    return result


def _table_previews(conn, table_ids: list[str]) -> dict[str, list[list[str]]]:
    if not table_ids:
        return {}
    placeholders = ",".join("?" for _ in table_ids)
    rows = conn.execute(
        f"""
        select table_id, row_index, col_index, text
        from cells
        where table_id in ({placeholders})
        order by table_id asc, row_index asc, col_index asc
        """,
        table_ids,
    ).fetchall()
    grouped: dict[str, dict[int, dict[int, str]]] = {}
    for row in rows:
        table_id = row["table_id"]
        row_index = row["row_index"] or 0
        col_index = row["col_index"] or 0
        grouped.setdefault(table_id, {}).setdefault(row_index, {})[col_index] = row["text"] or ""

    previews: dict[str, list[list[str]]] = {}
    for table_id, grid in grouped.items():
        columns = sorted({col_index for row in grid.values() for col_index in row.keys()})
        table_preview = []
        for row_index in sorted(grid.keys())[:4]:
            row = grid[row_index]
            table_preview.append([row.get(col_index, "") for col_index in columns[:5]])
        previews[table_id] = table_preview
    return previews


def _parse_json(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
