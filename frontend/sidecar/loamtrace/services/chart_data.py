from __future__ import annotations

import json
import re
import uuid
from typing import Optional

from loamtrace.db import connect
from loamtrace.services.audit import write_audit, write_run_artifacts
from loamtrace.services.paths import ensure_project, project_db_path


def generate_chart_data(
    project_id: str,
    table_id: str,
    label_column: int = 0,
    value_columns: Optional[list[int]] = None,
    chart_type: str = "line",
) -> dict:
    ensure_project(project_id)
    table, cells = _load_table_cells(project_id, table_id)
    grid = _cell_grid(cells)
    if len(grid) < 2:
        raise ValueError("table_has_no_data_rows")
    columns = sorted({col_index for row in grid.values() for col_index in row.keys()})
    max_col = max(columns, default=-1)
    if label_column > max_col:
        raise ValueError("label_column_out_of_range")
    label_column = _resolve_label_column(label_column, columns)

    header = grid[min(grid.keys())]
    selected_value_columns = value_columns if value_columns is not None else _default_value_columns(grid, label_column)
    if not selected_value_columns:
        raise ValueError("no_numeric_value_columns")

    series = []
    all_cell_ids = []
    for col_index in selected_value_columns:
        if col_index == label_column or col_index > max_col:
            continue
        points = []
        for row_index in sorted(index for index in grid.keys() if index != min(grid.keys())):
            row = grid[row_index]
            label_cell = row.get(label_column)
            value_cell = row.get(col_index)
            if not label_cell or not value_cell:
                continue
            value = _numeric_value(value_cell)
            if value is None:
                continue
            label = label_cell["text"] or label_cell["cell_ref"]
            points.append({"label": label, "value": value, "cell_id": value_cell["id"]})
            all_cell_ids.append(value_cell["id"])
        if points:
            name_cell = header.get(col_index)
            series.append({"name": name_cell["text"] if name_cell and name_cell["text"] else f"Column {col_index + 1}", "points": points})

    if not series:
        raise ValueError("no_chartable_values")
    data_source = {"table_id": table_id, "cell_ids": sorted(set(all_cell_ids))}
    chart = {
        "type": "chart",
        "chart_type": chart_type,
        "data_source": data_source,
        "series": series,
        "review_status": "verified",
    }
    run_id = f"run_{uuid.uuid4().hex}"
    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "generate_chart_data",
        {
            "input.json": {
                "project_id": project_id,
                "table_id": table_id,
                "label_column": label_column,
                "value_columns": value_columns,
                "chart_type": chart_type,
            },
            "table.json": table,
            "chart.json": chart,
        },
        logs=[{"type": "chart_data_generated", "table_id": table_id, "series_count": len(series)}],
    )
    write_audit(
        project_id,
        "chart_data_generated",
        {"run_id": run_id, "table_id": table_id, "series_count": len(series), "run_dir": str(run_dir)},
    )
    return {"run_id": run_id, "run_dir": str(run_dir), "chart": chart}


def _load_table_cells(project_id: str, table_id: str) -> tuple[dict, list[dict]]:
    with connect(project_db_path(project_id)) as conn:
        table = conn.execute("select * from tables where id = ?", (table_id,)).fetchone()
        if not table:
            raise KeyError("table_not_found")
        cells = conn.execute(
            """
            select * from cells
            where table_id = ?
            order by row_index asc, col_index asc
            """,
            (table_id,),
        ).fetchall()
    return dict(table), [dict(cell) for cell in cells]


def _cell_grid(cells: list[dict]) -> dict[int, dict[int, dict]]:
    grid: dict[int, dict[int, dict]] = {}
    for cell in cells:
        row_index = cell["row_index"] or 0
        col_index = cell["col_index"] or 0
        grid.setdefault(row_index, {})[col_index] = cell
    return grid


def _default_value_columns(grid: dict[int, dict[int, dict]], label_column: int) -> list[int]:
    header_index = min(grid.keys())
    columns = sorted({col_index for row in grid.values() for col_index in row.keys() if col_index != label_column})
    result = []
    for col_index in columns:
        if any(
            _numeric_value(row[col_index]) is not None
            for row_index, row in grid.items()
            if row_index != header_index and col_index in row
        ):
            result.append(col_index)
    return result


def _resolve_label_column(label_column: int, columns: list[int]) -> int:
    if label_column in columns or not columns:
        return label_column
    # Parser-created DOCX/PDF/XLSX tables are 1-based. Keep the public default
    # ergonomic by treating the default 0 as "first available column" when a
    # table does not actually contain column 0.
    if label_column == 0:
        return columns[0]
    return label_column


def _numeric_value(cell: dict) -> Optional[float]:
    raw = cell.get("value_json")
    if raw:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            for key in ["number", "value", "raw"]:
                number = _coerce_number(value.get(key))
                if number is not None:
                    return number
    return _coerce_number(cell.get("text"))


def _coerce_number(value) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    percent = text.endswith("%")
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0).replace(",", ""))
    return number / 100 if percent else number
