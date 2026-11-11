import json
import tempfile
import zipfile
from pathlib import Path

from docx import Document

from loamtrace import config
from loamtrace.db import connect
from loamtrace.services import documents
from loamtrace.services.docx_parser import parse_docx
from loamtrace.services.parse import parse_document
from loamtrace.services.source_targets import resolve_citation_target
from loamtrace.services.paths import project_db_path
from loamtrace.services.search import search_chunks
from loamtrace.services.xlsx_parser import parse_xlsx
from loamtrace.services.chart_data import generate_chart_data
from loamtrace.services.tables import list_tables


def test_parse_docx_creates_paragraph_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    path = tmp_path / "memo.docx"
    docx = Document()
    docx.add_heading("Financial Highlights", level=1)
    docx.add_paragraph("Revenue increased by 24% year over year in 2025.")
    docx.save(path)

    imported = documents.import_document("p1", str(path))
    result = parse_document("p1", imported["id"])

    assert result["paragraphs"] == 2
    assert result["chunks"] == 2
    results = search_chunks("p1", "Revenue 2025")
    assert len(results) == 1
    assert results[0]["source_uri"].startswith("docx://")
    assert "paragraph=" in results[0]["source_uri"]


def test_parse_docx_creates_table_cells_and_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    path = tmp_path / "memo.docx"
    docx = Document()
    table = docx.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Metric"
    table.cell(0, 1).text = "2025"
    table.cell(1, 0).text = "ARR"
    table.cell(1, 1).text = "120"
    docx.save(path)

    imported = documents.import_document("p1", str(path))
    result = parse_document("p1", imported["id"])

    assert result["paragraphs"] == 0
    assert result["tables"] == 1
    assert result["cells"] == 4
    assert result["chunks"] == 1
    results = search_chunks("p1", "ARR 2025")
    table_result = next(result for result in results if "ARR" in result["text"])
    assert table_result["chunk_type"] == "docx_table"
    assert table_result["source_uri"].startswith("docx://")
    assert "table=1" in table_result["source_uri"]
    assert table_result["cell_ids_json"]

    with connect(project_db_path("p1")) as conn:
        cells = conn.execute("select * from cells order by row_index asc, col_index asc").fetchall()
    assert [cell["cell_ref"] for cell in cells] == ["R1C1", "R1C2", "R2C1", "R2C2"]

    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.verifier import verify_claims

    verified = verify_claims(
        "p1",
        [
            ClaimInput(
                text="ARR was 120 in 2025.",
                citations=[CitationInput(chunk_id=table_result["id"], quote="| ARR | 120 |")],
            )
        ],
    )["claims"][0]
    assert verified["status"] == "verified"
    assert verified["citations"][0]["source_uri"] == table_result["source_uri"]


def test_parse_docx_table_matches_golden_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    path = tmp_path / "memo.docx"
    docx = Document()
    table = docx.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Metric"
    table.cell(0, 1).text = "2025"
    table.cell(1, 0).text = "ARR"
    table.cell(1, 1).text = "120"
    docx.save(path)

    imported = documents.import_document("p1", str(path))
    result = parse_docx("p1", imported["id"])

    with connect(project_db_path("p1")) as conn:
        cells = conn.execute("select * from cells order by row_index asc, col_index asc").fetchall()
        chunks = conn.execute("select * from chunks order by chunk_type asc").fetchall()

    actual = {
        "parse_result": {
            "paragraphs": result["paragraphs"],
            "tables": result["tables"],
            "cells": result["cells"],
            "chunks": result["chunks"],
            "status": result["status"],
        },
        "cells": [
            {
                "cell_ref": cell["cell_ref"],
                "row_index": cell["row_index"],
                "col_index": cell["col_index"],
                "text": cell["text"],
                "value_json": json.loads(cell["value_json"]),
            }
            for cell in cells
        ],
        "chunks": [
            {
                "chunk_type": chunk["chunk_type"],
                "text": chunk["text"],
                "source_fragment": chunk["source_uri"].split("#", 1)[1],
                "cell_count": len(json.loads(chunk["cell_ids_json"] or "[]")),
            }
            for chunk in chunks
        ],
    }
    expected_path = Path(__file__).parent / "fixtures" / "expected" / "docx_table_parse.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert actual == expected


def test_parse_xlsx_creates_cell_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    path = tmp_path / "model.xlsx"
    _write_minimal_xlsx(path)

    imported = documents.import_document("p1", str(path))
    result = parse_xlsx("p1", imported["id"])

    assert result["sheets"] == 1
    assert result["cells"] == 4
    assert result["chunks"] == 2
    results = search_chunks("p1", "Revenue 2025")
    assert len(results) >= 1
    revenue_result = next(result for result in results if "A2: Revenue" in result["text"])
    assert revenue_result["source_uri"].startswith("xlsx://")
    assert "sheet=Revenue" in revenue_result["source_uri"]

    with connect(project_db_path("p1")) as conn:
        cells = conn.execute("select * from cells order by cell_ref asc").fetchall()
        tables = conn.execute("select * from tables order by caption asc").fetchall()
    assert [cell["cell_ref"] for cell in cells] == ["A1", "A2", "B1", "B2"]
    assert len(tables) == 1
    assert tables[0]["caption"] == "Revenue"
    assert {cell["table_id"] for cell in cells} == {tables[0]["id"]}

    chart = generate_chart_data("p1", tables[0]["id"])["chart"]
    assert chart["review_status"] == "verified"
    assert chart["series"][0]["points"][0]["cell_id"]
    assert list_tables("p1")[0]["preview"] == [["Metric", "2025"], ["Revenue", "24"]]


def test_parse_xlsx_matches_golden_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    path = tmp_path / "model.xlsx"
    _write_minimal_xlsx(path)

    imported = documents.import_document("p1", str(path))
    result = parse_xlsx("p1", imported["id"])

    with connect(project_db_path("p1")) as conn:
        cells = conn.execute("select * from cells order by cell_ref asc").fetchall()
        chunks = conn.execute("select * from chunks order by source_uri asc").fetchall()

    actual = {
        "parse_result": {
            "sheets": result["sheets"],
            "cells": result["cells"],
            "chunks": result["chunks"],
            "status": result["status"],
        },
        "cells": [
            {
                "sheet_name": cell["sheet_name"],
                "cell_ref": cell["cell_ref"],
                "row_index": cell["row_index"],
                "col_index": cell["col_index"],
                "text": cell["text"],
                "value_json": json.loads(cell["value_json"]),
            }
            for cell in cells
        ],
        "chunks": [
            {
                "chunk_type": chunk["chunk_type"],
                "text": chunk["text"],
                "heading_path": chunk["heading_path"],
                "source_fragment": chunk["source_uri"].split("#", 1)[1],
                "cell_count": len(json.loads(chunk["cell_ids_json"] or "[]")),
            }
            for chunk in chunks
        ],
    }
    expected_path = Path(__file__).parent / "fixtures" / "expected" / "xlsx_row_parse.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert actual == expected


def test_parse_xlsx_url_encodes_sheet_name_in_source_uri(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    path = tmp_path / "model.xlsx"
    _write_minimal_xlsx(path, sheet_name="P&L Q1")

    imported = documents.import_document("p1", str(path))
    parse_xlsx("p1", imported["id"])

    results = search_chunks("p1", "Revenue")
    revenue_result = next(result for result in results if "A2: Revenue" in result["text"])
    assert "sheet=P%26L%20Q1" in revenue_result["source_uri"]
    assert "sheet=P&L Q1" not in revenue_result["source_uri"]


def test_parse_markdown_creates_block_chunks_and_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    path = tmp_path / "web_export.md"
    path.write_text(
        "# Market Overview\n\nRevenue increased by 24% in 2025.\n\n## Risk Factors\n\nCustomer concentration reached 41% of revenue.",
        encoding="utf-8",
    )

    imported = documents.import_document("p1", str(path))
    result = parse_document("p1", imported["id"])

    assert result["kind"] == "md"
    assert result["blocks"] == 4
    results = search_chunks("p1", "Customer concentration 41%")
    risk_result = next(result for result in results if "Customer concentration" in result["text"])
    assert risk_result["source_uri"].startswith("md://")
    assert "heading=Risk%20Factors" in risk_result["source_uri"]
    assert "block=" in risk_result["source_uri"]

    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.verifier import verify_claims

    verified = verify_claims(
        "p1",
        [
            ClaimInput(
                text="Customer concentration reached 41% of revenue.",
                citations=[CitationInput(chunk_id=risk_result["id"], quote="Customer concentration reached 41% of revenue.")],
            )
        ],
    )["claims"][0]
    assert verified["status"] == "verified"
    target = resolve_citation_target("p1", verified["citations"][0]["id"])
    assert target["scheme"] == "md"
    assert target["precision"] == "block"
    assert target["renderable"] is False
    assert target["block"]["heading_path"] == "Risk Factors"


def test_parse_html_creates_block_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    path = tmp_path / "export.html"
    path.write_text(
        "<html><body><h1>Risk Factors</h1><p>Liquidity risk increased after negative cash flow.</p></body></html>",
        encoding="utf-8",
    )

    imported = documents.import_document("p1", str(path))
    result = parse_document("p1", imported["id"])

    assert result["kind"] == "html"
    results = search_chunks("p1", "Liquidity risk cash flow")
    html_result = next(result for result in results if "Liquidity risk" in result["text"])
    assert html_result["source_uri"].startswith("html://")
    assert "heading=Risk%20Factors" in html_result["source_uri"]


def test_parse_text_creates_plain_text_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")
    path = tmp_path / "notes.txt"
    path.write_text("ARR was 120 in 2025.\n\nGross margin was 72%.", encoding="utf-8")

    imported = documents.import_document("p1", str(path))
    result = parse_document("p1", imported["id"])

    assert result["kind"] == "text"
    assert result["blocks"] == 2
    results = search_chunks("p1", "Gross margin 72")
    text_result = next(result for result in results if "Gross margin" in result["text"])
    assert text_result["source_uri"].startswith("text://")

    from loamtrace.models import CitationInput, ClaimInput
    from loamtrace.services.verifier import verify_claims

    verified = verify_claims(
        "p1",
        [
            ClaimInput(
                text="Gross margin was 72%.",
                citations=[
                    CitationInput(
                        chunk_id=text_result["id"],
                        quote="Gross margin was 72%.",
                        source_uri=text_result["source_uri"],
                    )
                ],
            )
        ],
    )["claims"][0]
    assert verified["status"] == "verified"
    assert verified["citations"][0]["source_uri"].startswith("text://")


def _write_minimal_xlsx(path: Path, sheet_name: str = "Revenue") -> None:
    sheet_xml_name = sheet_name.replace("&", "&amp;").replace('"', "&quot;")
    files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        "xl/workbook.xml": f"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="{sheet_xml_name}" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        "xl/worksheets/sheet1.xml": """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>Metric</t></is></c>
      <c r="B1" t="inlineStr"><is><t>2025</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>Revenue</t></is></c>
      <c r="B2"><v>24</v></c>
    </row>
  </sheetData>
</worksheet>""",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
