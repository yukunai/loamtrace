import pytest
import tempfile
from pathlib import Path
from loamtrace.services import generator, search, paths, documents
from loamtrace import config
from loamtrace.db import connect
from loamtrace.services.paths import project_db_path, ensure_project

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

def test_extract_quote():
    text = "The quick brown fox jumps over the lazy dog. Another sentence here."
    quote = generator._extract_quote(text)
    assert quote == "The quick brown fox jumps over the lazy dog."

    long_text = "A" * 400 + ". End."
    quote = generator._extract_quote(long_text)
    assert len(quote) <= 320

def test_generate_memo_extractive(tmp_workspace):
    project_id = "gen_test"
    ensure_project(project_id)
    
    # Insert a chunk
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("c1", "d1", "text", "Revenue grew by 24% in 2025. It was a good year.", "pdf://d1#page=1", "[]")
        )
        conn.execute(
            "insert into chunks_fts(id, document_id, text) values (?, ?, ?)",
            ("c1", "d1", "Revenue grew by 24% in 2025. It was a good year.")
        )
    
    res = generator.generate_memo(project_id, "Revenue")
    
    assert res["run_id"] is not None
    assert "Revenue grew by 24% in 2025." in res["answer"]
    assert len(res["claims"]) == 1
    assert res["claims"][0]["status"] == "verified"
    assert res["claims"][0]["citations"][0]["chunk_id"] == "c1"
    run_dir = Path(res["run_dir"])
    assert run_dir.exists()
    assert (run_dir / "input.json").exists()
    assert (run_dir / "retrieved_chunks.json").exists()
    assert (run_dir / "model_output.raw.json").exists()
    assert (run_dir / "verified_claims.json").exists()
    assert (run_dir / "final_memo.md").read_text(encoding="utf-8").startswith("# Verified Memo")
    assert (run_dir / "logs.jsonl").exists()
    assert "generate_memo_completed" in (run_dir.parent / "decision_log.jsonl").read_text(encoding="utf-8")
    with connect(project_db_path(project_id)) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("generate_memo_completed",)).fetchone()
    assert audit is not None
    assert res["model_status"] == "fallback_not_configured"


def test_generate_memo_uses_model_claims_when_available(tmp_workspace, monkeypatch):
    project_id = "gen_model"
    ensure_project(project_id)

    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("c1", "d1", "text", "Revenue grew by 24% in 2025. Gross margin was stable.", "pdf://d1#page=1", "[]")
        )
        conn.execute(
            "insert into chunks_fts(id, document_id, text) values (?, ?, ?)",
            ("c1", "d1", "Revenue grew by 24% in 2025. Gross margin was stable.")
        )

    def fake_chat_json(system_prompt, user_prompt):
        assert "Return JSON only" in system_prompt
        assert "c1" in user_prompt
        return {
            "claims": [
                {
                    "text": "Revenue grew by 24% in 2025.",
                    "type": "model_evidence",
                    "citations": [{"chunk_id": "c1", "quote": "Revenue grew by 24% in 2025."}],
                }
            ]
        }

    monkeypatch.setattr(generator, "chat_json", fake_chat_json)

    res = generator.generate_memo(project_id, "Revenue")

    assert res["model_status"] == "used"
    assert len(res["claims"]) == 1
    assert res["claims"][0]["type"] == "model_evidence"
    assert res["claims"][0]["status"] == "verified"
    assert "Revenue grew by 24% in 2025." in res["answer"]


def test_generate_memo_falls_back_when_model_claims_are_invalid(tmp_workspace, monkeypatch):
    project_id = "gen_model_invalid"
    ensure_project(project_id)

    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("c1", "d1", "text", "Revenue grew by 24% in 2025. It was a good year.", "pdf://d1#page=1", "[]")
        )
        conn.execute(
            "insert into chunks_fts(id, document_id, text) values (?, ?, ?)",
            ("c1", "d1", "Revenue grew by 24% in 2025. It was a good year.")
        )

    monkeypatch.setattr(
        generator,
        "chat_json",
        lambda _system, _user: {"claims": [{"text": "Invented claim", "citations": [{"chunk_id": "missing", "quote": "Invented"}]}]},
    )

    res = generator.generate_memo(project_id, "Revenue")

    assert res["model_status"] == "fallback_no_valid_claims"
    assert len(res["claims"]) == 1
    assert res["claims"][0]["type"] == "extractive_evidence"
    assert res["claims"][0]["status"] == "verified"


def test_generate_memo_no_results_writes_run_artifacts(tmp_workspace):
    project_id = "empty_gen"
    ensure_project(project_id)

    res = generator.generate_memo(project_id, "missing")

    assert res["run_id"] is not None
    assert res["claims"] == []
    run_dir = Path(res["run_dir"])
    assert run_dir.exists()
    assert (run_dir / "retrieved_chunks.json").read_text(encoding="utf-8").strip() == "[]"
    assert "No matching evidence" in (run_dir / "final_memo.md").read_text(encoding="utf-8")
    assert "generate_memo_completed" in (run_dir.parent / "decision_log.jsonl").read_text(encoding="utf-8")
    with connect(project_db_path(project_id)) as conn:
        audit = conn.execute("select * from audit_log where type = ?", ("generate_memo_completed",)).fetchone()
    assert audit is not None
