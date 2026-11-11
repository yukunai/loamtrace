from __future__ import annotations

import json
import uuid

from loamtrace.services.geometry import bbox_union


def _count_tokens(text: str) -> int:
    return len(text.split())


def chunk_words(document_id: str, page_number: int, words: list[dict], target_words: int = 180) -> list[dict]:
    chunks: list[dict] = []
    current: list[dict] = []

    for word in words:
        current.append(word)
        reached_target = len(current) >= target_words
        sentence_boundary = word["text"].endswith((".", "!", "?", "。", "！", "？"))
        if reached_target and sentence_boundary:
            chunks.append(_make_chunk(document_id, page_number, current))
            current = []

    if current:
        chunks.append(_make_chunk(document_id, page_number, current))
    return chunks


def _make_chunk(document_id: str, page_number: int, words: list[dict]) -> dict:
    chunk_id = f"chunk_{uuid.uuid4().hex}"
    text = " ".join(word["text"] for word in words).strip()
    word_ids = [word["id"] for word in words]
    boxes = [json.loads(word["bbox_json"]) for word in words]
    return {
        "id": chunk_id,
        "document_id": document_id,
        "chunk_type": "text",
        "text": text,
        "token_count": _count_tokens(text),
        "heading_path": None,
        "page_start": page_number,
        "page_end": page_number,
        "bbox_json": json.dumps(bbox_union(boxes)),
        "word_ids_json": json.dumps(word_ids),
        "cell_ids_json": None,
        "source_uri": f"pdf://{document_id}#page={page_number}&chunk={chunk_id}",
    }
