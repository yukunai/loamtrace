import sqlite3

import pytest
from loamtrace.services.verifier import _entities_are_covered, _numbers_are_covered, normalize_text


@pytest.fixture
def tmp_workspace():
    import tempfile
    from loamtrace import config
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_root = config.WORKSPACE_ROOT
        orig_projects = config.PROJECTS_ROOT
        config.WORKSPACE_ROOT = Path(tmpdir)
        config.PROJECTS_ROOT = config.WORKSPACE_ROOT / "projects"
        yield Path(tmpdir)
        config.WORKSPACE_ROOT = orig_root
        config.PROJECTS_ROOT = orig_projects


def test_normalize_text_collapses_spacing_and_width() -> None:
    assert normalize_text("Revenue　grew\n 24％") == "Revenue grew 24%"


def test_numbers_are_covered_when_exact_number_in_quote() -> None:
    assert _numbers_are_covered(
        "Revenue grew 24% year over year in 2025.",
        "Revenue increased by 24% year over year in 2025.",
        "Revenue increased by 24% year over year in 2025.",
    )


def test_numbers_are_blocked_when_claim_number_missing() -> None:
    assert not _numbers_are_covered(
        "Revenue grew 25% year over year in 2025.",
        "Revenue increased by 24% year over year in 2025.",
        "Revenue increased by 24% year over year in 2025.",
    )


def test_numbers_accept_comma_equivalence() -> None:
    assert _numbers_are_covered(
        "Revenue was $1200 million.",
        "Revenue was $1,200 million.",
        "Revenue was $1,200 million.",
    )


def test_computed_numbers_use_source_numbers_instead_of_derived_number() -> None:
    assert _numbers_are_covered(
        "Revenue growth was 25% computed from 100 in 2024 and 125 in 2025.",
        "Revenue growth was computed from 100 in 2024 and 125 in 2025.",
        "Revenue growth was computed from 100 in 2024 and 125 in 2025.",
        "computed",
        ["100", "2024", "125", "2025"],
    )


def test_computed_numbers_block_when_source_number_missing() -> None:
    assert not _numbers_are_covered(
        "Revenue growth was 25% computed from 100 and 125.",
        "Revenue growth was computed from 100.",
        "Revenue growth was computed from 100.",
        "computed",
        ["100", "125"],
    )


def test_entities_are_covered_for_title_entities_and_acronyms() -> None:
    assert _entities_are_covered(
        "Acme Corp ARR grew 24% in 2025.",
        "Acme Corp ARR grew 24% in 2025.",
        "Acme Corp ARR grew 24% in 2025.",
    )
    assert not _entities_are_covered(
        "Acme Corp ARR grew 24% in 2025.",
        "Revenue grew 24% in 2025.",
        "Revenue grew 24% in 2025.",
    )


def test_verify_citation_exact_match() -> None:
    chunk = {
        "id": "chk1",
        "text": "The revenue grew by 24% in 2025.",
        "document_id": "doc1",
        "source_uri": "pdf://doc1#page=1",
        "bbox_json": '{"page": 1}',
        "word_ids_json": "[]",
    }
    from loamtrace.services.verifier import _verify_citation

    res = _verify_citation("p1", "cit1", "Revenue grew by 24% in 2025.", "revenue grew by 24% in 2025", chunk)
    assert res["verified"] == 1
    assert res["verification_method"] == "normalized_exact"
    assert res["support_level"] == "direct"


def test_verify_citation_fuzzy_quote_match() -> None:
    chunk = {
        "id": "chk1",
        "text": "The revenue grew by 24% in 2025.",
        "document_id": "doc1",
        "source_uri": "pdf://doc1#page=1",
        "bbox_json": '{"page": 1}',
        "word_ids_json": "[]",
    }
    from loamtrace.services.verifier import _verify_citation

    res = _verify_citation("p1", "cit1", "Revenue grew 24% in 2025.", "the revenue grew by 24% in 2025", chunk)
    assert res["verified"] == 1
    assert res["verification_method"] == "fuzzy_quote_match"
    assert res["verification_score"] >= 0.92


def test_verify_citation_low_similarity_quote_blocks() -> None:
    chunk = {
        "id": "chk1",
        "text": "The revenue grew by 24% in 2025.",
        "document_id": "doc1",
        "source_uri": "pdf://doc1#page=1",
        "bbox_json": '{"page": 1}',
        "word_ids_json": "[]",
    }
    from loamtrace.services.verifier import _verify_citation

    res = _verify_citation("p1", "cit1", "Revenue grew 24% in 2025.", "gross margin declined 24% in 2025", chunk)
    assert res["verified"] == 0
    assert res["failure_reason"] == "quote_not_found"


def test_verify_citation_invalid_source_uri_blocks() -> None:
    chunk = {
        "id": "chk1",
        "text": "The revenue grew by 24% in 2025.",
        "document_id": "doc1",
        "source_uri": "uri1",
        "bbox_json": '{"page": 1}',
        "word_ids_json": "[]",
    }
    from loamtrace.services.verifier import _verify_citation

    res = _verify_citation("p1", "cit1", "Revenue 24% in 2025.", "24% in 2025", chunk)
    assert res["verified"] == 0
    assert res["failure_reason"] == "source_uri_invalid"


def test_verify_claims_blocks_mismatched_citation_source_uri(tmp_workspace):
    from loamtrace.db import connect
    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.paths import ensure_project, project_db_path
    from loamtrace.services.verifier import verify_claims

    project_id = "source_uri_mismatch"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("c1", "d1", "text", "Revenue grew 24% in 2025.", "pdf://d1#page=1", "[]"),
        )

    claim = verify_claims(
        project_id,
        [
            ClaimInput(
                text="Revenue grew 24% in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="c1",
                        quote="Revenue grew 24% in 2025.",
                        source_uri="pdf://d2#page=1",
                    )
                ],
            )
        ],
    )["claims"][0]

    assert claim["status"] == "blocked"
    assert claim["citations"][0]["source_uri"] == "pdf://d2#page=1"
    assert claim["citations"][0]["failure_reason"] == "source_uri_mismatch"


def test_correct_claim_preserves_source_uri_mismatch_when_chunk_unchanged(tmp_workspace):
    from loamtrace.db import connect
    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.paths import ensure_project, project_db_path
    from loamtrace.services.verifier import correct_claim, verify_claims

    project_id = "correct_source_uri_mismatch"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("c1", "d1", "text", "Revenue grew 24% in 2025.", "pdf://d1#page=1", "[]"),
        )

    claim = verify_claims(
        project_id,
        [
            ClaimInput(
                text="Revenue grew 24% in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="c1",
                        quote="Revenue grew 24% in 2025.",
                        source_uri="pdf://d2#page=1",
                    )
                ],
            )
        ],
    )["claims"][0]

    corrected = correct_claim(project_id, claim["id"], text="Revenue grew 24% in 2025.")

    assert corrected["status"] == "blocked"
    assert corrected["citations"][0]["source_uri"] == "pdf://d2#page=1"
    assert corrected["citations"][0]["failure_reason"] == "source_uri_mismatch"


def test_verify_claims_blocks_low_confidence_ocr_source(tmp_workspace):
    from loamtrace.db import connect
    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.paths import ensure_project, project_db_path
    from loamtrace.services.verifier import verify_claims

    project_id = "ocr_low_confidence"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into documents(
              id, project_id, sha256, filename, mime_type, source_path,
              created_at, parsed_at, parser_version, ocr_used, ocr_confidence, status
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "d1",
                project_id,
                "sha",
                "scan.pdf",
                "application/pdf",
                "/tmp/scan.pdf",
                "2026-06-09T00:00:00Z",
                "2026-06-09T00:00:00Z",
                "pdfplumber-0.11",
                1,
                42.0,
                "parsed",
            ),
        )
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("c1", "d1", "text", "Revenue grew 24% in 2025.", "pdf://d1#page=1", "[]"),
        )

    claim = verify_claims(
        project_id,
        [
            ClaimInput(
                text="Revenue grew 24% in 2025.",
                citations=[CitationInput(chunk_id="c1", quote="Revenue grew 24% in 2025.")],
            )
        ],
    )["claims"][0]

    assert claim["status"] == "blocked"
    assert claim["citations"][0]["failure_reason"] == "ocr_low_confidence"


def test_verify_citation_number_mismatch_blocks() -> None:
    chunk = {
        "id": "chk1",
        "text": "The revenue grew by 24% in 2025.",
        "document_id": "doc1",
        "source_uri": "pdf://doc1#page=1",
        "bbox_json": '{"page": 1}',
        "word_ids_json": "[]",
    }
    from loamtrace.services.verifier import _verify_citation

    # Number in claim (25%) not in chunk (24%)
    res = _verify_citation("p1", "cit1", "Revenue 25%", "24% in 2025", chunk)
    assert res["verified"] == 0
    assert res["failure_reason"] == "number_not_found"


def test_verify_citation_entity_mismatch_blocks() -> None:
    chunk = {
        "id": "chk1",
        "text": "Revenue grew by 24% in 2025.",
        "document_id": "doc1",
        "source_uri": "pdf://doc1#page=1",
        "bbox_json": '{"page": 1}',
        "word_ids_json": "[]",
    }
    from loamtrace.services.verifier import _verify_citation

    res = _verify_citation("p1", "cit1", "Acme Corp revenue grew 24% in 2025.", "Revenue grew by 24% in 2025.", chunk)
    assert res["verified"] == 0
    assert res["failure_reason"] == "entity_not_found"


def test_list_claims_and_enhanced_render_memo(tmp_workspace):
    import json

    from loamtrace.services.verifier import verify_claims, render_memo, list_claims
    from loamtrace.models import ClaimInput, CitationInput
    from loamtrace.services.paths import ensure_project
    from loamtrace.db import connect
    from loamtrace.services.paths import project_db_path, project_root

    project_id = "v_test"
    ensure_project(project_id)
    
    # Insert a chunk
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("c1", "d1", "text", "Revenue 24%", "pdf://d1#page=1", "[]")
        )
    
    claim = ClaimInput(
        text="Revenue 24%",
        citations=[CitationInput(chunk_id="c1", quote="Revenue 24%")]
    )
    verified = verify_claims(project_id, [claim])
    assert verified["claims"][0]["citations"][0]["claim_id"] == verified["claims"][0]["id"]
    
    claims = list_claims(project_id)
    assert len(claims) == 1
    assert claims[0]["text"] == "Revenue 24%"
    assert len(claims[0]["citations"]) == 1
    assert claims[0]["citations"][0]["quote"] == "Revenue 24%"
    assert claims[0]["citations"][0]["verified"] is True

    memo = render_memo(project_id)
    assert "Revenue 24%" in memo["markdown"]
    assert "claims" in memo
    assert len(memo["claims"]) == 1
    notes_dir = project_root(project_id) / "notes"
    claims_json = json.loads((notes_dir / "claims.json").read_text(encoding="utf-8"))
    citations_json = json.loads((notes_dir / "citations.json").read_text(encoding="utf-8"))
    assert claims_json[0]["id"] == claims[0]["id"]
    assert citations_json[0]["quote"] == "Revenue 24%"


def test_partial_support_claim_needs_review_and_stays_out_of_memo(tmp_workspace):
    from loamtrace.db import connect
    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.paths import ensure_project, project_db_path
    from loamtrace.services.verifier import render_memo, verify_claims

    project_id = "support_review"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "c1",
                "d1",
                "text",
                "Revenue grew by 24% in 2025. Customer retention was 91%.",
                "pdf://d1#page=1",
                "[]",
            ),
        )

    result = verify_claims(
        project_id,
        [
            ClaimInput(
                text="Revenue and customer retention improved in 2025.",
                citations=[CitationInput(chunk_id="c1", quote="Revenue grew by 24% in 2025.")],
            )
        ],
    )
    claim = result["claims"][0]

    assert claim["status"] == "needs_review"
    assert claim["citations"][0]["verified"] == 1
    assert claim["citations"][0]["support_level"] == "partial"
    assert "Revenue and customer retention improved" not in render_memo(project_id)["markdown"]


def test_computed_claim_persists_formula_and_allows_derived_number(tmp_workspace):
    from loamtrace.db import connect
    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.paths import ensure_project, project_db_path
    from loamtrace.services.verifier import list_claims, verify_claims

    project_id = "computed_claim"
    ensure_project(project_id)
    quote = "Revenue growth was computed from 100 in 2024 and 125 in 2025."
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("c1", "d1", "text", quote, "text://d1#block=block_1", "[]"),
        )

    result = verify_claims(
        project_id,
        [
            ClaimInput(
                text="Revenue growth was 25% computed from 100 in 2024 and 125 in 2025.",
                type="computed",
                calculation_formula="(125 - 100) / 100 = 25%",
                source_numbers=["100", "2024", "125", "2025"],
                citations=[CitationInput(chunk_id="c1", quote=quote)],
            )
        ],
    )
    claim = result["claims"][0]

    assert claim["status"] == "verified"
    assert claim["calculation_formula"] == "(125 - 100) / 100 = 25%"
    assert claim["source_numbers"] == ["100", "2024", "125", "2025"]
    assert claim["citations"][0]["verified"] == 1
    listed = list_claims(project_id)
    assert listed[0]["calculation_formula"] == "(125 - 100) / 100 = 25%"
    assert listed[0]["source_numbers"] == ["100", "2024", "125", "2025"]


def test_computed_claim_without_formula_blocks(tmp_workspace):
    from loamtrace.db import connect
    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.paths import ensure_project, project_db_path
    from loamtrace.services.verifier import verify_claims

    project_id = "computed_missing_formula"
    ensure_project(project_id)
    quote = "Revenue growth was computed from 100 in 2024 and 125 in 2025."
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("c1", "d1", "text", quote, "text://d1#block=block_1", "[]"),
        )

    claim = verify_claims(
        project_id,
        [
            ClaimInput(
                text="Revenue growth was 25% computed from 100 in 2024 and 125 in 2025.",
                type="computed",
                source_numbers=["100", "2024", "125", "2025"],
                citations=[CitationInput(chunk_id="c1", quote=quote)],
            )
        ],
    )["claims"][0]

    assert claim["status"] == "blocked"
    assert claim["citations"][0]["failure_reason"] == "computed_formula_missing"


def test_init_db_migrates_existing_citation_support_columns(tmp_path):
    from loamtrace.db import init_db

    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            create table documents(
              id text primary key,
              project_id text not null,
              sha256 text not null,
              filename text not null,
              mime_type text not null,
              source_path text not null,
              created_at text not null,
              parsed_at text,
              parser_version text,
              ocr_used integer default 0,
              status text not null
            )
            """
        )
        conn.execute(
            """
            create table citations(
              id text primary key,
              claim_id text not null,
              chunk_id text not null,
              document_id text not null,
              quote text not null,
              source_uri text not null,
              bbox_json text,
              verified integer not null default 0,
              verification_method text,
              verification_score real,
              failure_reason text
            )
            """
        )

    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        citation_columns = {row[1] for row in conn.execute("pragma table_info(citations)").fetchall()}
        claim_columns = {row[1] for row in conn.execute("pragma table_info(claims)").fetchall()}
        document_columns = {row[1] for row in conn.execute("pragma table_info(documents)").fetchall()}
    assert "support_level" in citation_columns
    assert "support_reason" in citation_columns
    assert "reviewer" in citation_columns
    assert "review_note" in citation_columns
    assert "reviewed_at" in citation_columns
    assert "calculation_formula" in claim_columns
    assert "source_numbers_json" in claim_columns
    assert "ocr_confidence" in document_columns


def test_missing_chunk_uses_stable_failure_code(tmp_path, monkeypatch) -> None:
    from loamtrace import config
    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.verifier import verify_claims

    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")

    result = verify_claims(
        "p1",
        [
            ClaimInput(
                text="Revenue grew 24%.",
                citations=[CitationInput(chunk_id="missing", quote="Revenue grew 24%.")],
            )
        ],
    )
    claim = result["claims"][0]
    from pathlib import Path

    run_dir = Path(result["run_dir"])
    assert run_dir.exists()
    assert (run_dir / "input.json").exists()
    assert (run_dir / "verified_claims.json").exists()
    assert (run_dir / "logs.jsonl").exists()
    decision_log = run_dir.parent / "decision_log.jsonl"
    assert "verify_completed" in decision_log.read_text(encoding="utf-8")
    from loamtrace.db import connect
    from loamtrace.services.paths import project_db_path

    with connect(project_db_path("p1")) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("verify_completed",)).fetchone()
    assert audit is not None
    assert claim["status"] == "blocked"
    assert claim["citations"][0]["failure_reason"] == "chunk_not_found"


def test_review_citation_approve_and_reject_persist(tmp_workspace):
    from loamtrace.db import connect
    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.paths import ensure_project, project_db_path
    from loamtrace.services.verifier import render_memo, review_citation, verify_claims

    project_id = "review_test"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("c1", "d1", "text", "Revenue grew 24% in 2025.", "pdf://d1#page=1", "[]"),
        )
        conn.execute(
            "insert into chunks_fts(id, document_id, text) values (?, ?, ?)",
            ("c1", "d1", "Revenue grew 24% in 2025."),
        )

    blocked = verify_claims(
        project_id,
        [
            ClaimInput(
                text="Revenue grew 25% in 2025.",
                citations=[CitationInput(chunk_id="c1", quote="Revenue grew 24% in 2025.")],
            )
        ],
    )["claims"][0]
    citation_id = blocked["citations"][0]["id"]

    approved = review_citation(project_id, citation_id, "approve", "alice", "Exception accepted after source review.")
    assert approved["status"] == "blocked"
    assert approved["citations"][0]["verified"] is False
    assert approved["citations"][0]["verification_method"] is None
    assert approved["citations"][0]["failure_reason"] == "number_not_found"
    assert approved["citations"][0]["reviewer"] == "alice"
    assert approved["citations"][0]["review_note"] == "Exception accepted after source review."
    assert approved["citations"][0]["reviewed_at"]
    assert "Revenue grew 25%" not in render_memo(project_id)["markdown"]

    rejected = review_citation(project_id, citation_id, "reject", "bob", "Quote does not support the number.")
    assert rejected["status"] == "rejected"
    assert rejected["citations"][0]["verified"] is False
    assert rejected["citations"][0]["failure_reason"] == "manual_rejected"
    assert rejected["citations"][0]["reviewer"] == "bob"
    assert rejected["citations"][0]["review_note"] == "Quote does not support the number."
    assert "Revenue grew 25%" not in render_memo(project_id)["markdown"]


def test_number_normalization_does_not_treat_decimal_comma_as_thousands(tmp_workspace):
    from loamtrace.db import connect
    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.paths import ensure_project, project_db_path
    from loamtrace.services.verifier import verify_claims

    project_id = "comma_number_test"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("c1", "d1", "text", "The ratio was 2,4 in 2025.", "pdf://d1#page=1", "[]"),
        )

    claim = verify_claims(
        project_id,
        [
            ClaimInput(
                text="The ratio was 24 in 2025.",
                citations=[CitationInput(chunk_id="c1", quote="The ratio was 2,4 in 2025.")],
            )
        ],
    )["claims"][0]

    assert claim["status"] == "blocked"
    assert claim["citations"][0]["failure_reason"] == "number_not_found"


def test_replace_citation_reverifies_and_updates_claim_status(tmp_workspace):
    from loamtrace.db import connect
    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.paths import ensure_project, project_db_path
    from loamtrace.services.verifier import render_memo, replace_citation, verify_claims

    project_id = "replace_test"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("bad", "d1", "text", "Revenue grew 24% in 2025.", "pdf://d1#page=1", "[]"),
        )
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("good", "d1", "text", "Revenue grew 25% in 2025.", "pdf://d1#page=2", "[]"),
        )

    blocked = verify_claims(
        project_id,
        [
            ClaimInput(
                text="Revenue grew 25% in 2025.",
                citations=[CitationInput(chunk_id="bad", quote="Revenue grew 24% in 2025.")],
            )
        ],
    )["claims"][0]
    assert blocked["status"] == "blocked"

    replaced = replace_citation(
        project_id,
        blocked["citations"][0]["id"],
        "good",
        "Revenue grew 25% in 2025.",
    )
    assert replaced["status"] == "verified"
    assert replaced["citations"][0]["chunk_id"] == "good"
    assert replaced["citations"][0]["verified"] is True
    assert replaced["citations"][0]["failure_reason"] is None
    assert replaced["citations"][0]["reviewer"] is None
    assert replaced["citations"][0]["review_note"] is None
    assert replaced["citations"][0]["reviewed_at"] is None
    assert "Revenue grew 25%" in render_memo(project_id)["markdown"]
