import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from urllib.parse import parse_qs
from loamtrace.services import pdf_parser, documents
from loamtrace import config
import tempfile

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

@patch("pdfplumber.open")
@patch("pypdfium2.PdfDocument")
def test_parse_pdf(mock_pdfium, mock_plumber_open, tmp_workspace):
    project_id = "p1"
    # Create a dummy pdf file record
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(b"%PDF-1.4 dummy")
        tf_path = tf.name
    
    doc = documents.import_document(project_id, tf_path)
    document_id = doc["id"]
    
    # Setup mock pdfplumber
    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.width = 100
    mock_page.height = 200
    mock_page.extract_text.return_value = "Hello World"
    mock_page.extract_words.return_value = [
        {"text": "Hello", "x0": 10, "top": 10, "x1": 40, "bottom": 20},
        {"text": "World", "x0": 50, "top": 10, "x1": 80, "bottom": 20},
    ]
    mock_pdf.pages = [mock_page]
    mock_plumber_open.return_value.__enter__.return_value = mock_pdf
    
    # Setup mock pdfium (for rendering)
    mock_pdfium_doc = MagicMock()
    mock_pdfium.return_value = mock_pdfium_doc
    
    result = pdf_parser.parse_pdf(project_id, document_id)
    
    assert result["status"] == "parsed"
    assert result["pages"] == 1
    assert result["words"] == 2
    
    # Check if database is populated
    from loamtrace.db import connect
    from loamtrace.services.paths import project_db_path
    with connect(project_db_path(project_id)) as conn:
        pages = conn.execute("select * from pages where document_id = ?", (document_id,)).fetchall()
        assert len(pages) == 1
        
        words = conn.execute("select * from words where document_id = ?", (document_id,)).fetchall()
        assert len(words) == 2
        assert words[0]["text"] == "Hello"
        
        chunks = conn.execute("select * from chunks where document_id = ?", (document_id,)).fetchall()
        assert len(chunks) >= 1


@patch("pdfplumber.open")
@patch("pypdfium2.PdfDocument")
def test_parse_pdf_text_layer_matches_golden_snapshot(mock_pdfium, mock_plumber_open, tmp_workspace):
    project_id = "p1"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(b"%PDF-1.4 text")
        tf_path = tf.name

    doc = documents.import_document(project_id, tf_path)
    document_id = doc["id"]

    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.width = 100
    mock_page.height = 200
    mock_page.extract_text.return_value = "Hello World"
    mock_page.extract_words.return_value = [
        {"text": "Hello", "x0": 10, "top": 10, "x1": 40, "bottom": 20},
        {"text": "World", "x0": 50, "top": 10, "x1": 80, "bottom": 20},
    ]
    mock_pdf.pages = [mock_page]
    mock_plumber_open.return_value.__enter__.return_value = mock_pdf
    mock_pdfium.return_value = MagicMock()

    result = pdf_parser.parse_pdf(project_id, document_id)

    from loamtrace.db import connect
    from loamtrace.services.paths import project_db_path

    with connect(project_db_path(project_id)) as conn:
        pages = conn.execute("select * from pages where document_id = ?", (document_id,)).fetchall()
        words = conn.execute("select * from words where document_id = ? order by word_index", (document_id,)).fetchall()
        chunks = conn.execute("select * from chunks where document_id = ? order by chunk_type", (document_id,)).fetchall()

    fragment = chunks[0]["source_uri"].split("#", 1)[1]
    params = parse_qs(fragment)
    actual = {
        "parse_result": {
            "pages": result["pages"],
            "words": result["words"],
            "tables": result["tables"],
            "cells": result["cells"],
            "chunks": result["chunks"],
            "status": result["status"],
            "ocr_used": result["ocr_used"],
            "reason": result["reason"],
        },
        "pages": [
            {
                "page_number": page["page_number"],
                "width": page["width"],
                "height": page["height"],
                "text_layer_available": page["text_layer_available"],
            }
            for page in pages
        ],
        "words": [
            {
                "text": word["text"],
                "char_start": word["char_start"],
                "char_end": word["char_end"],
                "bbox_json": json.loads(word["bbox_json"]),
                "word_index": word["word_index"],
            }
            for word in words
        ],
        "chunks": [
            {
                "chunk_type": chunks[0]["chunk_type"],
                "text": chunks[0]["text"],
                "token_count": chunks[0]["token_count"],
                "page_start": chunks[0]["page_start"],
                "page_end": chunks[0]["page_end"],
                "bbox_json": json.loads(chunks[0]["bbox_json"]),
                "source_params": {
                    "page": params.get("page", [None])[0],
                    "has_chunk": bool(params.get("chunk")),
                },
                "word_count": len(json.loads(chunks[0]["word_ids_json"] or "[]")),
            }
        ],
    }
    expected_path = Path(__file__).parent / "fixtures" / "expected" / "pdf_text_layer_parse.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert actual == expected


@patch("pdfplumber.open")
@patch("pypdfium2.PdfDocument")
def test_parse_pdf_extracts_tables_and_cells(mock_pdfium, mock_plumber_open, tmp_workspace):
    project_id = "p1"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(b"%PDF-1.4 table")
        tf_path = tf.name

    doc = documents.import_document(project_id, tf_path)
    document_id = doc["id"]

    mock_table = MagicMock()
    mock_table.bbox = (10, 20, 90, 80)
    mock_table.extract.return_value = [
        ["Metric", "2025"],
        ["Revenue", "24%"],
    ]

    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.width = 100
    mock_page.height = 200
    mock_page.extract_text.return_value = "Metric 2025 Revenue 24%"
    mock_page.extract_words.return_value = []
    mock_page.find_tables.return_value = [mock_table]
    mock_pdf.pages = [mock_page]
    mock_plumber_open.return_value.__enter__.return_value = mock_pdf
    mock_pdfium.return_value = MagicMock()

    result = pdf_parser.parse_pdf(project_id, document_id)

    assert result["status"] == "parsed"
    assert result["words"] == 0
    assert result["tables"] == 1
    assert result["cells"] == 4
    assert result["chunks"] == 1

    from loamtrace.db import connect
    from loamtrace.services.paths import project_db_path

    with connect(project_db_path(project_id)) as conn:
        tables = conn.execute("select * from tables where document_id = ?", (document_id,)).fetchall()
        cells = conn.execute("select * from cells where document_id = ? order by row_index, col_index", (document_id,)).fetchall()
        chunks = conn.execute("select * from chunks where document_id = ?", (document_id,)).fetchall()

    assert len(tables) == 1
    assert pdf_parser.json.loads(tables[0]["bbox_json"]) == {
        "page": 1,
        "x0": 0.1,
        "y0": 0.1,
        "x1": 0.9,
        "y1": 0.4,
    }
    assert [cell["text"] for cell in cells] == ["Metric", "2025", "Revenue", "24%"]
    assert chunks[0]["chunk_type"] == "pdf_table"
    assert "| Metric | 2025 |" in chunks[0]["text"]
    assert "table=" in chunks[0]["source_uri"]
    assert len(pdf_parser.json.loads(chunks[0]["cell_ids_json"])) == 4


@patch("pdfplumber.open")
@patch("pypdfium2.PdfDocument")
def test_parse_pdf_table_matches_golden_snapshot(mock_pdfium, mock_plumber_open, tmp_workspace):
    project_id = "p1"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(b"%PDF-1.4 table")
        tf_path = tf.name

    doc = documents.import_document(project_id, tf_path)
    document_id = doc["id"]

    mock_table = MagicMock()
    mock_table.bbox = (10, 20, 90, 80)
    mock_table.extract.return_value = [
        ["Metric", "2025"],
        ["Revenue", "24%"],
    ]

    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.width = 100
    mock_page.height = 200
    mock_page.extract_text.return_value = "Metric 2025 Revenue 24%"
    mock_page.extract_words.return_value = []
    mock_page.find_tables.return_value = [mock_table]
    mock_pdf.pages = [mock_page]
    mock_plumber_open.return_value.__enter__.return_value = mock_pdf
    mock_pdfium.return_value = MagicMock()

    result = pdf_parser.parse_pdf(project_id, document_id)

    from loamtrace.db import connect
    from loamtrace.services.paths import project_db_path

    with connect(project_db_path(project_id)) as conn:
        tables = conn.execute("select * from tables where document_id = ?", (document_id,)).fetchall()
        cells = conn.execute("select * from cells where document_id = ? order by row_index, col_index", (document_id,)).fetchall()
        chunks = conn.execute("select * from chunks where document_id = ? order by chunk_type", (document_id,)).fetchall()

    fragment = chunks[0]["source_uri"].split("#", 1)[1]
    params = parse_qs(fragment)
    actual = {
        "parse_result": {
            "pages": result["pages"],
            "words": result["words"],
            "tables": result["tables"],
            "cells": result["cells"],
            "chunks": result["chunks"],
            "status": result["status"],
            "ocr_used": result["ocr_used"],
            "reason": result["reason"],
        },
        "tables": [
            {
                "bbox_json": json.loads(table["bbox_json"]),
                "parser": table["parser"],
            }
            for table in tables
        ],
        "cells": [
            {
                "row_index": cell["row_index"],
                "col_index": cell["col_index"],
                "text": cell["text"],
                "value_json": json.loads(cell["value_json"]),
            }
            for cell in cells
        ],
        "chunks": [
            {
                "chunk_type": chunks[0]["chunk_type"],
                "text": chunks[0]["text"],
                "page_start": chunks[0]["page_start"],
                "page_end": chunks[0]["page_end"],
                "source_params": {
                    "page": params.get("page", [None])[0],
                    "has_table": bool(params.get("table")),
                    "has_chunk": bool(params.get("chunk")),
                },
                "cell_count": len(json.loads(chunks[0]["cell_ids_json"] or "[]")),
            }
        ],
    }
    expected_path = Path(__file__).parent / "fixtures" / "expected" / "pdf_table_parse.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert actual == expected


@patch("pdfplumber.open")
@patch("pypdfium2.PdfDocument")
def test_parse_pdf_without_text_layer_requires_ocr(mock_pdfium, mock_plumber_open, tmp_workspace):
    project_id = "p1"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(b"%PDF-1.4 scanned")
        tf_path = tf.name

    doc = documents.import_document(project_id, tf_path)
    document_id = doc["id"]

    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.width = 100
    mock_page.height = 200
    mock_page.extract_text.return_value = ""
    mock_page.extract_words.return_value = []
    mock_pdf.pages = [mock_page]
    mock_plumber_open.return_value.__enter__.return_value = mock_pdf
    mock_pdfium.return_value = MagicMock()

    result = pdf_parser.parse_pdf(project_id, document_id)

    assert result["status"] == "failed"
    assert result["reason"] == "ocr_required"
    assert result["pages"] == 1
    assert result["words"] == 0
    assert result["chunks"] == 0

    from loamtrace.db import connect
    from loamtrace.services.paths import project_db_path

    with connect(project_db_path(project_id)) as conn:
        document = conn.execute("select * from documents where id = ?", (document_id,)).fetchone()
        assert document["status"] == "failed"
        assert document["ocr_used"] == 0

        page = conn.execute("select * from pages where document_id = ?", (document_id,)).fetchone()
        assert page["text_layer_available"] == 0

        chunks = conn.execute("select * from chunks where document_id = ?", (document_id,)).fetchall()
        assert chunks == []

        audit = conn.execute("select * from audit_log where type = ?", ("pdf_ocr_required",)).fetchone()
        assert audit is not None

    listed = documents.list_documents(project_id)
    assert listed[0]["ocr_required"] is True
    detailed = documents.get_document(project_id, document_id)
    assert detailed["ocr_required"] is True


@patch("pdfplumber.open")
@patch("pypdfium2.PdfDocument")
def test_parse_pdf_scanned_requires_ocr_matches_golden_snapshot(mock_pdfium, mock_plumber_open, tmp_workspace):
    project_id = "p1"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(b"%PDF-1.4 scanned")
        tf_path = tf.name

    doc = documents.import_document(project_id, tf_path)
    document_id = doc["id"]

    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.width = 100
    mock_page.height = 200
    mock_page.extract_text.return_value = ""
    mock_page.extract_words.return_value = []
    mock_pdf.pages = [mock_page]
    mock_plumber_open.return_value.__enter__.return_value = mock_pdf
    mock_pdfium.return_value = MagicMock()

    result = pdf_parser.parse_pdf(project_id, document_id)

    from loamtrace.db import connect
    from loamtrace.services.paths import project_db_path

    with connect(project_db_path(project_id)) as conn:
        document = conn.execute("select * from documents where id = ?", (document_id,)).fetchone()
        pages = conn.execute("select * from pages where document_id = ?", (document_id,)).fetchall()
        chunks = conn.execute("select * from chunks where document_id = ?", (document_id,)).fetchall()
        audit = conn.execute("select * from audit_log where type = ?", ("pdf_ocr_required",)).fetchall()

    listed = documents.list_documents(project_id)
    actual = {
        "parse_result": {
            "pages": result["pages"],
            "words": result["words"],
            "tables": result["tables"],
            "cells": result["cells"],
            "chunks": result["chunks"],
            "status": result["status"],
            "ocr_used": result["ocr_used"],
            "reason": result["reason"],
        },
        "document": {
            "status": document["status"],
            "ocr_used": document["ocr_used"],
            "ocr_required": listed[0]["ocr_required"],
        },
        "pages": [
            {
                "page_number": page["page_number"],
                "width": page["width"],
                "height": page["height"],
                "text_layer_available": page["text_layer_available"],
            }
            for page in pages
        ],
        "chunks": len(chunks),
        "audit_events": [row["type"] for row in audit],
    }
    expected_path = Path(__file__).parent / "fixtures" / "expected" / "pdf_scanned_ocr_required.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert actual == expected


@patch("loamtrace.services.pdf_parser._ocr_words_for_page", return_value=[])
@patch("loamtrace.services.pdf_parser._ocr_text_for_page", return_value="Revenue grew 24% in 2025.")
@patch("pdfplumber.open")
@patch("pypdfium2.PdfDocument")
def test_parse_pdf_without_text_layer_uses_optional_ocr(
    mock_pdfium,
    mock_plumber_open,
    mock_ocr_text,
    mock_ocr_words,
    tmp_workspace,
):
    project_id = "p1"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(b"%PDF-1.4 scanned")
        tf_path = tf.name

    doc = documents.import_document(project_id, tf_path)
    document_id = doc["id"]

    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.width = 100
    mock_page.height = 200
    mock_page.extract_text.return_value = ""
    mock_page.extract_words.return_value = []
    mock_pdf.pages = [mock_page]
    mock_plumber_open.return_value.__enter__.return_value = mock_pdf
    mock_pdfium.return_value = MagicMock()

    result = pdf_parser.parse_pdf(project_id, document_id)

    assert result["status"] == "parsed"
    assert result["reason"] is None
    assert result["ocr_used"] is True
    assert result["words"] == 5
    assert result["chunks"] >= 1
    mock_ocr_text.assert_called_once()
    mock_ocr_words.assert_called_once()

    from loamtrace.db import connect
    from loamtrace.services.paths import project_db_path

    with connect(project_db_path(project_id)) as conn:
        document = conn.execute("select * from documents where id = ?", (document_id,)).fetchone()
        assert document["status"] == "parsed"
        assert document["ocr_used"] == 1
        assert document["ocr_confidence"] is None

        page = conn.execute("select * from pages where document_id = ?", (document_id,)).fetchone()
        assert page["text_layer_available"] == 0

        chunks = conn.execute("select * from chunks where document_id = ?", (document_id,)).fetchall()
        assert chunks
        assert "Revenue grew 24%" in chunks[0]["text"]

        audit = conn.execute("select * from audit_log where type = ?", ("pdf_ocr_applied",)).fetchone()
        assert audit is not None

    listed = documents.list_documents(project_id)
    assert listed[0]["ocr_required"] is False


@patch(
    "loamtrace.services.pdf_parser._ocr_words_for_page",
    return_value=[
        {"text": "Revenue", "x0": 10, "top": 20, "x1": 70, "bottom": 35},
        {"text": "grew", "x0": 75, "top": 20, "x1": 110, "bottom": 35},
    ],
)
@patch("loamtrace.services.pdf_parser._ocr_text_for_page", return_value="Revenue grew")
@patch("pdfplumber.open")
@patch("pypdfium2.PdfDocument")
def test_parse_pdf_ocr_uses_tesseract_word_boxes(
    mock_pdfium,
    mock_plumber_open,
    mock_ocr_text,
    mock_ocr_words,
    tmp_workspace,
):
    project_id = "p1"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(b"%PDF-1.4 scanned")
        tf_path = tf.name

    doc = documents.import_document(project_id, tf_path)
    document_id = doc["id"]

    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.width = 100
    mock_page.height = 200
    mock_page.extract_text.return_value = ""
    mock_page.extract_words.return_value = []
    mock_pdf.pages = [mock_page]
    mock_plumber_open.return_value.__enter__.return_value = mock_pdf
    mock_pdfium.return_value = MagicMock()

    result = pdf_parser.parse_pdf(project_id, document_id)

    assert result["status"] == "parsed"
    assert result["words"] == 2
    mock_ocr_text.assert_called_once()
    mock_ocr_words.assert_called_once()

    from loamtrace.db import connect
    from loamtrace.services.paths import project_db_path

    with connect(project_db_path(project_id)) as conn:
        document = conn.execute("select * from documents where id = ?", (document_id,)).fetchone()
        assert document["ocr_confidence"] is None
        row = conn.execute(
            "select bbox_json from words where document_id = ? and text = ?",
            (document_id, "Revenue"),
        ).fetchone()

    bbox = pdf_parser.json.loads(row["bbox_json"])
    assert bbox["x0"] == 0.1
    assert bbox["y0"] == 0.1
    assert bbox["x1"] == 0.7
    assert bbox["y1"] == 0.175


@patch(
    "loamtrace.services.pdf_parser._ocr_words_for_page",
    return_value=[
        {"text": "Revenue", "x0": 10, "top": 20, "x1": 70, "bottom": 35, "ocr_confidence": 55.0},
        {"text": "grew", "x0": 75, "top": 20, "x1": 110, "bottom": 35, "ocr_confidence": 65.0},
    ],
)
@patch("loamtrace.services.pdf_parser._ocr_text_for_page", return_value="Revenue grew")
@patch("pdfplumber.open")
@patch("pypdfium2.PdfDocument")
def test_parse_pdf_ocr_persists_average_confidence(
    mock_pdfium,
    mock_plumber_open,
    mock_ocr_text,
    mock_ocr_words,
    tmp_workspace,
):
    project_id = "p1"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(b"%PDF-1.4 scanned")
        tf_path = tf.name

    doc = documents.import_document(project_id, tf_path)
    document_id = doc["id"]

    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.width = 100
    mock_page.height = 200
    mock_page.extract_text.return_value = ""
    mock_page.extract_words.return_value = []
    mock_pdf.pages = [mock_page]
    mock_plumber_open.return_value.__enter__.return_value = mock_pdf
    mock_pdfium.return_value = MagicMock()

    result = pdf_parser.parse_pdf(project_id, document_id)

    assert result["ocr_confidence"] == 60.0
    from loamtrace.db import connect
    from loamtrace.services.paths import project_db_path

    with connect(project_db_path(project_id)) as conn:
        document = conn.execute("select * from documents where id = ?", (document_id,)).fetchone()
        assert document["ocr_confidence"] == 60.0
        audit = conn.execute("select * from audit_log where type = ?", ("pdf_ocr_applied",)).fetchone()
        assert pdf_parser.json.loads(audit["payload_json"])["ocr_confidence"] == 60.0


def test_parse_tesseract_tsv_scales_word_boxes():
    tsv = "\n".join(
        [
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t30\t60\t90\t30\t96\tRevenue",
            "5\t1\t1\t1\t1\t2\t130\t60\t40\t30\t91\tgrew",
            "5\t1\t1\t1\t1\t3\t0\t0\t0\t0\t-1\t",
        ]
    )

    words = pdf_parser._parse_tesseract_tsv(
        tsv,
        page_width=100,
        page_height=200,
        image_width=300,
        image_height=600,
    )

    assert words[0] == {
        "text": "Revenue",
        "x0": 10.0,
        "top": 20.0,
        "x1": 40.0,
        "bottom": 30.0,
        "ocr_confidence": 96.0,
    }
    assert words[1]["text"] == "grew"
    assert words[1]["ocr_confidence"] == 91.0
    assert words[1]["x0"] == pytest.approx(43.333333333333336)
    assert words[1]["top"] == 20.0
    assert words[1]["x1"] == pytest.approx(56.66666666666667)
    assert words[1]["bottom"] == 30.0


def test_tesseract_image_path_converts_png_to_tiff(tmp_path):
    from PIL import Image

    png_path = tmp_path / "page.png"
    Image.new("RGB", (20, 20), "white").save(png_path)

    ocr_path = pdf_parser._tesseract_image_path(png_path)

    assert ocr_path != png_path
    assert ocr_path.suffix == ".tif"
    assert ocr_path.exists()

    pdf_parser._remove_temp_ocr_path(png_path, ocr_path)
    assert not ocr_path.exists()
