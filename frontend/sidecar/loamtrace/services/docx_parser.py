from __future__ import annotations

import json
import uuid
from pathlib import Path

from docx import Document

from typing import Optional

from loamtrace.db import connect
from loamtrace.services.chunk_store import clear_existing_parse, insert_chunk
from loamtrace.services.documents import get_document
from loamtrace.services.paths import project_db_path
from loamtrace.services.time import now_iso

PARSER_VERSION = "python-docx-1"


def parse_docx(project_id: str, document_id: str) -> dict:
    document = get_document(project_id, document_id)
    source_path = Path(document["source_path"])

    parsed = Document(source_path)
    paragraph_count = 0
    table_count = 0
    cell_count = 0
    chunk_count = 0

    with connect(project_db_path(project_id)) as conn:
        clear_existing_parse(conn, document_id)
        for index, paragraph in enumerate(parsed.paragraphs, start=1):
            text = paragraph.text.strip()
            if not text:
                continue
            paragraph_count += 1
            block_id = f"block_{uuid.uuid4().hex}"
            heading_path = _heading_path(paragraph)
            conn.execute(
                """
                insert into blocks(
                  id, document_id, page_id, block_type, text, bbox_json,
                  reading_order, heading_path
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    block_id,
                    document_id,
                    None,
                    "paragraph",
                    text,
                    None,
                    index,
                    heading_path,
                ),
            )
            chunk_id = f"chunk_{uuid.uuid4().hex}"
            insert_chunk(
                conn,
                {
                    "id": chunk_id,
                    "document_id": document_id,
                    "chunk_type": "docx_paragraph",
                    "text": text,
                    "token_count": len(text.split()),
                    "heading_path": heading_path,
                    "page_start": None,
                    "page_end": None,
                    "bbox_json": None,
                    "word_ids_json": json.dumps([]),
                    "cell_ids_json": None,
                    "source_uri": f"docx://{document_id}#paragraph={index}",
                },
            )
            chunk_count += 1

        for table_index, table in enumerate(parsed.tables, start=1):
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if not any(any(cell for cell in row) for row in rows):
                continue
            table_count += 1
            table_id = f"table_{uuid.uuid4().hex}"
            conn.execute(
                """
                insert into tables(id, document_id, page_id, bbox_json, caption, parser)
                values (?, ?, ?, ?, ?, ?)
                """,
                (table_id, document_id, None, None, f"DOCX table {table_index}", PARSER_VERSION),
            )
            cell_ids = []
            for row_index, row in enumerate(rows, start=1):
                for col_index, text in enumerate(row, start=1):
                    if not text:
                        continue
                    cell_id = f"cell_{uuid.uuid4().hex}"
                    cell_ids.append(cell_id)
                    cell_count += 1
                    conn.execute(
                        """
                        insert into cells(
                          id, table_id, document_id, page_id, sheet_name, cell_ref,
                          row_index, col_index, text, value_json, bbox_json
                        )
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cell_id,
                            table_id,
                            document_id,
                            None,
                            None,
                            f"R{row_index}C{col_index}",
                            row_index,
                            col_index,
                            text,
                            json.dumps({"text": text}),
                            None,
                        ),
                    )
            if cell_ids:
                chunk_id = f"chunk_{uuid.uuid4().hex}"
                insert_chunk(
                    conn,
                    {
                        "id": chunk_id,
                        "document_id": document_id,
                        "chunk_type": "docx_table",
                        "text": _markdown_table(rows),
                        "token_count": sum(len(cell.split()) for row in rows for cell in row),
                        "heading_path": None,
                        "page_start": None,
                        "page_end": None,
                        "bbox_json": None,
                        "word_ids_json": json.dumps([]),
                        "cell_ids_json": json.dumps(cell_ids),
                        "source_uri": f"docx://{document_id}#table={table_index}",
                    },
                )
                chunk_count += 1

        conn.execute(
            """
            update documents
            set parsed_at = ?, parser_version = ?, ocr_used = 0, status = ?
            where id = ?
            """,
            (now_iso(), PARSER_VERSION, "parsed", document_id),
        )

    return {
        "document_id": document_id,
        "paragraphs": paragraph_count,
        "tables": table_count,
        "cells": cell_count,
        "chunks": chunk_count,
        "status": "parsed",
    }


def _heading_path(paragraph) -> Optional[str]:
    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    if style_name.lower().startswith("heading"):
        return paragraph.text.strip()
    return None


def _markdown_table(rows: list[list[str]]) -> str:
    max_cols = max((len(row) for row in rows), default=0)
    padded = [row + [""] * (max_cols - len(row)) for row in rows]
    if not padded:
        return ""
    header = padded[0]
    body = padded[1:]
    lines = [
        "| " + " | ".join(_escape_markdown_cell(cell) for cell in header) + " |",
        "| " + " | ".join("---" for _ in range(max_cols)) + " |",
    ]
    lines.extend("| " + " | ".join(_escape_markdown_cell(cell) for cell in row) + " |" for row in body)
    return "\n".join(lines)


def _escape_markdown_cell(value: str) -> str:
    return value.replace("\n", " ").replace("|", "\\|")
