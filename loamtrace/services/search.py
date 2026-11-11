from __future__ import annotations

import re
from typing import Optional

from loamtrace.db import connect
from loamtrace.services.embeddings import cosine_similarity, embed_text, loads_embedding, text_tokens
from loamtrace.services.paths import ensure_project, project_db_path


def search_chunks(
    project_id: str,
    query: str,
    top_n: int = 12,
    rrf_k: int = 60,
    fts_top_n: int = 50,
    vector_top_n: int = 50,
    keyword_boost: float = 1.0,
    vector_boost: float = 1.0,
) -> list[dict]:
    ensure_project(project_id)
    query = query.strip()
    if not query:
        return []

    fts_results = _fts_search(project_id, query, top_n=fts_top_n)
    vector_results = _vector_search(project_id, query, top_n=vector_top_n)
    return _rrf_fuse(
        fts_results,
        vector_results,
        top_n=top_n,
        k=rrf_k,
        weights={"fts": keyword_boost, "vector": vector_boost},
    )


def _fts_search(project_id: str, query: str, top_n: int = 50) -> list[dict]:
    match_query = _fts_query(query)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            """
            select
              c.*,
              rank as score
            from chunks_fts
            join chunks c on c.id = chunks_fts.id
            where chunks_fts match ?
            order by rank
            limit ?
            """,
            (match_query, top_n),
        ).fetchall()
    return [dict(row) for row in rows]


def _vector_search(project_id: str, query: str, top_n: int = 50) -> list[dict]:
    query_vector = embed_text(query)
    query_tokens = set(text_tokens(query))
    if not query_tokens:
        return []
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            """
            select c.*, e.embedding_json
            from chunks c
            left join chunk_embeddings e on e.chunk_id = c.id
            """
        ).fetchall()

    scored = []
    for row in rows:
        chunk = dict(row)
        embedding_json = chunk.pop("embedding_json", None)
        if not query_tokens.intersection(text_tokens(chunk["text"])):
            continue
        chunk_vector = loads_embedding(embedding_json) if embedding_json else embed_text(chunk["text"])
        score = cosine_similarity(query_vector, chunk_vector)
        if score <= 0:
            continue
        chunk["score"] = score
        scored.append(chunk)

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_n]


def _rrf_fuse(
    fts_results: list[dict],
    vector_results: list[dict],
    top_n: int,
    k: int = 60,
    weights: Optional[dict[str, float]] = None,
) -> list[dict]:
    fused: dict[str, dict] = {}
    weights = weights or {"fts": 1.0, "vector": 1.0}

    for source, results in [("fts", fts_results), ("vector", vector_results)]:
        weight = float(weights.get(source, 1.0))
        if weight <= 0:
            continue
        for rank, result in enumerate(results, start=1):
            chunk_id = result["id"]
            if chunk_id not in fused:
                fused[chunk_id] = {**result, "rrf_score": 0.0, "retrieval_sources": []}
            fused[chunk_id]["rrf_score"] += weight / (k + rank)
            fused[chunk_id]["retrieval_sources"].append(source)

    ranked = sorted(fused.values(), key=lambda item: item["rrf_score"], reverse=True)
    for item in ranked:
        item["score"] = item["rrf_score"]
    return ranked[:top_n]


def get_chunk(project_id: str, chunk_id: str) -> dict:
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute("select * from chunks where id = ?", (chunk_id,)).fetchone()
    if not row:
        raise KeyError(f"Chunk not found: {chunk_id}")
    return dict(row)


def _fts_query(query: str) -> str:
    terms = re.findall(r"[\w.%$-]+", query, flags=re.UNICODE)
    if not terms:
        return '""'
    return " OR ".join(f'"{term.replace(chr(34), chr(34) + chr(34))}"' for term in terms)
