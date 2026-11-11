from __future__ import annotations

import json
from typing import Optional

from loamtrace.db import connect
from loamtrace.services.audit import write_audit
from loamtrace.services.model_provider import ModelProviderError, chat_json
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.search import get_chunk
from loamtrace.services.verifier import list_claims


JUDGE_LABELS = {"direct", "partial", "weak"}


def judge_claim_support(project_id: str, claim_id: str) -> dict:
    ensure_project(project_id)
    claim = _load_claim(project_id, claim_id)
    citations = claim.get("citations", [])
    candidates = []
    for citation in citations:
        if not citation.get("verified"):
            continue
        try:
            chunk = get_chunk(project_id, citation["chunk_id"])
        except KeyError:
            continue
        candidates.append(
            {
                "citation_id": citation["id"],
                "quote": citation["quote"],
                "source_uri": citation["source_uri"],
                "chunk_text": _clip(chunk["text"], 1400),
                "rule_support_level": citation.get("support_level"),
                "rule_support_reason": citation.get("support_reason"),
            }
        )

    if not candidates:
        return {"judge_status": "no_verified_citations", "claim": claim, "model_error": None}

    try:
        raw = _call_support_judge(claim["text"], candidates)
    except ModelProviderError as exc:
        write_audit(project_id, "support_judge_failed", {"claim_id": claim_id, "error": str(exc)})
        return {"judge_status": "failed", "claim": claim, "model_error": str(exc)}

    if raw is None:
        return {"judge_status": "not_configured", "claim": claim, "model_error": None}

    applied = _apply_judge_output(project_id, claim_id, raw)
    updated = _load_claim(project_id, claim_id)
    status = "used" if applied else "no_applicable_judgements"
    write_audit(
        project_id,
        "support_judge_completed",
        {"claim_id": claim_id, "applied_count": applied, "judge_status": status},
    )
    return {"judge_status": status, "claim": updated, "model_error": None, "applied_count": applied}


def _load_claim(project_id: str, claim_id: str) -> dict:
    claims = list_claims(project_id, [claim_id])
    if not claims:
        raise KeyError("claim_not_found")
    return claims[0]


def _call_support_judge(claim_text: str, candidates: list[dict]) -> Optional[dict]:
    system_prompt = (
        "You judge whether citations support a research claim. "
        "Return JSON only. You must not change verification status. "
        "Use labels direct, partial, or weak. direct means the quote alone supports the claim; "
        "partial means the quote supports only part of the claim; weak means related but insufficient."
    )
    user_prompt = json.dumps(
        {
            "claim": claim_text,
            "schema": {
                "citations": [
                    {
                        "citation_id": "existing citation id",
                        "support_label": "direct|partial|weak",
                        "reason": "brief reason based only on quote and chunk text",
                    }
                ]
            },
            "citations": candidates,
        },
        ensure_ascii=False,
    )
    return chat_json(system_prompt, user_prompt)


def _apply_judge_output(project_id: str, claim_id: str, raw: dict) -> int:
    allowed_ids = {citation["id"] for citation in _load_claim(project_id, claim_id).get("citations", [])}
    rows = _judge_rows(raw, allowed_ids)
    applied = 0
    with connect(project_db_path(project_id)) as conn:
        for item in rows:
            if not isinstance(item, dict):
                continue
            citation_id = item.get("citation_id") or item.get("id") or item.get("citation")
            label = _normalize_label(item.get("support_label") or item.get("support_level") or item.get("label"))
            if citation_id not in allowed_ids or label not in JUDGE_LABELS:
                continue
            reason = item.get("reason") or item.get("explanation") or item.get("rationale")
            if not isinstance(reason, str):
                reason = ""
            conn.execute(
                """
                update citations
                set support_judge_label = ?,
                    support_judge_reason = ?
                where id = ? and claim_id = ?
                """,
                (label, _clip(reason, 600), citation_id, claim_id),
            )
            applied += 1
    return applied


def _judge_rows(raw: dict, allowed_ids: set[str]) -> list[dict]:
    rows = raw.get("citations") or raw.get("results") or raw.get("judgements") or raw.get("judgments")
    if isinstance(rows, dict):
        rows = [rows]
    if isinstance(rows, list):
        return rows
    if len(allowed_ids) == 1:
        label = raw.get("support_label") or raw.get("support_level") or raw.get("label")
        if label:
            return [{**raw, "citation_id": next(iter(allowed_ids))}]
    return []


def _normalize_label(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    for label in JUDGE_LABELS:
        if lowered == label or lowered.startswith(f"{label}:") or lowered.startswith(f"{label} "):
            return label
    return None


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"
