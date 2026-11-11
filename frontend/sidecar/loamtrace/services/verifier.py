from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from loamtrace.db import connect
from loamtrace.models import ClaimInput
from loamtrace.services.audit import write_audit, write_run_artifacts
from loamtrace.services.geometry import bbox_union
from loamtrace.services.paths import ensure_project, project_db_path, project_root
from loamtrace.services.search import get_chunk
from loamtrace.services.time import now_iso


NUMBER_RE = re.compile(
    r"""
    (?<![\w.])
    (?:[$¥€]|USD|RMB|CNY|EUR|GBP)?\s*
    -?\d[\d,]*(?:\.\d+)?
    \s*(?:%|percent|percentage|million|billion|thousand|mn|bn|x)?
    (?!\w)
    """,
    re.IGNORECASE | re.VERBOSE,
)
ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9&.-]{1,}\b")
TITLE_ENTITY_RE = re.compile(r"\b[A-Z][a-zA-Z0-9&.-]{2,}(?:\s+[A-Z][a-zA-Z0-9&.-]{2,})+\b")
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
SUPPORT_STOPWORDS = {
    "the",
    "and",
    "or",
    "but",
    "that",
    "this",
    "with",
    "from",
    "into",
    "for",
    "are",
    "was",
    "were",
    "has",
    "had",
    "have",
    "its",
    "their",
    "year",
    "over",
}
OCR_CONFIDENCE_THRESHOLD = 60.0


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def verify_claims(project_id: str, claims: list[ClaimInput]) -> dict:
    ensure_project(project_id)
    run_id = f"run_{uuid.uuid4().hex}"
    started = now_iso()
    output_claims = []

    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into runs(id, project_id, run_type, input_json, started_at, status)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                project_id,
                "verify",
                json.dumps([claim.model_dump() for claim in claims]),
                started,
                "running",
            ),
        )

    for claim in claims:
        verified = _verify_one_claim(project_id, run_id, claim)
        output_claims.append(verified)

    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            "update runs set output_json = ?, finished_at = ?, status = ? where id = ?",
            (json.dumps(output_claims), now_iso(), "completed", run_id),
        )

    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "verify",
        {
            "input.json": {"project_id": project_id, "claims": [claim.model_dump() for claim in claims]},
            "verified_claims.json": output_claims,
        },
        logs=[
            {
                "type": "verify_completed",
                "claim_count": len(output_claims),
                "blocked_count": sum(1 for claim in output_claims if claim["status"] == "blocked"),
            }
        ],
    )
    write_audit(
        project_id,
        "verify_completed",
        {
            "run_id": run_id,
            "claim_count": len(output_claims),
            "blocked_count": sum(1 for claim in output_claims if claim["status"] == "blocked"),
            "run_dir": str(run_dir),
        },
    )

    return {"run_id": run_id, "run_dir": str(run_dir), "claims": output_claims}


def render_memo(project_id: str, claim_ids: Optional[list[str]] = None) -> dict:
    ensure_project(project_id)
    params: list[str] = []
    where = "where project_id = ? and status in ('verified', 'approved')"
    params.append(project_id)
    if claim_ids:
        placeholders = ",".join("?" for _ in claim_ids)
        where += f" and id in ({placeholders})"
        params.extend(claim_ids)

    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            f"select * from claims {where} order by created_at asc",
            params,
        ).fetchall()

    lines = ["# Verified Memo", ""]
    for row in rows:
        lines.append(f"- {row['claim_text']} [E:{row['id']}]")
    memo = "\n".join(lines) + "\n"
    notes_dir = project_root(project_id) / "notes"
    path = notes_dir / "memo.md"
    path.write_text(memo, encoding="utf-8")
    rendered_claims = list_claims(project_id, claim_ids)
    _write_notes_assets(notes_dir, rendered_claims)
    return {"path": str(path), "markdown": memo, "claims": rendered_claims}


def list_claims(project_id: str, claim_ids: Optional[list[str]] = None) -> list[dict]:
    ensure_project(project_id)
    params: list[str] = [project_id]
    where = "where project_id = ?"
    if claim_ids:
        placeholders = ",".join("?" for _ in claim_ids)
        where += f" and id in ({placeholders})"
        params.extend(claim_ids)

    with connect(project_db_path(project_id)) as conn:
        claim_rows = conn.execute(
            f"select * from claims {where} order by created_at asc",
            params,
        ).fetchall()
        ordered_claim_ids = [row["id"] for row in claim_rows]
        citations_by_claim = {claim_id: [] for claim_id in ordered_claim_ids}
        if ordered_claim_ids:
            placeholders = ",".join("?" for _ in ordered_claim_ids)
            citation_rows = conn.execute(
                f"select * from citations where claim_id in ({placeholders}) order by id asc",
                ordered_claim_ids,
            ).fetchall()
            for row in citation_rows:
                citation = dict(row)
                citation["verified"] = bool(citation["verified"])
                citations_by_claim.setdefault(citation["claim_id"], []).append(citation)

    return [
        {
            "id": row["id"],
            "text": row["claim_text"],
            "type": row["claim_type"],
            "calculation_formula": row["calculation_formula"],
            "source_numbers": json.loads(row["source_numbers_json"] or "[]"),
            "status": row["status"],
            "citations": citations_by_claim.get(row["id"], []),
        }
        for row in claim_rows
    ]


def _write_notes_assets(notes_dir: Path, claims: list[dict]) -> None:
    citations = [citation for claim in claims for citation in claim.get("citations", [])]
    (notes_dir / "claims.json").write_text(
        json.dumps(claims, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (notes_dir / "citations.json").write_text(
        json.dumps(citations, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def review_citation(
    project_id: str,
    citation_id: str,
    action: str,
    reviewer: str = "reviewer",
    note: Optional[str] = None,
) -> dict:
    ensure_project(project_id)
    if action not in {"approve", "reject"}:
        raise ValueError("action must be approve or reject")
    reviewer = (reviewer or "reviewer").strip()[:120]
    note = note.strip()[:2000] if note else None
    reviewed_at = now_iso()

    with connect(project_db_path(project_id)) as conn:
        row = conn.execute("select * from citations where id = ?", (citation_id,)).fetchone()
        if not row:
            raise KeyError("citation_not_found")

        claim_id = row["claim_id"]
        if action == "approve":
            conn.execute(
                """
                update citations
                set reviewer = ?,
                    review_note = ?,
                    reviewed_at = ?
                where id = ?
                """,
                (reviewer, note, reviewed_at, citation_id),
            )
            remaining_failed = conn.execute(
                """
                select count(*) as n from citations
                where claim_id = ? and verified = 0
                """,
                (claim_id,),
            ).fetchone()["n"]
            direct_citations = conn.execute(
                """
                select count(*) as n from citations
                where claim_id = ? and verified = 1 and support_level = 'direct'
                """,
                (claim_id,),
            ).fetchone()["n"]
            new_status = "blocked" if remaining_failed else ("verified" if direct_citations else "needs_review")
            conn.execute("update claims set status = ? where id = ?", (new_status, claim_id))
            event_type = "citation_manual_approved"
        else:
            conn.execute(
                """
                update citations
                set verified = 0,
                    verification_method = null,
                    verification_score = 0,
                    support_level = ?,
                    support_reason = ?,
                    failure_reason = ?,
                    reviewer = ?,
                    review_note = ?,
                    reviewed_at = ?
                where id = ?
                """,
                ("weak", "manual_rejected", "manual_rejected", reviewer, note, reviewed_at, citation_id),
            )
            conn.execute("update claims set status = ? where id = ?", ("rejected", claim_id))
            event_type = "citation_rejected"

    write_audit(
        project_id,
        event_type,
        {"claim_id": claim_id, "citation_id": citation_id, "reviewer": reviewer, "note": note},
    )
    reviewed = list_claims(project_id, [claim_id])
    return reviewed[0] if reviewed else {}


def replace_citation(project_id: str, citation_id: str, chunk_id: str, quote: str) -> dict:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute("select * from citations where id = ?", (citation_id,)).fetchone()
        if not row:
            raise KeyError("citation_not_found")
        claim_row = conn.execute("select * from claims where id = ?", (row["claim_id"],)).fetchone()
        if not claim_row:
            raise KeyError("claim_not_found")

    chunk = get_chunk(project_id, chunk_id)
    result = _verify_citation(project_id, citation_id, claim_row["claim_text"], quote, chunk)
    claim_id = row["claim_id"]

    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            update citations
            set chunk_id = ?,
                document_id = ?,
                quote = ?,
                source_uri = ?,
                bbox_json = ?,
                verified = ?,
                verification_method = ?,
                verification_score = ?,
                support_level = ?,
                support_reason = ?,
                failure_reason = ?,
                reviewer = null,
                review_note = null,
                reviewed_at = null
            where id = ?
            """,
            (
                result["chunk_id"],
                result["document_id"],
                result["quote"],
                result["source_uri"],
                result["bbox_json"],
                result["verified"],
                result["verification_method"],
                result["verification_score"],
                result["support_level"],
                result["support_reason"],
                result["failure_reason"],
                citation_id,
            ),
        )
        remaining_failed = conn.execute(
            """
            select count(*) as n from citations
            where claim_id = ? and verified = 0
            """,
            (claim_id,),
        ).fetchone()["n"]
        direct_citations = conn.execute(
            """
            select count(*) as n from citations
            where claim_id = ? and verified = 1 and support_level = 'direct'
            """,
            (claim_id,),
        ).fetchone()["n"]
        new_status = "blocked" if remaining_failed else ("verified" if direct_citations else "needs_review")
        conn.execute("update claims set status = ? where id = ?", (new_status, claim_id))

    write_audit(
        project_id,
        "citation_replaced",
        {
            "claim_id": claim_id,
            "citation_id": citation_id,
            "chunk_id": chunk_id,
            "verified": bool(result["verified"]),
            "failure_reason": result["failure_reason"],
        },
    )
    reviewed = list_claims(project_id, [claim_id])
    return reviewed[0] if reviewed else {}


def correct_claim(
    project_id: str,
    claim_id: str,
    text: Optional[str] = None,
    citation_id: Optional[str] = None,
    chunk_id: Optional[str] = None,
    quote: Optional[str] = None,
    reviewer: str = "reviewer",
    note: Optional[str] = None,
) -> dict:
    """Apply a human correction, then re-run deterministic verification.

    This differs from manual approval: the corrected claim/citation still has to
    pass quote, source_uri, number, entity, OCR, and support checks before it can
    become verified.
    """
    ensure_project(project_id)
    reviewer = (reviewer or "reviewer").strip()[:120]
    note = note.strip()[:2000] if note else None
    reviewed_at = now_iso()

    with connect(project_db_path(project_id)) as conn:
        claim_row = conn.execute(
            "select * from claims where project_id = ? and id = ?",
            (project_id, claim_id),
        ).fetchone()
        if not claim_row:
            raise KeyError("claim_not_found")
        citation_rows = conn.execute(
            "select * from citations where claim_id = ? order by id asc",
            (claim_id,),
        ).fetchall()

    if not citation_rows:
        raise ValueError("claim_has_no_citations")

    normalized_text = normalize_text(text or claim_row["claim_text"])
    if not normalized_text:
        raise ValueError("claim_text_empty")

    target_citation_id = citation_id or citation_rows[0]["id"]
    if target_citation_id not in {row["id"] for row in citation_rows}:
        raise KeyError("citation_not_found")

    before = {
        "text": claim_row["claim_text"],
        "status": claim_row["status"],
        "citation_id": target_citation_id,
    }
    citation_results = []
    for row in citation_rows:
        next_chunk_id = chunk_id if row["id"] == target_citation_id and chunk_id else row["chunk_id"]
        next_quote = quote if row["id"] == target_citation_id and quote else row["quote"]
        expected_source_uri = None if row["id"] == target_citation_id and chunk_id else row["source_uri"]
        try:
            chunk = get_chunk(project_id, next_chunk_id)
            result = _verify_citation(
                project_id,
                row["id"],
                normalized_text,
                next_quote,
                chunk,
                expected_source_uri,
                claim_row["claim_type"],
                json.loads(claim_row["source_numbers_json"] or "[]"),
                _computed_failure_reason(
                    ClaimInput(
                        id=claim_id,
                        text=normalized_text,
                        type=claim_row["claim_type"],
                        calculation_formula=claim_row["calculation_formula"],
                        source_numbers=json.loads(claim_row["source_numbers_json"] or "[]"),
                        citations=[],
                    )
                ),
                claim_id=claim_id,
            )
        except KeyError:
            result = {
                "id": row["id"],
                "claim_id": claim_id,
                "chunk_id": next_chunk_id,
                "document_id": "",
                "quote": next_quote,
                "source_uri": "",
                "bbox_json": None,
                "verified": 0,
                "verification_method": None,
                "verification_score": 0,
                "failure_reason": "chunk_not_found",
                "support_level": "weak",
                "support_reason": "chunk_not_found",
            }
        citation_results.append(result)

    claim_status = _claim_status(citation_results)
    if claim_status == "blocked":
        write_audit(
            project_id,
            "claim_blocked",
            {"claim_id": claim_id, "reason": _claim_failure_reason(citation_results), "source": "manual_correction"},
        )

    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            update claims
            set claim_text = ?, status = ?
            where project_id = ? and id = ?
            """,
            (normalized_text, claim_status, project_id, claim_id),
        )
        for result in citation_results:
            is_target = result["id"] == target_citation_id
            conn.execute(
                """
                update citations
                set chunk_id = ?,
                    document_id = ?,
                    quote = ?,
                    source_uri = ?,
                    bbox_json = ?,
                    verified = ?,
                    verification_method = ?,
                    verification_score = ?,
                    support_level = ?,
                    support_reason = ?,
                    failure_reason = ?,
                    reviewer = ?,
                    review_note = ?,
                    reviewed_at = ?,
                    support_judge_label = null,
                    support_judge_reason = null
                where id = ?
                """,
                (
                    result["chunk_id"],
                    result["document_id"],
                    result["quote"],
                    result["source_uri"],
                    result["bbox_json"],
                    result["verified"],
                    result["verification_method"],
                    result["verification_score"],
                    result["support_level"],
                    result["support_reason"],
                    result["failure_reason"],
                    reviewer if is_target else None,
                    note if is_target else None,
                    reviewed_at if is_target else None,
                    result["id"],
                ),
            )

    write_audit(
        project_id,
        "claim_corrected",
        {
            "claim_id": claim_id,
            "citation_id": target_citation_id,
            "reviewer": reviewer,
            "note": note,
            "before": before,
            "after": {
                "text": normalized_text,
                "status": claim_status,
                "verified_citations": sum(1 for citation in citation_results if citation["verified"]),
                "failed_citations": sum(1 for citation in citation_results if not citation["verified"]),
            },
        },
    )
    reviewed = list_claims(project_id, [claim_id])
    return reviewed[0] if reviewed else {}


def _verify_one_claim(project_id: str, run_id: str, claim: ClaimInput) -> dict:
    claim_id = claim.id or f"claim_{uuid.uuid4().hex}"
    created_at = now_iso()
    citation_results = []
    computed_failure = _computed_failure_reason(claim)

    for citation in claim.citations:
        citation_id = f"cit_{uuid.uuid4().hex}"
        try:
            chunk = get_chunk(project_id, citation.chunk_id)
            result = _verify_citation(
                project_id,
                citation_id,
                claim.text,
                citation.quote,
                chunk,
                citation.source_uri,
                claim.type,
                claim.source_numbers,
                computed_failure,
                claim_id=claim_id,
            )
        except KeyError:
            result = {
                "id": citation_id,
                "claim_id": claim_id,
                "chunk_id": citation.chunk_id,
                "document_id": "",
                "quote": citation.quote,
                "source_uri": citation.source_uri or "",
                "bbox_json": None,
                "verified": 0,
                "verification_method": None,
                "verification_score": 0,
                "failure_reason": "chunk_not_found",
                "support_level": "weak",
                "support_reason": "chunk_not_found",
            }
        citation_results.append(result)

    claim_status = _claim_status(citation_results)
    if claim_status == "blocked":
        write_audit(
            project_id,
            "claim_blocked",
            {"claim_id": claim_id, "reason": _claim_failure_reason(citation_results)},
        )

    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert or replace into claims(
              id, project_id, run_id, claim_text, claim_type,
              calculation_formula, source_numbers_json, status, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim_id,
                project_id,
                run_id,
                claim.text,
                claim.type,
                claim.calculation_formula,
                json.dumps(claim.source_numbers),
                claim_status,
                created_at,
            ),
        )
        for result in citation_results:
            conn.execute(
                """
                insert or replace into citations(
                  id, claim_id, chunk_id, document_id, quote, source_uri, bbox_json,
                  verified, verification_method, verification_score, failure_reason,
                  support_level, support_reason
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["id"],
                    claim_id,
                    result["chunk_id"],
                    result["document_id"],
                    result["quote"],
                    result["source_uri"],
                    result["bbox_json"],
                    result["verified"],
                    result["verification_method"],
                    result["verification_score"],
                    result["failure_reason"],
                    result["support_level"],
                    result["support_reason"],
                ),
            )

    return {
        "id": claim_id,
        "text": claim.text,
        "type": claim.type,
        "calculation_formula": claim.calculation_formula,
        "source_numbers": claim.source_numbers,
        "status": claim_status,
        "citations": citation_results,
    }


def _verify_citation(
    project_id: str,
    citation_id: str,
    claim_text: str,
    quote: str,
    chunk: dict,
    source_uri: Optional[str] = None,
    claim_type: Optional[str] = None,
    source_numbers: Optional[list[str]] = None,
    preflight_failure: Optional[str] = None,
    claim_id: str = "",
) -> dict:
    normalized_chunk = normalize_text(chunk["text"])
    normalized_quote = normalize_text(quote)
    exact_index = normalized_chunk.find(normalized_quote)
    method = None
    score = 0.0
    failure_reason = None

    if preflight_failure:
        failure_reason = preflight_failure
    elif not normalized_quote or not normalize_text(claim_text):
        # 空 quote / 空 claim 文本不构成证据支撑（str.find("") 会误返 0）
        failure_reason = "quote_not_found"
    elif exact_index >= 0:
        method = "normalized_exact"
        score = 1.0
    else:
        score = _fuzzy_score(normalized_quote, normalized_chunk)
        if score >= 0.92:
            method = "fuzzy_quote_match"
        else:
            failure_reason = "quote_not_found"

    resolved_source_uri = source_uri or chunk["source_uri"]

    if not failure_reason and not _source_uri_is_parseable(resolved_source_uri):
        failure_reason = "source_uri_invalid"
        method = None
        score = 0.0

    if not failure_reason and source_uri and source_uri != chunk["source_uri"]:
        failure_reason = "source_uri_mismatch"
        method = None
        score = 0.0

    if not failure_reason and _ocr_low_confidence(project_id, chunk["document_id"]):
        failure_reason = "ocr_low_confidence"
        method = None
        score = 0.0

    if not failure_reason and not _numbers_are_covered(claim_text, quote, chunk["text"], claim_type, source_numbers):
        failure_reason = "number_not_found"
        method = None
        score = 0.0

    if not failure_reason and not _entities_are_covered(claim_text, quote, chunk["text"]):
        failure_reason = "entity_not_found"
        method = None
        score = 0.0

    bbox = _quote_bbox(project_id, chunk, quote) if not failure_reason else None
    verified = 0 if failure_reason else 1
    support_level, support_reason = _assess_support(claim_text, quote, chunk["text"]) if not failure_reason else (
        "weak",
        failure_reason,
    )

    if failure_reason:
        write_audit(
            project_id,
            "citation_failed",
            {
                "citation_id": citation_id,
                "chunk_id": chunk["id"],
                "reason": failure_reason,
            },
        )

    return {
        "id": citation_id,
        "claim_id": claim_id,
        "chunk_id": chunk["id"],
        "document_id": chunk["document_id"],
        "quote": quote,
        "source_uri": resolved_source_uri,
        "bbox_json": json.dumps(bbox) if bbox else None,
        "verified": verified,
        "verification_method": method,
        "verification_score": score,
        "failure_reason": failure_reason,
        "support_level": support_level,
        "support_reason": support_reason,
    }


def _fuzzy_score(quote: str, chunk_text: str) -> float:
    if not quote or not chunk_text:
        return 0.0
    quote = quote.casefold()
    chunk_text = chunk_text.casefold()
    quote_len = len(quote)
    if quote_len >= len(chunk_text):
        return SequenceMatcher(None, quote, chunk_text).ratio()
    best = 0.0
    step = max(1, quote_len // 8)
    for start in range(0, len(chunk_text) - quote_len + 1, step):
        candidate = chunk_text[start : start + quote_len]
        best = max(best, SequenceMatcher(None, quote, candidate).ratio())
    return best


def _source_uri_is_parseable(source_uri: str) -> bool:
    parsed = urlparse(source_uri)
    if parsed.scheme not in {"pdf", "docx", "xlsx", "md", "html", "text"} or not parsed.netloc:
        return False
    params = parse_qs(parsed.fragment, keep_blank_values=False)
    if parsed.scheme == "pdf":
        return _has_int_param(params, "page")
    if parsed.scheme == "docx":
        return _has_int_param(params, "paragraph") or _has_int_param(params, "table") or _has_text_param(params, "heading")
    if parsed.scheme == "xlsx":
        return _has_text_param(params, "sheet") and any(
            _has_text_param(params, key) for key in ("cell", "range", "row")
        )
    if parsed.scheme in {"md", "html", "text"}:
        return _has_text_param(params, "block") or _has_text_param(params, "heading")
    return bool(parsed.fragment)


def _has_int_param(params: dict[str, list[str]], key: str) -> bool:
    values = params.get(key) or []
    return any(value.isdigit() for value in values)


def _has_text_param(params: dict[str, list[str]], key: str) -> bool:
    values = params.get(key) or []
    return any(bool(value.strip()) for value in values)


def _numbers_are_covered(
    claim_text: str,
    quote: str,
    chunk_text: str,
    claim_type: Optional[str] = None,
    source_numbers: Optional[list[str]] = None,
) -> bool:
    evidence_text = f"{quote} {chunk_text}"
    evidence_numbers = {_normalize_number_token(match.group(0)) for match in NUMBER_RE.finditer(evidence_text)}
    if (claim_type or "").casefold() == "computed":
        required_numbers = {_normalize_number_token(value) for value in (source_numbers or []) if value.strip()}
        return bool(required_numbers) and required_numbers.issubset(evidence_numbers)

    claim_numbers = {_normalize_number_token(match.group(0)) for match in NUMBER_RE.finditer(claim_text)}
    if not claim_numbers:
        return True
    return claim_numbers.issubset(evidence_numbers)


def _ocr_low_confidence(project_id: str, document_id: str) -> bool:
    with connect(project_db_path(project_id)) as conn:
        try:
            row = conn.execute(
                "select ocr_used, ocr_confidence from documents where id = ?",
                (document_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return False
    if not row or not row["ocr_used"]:
        return False
    confidence = row["ocr_confidence"]
    return confidence is not None and float(confidence) < OCR_CONFIDENCE_THRESHOLD


def _computed_failure_reason(claim: ClaimInput) -> Optional[str]:
    if (claim.type or "").casefold() != "computed":
        return None
    if not (claim.calculation_formula or "").strip():
        return "computed_formula_missing"
    if not [value for value in claim.source_numbers if value.strip()]:
        return "computed_source_numbers_missing"
    return None


def _claim_status(citation_results: list[dict]) -> str:
    if not citation_results:
        return "blocked"
    if any(not citation["verified"] for citation in citation_results):
        return "blocked"
    if any(citation.get("support_level") == "direct" for citation in citation_results):
        return "verified"
    return "needs_review"


def _assess_support(claim_text: str, quote: str, chunk_text: str) -> tuple[str, str]:
    normalized_claim = normalize_text(claim_text).casefold()
    normalized_quote = normalize_text(quote).casefold()
    if normalized_claim and normalized_claim in normalized_quote:
        return "direct", "claim_text_in_quote"

    claim_tokens = _support_tokens(claim_text)
    if not claim_tokens:
        return "direct", "no_content_tokens"

    quote_tokens = _support_tokens(quote)
    chunk_tokens = _support_tokens(chunk_text)
    quote_coverage = len(claim_tokens & quote_tokens) / len(claim_tokens)
    chunk_coverage = len(claim_tokens & chunk_tokens) / len(claim_tokens)

    if quote_coverage >= 0.55:
        return "direct", f"quote_token_coverage:{quote_coverage:.2f}"
    if quote_coverage >= 0.25 or chunk_coverage >= 0.55:
        return "partial", f"quote_token_coverage:{quote_coverage:.2f};chunk_token_coverage:{chunk_coverage:.2f}"
    return "weak", f"quote_token_coverage:{quote_coverage:.2f};chunk_token_coverage:{chunk_coverage:.2f}"


def _support_tokens(value: str) -> set[str]:
    tokens = {token.casefold() for token in TOKEN_RE.findall(normalize_text(value))}
    return {token for token in tokens if len(token) > 2 and token not in SUPPORT_STOPWORDS}


def _entities_are_covered(claim_text: str, quote: str, chunk_text: str) -> bool:
    claim_entities = _claim_entities(claim_text)
    if not claim_entities:
        return True
    evidence = normalize_text(f"{quote} {chunk_text}").casefold()
    return all(entity.casefold() in evidence for entity in claim_entities)


def _claim_entities(claim_text: str) -> set[str]:
    normalized = normalize_text(claim_text)
    entities = set(TITLE_ENTITY_RE.findall(normalized))
    entities.update(ACRONYM_RE.findall(normalized))
    return {entity.strip() for entity in entities if entity.strip()}


def _normalize_number_token(value: str) -> str:
    value = normalize_text(value).lower()
    value = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", value)
    value = value.replace(" percentage", "%").replace(" percent", "%")
    value = value.replace("usd", "$").replace("cny", "rmb")
    return re.sub(r"\s+", "", value)


def _quote_bbox(project_id: str, chunk: dict, quote: str) -> Optional[dict]:
    word_ids = json.loads(chunk["word_ids_json"] or "[]")
    if not word_ids:
        return None

    quote_tokens = [_normalize_word_token(token) for token in quote.split()]
    quote_tokens = [token for token in quote_tokens if token]
    if not quote_tokens:
        return json.loads(chunk["bbox_json"]) if chunk["bbox_json"] else None

    placeholders = ",".join("?" for _ in word_ids)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            f"select * from words where id in ({placeholders}) order by word_index asc",
            word_ids,
        ).fetchall()
    words = [dict(row) for row in rows]
    word_tokens = [_normalize_word_token(word["text"]) for word in words]

    for start in range(0, len(word_tokens) - len(quote_tokens) + 1):
        if word_tokens[start : start + len(quote_tokens)] == quote_tokens:
            boxes = [json.loads(word["bbox_json"]) for word in words[start : start + len(quote_tokens)]]
            return bbox_union(boxes)
    return json.loads(chunk["bbox_json"]) if chunk["bbox_json"] else None


def _normalize_word_token(value: str) -> str:
    value = normalize_text(value).lower()
    return re.sub(r"^\W+|\W+$", "", value)


def _claim_failure_reason(citations: list[dict]) -> str:
    if not citations:
        return "missing_citation"
    return next((citation["failure_reason"] for citation in citations if citation["failure_reason"]), "blocked")
