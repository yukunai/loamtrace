from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from loamtrace.db import connect
from loamtrace.services.paths import ensure_project, project_db_path


def resolve_citation_target(project_id: str, citation_id: str) -> dict:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute(
            """
            select
              c.*,
              cl.project_id,
              cl.claim_text,
              cl.status as claim_status,
              d.filename,
              d.mime_type,
              d.ocr_used,
              d.ocr_confidence
            from citations c
            join claims cl on cl.id = c.claim_id
            left join documents d on d.id = c.document_id
            where cl.project_id = ? and c.id = ?
            """,
            (project_id, citation_id),
        ).fetchone()
        if not row:
            raise KeyError("citation_not_found")
        citation = dict(row)
        chunk = conn.execute("select * from chunks where id = ?", (citation["chunk_id"],)).fetchone()

    parsed = _parse_source_uri(citation["source_uri"])
    if parsed["document_id"] and citation["document_id"] and parsed["document_id"] != citation["document_id"]:
        raise ValueError("source_uri_document_mismatch")

    bbox = _loads_json(citation.get("bbox_json")) or _loads_json(chunk["bbox_json"] if chunk else None)
    locator = parsed["locator"]
    target = {
        "citation_id": citation["id"],
        "claim_id": citation["claim_id"],
        "claim_status": citation["claim_status"],
        "claim_text": citation["claim_text"],
        "document_id": citation["document_id"] or parsed["document_id"],
        "filename": citation.get("filename"),
        "mime_type": citation.get("mime_type"),
        "ocr_used": bool(citation.get("ocr_used")) if citation.get("ocr_used") is not None else False,
        "ocr_confidence": citation.get("ocr_confidence"),
        "source_uri": citation["source_uri"],
        "quote": citation["quote"],
        "scheme": parsed["scheme"],
        "locator": locator,
        "bbox": bbox,
        "precision": _precision(parsed["scheme"], locator, bbox),
        "renderable": parsed["scheme"] == "pdf" and _int(locator.get("page")) is not None,
        "location_label": _location_label(parsed["scheme"], locator),
        "chunk": _chunk_summary(dict(chunk)) if chunk else None,
    }
    target.update(_load_structured_target(project_id, target["document_id"], parsed["scheme"], locator))
    return target


def _parse_source_uri(source_uri: str) -> dict:
    parsed = urlparse(source_uri)
    if parsed.scheme not in {"pdf", "docx", "xlsx", "md", "html", "text"} or not parsed.netloc:
        raise ValueError("source_uri_invalid")
    raw_params = parse_qs(parsed.fragment, keep_blank_values=False)
    locator = {key: values[-1] for key, values in raw_params.items() if values}
    return {"scheme": parsed.scheme, "document_id": parsed.netloc, "locator": locator}


def _load_structured_target(project_id: str, document_id: str, scheme: str, locator: dict) -> dict:
    if scheme == "pdf":
        return _load_pdf_target(project_id, document_id, locator)
    if scheme == "docx":
        return _load_docx_target(project_id, document_id, locator)
    if scheme == "xlsx":
        return _load_xlsx_target(project_id, document_id, locator)
    if scheme in {"md", "html", "text"}:
        return _load_text_target(project_id, document_id, locator)
    return {}


def _load_pdf_target(project_id: str, document_id: str, locator: dict) -> dict:
    page_number = _int(locator.get("page"))
    if page_number is None:
        return {}
    with connect(project_db_path(project_id)) as conn:
        page = conn.execute(
            """
            select id, page_number, width, height, render_path, text_layer_available
            from pages
            where document_id = ? and page_number = ?
            """,
            (document_id, page_number),
        ).fetchone()
        table = None
        if locator.get("table"):
            table = conn.execute("select * from tables where document_id = ? and id = ?", (document_id, locator["table"])).fetchone()
    result = {"page": dict(page) if page else {"page_number": page_number}}
    if table:
        result["table"] = dict(table)
    return result


def _load_docx_target(project_id: str, document_id: str, locator: dict) -> dict:
    paragraph = _int(locator.get("paragraph"))
    table_index = _int(locator.get("table"))
    with connect(project_db_path(project_id)) as conn:
        if paragraph is not None:
            block = conn.execute(
                """
                select id, block_type, text, reading_order, heading_path
                from blocks
                where document_id = ? and reading_order = ?
                """,
                (document_id, paragraph),
            ).fetchone()
            return {"paragraph": dict(block) if block else {"reading_order": paragraph}}
        if table_index is not None:
            table = conn.execute(
                "select * from tables where document_id = ? and caption = ?",
                (document_id, f"DOCX table {table_index}"),
            ).fetchone()
            return {"table": dict(table) if table else {"index": table_index}}
    return {}


def _load_xlsx_target(project_id: str, document_id: str, locator: dict) -> dict:
    sheet = locator.get("sheet")
    if not sheet:
        return {}
    cell_ref = locator.get("cell")
    row_index = _int(locator.get("row"))
    cell_range = locator.get("range")
    with connect(project_db_path(project_id)) as conn:
        if cell_ref:
            rows = conn.execute(
                """
                select id, sheet_name, cell_ref, row_index, col_index, text, value_json
                from cells
                where document_id = ? and sheet_name = ? and upper(cell_ref) = upper(?)
                order by row_index, col_index
                """,
                (document_id, sheet, cell_ref),
            ).fetchall()
        elif row_index is not None:
            rows = conn.execute(
                """
                select id, sheet_name, cell_ref, row_index, col_index, text, value_json
                from cells
                where document_id = ? and sheet_name = ? and row_index = ?
                order by col_index
                """,
                (document_id, sheet, row_index),
            ).fetchall()
        elif cell_range:
            bounds = _range_bounds(cell_range)
            rows = []
            if bounds:
                start_row, start_col, end_row, end_col = bounds
                rows = conn.execute(
                    """
                    select id, sheet_name, cell_ref, row_index, col_index, text, value_json
                    from cells
                    where document_id = ? and sheet_name = ?
                      and row_index between ? and ?
                      and col_index between ? and ?
                    order by row_index, col_index
                    """,
                    (document_id, sheet, start_row, end_row, start_col, end_col),
                ).fetchall()
        else:
            rows = []
    return {"cells": [_cell_result(dict(row)) for row in rows]}


def _load_text_target(project_id: str, document_id: str, locator: dict) -> dict:
    block_id = locator.get("block")
    if not block_id:
        return {}
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute(
            """
            select id, block_type, text, reading_order, heading_path
            from blocks
            where document_id = ? and id = ?
            """,
            (document_id, block_id),
        ).fetchone()
    return {"block": dict(row) if row else {"id": block_id}}


def _precision(scheme: str, locator: dict, bbox: Optional[dict]) -> str:
    if scheme == "pdf":
        if bbox:
            return "bbox"
        if locator.get("table"):
            return "table"
        return "page"
    if scheme == "docx":
        return "paragraph" if locator.get("paragraph") else "table" if locator.get("table") else "document"
    if scheme == "xlsx":
        if locator.get("cell"):
            return "cell"
        if locator.get("range"):
            return "range"
        if locator.get("row"):
            return "row"
        return "sheet"
    if scheme in {"md", "html", "text"}:
        return "block" if locator.get("block") else "document"
    return "fragment"


def _location_label(scheme: str, locator: dict) -> str:
    if scheme == "pdf":
        page = locator.get("page")
        table = locator.get("table")
        return "page " + page + (f", table {table}" if table else "") if page else "PDF document"
    if scheme == "docx":
        if locator.get("paragraph"):
            return f"paragraph {locator['paragraph']}"
        if locator.get("table"):
            return f"table {locator['table']}"
        return "DOCX document"
    if scheme == "xlsx":
        label = f"sheet {locator.get('sheet')}" if locator.get("sheet") else "worksheet"
        if locator.get("cell"):
            label += f", cell {locator['cell']}"
        elif locator.get("range"):
            label += f", range {locator['range']}"
        elif locator.get("row"):
            label += f", row {locator['row']}"
        return label
    if scheme in {"md", "html", "text"}:
        label = "text block"
        if locator.get("heading"):
            label += f" under {unquote(locator['heading'])}"
        return label
    return "source fragment"


def _chunk_summary(chunk: dict) -> dict:
    return {
        "id": chunk["id"],
        "chunk_type": chunk["chunk_type"],
        "text": chunk["text"],
        "source_uri": chunk["source_uri"],
        "page_start": chunk["page_start"],
        "page_end": chunk["page_end"],
    }


def _cell_result(row: dict) -> dict:
    row["value"] = _loads_json(row.pop("value_json", None))
    return row


def _loads_json(value: Optional[str]) -> Optional[dict]:
    if not value:
        return None
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _range_bounds(value: str) -> Optional[tuple[int, int, int, int]]:
    match = re.fullmatch(r"([A-Za-z]+)(\d+):([A-Za-z]+)(\d+)", unquote(value).strip())
    if not match:
        return None
    start_col = _column_index(match.group(1))
    end_col = _column_index(match.group(3))
    start_row = int(match.group(2))
    end_row = int(match.group(4))
    return min(start_row, end_row), min(start_col, end_col), max(start_row, end_row), max(start_col, end_col)


def _column_index(value: str) -> int:
    total = 0
    for char in value.upper():
        if not ("A" <= char <= "Z"):
            break
        total = total * 26 + (ord(char) - ord("A") + 1)
    return total
