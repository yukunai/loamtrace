from __future__ import annotations

import json
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from loamtrace.db import connect
from loamtrace.services.chunk_store import clear_existing_parse, insert_chunk
from loamtrace.services.documents import get_document
from loamtrace.services.paths import project_db_path
from loamtrace.services.time import now_iso

PARSER_VERSION = "text-markup-stdlib-1"


def parse_text_document(project_id: str, document_id: str) -> dict:
    document = get_document(project_id, document_id)
    source_path = Path(document["source_path"])
    text = _read_text(source_path)
    kind = _document_kind(document["filename"], document["mime_type"])
    segments = _segments_for_kind(kind, text)

    with connect(project_db_path(project_id)) as conn:
        clear_existing_parse(conn, document_id)
        chunk_count = 0
        for index, segment in enumerate(segments, start=1):
            block_id = f"block_{uuid.uuid4().hex}"
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
                    segment["block_type"],
                    segment["text"],
                    None,
                    index,
                    segment.get("heading_path"),
                ),
            )
            chunk_id = f"chunk_{uuid.uuid4().hex}"
            insert_chunk(
                conn,
                {
                    "id": chunk_id,
                    "document_id": document_id,
                    "chunk_type": f"{kind}_block",
                    "text": segment["text"],
                    "token_count": len(segment["text"].split()),
                    "heading_path": segment.get("heading_path"),
                    "page_start": None,
                    "page_end": None,
                    "bbox_json": None,
                    "word_ids_json": json.dumps([]),
                    "cell_ids_json": None,
                    "source_uri": _source_uri(kind, document_id, block_id, segment.get("heading_path")),
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
        "kind": kind,
        "blocks": len(segments),
        "chunks": chunk_count,
        "status": "parsed",
    }


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _document_kind(filename: str, mime_type: str) -> str:
    lower = filename.lower()
    if lower.endswith((".md", ".markdown")) or mime_type in {"text/markdown", "text/x-markdown"}:
        return "md"
    if lower.endswith((".html", ".htm")) or mime_type == "text/html":
        return "html"
    return "text"


def _segments_for_kind(kind: str, text: str) -> list[dict]:
    if kind == "md":
        return _markdown_segments(text)
    if kind == "html":
        return _html_segments(text)
    return _plain_text_segments(text)


def _plain_text_segments(text: str) -> list[dict]:
    return [
        {"block_type": "paragraph", "text": paragraph, "heading_path": None}
        for paragraph in _paragraphs(text)
    ]


def _markdown_segments(text: str) -> list[dict]:
    segments = []
    current_heading: Optional[str] = None
    buffer = []

    def flush() -> None:
        if not buffer:
            return
        paragraph = _normalize_text(" ".join(buffer))
        buffer.clear()
        if paragraph:
            segments.append({"block_type": "paragraph", "text": paragraph, "heading_path": current_heading})

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            flush()
            current_heading = _normalize_text(heading.group(2).strip("# "))
            segments.append({"block_type": "heading", "text": current_heading, "heading_path": current_heading})
            continue
        if not line:
            flush()
            continue
        buffer.append(_strip_markdown_markup(line))
    flush()
    return segments


def _html_segments(text: str) -> list[dict]:
    parser = _BlockHtmlParser()
    parser.feed(text)
    parser.close()
    return parser.segments


def _paragraphs(text: str) -> list[str]:
    return [paragraph for paragraph in (_normalize_text(part) for part in re.split(r"\n\s*\n", text)) if paragraph]


def _strip_markdown_markup(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`~]+", "", text)
    return _normalize_text(text)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _source_uri(kind: str, document_id: str, block_id: str, heading_path: Optional[str]) -> str:
    scheme = "text" if kind == "text" else kind
    parts = []
    if heading_path:
        parts.append(f"heading={quote(heading_path, safe='')}")
    parts.append(f"block={quote(block_id, safe='')}")
    return f"{scheme}://{document_id}#" + "&".join(parts)


class _BlockHtmlParser(HTMLParser):
    BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "blockquote"}
    SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.segments: list[dict] = []
        self._current_tag: Optional[str] = None
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._heading_path: Optional[str] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self.BLOCK_TAGS:
            self._flush()
            self._current_tag = tag
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == self._current_tag:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not self._current_tag:
            return
        self._buffer.append(data)

    def close(self) -> None:
        self._flush()
        super().close()

    def _flush(self) -> None:
        if not self._current_tag:
            return
        text = _normalize_text(" ".join(self._buffer))
        tag = self._current_tag
        self._current_tag = None
        self._buffer = []
        if not text:
            return
        if tag.startswith("h"):
            self._heading_path = text
            self.segments.append({"block_type": "heading", "text": text, "heading_path": text})
        else:
            self.segments.append({"block_type": tag, "text": text, "heading_path": self._heading_path})
