import pytest
import tempfile
from pathlib import Path
from loamtrace.services import search, pdf_parser, documents
from loamtrace import config
from loamtrace.db import connect
from loamtrace.services.paths import project_db_path
from loamtrace.services.chunk_store import insert_chunk

@pytest.fixture
def tmp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_root = config.WORKSPACE_ROOT
        orig_projects = config.PROJECTS_ROOT
        config.WORKSPACE_ROOT = Path(tmpdir)
        config.PROJECTS_ROOT = config.WORKSPACE_ROOT / "projects"
        yield Path(tmpdir)
        config.WORKSPACE_ROOT = orig_root
        config.PROJECTS_ROOT = orig_projects

def test_search_chunks(tmp_workspace):
    project_id = "p1"
    doc_id = "d1"
    from loamtrace.services.paths import ensure_project
    ensure_project(project_id)
    
    # Manually insert a chunk and fts entry
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri)
            values (?, ?, ?, ?, ?)
            """,
            ("c1", doc_id, "text", "The quick brown fox", "uri1")
        )
        conn.execute(
            "insert into chunks_fts(id, document_id, text) values (?, ?, ?)",
            ("c1", doc_id, "The quick brown fox")
        )
    
    results = search.search_chunks(project_id, "fox")
    assert len(results) == 1
    assert results[0]["id"] == "c1"
    assert results[0]["text"] == "The quick brown fox"
    assert "fts" in results[0]["retrieval_sources"]

def test_search_no_results(tmp_workspace):
    project_id = "p1"
    results = search.search_chunks(project_id, "missing")
    assert len(results) == 0


def test_search_uses_vector_rrf_and_stores_embedding(tmp_workspace):
    project_id = "p1"
    from loamtrace.services.paths import ensure_project
    ensure_project(project_id)

    with connect(project_db_path(project_id)) as conn:
        insert_chunk(
            conn,
            {
                "id": "c1",
                "document_id": "d1",
                "chunk_type": "text",
                "text": "Annual recurring revenue expanded in 2025.",
                "token_count": 6,
                "source_uri": "pdf://d1#page=1",
                "word_ids_json": "[]",
                "cell_ids_json": None,
                "bbox_json": None,
                "heading_path": None,
                "page_start": 1,
                "page_end": 1,
            },
        )
        embedding = conn.execute(
            "select * from chunk_embeddings where chunk_id = ?",
            ("c1",),
        ).fetchone()

    assert embedding is not None
    results = search.search_chunks(project_id, "recurring revenue")
    assert results[0]["id"] == "c1"
    assert "vector" in results[0]["retrieval_sources"]
    assert results[0]["score"] > 0


def test_vector_search_uses_research_aliases_without_keyword_hit(tmp_workspace):
    project_id = "p1"
    from loamtrace.services.paths import ensure_project
    ensure_project(project_id)

    with connect(project_db_path(project_id)) as conn:
        insert_chunk(
            conn,
            {
                "id": "c1",
                "document_id": "d1",
                "chunk_type": "text",
                "text": "Annual recurring revenue expanded after enterprise renewals improved.",
                "token_count": 8,
                "source_uri": "pdf://d1#page=1",
                "word_ids_json": "[]",
                "cell_ids_json": None,
                "bbox_json": None,
                "heading_path": None,
                "page_start": 1,
                "page_end": 1,
            },
        )

    results = search.search_chunks(project_id, "subscription sales", top_n=3)
    assert results
    assert results[0]["id"] == "c1"
    assert "vector" in results[0]["retrieval_sources"]
    assert "fts" not in results[0]["retrieval_sources"]

def test_fts_query_normalization():
    query = '"hello" world!'
    match_query = search._fts_query(query)
    # re.findall(r"[\w.%$-]+", query) will find ['hello', 'world']
    # then join with " OR "
    assert match_query == '"hello" OR "world"'


def test_rrf_fuse_respects_source_weights():
    fts_results = [{"id": "keyword", "text": "Keyword exact", "document_id": "d1"}]
    vector_results = [{"id": "semantic", "text": "Semantic match", "document_id": "d1"}]

    keyword_first = search._rrf_fuse(
        fts_results,
        vector_results,
        top_n=2,
        weights={"fts": 2.0, "vector": 1.0},
    )
    vector_first = search._rrf_fuse(
        fts_results,
        vector_results,
        top_n=2,
        weights={"fts": 0.0, "vector": 1.0},
    )

    assert keyword_first[0]["id"] == "keyword"
    assert vector_first[0]["id"] == "semantic"
    assert vector_first[0]["retrieval_sources"] == ["vector"]
