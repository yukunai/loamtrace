from __future__ import annotations

import json
import re
import uuid
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from xml.etree import ElementTree as ET

from loamtrace.db import connect
from loamtrace.services.chunk_store import clear_existing_parse, insert_chunk
from loamtrace.services.documents import get_document
from loamtrace.services.paths import project_db_path
from loamtrace.services.time import now_iso

PARSER_VERSION = "xlsx-ooxml-stdlib-1"
NS_MAIN = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
NS_DOC_REL = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def parse_xlsx(project_id: str, document_id: str) -> dict:
    document = get_document(project_id, document_id)
    source_path = Path(document["source_path"])
    sheet_count = 0
    cell_count = 0
    chunk_count = 0

    with zipfile.ZipFile(source_path) as archive:
        shared_strings = _read_shared_strings(archive)
        sheets = _read_sheets(archive)

        with connect(project_db_path(project_id)) as conn:
            clear_existing_parse(conn, document_id)
            for sheet_name, sheet_path in sheets:
                sheet_count += 1
                rows = _read_sheet_rows(archive, sheet_path, shared_strings)
                table_id = f"table_{uuid.uuid4().hex}"
                conn.execute(
                    """
                    insert into tables(id, document_id, page_id, bbox_json, caption, parser)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (table_id, document_id, None, None, sheet_name, PARSER_VERSION),
                )
                for row_index, cells in rows:
                    if not cells:
                        continue
                    row_cell_ids = []
                    row_parts = []
                    for cell_ref, text in cells:
                        if not text:
                            continue
                        cell_id = f"cell_{uuid.uuid4().hex}"
                        row_cell_ids.append(cell_id)
                        row_parts.append(f"{cell_ref}: {text}")
                        conn.execute(
                            """
                            insert into cells(
                              id, table_id, document_id, page_id, sheet_name,
                              cell_ref, row_index, col_index, text, value_json, bbox_json
                            )
                            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                cell_id,
                                table_id,
                                document_id,
                                None,
                                sheet_name,
                                cell_ref,
                                row_index,
                                _column_index(cell_ref),
                                text,
                                json.dumps({"text": text}),
                                None,
                            ),
                        )
                        cell_count += 1

                    if row_cell_ids:
                        chunk_id = f"chunk_{uuid.uuid4().hex}"
                        insert_chunk(
                            conn,
                            {
                                "id": chunk_id,
                                "document_id": document_id,
                                "chunk_type": "xlsx_row",
                                "text": f"{sheet_name} row {row_index}: " + " | ".join(row_parts),
                                "token_count": len(row_parts),
                                "heading_path": sheet_name,
                                "page_start": None,
                                "page_end": None,
                                "bbox_json": None,
                                "word_ids_json": json.dumps([]),
                                "cell_ids_json": json.dumps(row_cell_ids),
                                "source_uri": (
                                    f"xlsx://{document_id}#sheet={quote(sheet_name, safe='')}"
                                    f"&row={row_index}"
                                ),
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
        "sheets": sheet_count,
        "tables": sheet_count,
        "cells": cell_count,
        "chunks": chunk_count,
        "status": "parsed",
    }


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values = []
    for item in root.findall("m:si", NS_MAIN):
        text_parts = [node.text or "" for node in item.findall(".//m:t", NS_MAIN)]
        values.append("".join(text_parts))
    return values


def _read_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("r:Relationship", NS_REL)
        if rel.attrib.get("Target")
    }

    sheets = []
    for sheet in workbook.findall("m:sheets/m:sheet", NS_MAIN):
        name = sheet.attrib["name"]
        rel_id = sheet.attrib.get("{%s}id" % NS_DOC_REL["r"])
        target = rel_targets.get(rel_id or "")
        if not target:
            continue
        path = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
        sheets.append((name, path))
    return sheets


def _read_sheet_rows(
    archive: zipfile.ZipFile,
    sheet_path: str,
    shared_strings: list[str],
) -> list[tuple[int, list[tuple[str, str]]]]:
    root = ET.fromstring(archive.read(sheet_path))
    rows = []
    for row in root.findall("m:sheetData/m:row", NS_MAIN):
        row_index = int(row.attrib.get("r", "0") or 0)
        cells = []
        for cell in row.findall("m:c", NS_MAIN):
            cell_ref = cell.attrib.get("r", "")
            text = _cell_text(cell, shared_strings)
            if cell_ref and text:
                cells.append((cell_ref, text))
        rows.append((row_index, cells))
    return rows


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", NS_MAIN)).strip()
    value = cell.find("m:v", NS_MAIN)
    if value is None or value.text is None:
        return ""
    raw = value.text.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (IndexError, ValueError):
            return raw
    return raw


def _column_index(cell_ref: str) -> Optional[int]:
    match = re.match(r"([A-Z]+)", cell_ref.upper())
    if not match:
        return None
    value = 0
    for char in match.group(1):
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value
