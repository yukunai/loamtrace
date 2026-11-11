import zipfile
from pathlib import Path

from docx import Document

from loamtrace import config
from loamtrace.models import CitationInput, ClaimInput
from loamtrace.services.documents import import_document
from loamtrace.services.parse import parse_document
from loamtrace.services.search import search_chunks
from loamtrace.services.verifier import render_memo, verify_claims


def test_docx_real_sample_e2e(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")

    source = tmp_path / "sample_memo.docx"
    docx = Document()
    docx.add_heading("Financial Highlights", level=1)
    docx.add_paragraph("Revenue increased by 24% year over year in 2025.")
    docx.save(source)

    imported = import_document("real_docx", str(source))
    parse_result = parse_document("real_docx", imported["id"])
    results = search_chunks("real_docx", "Revenue 2025")

    assert parse_result["status"] == "parsed"
    assert results
    evidence = next(result for result in results if "24%" in result["text"])

    verified = verify_claims(
        "real_docx",
        [
            ClaimInput(
                text="Revenue increased by 24% year over year in 2025.",
                citations=[
                    CitationInput(
                        chunk_id=evidence["id"],
                        quote="Revenue increased by 24% year over year in 2025.",
                    )
                ],
            )
        ],
    )

    assert verified["claims"][0]["status"] == "verified"
    assert verified["claims"][0]["citations"][0]["source_uri"].startswith("docx://")
    assert "Revenue increased by 24%" in render_memo("real_docx")["markdown"]


def test_xlsx_real_sample_e2e_blocks_bad_number(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_ROOT", tmp_path / "projects")

    source = tmp_path / "sample_model.xlsx"
    _write_xlsx(source)

    imported = import_document("real_xlsx", str(source))
    parse_result = parse_document("real_xlsx", imported["id"])
    results = search_chunks("real_xlsx", "Revenue")

    assert parse_result["status"] == "parsed"
    assert results
    evidence = next(result for result in results if "A2: Revenue" in result["text"])
    assert evidence["source_uri"].startswith("xlsx://")

    checked = verify_claims(
        "real_xlsx",
        [
            ClaimInput(
                text="Revenue was 24.",
                citations=[CitationInput(chunk_id=evidence["id"], quote="A2: Revenue | B2: 24")],
            ),
            ClaimInput(
                text="Revenue was 38.",
                citations=[CitationInput(chunk_id=evidence["id"], quote="A2: Revenue | B2: 24")],
            ),
        ],
    )

    assert checked["claims"][0]["status"] == "verified"
    assert checked["claims"][1]["status"] == "blocked"
    assert checked["claims"][1]["citations"][0]["failure_reason"] == "number_not_found"

    memo = render_memo("real_xlsx")["markdown"]
    assert "Revenue was 24." in memo
    assert "Revenue was 38." not in memo


def _write_xlsx(path: Path) -> None:
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
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Revenue" sheetId="1" r:id="rId1"/></sheets>
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
      <c r="B1" t="inlineStr"><is><t>Value</t></is></c>
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
