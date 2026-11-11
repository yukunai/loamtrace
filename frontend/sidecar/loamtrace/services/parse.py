from __future__ import annotations

from loamtrace.services.documents import get_document
from loamtrace.services.docx_parser import parse_docx
from loamtrace.services.pdf_parser import parse_pdf
from loamtrace.services.text_parser import parse_text_document
from loamtrace.services.xlsx_parser import parse_xlsx


def parse_document(project_id: str, document_id: str) -> dict:
    document = get_document(project_id, document_id)
    filename = document["filename"].lower()
    mime_type = document["mime_type"]
    if mime_type == "application/pdf" or filename.endswith(".pdf"):
        return parse_pdf(project_id, document_id)
    if (
        mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or filename.endswith(".docx")
    ):
        return parse_docx(project_id, document_id)
    if (
        mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        or filename.endswith(".xlsx")
    ):
        return parse_xlsx(project_id, document_id)
    if (
        mime_type in {"text/markdown", "text/x-markdown", "text/html", "text/plain"}
        or filename.endswith((".md", ".markdown", ".html", ".htm", ".txt"))
    ):
        return parse_text_document(project_id, document_id)
    raise ValueError("Unsupported document type. Parse support is PDF, DOCX, XLSX, Markdown, HTML, and TXT.")
