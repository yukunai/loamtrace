from __future__ import annotations

from typing import Optional

from loamtrace.db import connect
from loamtrace.services.paths import ensure_project, project_db_path, project_root


def workflow_status(project_id: str) -> dict:
    root = ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        documents = _count(conn, "documents")
        parsed_documents = conn.execute(
            "select count(*) from documents where status = ?",
            ("parsed",),
        ).fetchone()[0]
        failed_documents = conn.execute(
            "select count(*) from documents where status = ?",
            ("failed",),
        ).fetchone()[0]
        chunks = _count(conn, "chunks")
        claims = _count(conn, "claims")
        verified_claims = conn.execute(
            "select count(*) from claims where status in (?, ?)",
            ("verified", "approved"),
        ).fetchone()[0]
        review_claims = conn.execute(
            "select count(*) from claims where status in (?, ?, ?)",
            ("needs_review", "blocked", "rejected"),
        ).fetchone()[0]
        citations = _count(conn, "citations")
        failed_citations = conn.execute(
            "select count(*) from citations where verified = 0",
        ).fetchone()[0]
        manual_approved_citations = conn.execute(
            "select count(*) from citations where verification_method = ?",
            ("manual_approved",),
        ).fetchone()[0]
        active_review_tasks = conn.execute(
            "select count(*) from review_tasks where status in (?, ?)",
            ("open", "in_review"),
        ).fetchone()[0]
        latest_audit = conn.execute(
            "select ts, type, payload_json from audit_log order by ts desc limit 1",
        ).fetchone()
        slides = len(list((root / "slides").glob("*.slide.json")))
        pptx_exports = len(list((root / "slides").glob("*.pptx")))
        research_packages = len([path for path in (root / "exports").iterdir() if path.is_dir()])
        research_package_archives = len(list((root / "exports").glob("*.zip")))

    steps = [
        _step("project", "Project", "complete", "Project workspace is ready."),
        _step(
            "import",
            "Import",
            "complete" if documents else "not_started",
            f"{documents} document(s) imported.",
            {"documents": documents},
        ),
        _step(
            "parse",
            "Parse / OCR",
            _parse_state(documents, parsed_documents, failed_documents),
            f"{parsed_documents}/{documents} document(s) parsed.",
            {"documents": documents, "parsed_documents": parsed_documents, "failed_documents": failed_documents},
        ),
        _step(
            "evidence",
            "Evidence Index",
            "complete" if chunks else ("blocked" if failed_documents and not chunks else "not_started"),
            f"{chunks} evidence chunk(s) indexed.",
            {"chunks": chunks},
        ),
        _step(
            "memo",
            "Memo",
            "complete" if claims else ("ready" if chunks else "not_started"),
            f"{claims} claim(s), {verified_claims} verified.",
            {"claims": claims, "verified_claims": verified_claims},
        ),
        _step(
            "review",
            "Claim Review",
            _review_state(claims, verified_claims, review_claims, active_review_tasks),
            _review_detail(review_claims, failed_citations, active_review_tasks),
            {
                "claims": claims,
                "verified_claims": verified_claims,
                "review_claims": review_claims,
                "citations": citations,
                "failed_citations": failed_citations,
                "manual_approved_citations": manual_approved_citations,
                "active_review_tasks": active_review_tasks,
            },
        ),
        _step(
            "slides",
            "Slides",
            "complete" if slides else ("ready" if verified_claims else "not_started"),
            f"{slides} deck(s) generated.",
            {"decks": slides},
        ),
        _step(
            "export",
            "Export",
            "complete" if pptx_exports or research_packages or research_package_archives else ("ready" if slides else "not_started"),
            (
                f"{pptx_exports} PPTX export(s), {research_packages} research package(s), "
                f"{research_package_archives} ZIP archive(s)."
            ),
            {
                "pptx_exports": pptx_exports,
                "research_packages": research_packages,
                "research_package_archives": research_package_archives,
            },
        ),
    ]
    return {
        "project_id": project_id,
        "overall_status": _overall_status(steps),
        "steps": steps,
        "counts": {
            "documents": documents,
            "parsed_documents": parsed_documents,
            "failed_documents": failed_documents,
            "chunks": chunks,
            "claims": claims,
            "verified_claims": verified_claims,
            "review_claims": review_claims,
            "citations": citations,
            "failed_citations": failed_citations,
            "manual_approved_citations": manual_approved_citations,
            "active_review_tasks": active_review_tasks,
            "decks": slides,
            "pptx_exports": pptx_exports,
            "research_packages": research_packages,
            "research_package_archives": research_package_archives,
        },
        "blockers": _blockers(failed_documents, failed_citations, review_claims, active_review_tasks),
        "next_actions": _next_actions(
            documents,
            parsed_documents,
            failed_documents,
            chunks,
            claims,
            verified_claims,
            review_claims,
            active_review_tasks,
            slides,
            pptx_exports,
            research_packages,
            research_package_archives,
        ),
        "latest_audit": dict(latest_audit) if latest_audit else None,
    }


def _count(conn, table: str) -> int:
    return conn.execute(f"select count(*) from {table}").fetchone()[0]


def _step(key: str, label: str, status: str, detail: str, counts: Optional[dict] = None) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail, "counts": counts or {}}


def _parse_state(documents: int, parsed_documents: int, failed_documents: int) -> str:
    if not documents:
        return "not_started"
    if failed_documents:
        return "needs_review"
    if parsed_documents == documents:
        return "complete"
    if parsed_documents:
        return "in_progress"
    return "ready"


def _review_state(claims: int, verified_claims: int, review_claims: int, active_review_tasks: int = 0) -> str:
    if not claims:
        return "not_started"
    if review_claims or active_review_tasks:
        return "needs_review"
    if verified_claims:
        return "complete"
    return "blocked"


def _overall_status(steps: list[dict]) -> str:
    statuses = {step["status"] for step in steps}
    if "blocked" in statuses:
        return "blocked"
    if "needs_review" in statuses:
        return "needs_review"
    if all(step["status"] == "complete" for step in steps):
        return "complete"
    return "in_progress"


def _review_detail(review_claims: int, failed_citations: int, active_review_tasks: int) -> str:
    parts = [f"{review_claims} claim(s) need review"]
    if failed_citations:
        parts.append(f"{failed_citations} failed citation(s)")
    if active_review_tasks:
        parts.append(f"{active_review_tasks} active review task(s)")
    return ", ".join(parts) + "."


def _blockers(
    failed_documents: int,
    failed_citations: int,
    review_claims: int,
    active_review_tasks: int,
) -> list[dict]:
    blockers = []
    if failed_documents:
        blockers.append(
            {
                "key": "failed_documents",
                "severity": "needs_review",
                "message": f"{failed_documents} document(s) failed parsing or OCR.",
            }
        )
    if failed_citations:
        blockers.append(
            {
                "key": "failed_citations",
                "severity": "blocked",
                "message": f"{failed_citations} citation(s) failed verification.",
            }
        )
    if review_claims:
        blockers.append(
            {
                "key": "review_claims",
                "severity": "needs_review",
                "message": f"{review_claims} claim(s) are blocked, rejected, or need review.",
            }
        )
    if active_review_tasks:
        blockers.append(
            {
                "key": "active_review_tasks",
                "severity": "needs_review",
                "message": f"{active_review_tasks} review task(s) are still open or in review.",
            }
        )
    return blockers


def _next_actions(
    documents: int,
    parsed_documents: int,
    failed_documents: int,
    chunks: int,
    claims: int,
    verified_claims: int,
    review_claims: int,
    active_review_tasks: int,
    slides: int,
    pptx_exports: int,
    research_packages: int,
    research_package_archives: int,
) -> list[dict]:
    actions = []
    if not documents and not (chunks or claims or slides):
        actions.append({"key": "import_document", "label": "Import source documents", "step": "import"})
        return actions
    if failed_documents:
        actions.append({"key": "review_parse_failures", "label": "Review failed document parsing/OCR", "step": "parse"})
    if parsed_documents < documents:
        actions.append({"key": "parse_documents", "label": "Parse imported documents", "step": "parse"})
    if parsed_documents and not chunks:
        actions.append({"key": "rebuild_evidence_index", "label": "Rebuild evidence chunks/index", "step": "evidence"})
    if chunks and not claims:
        actions.append({"key": "generate_memo", "label": "Generate source-grounded memo claims", "step": "memo"})
    if review_claims or active_review_tasks:
        actions.append({"key": "review_claims", "label": "Review blocked or pending claims/citations", "step": "review"})
    if verified_claims and not slides:
        actions.append({"key": "generate_slides", "label": "Generate slide deck from verified claims", "step": "slides"})
    if slides and not (pptx_exports or research_packages or research_package_archives):
        actions.append({"key": "export_package", "label": "Export PPTX or research package", "step": "export"})
    return actions
