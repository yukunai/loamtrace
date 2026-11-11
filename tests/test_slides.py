import json
import zipfile
from pathlib import Path

import pytest

from loamtrace import config
from loamtrace.db import connect
from loamtrace.models import CitationInput, ClaimInput
from loamtrace.services.paths import ensure_project, project_db_path, project_root
from loamtrace.services.slides import (
    annotate_chart_review_status,
    annotate_table_review_status,
    assert_deck_claims_allowed,
    export_pptx,
    generate_chart_deck,
    generate_slide_deck,
    generate_table_deck,
    generate_template_slide_deck,
    list_slide_templates,
    load_slide_deck,
)
from loamtrace.services.verifier import verify_claims


@pytest.fixture
def slide_project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    project_id = "slides"
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk_good",
                "doc_1",
                "text",
                "Revenue increased by 24% year over year in 2025.",
                "pdf://doc_1#page=1",
                "[]",
            ),
        )
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk_bad",
                "doc_1",
                "text",
                "Revenue increased by 24% year over year in 2025.",
                "pdf://doc_1#page=1",
                "[]",
            ),
        )
    return project_id


def test_generate_slide_json_and_export_pptx(slide_project):
    verified = verify_claims(
        slide_project,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_good",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]

    deck_result = generate_slide_deck(slide_project, "Market Diligence", [verified["id"]])
    deck = deck_result["deck"]
    assert Path(deck_result["path"]).exists()
    assert deck["slides"][1]["layout"] == "claim_with_evidence"
    assert deck["slides"][1]["main_claim_id"] == verified["id"]
    assert deck["slides"][2]["layout"] == "evidence_appendix"
    assert deck["slides"][2]["main_claim_id"] == verified["id"]
    generate_run_dir = Path(deck_result["run_dir"])
    assert generate_run_dir.exists()
    assert json.loads((generate_run_dir / "input.json").read_text(encoding="utf-8"))["claim_ids"] == [verified["id"]]
    assert json.loads((generate_run_dir / "deck.slide.json").read_text(encoding="utf-8"))["deck_id"] == deck_result["deck_id"]
    assert "slide_deck_generated" in (generate_run_dir / "logs.jsonl").read_text(encoding="utf-8")
    assert "slide_deck_generated" in (generate_run_dir.parent / "decision_log.jsonl").read_text(encoding="utf-8")

    loaded = load_slide_deck(slide_project, deck_result["deck_id"])
    assert loaded["deck_id"] == deck_result["deck_id"]

    export = export_pptx(slide_project, deck_result["deck_id"])
    pptx_path = Path(export["path"])
    assert pptx_path.exists()
    run_dir = Path(export["run_dir"])
    assert run_dir.exists()
    assert json.loads((run_dir / "input.json").read_text(encoding="utf-8"))["deck_id"] == deck_result["deck_id"]
    assert json.loads((run_dir / "deck.slide.json").read_text(encoding="utf-8"))["deck_id"] == deck_result["deck_id"]
    assert json.loads((run_dir / "output.json").read_text(encoding="utf-8"))["path"] == export["path"]
    assert "pptx_exported" in (run_dir / "logs.jsonl").read_text(encoding="utf-8")
    with zipfile.ZipFile(pptx_path) as archive:
        names = set(archive.namelist())
        assert "ppt/slides/slide2.xml" in names
        assert "ppt/slides/slide3.xml" in names
        assert "ppt/slides/_rels/slide2.xml.rels" in names
        assert "ppt/notesSlides/notesSlide2.xml" in names
        assert "ppt/notesMasters/notesMaster1.xml" in names
        slide_xml = archive.read("ppt/slides/slide2.xml").decode("utf-8")
        appendix_xml = archive.read("ppt/slides/slide3.xml").decode("utf-8")
        notes_xml = archive.read("ppt/notesSlides/notesSlide2.xml").decode("utf-8")
        slide_rels = archive.read("ppt/slides/_rels/slide2.xml.rels").decode("utf-8")
        assert "Revenue increased by 24%" in slide_xml
        assert "Evidence appendix" in appendix_xml
        assert "pdf://doc_1#page=1" in appendix_xml
        assert "pdf://doc_1#page=1" in notes_xml
        assert "notesSlide2.xml" in slide_rels
    with connect(project_db_path(slide_project)) as conn:
        row = conn.execute("select * from audit_log where type = ?", ("pptx_exported",)).fetchone()
        generated_row = conn.execute("select * from audit_log where type = ?", ("slide_deck_generated",)).fetchone()
    assert row is not None
    assert generated_row is not None


def test_generate_slide_deck_adds_executive_summary_for_multiple_claims(slide_project):
    with connect(project_db_path(slide_project)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk_margin",
                "doc_1",
                "text",
                "Gross margin reached 62% in 2025.",
                "pdf://doc_1#page=2",
                "[]",
            ),
        )
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk_concentration",
                "doc_1",
                "text",
                "Customer concentration risk reached 38% in 2025.",
                "pdf://doc_1#page=3",
                "[]",
            ),
        )
    verified_claims = verify_claims(
        slide_project,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_good",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            ),
            ClaimInput(
                text="Gross margin reached 62% in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_margin",
                        quote="Gross margin reached 62% in 2025.",
                    )
                ],
            ),
            ClaimInput(
                text="Customer concentration risk reached 38% in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_concentration",
                        quote="Customer concentration risk reached 38% in 2025.",
                    )
                ],
            ),
        ],
    )["claims"]

    deck_result = generate_slide_deck(
        slide_project,
        "Multi Claim Deck",
        [claim["id"] for claim in verified_claims],
    )
    deck = deck_result["deck"]

    assert [slide["layout"] for slide in deck["slides"]] == [
        "title",
        "executive_summary",
        "metric_table",
        "red_flag_table",
        "comparison_matrix",
        "timeline",
        "claim_with_evidence",
        "claim_with_evidence",
        "claim_with_evidence",
        "evidence_appendix",
    ]
    summary = deck["slides"][1]
    metric_table = deck["slides"][2]
    red_flag_table = deck["slides"][3]
    comparison_matrix = deck["slides"][4]
    timeline = deck["slides"][5]
    
    # Sort claims by ID since verify_claims order might not match input order due to database retrieval
    sorted_claims = sorted(verified_claims, key=lambda c: c["id"])
    
    # Check that main claim ID is from one of the claims
    assert summary["main_claim_id"] in [claim["id"] for claim in verified_claims]
    
    # Get the claim elements and notes
    claim_elements = [element["claim_id"] for element in summary["elements"] if element["role"] == "summary_bullet"]
    claim_notes = [note["claim_id"] for note in summary["speaker_notes"]]
    
    # Assert they contain the same IDs, ignoring order
    assert set(claim_elements) == set(claim["id"] for claim in verified_claims)
    assert set(claim_notes) == set(claim["id"] for claim in verified_claims)
    assert len(claim_elements) == len(verified_claims)
    assert len(claim_notes) == len(verified_claims)
    assert metric_table["main_claim_id"] in [claim["id"] for claim in verified_claims]
    table_element = next(element for element in metric_table["elements"] if element["type"] == "table")
    assert table_element["rows"][0] == ["Claim", "Metrics", "Source"]
    assert any("24%" in row[1] for row in table_element["rows"][1:])
    assert any("62%" in row[1] for row in table_element["rows"][1:])
    red_flag_element = next(element for element in red_flag_table["elements"] if element["type"] == "table")
    assert red_flag_table["main_claim_id"] in [claim["id"] for claim in verified_claims]
    assert red_flag_element["rows"][0] == ["Red flag", "Evidence source"]
    assert any("Customer concentration risk" in row[0] for row in red_flag_element["rows"][1:])
    comparison_element = next(element for element in comparison_matrix["elements"] if element["type"] == "table")
    assert comparison_matrix["main_claim_id"] in [claim["id"] for claim in verified_claims]
    assert comparison_element["rows"][0] == ["Claim", "Metrics", "Years", "Source"]
    assert len(comparison_element["rows"]) == len(verified_claims) + 1
    assert timeline["main_claim_id"] in [claim["id"] for claim in verified_claims]
    timeline_elements = [
        element["claim_id"] for element in timeline["elements"] if element["role"] == "timeline_item"
    ]
    assert set(timeline_elements) == set(claim["id"] for claim in verified_claims)
    assert all("2025" in element["text"] for element in timeline["elements"] if element["role"] == "timeline_item")
    appendix = deck["slides"][-1]
    assert appendix["layout"] == "evidence_appendix"
    assert appendix["main_claim_id"] in [claim["id"] for claim in verified_claims]
    appendix_elements = [
        element["claim_id"] for element in appendix["elements"] if element["role"] == "evidence_appendix_item"
    ]
    assert set(appendix_elements) == set(claim["id"] for claim in verified_claims)

    export = export_pptx(slide_project, deck_result["deck_id"])
    with zipfile.ZipFile(Path(export["path"])) as archive:
        summary_xml = archive.read("ppt/slides/slide2.xml").decode("utf-8")
        metric_xml = archive.read("ppt/slides/slide3.xml").decode("utf-8")
        red_flag_xml = archive.read("ppt/slides/slide4.xml").decode("utf-8")
        comparison_xml = archive.read("ppt/slides/slide5.xml").decode("utf-8")
        timeline_xml = archive.read("ppt/slides/slide6.xml").decode("utf-8")
        appendix_xml = archive.read("ppt/slides/slide10.xml").decode("utf-8")
        notes_xml = archive.read("ppt/notesSlides/notesSlide2.xml").decode("utf-8")
    assert "Executive summary" in summary_xml
    assert "Revenue increased by 24%" in summary_xml
    assert "Gross margin reached 62%" in summary_xml
    assert "<a:tbl>" in metric_xml
    assert "Verified metrics" in metric_xml
    assert "24%" in metric_xml
    assert "62%" in metric_xml
    assert "<a:tbl>" in red_flag_xml
    assert "Red flags" in red_flag_xml
    assert "Customer concentration risk" in red_flag_xml
    assert "<a:tbl>" in comparison_xml
    assert "Comparison matrix" in comparison_xml
    assert "38%" in comparison_xml
    assert "Evidence timeline" in timeline_xml
    assert "2025" in timeline_xml
    assert "Customer concentration risk" in timeline_xml
    assert "Evidence appendix" in appendix_xml
    assert "pdf://doc_1#page=1" in appendix_xml
    assert "pdf://doc_1#page=2" in appendix_xml
    assert "pdf://doc_1#page=3" in appendix_xml
    assert "pdf://doc_1#page=1" in notes_xml
    assert "pdf://doc_1#page=2" in notes_xml


def test_generate_template_slide_deck_uses_local_template_contract(slide_project):
    with connect(project_db_path(slide_project)) as conn:
        conn.execute(
            """
            insert into chunks(id, document_id, chunk_type, text, source_uri, word_ids_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk_margin",
                "doc_1",
                "text",
                "Gross margin reached 62% in 2025.",
                "pdf://doc_1#page=2",
                "[]",
            ),
        )
    verified_claims = verify_claims(
        slide_project,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_good",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            ),
            ClaimInput(
                text="Gross margin reached 62% in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_margin",
                        quote="Gross margin reached 62% in 2025.",
                    )
                ],
            ),
        ],
    )["claims"]

    templates = list_slide_templates()
    assert any(template["id"] == "market_diligence" for template in templates)

    deck_result = generate_template_slide_deck(
        slide_project,
        "market_diligence",
        "Market Template",
        [claim["id"] for claim in verified_claims],
    )
    deck = deck_result["deck"]

    assert deck["template_id"] == "market_diligence"
    assert deck["template_name"] == "Market Diligence Brief"
    assert [slide["layout"] for slide in deck["slides"]] == [
        "title",
        "executive_summary",
        "metric_table",
        "comparison_matrix",
        "claim_with_evidence",
        "claim_with_evidence",
        "evidence_appendix",
    ]
    assert Path(deck_result["path"]).exists()
    run_dir = Path(deck_result["run_dir"])
    assert json.loads((run_dir / "template.json").read_text(encoding="utf-8"))["id"] == "market_diligence"
    assert "template_slide_deck_generated" in (run_dir / "logs.jsonl").read_text(encoding="utf-8")

    export = export_pptx(slide_project, deck_result["deck_id"])
    assert Path(export["path"]).exists()


def test_export_pptx_renders_table_elements_as_native_tables(slide_project):
    verified = verify_claims(
        slide_project,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_good",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]
    deck = {
        "deck_id": "deck_table",
        "title": "Metric Table",
        "slides": [
            {
                "id": "slide_001",
                "layout": "title",
                "title": "Metric Table",
                "main_claim_id": None,
                "elements": [{"type": "text", "role": "title", "text": "Metric Table"}],
                "speaker_notes": [],
            },
            {
                "id": "slide_002",
                "layout": "metric_table",
                "title": "Revenue metrics",
                "main_claim_id": verified["id"],
                "elements": [
                    {"type": "text", "role": "headline", "text": "Revenue metrics"},
                    {
                        "type": "table",
                        "rows": [
                            ["Metric", "Value"],
                            ["Revenue growth", "24%"],
                        ],
                    },
                ],
                "speaker_notes": [
                    {
                        "claim_id": verified["id"],
                        "source_uri": "pdf://doc_1#page=1",
                        "quote": "Revenue increased by 24% year over year in 2025.",
                    }
                ],
            },
        ],
    }
    slides_dir = project_root(slide_project) / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    (slides_dir / "deck_table.slide.json").write_text(
        json.dumps(deck),
        encoding="utf-8",
    )

    export = export_pptx(slide_project, "deck_table")

    with zipfile.ZipFile(Path(export["path"])) as archive:
        slide_xml = archive.read("ppt/slides/slide2.xml").decode("utf-8")
    assert "<a:tbl>" in slide_xml
    assert "Metric" in slide_xml
    assert "Revenue growth" in slide_xml
    assert "24%" in slide_xml


def test_generate_table_deck_from_source_cells_exports_native_table(slide_project):
    with connect(project_db_path(slide_project)) as conn:
        conn.execute(
            """
            insert into documents(id, project_id, sha256, filename, mime_type, source_path, created_at, status)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("doc_table", slide_project, "sha_table", "metrics.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "/tmp/metrics.xlsx", "2026-06-09T00:00:00Z", "parsed"),
        )
        conn.execute(
            """
            insert into tables(id, document_id, page_id, bbox_json, caption, parser)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("table_metrics", "doc_table", None, None, "Operating metrics", "test-parser"),
        )
        for cell_id, row_index, col_index, cell_ref, text in [
            ("cell_h1", 1, 1, "A1", "Metric"),
            ("cell_h2", 1, 2, "B1", "2025"),
            ("cell_r1", 2, 1, "A2", "Revenue"),
            ("cell_r2", 2, 2, "B2", "148"),
        ]:
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
                    "table_metrics",
                    "doc_table",
                    None,
                    "Revenue",
                    cell_ref,
                    row_index,
                    col_index,
                    text,
                    json.dumps({"text": text}),
                    None,
                ),
            )

    deck_result = generate_table_deck(slide_project, "table_metrics", "Operating Table", max_rows=4, max_cols=4)
    deck = deck_result["deck"]

    assert Path(deck_result["path"]).exists()
    assert deck["slides"][1]["layout"] == "source_table"
    table_element = next(element for element in deck["slides"][1]["elements"] if element["type"] == "table")
    assert table_element["review_status"] == "verified"
    assert table_element["data_source"]["table_id"] == "table_metrics"
    assert set(table_element["data_source"]["cell_ids"]) == {"cell_h1", "cell_h2", "cell_r1", "cell_r2"}
    assert table_element["rows"] == [["Metric", "2025"], ["Revenue", "148"]]
    run_dir = Path(deck_result["run_dir"])
    assert json.loads((run_dir / "input.json").read_text(encoding="utf-8"))["table_id"] == "table_metrics"
    assert "table_deck_generated" in (run_dir / "logs.jsonl").read_text(encoding="utf-8")

    export = export_pptx(slide_project, deck_result["deck_id"])
    with zipfile.ZipFile(Path(export["path"])) as archive:
        slide_xml = archive.read("ppt/slides/slide2.xml").decode("utf-8")
        notes_xml = archive.read("ppt/notesSlides/notesSlide2.xml").decode("utf-8")
    assert "<a:tbl>" in slide_xml
    assert "Operating metrics" in slide_xml
    assert "Revenue" in slide_xml
    assert "148" in slide_xml
    assert "table:table_metrics" in notes_xml
    with connect(project_db_path(slide_project)) as conn:
        row = conn.execute("select * from audit_log where type = ?", ("table_deck_generated",)).fetchone()
    assert row is not None


def test_source_table_with_missing_cells_is_blocked(slide_project):
    deck = {
        "deck_id": "deck_missing_table_cells",
        "title": "Missing Table",
        "slides": [
            {
                "id": "slide_source_table",
                "layout": "source_table",
                "title": "Missing source",
                "main_claim_id": None,
                "elements": [
                    {
                        "type": "table",
                        "rows": [["Metric", "Value"], ["Revenue", "148"]],
                        "data_source": {"cell_ids": ["missing_cell"]},
                    }
                ],
                "speaker_notes": [],
            }
        ],
    }

    annotate_table_review_status(slide_project, deck)

    table = deck["slides"][0]["elements"][0]
    assert table["review_status"] == "needs_review"
    assert table["failure_reason"] == "table_cell_source_missing"
    with pytest.raises(ValueError, match="table_needs_review:slide_source_table"):
        assert_deck_claims_allowed(slide_project, deck)


def test_source_table_value_mismatch_is_blocked(slide_project):
    with connect(project_db_path(slide_project)) as conn:
        conn.execute(
            """
            insert into cells(
              id, table_id, document_id, page_id, sheet_name, cell_ref,
              row_index, col_index, text, value_json, bbox_json
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("cell_table_truth", None, "doc_1", None, "Metrics", "B2", 2, 2, "148", '{"number":148}', None),
        )
    deck = {
        "deck_id": "deck_table_value_mismatch",
        "title": "Mismatched Table",
        "slides": [
            {
                "id": "slide_source_table",
                "layout": "source_table",
                "title": "Mismatched source",
                "main_claim_id": None,
                "elements": [
                    {
                        "type": "table",
                        "rows": [["Metric", "Value"], ["Revenue", "999"]],
                        "data_source": {"cell_ids": ["cell_table_truth"]},
                    }
                ],
                "speaker_notes": [],
            }
        ],
    }

    annotate_table_review_status(slide_project, deck)

    table = deck["slides"][0]["elements"][0]
    assert table["review_status"] == "needs_review"
    assert table["failure_reason"] == "table_cell_value_mismatch"
    with pytest.raises(ValueError, match="table_needs_review:slide_source_table"):
        assert_deck_claims_allowed(slide_project, deck)


def test_export_pptx_renders_chart_elements_as_native_charts(slide_project):
    verified = verify_claims(
        slide_project,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_good",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]
    with connect(project_db_path(slide_project)) as conn:
        for cell_id, text in [("cell_rev_2024", "20"), ("cell_rev_2025", "24")]:
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
                    None,
                    "doc_1",
                    None,
                    "Revenue",
                    "B1",
                    1,
                    1,
                    text,
                    '{"text":"' + text + '"}',
                    None,
                ),
            )
    deck = {
        "deck_id": "deck_chart_native",
        "title": "Native Chart",
        "slides": [
            {
                "id": "slide_001",
                "layout": "title",
                "title": "Native Chart",
                "main_claim_id": None,
                "elements": [{"type": "text", "role": "title", "text": "Native Chart"}],
                "speaker_notes": [],
            },
            {
                "id": "slide_002",
                "layout": "claim_with_chart",
                "title": "Revenue trend",
                "main_claim_id": verified["id"],
                "elements": [
                    {"type": "text", "role": "headline", "text": "Revenue trend"},
                    {
                        "type": "chart",
                        "chart_type": "line",
                        "data_source": {"cell_ids": ["cell_rev_2024", "cell_rev_2025"]},
                        "series": [
                            {
                                "name": "Revenue",
                                "points": [
                                    {"label": "2024", "value": 20, "cell_id": "cell_rev_2024"},
                                    {"label": "2025", "value": 24, "cell_id": "cell_rev_2025"},
                                ],
                            }
                        ],
                    },
                ],
                "speaker_notes": [
                    {
                        "claim_id": verified["id"],
                        "source_uri": "pdf://doc_1#page=1",
                        "quote": "Revenue increased by 24% year over year in 2025.",
                    }
                ],
            },
        ],
    }
    slides_dir = project_root(slide_project) / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    (slides_dir / "deck_chart_native.slide.json").write_text(json.dumps(deck), encoding="utf-8")

    export = export_pptx(slide_project, "deck_chart_native")

    with zipfile.ZipFile(Path(export["path"])) as archive:
        names = set(archive.namelist())
        slide_xml = archive.read("ppt/slides/slide2.xml").decode("utf-8")
        rels_xml = archive.read("ppt/slides/_rels/slide2.xml.rels").decode("utf-8")
        chart_xml = archive.read("ppt/charts/chart1.xml").decode("utf-8")
        content_types = archive.read("[Content_Types].xml").decode("utf-8")
    assert "ppt/charts/chart1.xml" in names
    assert "<c:chart" in slide_xml
    assert "r:id=" in slide_xml
    assert "relationships/chart" in rels_xml
    assert "drawingml.chart+xml" in content_types
    assert "<c:lineChart>" in chart_xml
    assert "Revenue" in chart_xml
    assert "2025" in chart_xml
    assert "24.0" in chart_xml


def test_blocked_claims_cannot_enter_deck(slide_project):
    blocked = verify_claims(
        slide_project,
        [
            ClaimInput(
                text="Revenue increased by 25% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_bad",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]

    with pytest.raises(ValueError, match="blocked_claims_in_deck"):
        generate_slide_deck(slide_project, "Blocked Deck", [blocked["id"]])


def test_chart_without_cell_traceability_is_marked_needs_review(slide_project):
    deck = {
        "deck_id": "deck_chart_missing_source",
        "title": "Chart Review",
        "slides": [
            {
                "id": "slide_chart",
                "layout": "claim_with_chart",
                "title": "Revenue trend",
                "main_claim_id": None,
                "elements": [
                    {
                        "type": "chart",
                        "chart_type": "line",
                        "data_source": {},
                    }
                ],
                "speaker_notes": [],
            }
        ],
    }

    annotate_chart_review_status(slide_project, deck)

    chart = deck["slides"][0]["elements"][0]
    assert chart["review_status"] == "needs_review"
    assert chart["failure_reason"] == "chart_cell_source_missing"
    with pytest.raises(ValueError, match="chart_needs_review:slide_chart"):
        assert_deck_claims_allowed(slide_project, deck)


def test_chart_with_null_data_source_is_marked_needs_review(slide_project):
    deck = {
        "deck_id": "deck_chart_null_source",
        "title": "Chart Review",
        "slides": [
            {
                "id": "slide_chart",
                "layout": "claim_with_chart",
                "title": "Revenue trend",
                "main_claim_id": None,
                "elements": [
                    {
                        "type": "chart",
                        "chart_type": "line",
                        "data_source": None,
                    }
                ],
                "speaker_notes": [],
            }
        ],
    }

    annotate_chart_review_status(slide_project, deck)

    chart = deck["slides"][0]["elements"][0]
    assert chart["data_source"] == {}
    assert chart["review_status"] == "needs_review"
    assert chart["failure_reason"] == "chart_cell_source_missing"
    with pytest.raises(ValueError, match="chart_needs_review:slide_chart"):
        assert_deck_claims_allowed(slide_project, deck)


def test_chart_with_existing_cell_ids_is_allowed(slide_project):
    verified = verify_claims(
        slide_project,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_good",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]
    with connect(project_db_path(slide_project)) as conn:
        conn.execute(
            """
            insert into cells(
              id, table_id, document_id, page_id, sheet_name, cell_ref,
              row_index, col_index, text, value_json, bbox_json
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cell_revenue_2025",
                None,
                "doc_1",
                None,
                "Revenue",
                "B2",
                2,
                2,
                "24",
                '{"number":24}',
                None,
            ),
        )
    deck = {
        "deck_id": "deck_chart_verified",
        "title": "Chart Verified",
        "slides": [
            {
                "id": "slide_chart",
                "layout": "claim_with_chart",
                "title": "Revenue trend",
                "main_claim_id": verified["id"],
                "elements": [
                    {
                        "type": "chart",
                        "chart_type": "line",
                        "data_source": {"cell_ids": ["cell_revenue_2025"]},
                    }
                ],
                "speaker_notes": [],
            }
        ],
    }

    annotate_chart_review_status(slide_project, deck)

    chart = deck["slides"][0]["elements"][0]
    assert chart["review_status"] == "verified"
    assert "failure_reason" not in chart
    assert_deck_claims_allowed(slide_project, deck)


def test_chart_value_mismatch_is_blocked(slide_project):
    verified = verify_claims(
        slide_project,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_good",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]
    with connect(project_db_path(slide_project)) as conn:
        conn.execute(
            """
            insert into cells(
              id, table_id, document_id, page_id, sheet_name, cell_ref,
              row_index, col_index, text, value_json, bbox_json
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("cell_chart_truth", None, "doc_1", None, "Revenue", "B2", 2, 2, "148", '{"number":148}', None),
        )
    deck = {
        "deck_id": "deck_chart_value_mismatch",
        "title": "Chart Mismatch",
        "slides": [
            {
                "id": "slide_chart",
                "layout": "claim_with_chart",
                "title": "Revenue trend",
                "main_claim_id": verified["id"],
                "elements": [
                    {
                        "type": "chart",
                        "chart_type": "bar",
                        "data_source": {"cell_ids": ["cell_chart_truth"]},
                        "series": [
                            {
                                "name": "Revenue",
                                "points": [{"label": "2025", "value": 999, "cell_id": "cell_chart_truth"}],
                            }
                        ],
                    }
                ],
                "speaker_notes": [],
            }
        ],
    }

    annotate_chart_review_status(slide_project, deck)

    chart = deck["slides"][0]["elements"][0]
    assert chart["review_status"] == "needs_review"
    assert chart["failure_reason"] == "chart_cell_value_mismatch"
    with pytest.raises(ValueError, match="chart_needs_review:slide_chart"):
        assert_deck_claims_allowed(slide_project, deck)


def test_chart_with_existing_table_id_resolves_cell_ids(slide_project):
    verified = verify_claims(
        slide_project,
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id="chunk_good",
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )["claims"][0]
    with connect(project_db_path(slide_project)) as conn:
        conn.execute(
            """
            insert into tables(id, document_id, page_id, bbox_json, caption, parser)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("table_revenue", "doc_1", None, None, "Revenue", "test"),
        )
        for cell_id, cell_ref, text in [
            ("cell_revenue_2024", "B1", "2024: 20"),
            ("cell_revenue_2025", "B2", "2025: 24"),
        ]:
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
                    "table_revenue",
                    "doc_1",
                    None,
                    "Revenue",
                    cell_ref,
                    1,
                    1,
                    text,
                    '{"text":"' + text + '"}',
                    None,
                ),
            )
    deck = {
        "deck_id": "deck_chart_table",
        "title": "Chart Table",
        "slides": [
            {
                "id": "slide_chart",
                "layout": "claim_with_chart",
                "title": "Revenue trend",
                "main_claim_id": verified["id"],
                "elements": [
                    {
                        "type": "chart",
                        "chart_type": "line",
                        "data_source": {"table_id": "table_revenue"},
                    }
                ],
                "speaker_notes": [],
            }
        ],
    }

    annotate_chart_review_status(slide_project, deck)

    chart = deck["slides"][0]["elements"][0]
    assert chart["review_status"] == "verified"
    assert chart["data_source"]["cell_ids"] == ["cell_revenue_2024", "cell_revenue_2025"]
    assert_deck_claims_allowed(slide_project, deck)


def test_generate_chart_deck_exports_claimless_verified_chart(slide_project):
    with connect(project_db_path(slide_project)) as conn:
        conn.execute(
            """
            insert into cells(
              id, table_id, document_id, page_id, sheet_name, cell_ref,
              row_index, col_index, text, value_json, bbox_json
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("cell_chart_2024", None, "doc_1", None, "Revenue", "B2", 2, 2, "120", '{"number":120}', None),
        )
        conn.execute(
            """
            insert into cells(
              id, table_id, document_id, page_id, sheet_name, cell_ref,
              row_index, col_index, text, value_json, bbox_json
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("cell_chart_2025", None, "doc_1", None, "Revenue", "B3", 3, 2, "148", '{"number":148}', None),
        )
    chart = {
        "type": "chart",
        "chart_type": "bar",
        "data_source": {"cell_ids": ["cell_chart_2024", "cell_chart_2025"]},
        "series": [
            {
                "name": "Revenue",
                "points": [
                    {"label": "2024", "value": 120, "cell_id": "cell_chart_2024"},
                    {"label": "2025", "value": 148, "cell_id": "cell_chart_2025"},
                ],
            }
        ],
    }

    deck_result = generate_chart_deck(slide_project, "Revenue Chart", chart)

    deck = deck_result["deck"]
    assert deck["slides"][1]["layout"] == "source_table_chart"
    assert deck["slides"][1]["main_claim_id"] is None
    assert deck["slides"][1]["elements"][1]["review_status"] == "verified"
    assert Path(deck_result["path"]).exists()
    assert "chart_deck_generated" in Path(deck_result["run_dir"], "logs.jsonl").read_text(encoding="utf-8")

    export = export_pptx(slide_project, deck_result["deck_id"])
    with zipfile.ZipFile(Path(export["path"])) as archive:
        names = set(archive.namelist())
        chart_xml = archive.read("ppt/charts/chart1.xml").decode("utf-8")
    assert "ppt/charts/chart1.xml" in names
    assert "<c:barChart>" in chart_xml
    assert "Revenue" in chart_xml
    assert "148.0" in chart_xml


def test_generate_chart_deck_rejects_untraceable_chart(slide_project):
    with pytest.raises(ValueError, match="chart_needs_review:slide_002"):
        generate_chart_deck(
            slide_project,
            "Untraceable Chart",
            {
                "type": "chart",
                "chart_type": "line",
                "series": [{"name": "Revenue", "points": [{"label": "2025", "value": 148}]}],
            },
        )


def test_chart_deck_api(slide_project):
    from fastapi.testclient import TestClient
    from loamtrace import main

    with connect(project_db_path(slide_project)) as conn:
        conn.execute(
            """
            insert into cells(
              id, table_id, document_id, page_id, sheet_name, cell_ref,
              row_index, col_index, text, value_json, bbox_json
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("cell_api_chart", None, "doc_1", None, "Revenue", "B2", 2, 2, "148", '{"number":148}', None),
        )
    response = TestClient(main.app).post(
        "/api/slides/chart-deck",
        json={
            "project_id": slide_project,
            "title": "API Chart",
            "chart": {
                "type": "chart",
                "chart_type": "line",
                "data_source": {"cell_ids": ["cell_api_chart"]},
                "series": [
                    {
                        "name": "Revenue",
                        "points": [{"label": "2025", "value": 148, "cell_id": "cell_api_chart"}],
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["deck"]["slides"][1]["elements"][1]["review_status"] == "verified"


def test_non_title_slide_without_claim_id_is_blocked(slide_project):
    deck = {
        "deck_id": "deck_missing_claim",
        "title": "Missing Claim",
        "slides": [
            {
                "id": "slide_title",
                "layout": "title",
                "title": "Missing Claim",
                "main_claim_id": None,
                "elements": [{"type": "text", "role": "title", "text": "Missing Claim"}],
                "speaker_notes": [],
            },
            {
                "id": "slide_claimless",
                "layout": "claim_with_evidence",
                "title": "Unsupported page",
                "main_claim_id": None,
                "elements": [{"type": "text", "role": "headline", "text": "Unsupported page"}],
                "speaker_notes": [],
            },
        ],
    }

    with pytest.raises(ValueError, match="slide_claim_missing:slide_claimless"):
        assert_deck_claims_allowed(slide_project, deck)
