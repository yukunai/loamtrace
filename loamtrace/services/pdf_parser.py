from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote

import pdfplumber
import pypdfium2 as pdfium

from loamtrace.db import connect
from loamtrace.services.audit import write_audit
from loamtrace.services.chunker import chunk_words
from loamtrace.services.chunk_store import clear_existing_parse, insert_chunk
from loamtrace.services.documents import get_document
from loamtrace.services.geometry import normalize_bbox
from loamtrace.services.ocr_backend import find_tesseract, tesseract_env
from loamtrace.services.paths import project_db_path, project_root
from loamtrace.services.time import now_iso

PARSER_VERSION = "pdfplumber-0.11"


def parse_pdf(project_id: str, document_id: str) -> dict:
    document = get_document(project_id, document_id)
    if document["mime_type"] != "application/pdf" and not document["filename"].lower().endswith(".pdf"):
        raise ValueError("Only PDF parsing is implemented in V0")

    source_path = Path(document["source_path"])
    render_dir = project_root(project_id) / "sources" / "rendered_pages" / document_id
    render_dir.mkdir(parents=True, exist_ok=True)

    with connect(project_db_path(project_id)) as conn:
        clear_existing_parse(conn, document_id)
        page_count = 0
        word_count = 0
        table_count = 0
        cell_count = 0
        chunk_count = 0
        ocr_used = False
        ocr_confidences = []

        with pdfplumber.open(source_path) as pdf:
            rendered_paths = _render_pages(source_path, render_dir, len(pdf.pages))
            for page_index, page in enumerate(pdf.pages, start=1):
                page_count += 1
                page_id = f"page_{uuid.uuid4().hex}"
                extracted_text = page.extract_text() or ""
                text_layer_available = 1 if extracted_text.strip() else 0
                ocr_text = ""
                if not text_layer_available:
                    ocr_text = _ocr_text_for_page(rendered_paths.get(page_index))
                    ocr_used = ocr_used or bool(ocr_text.strip())
                text = extracted_text or ocr_text
                conn.execute(
                    """
                    insert into pages(
                      id, document_id, page_number, width, height, render_path,
                      text_layer_available
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        page_id,
                        document_id,
                        page_index,
                        float(page.width),
                        float(page.height),
                        str(rendered_paths.get(page_index)) if rendered_paths.get(page_index) else None,
                        text_layer_available,
                    ),
                )

                block_id = f"block_{uuid.uuid4().hex}"
                conn.execute(
                    """
                    insert into blocks(
                      id, document_id, page_id, block_type, text, bbox_json,
                      reading_order, heading_path
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (block_id, document_id, page_id, "page_text", text, None, page_index, None),
                )

                page_words = []
                char_cursor = 0
                raw_words = page.extract_words() or []
                if not raw_words and ocr_text.strip():
                    raw_words = _ocr_words_for_page(
                        rendered_paths.get(page_index),
                        page.width,
                        page.height,
                    ) or _synthetic_ocr_words(ocr_text, page.width, page.height)

                for word_index, raw_word in enumerate(raw_words):
                    word_text = raw_word.get("text", "")
                    if not word_text:
                        continue
                    word_id = f"word_{uuid.uuid4().hex}"
                    bbox_json = json.dumps(normalize_bbox(raw_word, page.width, page.height, page_index))
                    word_row = {
                        "id": word_id,
                        "document_id": document_id,
                        "page_id": page_id,
                        "block_id": block_id,
                        "text": word_text,
                        "char_start": char_cursor,
                        "char_end": char_cursor + len(word_text),
                        "bbox_json": bbox_json,
                        "word_index": word_index,
                    }
                    page_words.append(word_row)
                    confidence = raw_word.get("ocr_confidence")
                    if confidence is not None:
                        ocr_confidences.append(float(confidence))
                    char_cursor += len(word_text) + 1
                    word_count += 1
                    conn.execute(
                        """
                        insert into words(
                          id, document_id, page_id, block_id, text, char_start,
                          char_end, bbox_json, word_index
                        )
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        tuple(word_row.values()),
                    )

                for chunk in chunk_words(document_id, page_index, page_words):
                    chunk_count += 1
                    insert_chunk(conn, chunk)

                for table in _extract_pdf_tables(page):
                    table_id = f"table_{uuid.uuid4().hex}"
                    table_count += 1
                    table_bbox_json = _table_bbox_json(table.get("bbox"), page.width, page.height, page_index)
                    conn.execute(
                        """
                        insert into tables(id, document_id, page_id, bbox_json, caption, parser)
                        values (?, ?, ?, ?, ?, ?)
                        """,
                        (table_id, document_id, page_id, table_bbox_json, None, "pdfplumber-find_tables"),
                    )

                    table_cell_ids = []
                    for row_index, row in enumerate(table["rows"], start=1):
                        for col_index, value in enumerate(row, start=1):
                            text_value = (value or "").strip()
                            if not text_value:
                                continue
                            cell_id = f"cell_{uuid.uuid4().hex}"
                            table_cell_ids.append(cell_id)
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
                                    page_id,
                                    None,
                                    None,
                                    row_index,
                                    col_index,
                                    text_value,
                                    json.dumps({"text": text_value}),
                                    None,
                                ),
                            )
                            cell_count += 1

                    if table_cell_ids:
                        chunk_id = f"chunk_{uuid.uuid4().hex}"
                        table_text = _markdown_table(table["rows"])
                        insert_chunk(
                            conn,
                            {
                                "id": chunk_id,
                                "document_id": document_id,
                                "chunk_type": "pdf_table",
                                "text": table_text,
                                "token_count": len(table_text.split()),
                                "heading_path": None,
                                "page_start": page_index,
                                "page_end": page_index,
                                "bbox_json": table_bbox_json,
                                "word_ids_json": json.dumps([]),
                                "cell_ids_json": json.dumps(table_cell_ids),
                                "source_uri": (
                                    f"pdf://{document_id}#page={page_index}"
                                    f"&table={quote(table_id, safe='')}&chunk={chunk_id}"
                                ),
                            },
                        )
                        chunk_count += 1

        status = "failed" if page_count > 0 and word_count == 0 and cell_count == 0 else "parsed"
        conn.execute(
            """
            update documents
            set parsed_at = ?, parser_version = ?, ocr_used = ?, ocr_confidence = ?, status = ?
            where id = ?
            """,
            (now_iso(), PARSER_VERSION, 1 if ocr_used else 0, _average(ocr_confidences), status, document_id),
        )

    if status == "failed":
        write_audit(
            project_id,
            "pdf_ocr_required",
            {
                "document_id": document_id,
                "pages": page_count,
                "reason": "no_text_layer_or_extractable_words",
            },
        )
    elif ocr_used:
        write_audit(
            project_id,
            "pdf_ocr_applied",
            {
                "document_id": document_id,
                "pages": page_count,
                "engine": "tesseract",
                "precision": "word_bbox_if_tsv_available",
                "ocr_confidence": _average(ocr_confidences),
            },
        )

    return {
        "document_id": document_id,
        "pages": page_count,
        "words": word_count,
        "tables": table_count,
        "cells": cell_count,
        "chunks": chunk_count,
        "status": status,
        "ocr_used": ocr_used,
        "ocr_confidence": _average(ocr_confidences),
        "reason": "ocr_required" if status == "failed" else None,
    }


def _render_pages(source_path: Path, render_dir: Path, page_count: int) -> dict[int, Path]:
    rendered: dict[int, Path] = {}
    try:
        pdf = pdfium.PdfDocument(source_path)
        for index in range(page_count):
            page = pdf[index]
            bitmap = page.render(scale=1.5).to_pil()
            path = render_dir / f"page_{index + 1}.png"
            bitmap.save(path)
            rendered[index + 1] = path
        pdf.close()
    except Exception:
        return rendered
    return rendered


def _ocr_text_for_page(image_path: Optional[Path]) -> str:
    tesseract = find_tesseract()
    if image_path is None or not image_path.exists() or tesseract is None:
        return ""
    ocr_path = _tesseract_image_path(image_path)
    try:
        result = subprocess.run(
            [tesseract, str(ocr_path), "stdout", "--psm", "6"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=tesseract_env(tesseract),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    finally:
        _remove_temp_ocr_path(image_path, ocr_path)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _ocr_words_for_page(image_path: Optional[Path], page_width: float, page_height: float) -> list[dict]:
    tesseract = find_tesseract()
    if image_path is None or not image_path.exists() or tesseract is None:
        return []
    ocr_path = _tesseract_image_path(image_path)
    try:
        result = subprocess.run(
            [tesseract, str(ocr_path), "stdout", "--psm", "6", "tsv"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=tesseract_env(tesseract),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    finally:
        _remove_temp_ocr_path(image_path, ocr_path)
    if result.returncode != 0:
        return []

    image_width, image_height = _image_size(image_path)
    return _parse_tesseract_tsv(
        result.stdout,
        page_width,
        page_height,
        image_width=image_width,
        image_height=image_height,
    )


def _tesseract_image_path(image_path: Path) -> Path:
    if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        return image_path
    try:
        from PIL import Image

        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as handle:
            temp_path = Path(handle.name)
        with Image.open(image_path) as image:
            image.save(temp_path, "TIFF")
        return temp_path
    except Exception:
        return image_path


def _remove_temp_ocr_path(original_path: Path, ocr_path: Path) -> None:
    if ocr_path == original_path:
        return
    try:
        ocr_path.unlink()
    except OSError:
        pass


def _parse_tesseract_tsv(
    value: str,
    page_width: float,
    page_height: float,
    image_width: Optional[float] = None,
    image_height: Optional[float] = None,
) -> list[dict]:
    lines = [line for line in value.splitlines() if line.strip()]
    if not lines:
        return []
    header = lines[0].split("\t")
    required = {"left", "top", "width", "height", "text"}
    if not required.issubset(header):
        return []

    scale_x = float(page_width) / float(image_width) if image_width else 1.0
    scale_y = float(page_height) / float(image_height) if image_height else 1.0
    words = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < len(header):
            continue
        row = dict(zip(header, parts))
        text = row.get("text", "").strip()
        if not text:
            continue
        try:
            left = float(row["left"]) * scale_x
            top = float(row["top"]) * scale_y
            width = float(row["width"]) * scale_x
            height = float(row["height"]) * scale_y
            confidence = _parse_confidence(row.get("conf"))
        except (KeyError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        words.append(
            {
                "text": text,
                "x0": max(0.0, min(left, float(page_width))),
                "top": max(0.0, min(top, float(page_height))),
                "x1": max(0.0, min(left + width, float(page_width))),
                "bottom": max(0.0, min(top + height, float(page_height))),
                "ocr_confidence": confidence,
            }
        )
    return words


def _parse_confidence(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        confidence = float(value)
    except ValueError:
        return None
    if confidence < 0:
        return None
    return confidence


def _average(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _image_size(image_path: Path) -> tuple[Optional[float], Optional[float]]:
    try:
        from PIL import Image

        with Image.open(image_path) as image:
            return float(image.width), float(image.height)
    except Exception:
        return None, None


def _extract_pdf_tables(page) -> list[dict]:
    finder = getattr(page, "find_tables", None)
    if not callable(finder):
        return []
    try:
        tables = finder()
    except Exception:
        return []
    if not isinstance(tables, (list, tuple)):
        return []

    parsed = []
    for table in tables:
        try:
            rows = table.extract() or []
        except Exception:
            continue
        normalized_rows = [
            [str(cell).strip() if cell is not None else "" for cell in row]
            for row in rows
            if row and any((cell or "").strip() for cell in row)
        ]
        if normalized_rows:
            parsed.append({"bbox": getattr(table, "bbox", None), "rows": normalized_rows})
    return parsed


def _table_bbox_json(bbox, page_width: float, page_height: float, page_number: int) -> Optional[str]:
    if not bbox or len(bbox) != 4:
        return None
    try:
        x0, top, x1, bottom = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    return json.dumps(
        normalize_bbox(
            {"x0": x0, "top": top, "x1": x1, "bottom": bottom},
            page_width,
            page_height,
            page_number,
        )
    )


def _markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    escaped = [[cell.replace("|", "\\|") for cell in row] for row in padded]
    header = escaped[0]
    separator = ["---"] * width
    body = escaped[1:]
    rendered = ["| " + " | ".join(header) + " |", "| " + " | ".join(separator) + " |"]
    rendered.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(rendered)


def _synthetic_ocr_words(text: str, page_width: float, page_height: float) -> list[dict]:
    tokens = re.findall(r"\S+", text)
    if not tokens:
        return []
    line_height = max(float(page_height) / max(len(tokens), 1), 1.0)
    words = []
    for index, token in enumerate(tokens):
        y0 = min(index * line_height, float(page_height) - 1)
        y1 = min(y0 + line_height, float(page_height))
        words.append(
            {
                "text": token,
                "x0": 0.0,
                "top": y0,
                "x1": float(page_width),
                "bottom": y1,
            }
        )
    return words
