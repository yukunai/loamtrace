from __future__ import annotations

import re
import uuid
from typing import Optional

from loamtrace.models import CitationInput, ClaimInput
from loamtrace.services.audit import write_audit, write_run_artifacts
from loamtrace.services.model_provider import ModelProviderError, chat_json
from loamtrace.services.search import search_chunks
from loamtrace.services.verifier import render_memo, verify_claims


def generate_memo(project_id: str, query: str, top_n: int = 5) -> dict:
    chunks = search_chunks(project_id, query, top_n)
    if not chunks:
        run_id = f"run_{uuid.uuid4().hex}"
        answer = "# Verified Memo\n\nNo matching evidence was found.\n"
        run_dir = write_run_artifacts(
            project_id,
            run_id,
            "generate_memo",
            {
                "input.json": {"project_id": project_id, "query": query, "top_n": top_n},
                "retrieved_chunks.json": [],
                "model_output.raw.json": {"claims": []},
                "verified_claims.json": [],
                "final_memo.md": answer,
            },
            logs=[{"type": "generate_no_results", "query": query}],
        )
        write_audit(
            project_id,
            "generate_memo_completed",
            {
                "run_id": run_id,
                "query": query,
                "top_n": top_n,
                "retrieved_count": 0,
                "verified_claim_count": 0,
                "run_dir": str(run_dir),
            },
        )
        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "answer": answer,
            "claims": [],
            "retrieved_chunks": [],
        }

    model_status = "not_configured"
    model_error = None
    raw_model_output = None
    claims = []
    try:
        raw_model_output = _generate_model_claims(query, chunks)
        if raw_model_output is not None:
            claims = _claims_from_model_output(raw_model_output, chunks)
            model_status = "used" if claims else "no_valid_claims"
    except ModelProviderError as exc:
        model_status = "failed"
        model_error = str(exc)

    if not claims:
        claims = _extractive_claims(chunks)
        if model_status == "not_configured":
            model_status = "fallback_not_configured"
        elif model_status == "no_valid_claims":
            model_status = "fallback_no_valid_claims"
        elif model_status == "failed":
            model_status = "fallback_after_model_error"

    verification = verify_claims(project_id, claims)
    verified_ids = [
        claim["id"] for claim in verification["claims"] if claim["status"] in ("verified", "approved")
    ]
    memo = render_memo(project_id, verified_ids)
    run_dir = write_run_artifacts(
        project_id,
        verification["run_id"],
        "generate_memo",
        {
            "input.json": {"project_id": project_id, "query": query, "top_n": top_n},
            "retrieved_chunks.json": chunks,
            "model_output.raw.json": raw_model_output or {"claims": [claim.model_dump() for claim in claims]},
            "verified_claims.json": verification["claims"],
            "final_memo.md": memo["markdown"],
        },
        logs=[
            {"type": "retrieved_chunks", "count": len(chunks)},
            {"type": "model_generation", "status": model_status, "error": model_error},
            {"type": "verified_claims", "count": len(verified_ids)},
        ],
    )
    write_audit(
        project_id,
        "generate_memo_completed",
        {
            "run_id": verification["run_id"],
            "query": query,
            "top_n": top_n,
            "retrieved_count": len(chunks),
            "verified_claim_count": len(verified_ids),
            "model_status": model_status,
            "model_error": model_error,
            "run_dir": str(run_dir),
        },
    )
    return {
        "run_id": verification["run_id"],
        "run_dir": str(run_dir),
        "answer": memo["markdown"],
        "claims": verification["claims"],
        "retrieved_chunks": chunks,
        "model_status": model_status,
        "model_error": model_error,
    }


def _generate_model_claims(query: str, chunks: list[dict]) -> Optional[dict]:
    evidence = []
    for chunk in chunks:
        evidence.append(
            {
                "chunk_id": chunk["id"],
                "source_uri": chunk["source_uri"],
                "text": _clip_text(chunk["text"], 900),
            }
        )
    system_prompt = (
        "You extract evidence-grounded claims for a research memo. "
        "Return JSON only. Do not invent facts. Every claim must cite one of the provided chunk_id values "
        "and use an exact quote copied from that chunk text."
    )
    user_prompt = json_dumps(
        {
            "task": "Create concise memo claims answering the query. Use only provided evidence.",
            "query": query,
            "schema": {
                "claims": [
                    {
                        "text": "claim sentence grounded in evidence",
                        "type": "model_evidence",
                        "citations": [
                            {
                                "chunk_id": "one provided chunk_id",
                                "quote": "exact quote from that chunk",
                            }
                        ],
                    }
                ]
            },
            "evidence": evidence,
        }
    )
    return chat_json(system_prompt, user_prompt)


def _claims_from_model_output(output: dict, chunks: list[dict]) -> list[ClaimInput]:
    chunk_by_id = {chunk["id"]: chunk for chunk in chunks}
    raw_claims = output.get("claims")
    if not isinstance(raw_claims, list):
        return []
    claims = []
    for raw_claim in raw_claims[:8]:
        if not isinstance(raw_claim, dict):
            continue
        text = _clean_text(raw_claim.get("text"))
        raw_citations = raw_claim.get("citations")
        if not text or not isinstance(raw_citations, list):
            continue
        citations = []
        for raw_citation in raw_citations[:4]:
            if not isinstance(raw_citation, dict):
                continue
            chunk_id = _clean_text(raw_citation.get("chunk_id"))
            quote = _clean_text(raw_citation.get("quote"))
            chunk = chunk_by_id.get(chunk_id)
            if not chunk or not quote:
                continue
            citations.append(CitationInput(chunk_id=chunk_id, quote=quote, source_uri=chunk["source_uri"]))
        if citations:
            claims.append(
                ClaimInput(
                    text=text,
                    type=_clean_text(raw_claim.get("type")) or "model_evidence",
                    citations=citations,
                )
            )
    return claims


def _extractive_claims(chunks: list[dict]) -> list[ClaimInput]:
    claims = []
    for chunk in chunks:
        quote = _extract_quote(chunk["text"])
        if not quote:
            continue
        claims.append(
            ClaimInput(
                text=quote,
                type="extractive_evidence",
                citations=[
                    CitationInput(
                        chunk_id=chunk["id"],
                        quote=quote,
                        source_uri=chunk["source_uri"],
                    )
                ],
            )
        )
    return claims


def _extract_quote(text: str, max_chars: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    sentence_match = re.search(r"^(.{20,}?[.!?。！？])(?:\s|$)", text)
    quote = sentence_match.group(1) if sentence_match else text
    if len(quote) <= max_chars:
        return quote
    clipped = quote[:max_chars].rsplit(" ", 1)[0].strip()
    return clipped or quote[:max_chars].strip()


def _clean_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clip_text(value: str, max_chars: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rsplit(" ", 1)[0].strip()


def json_dumps(value: dict) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)
