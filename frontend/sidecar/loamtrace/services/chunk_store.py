from __future__ import annotations

from loamtrace.services.embeddings import dumps_embedding, embed_text
from loamtrace.services.time import now_iso


def insert_chunk(conn, chunk: dict) -> None:
    conn.execute(
        """
        insert into chunks(
          id, document_id, chunk_type, text, token_count, heading_path,
          page_start, page_end, bbox_json, word_ids_json, cell_ids_json, source_uri
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk["id"],
            chunk["document_id"],
            chunk["chunk_type"],
            chunk["text"],
            chunk["token_count"],
            chunk.get("heading_path"),
            chunk.get("page_start"),
            chunk.get("page_end"),
            chunk.get("bbox_json"),
            chunk.get("word_ids_json"),
            chunk.get("cell_ids_json"),
            chunk["source_uri"],
        ),
    )
    conn.execute(
        "insert into chunks_fts(id, document_id, text) values (?, ?, ?)",
        (chunk["id"], chunk["document_id"], chunk["text"]),
    )
    conn.execute(
        """
        insert or replace into chunk_embeddings(chunk_id, document_id, embedding_json, updated_at)
        values (?, ?, ?, ?)
        """,
        (
            chunk["id"],
            chunk["document_id"],
            dumps_embedding(embed_text(chunk["text"])),
            now_iso(),
        ),
    )


def clear_existing_parse(conn, document_id: str) -> None:
    conn.execute("delete from chunks_fts where document_id = ?", (document_id,))
    conn.execute("delete from chunk_embeddings where document_id = ?", (document_id,))
    for table in ["chunks", "cells", "tables", "words", "blocks", "pages"]:
        conn.execute(f"delete from {table} where document_id = ?", (document_id,))
