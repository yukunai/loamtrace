from __future__ import annotations

import re
import uuid
from typing import Optional

from loamtrace.db import connect
from loamtrace.services.audit import write_audit, write_run_artifacts
from loamtrace.services.paths import ensure_project, project_db_path


RED_FLAG_RULES = [
    {
        "category": "customer_concentration",
        "severity": "high",
        "patterns": [
            r"\bcustomer concentration\b",
            r"\btop\s+(?:three|3|five|5|ten|10)\s+customers?\b",
            r"\bconcentrat(?:e|ed|ion)\b.*\bcustomers?\b",
        ],
    },
    {
        "category": "churn_or_retention",
        "severity": "medium",
        "patterns": [r"\bchurn\b", r"\bretention\b.*\bdeclin(?:e|ed|ing)\b"],
    },
    {
        "category": "financial_decline",
        "severity": "medium",
        "patterns": [
            r"\brevenue\b.*\bdeclin(?:e|ed|ing)\b",
            r"\bmargin\b.*\bdeclin(?:e|ed|ing)\b",
            r"\bloss(?:es)?\b",
            r"\bnegative\s+(?:cash flow|free cash flow|ebitda)\b",
        ],
    },
    {
        "category": "debt_or_default",
        "severity": "high",
        "patterns": [
            r"\bdefault\b",
            r"\bcovenant\b",
            r"\bgoing concern\b",
            r"\bliquidity\b.*\b(risk|shortfall|constraint)\b",
        ],
    },
    {
        "category": "legal_or_contract",
        "severity": "medium",
        "patterns": [
            r"\bbreach\b",
            r"\btermination\b",
            r"\bmaterial adverse\b",
            r"\bindemnif(?:y|ication)\b",
        ],
    },
]
FINANCIAL_METRIC_PATTERNS = {
    "revenue": r"\b(?:revenue|sales)\b",
    "gross_margin": r"\bgross\s+margin\b",
    "ebitda": r"\bebitda\b",
    "arr": r"\barr\b",
    "gmv": r"\bgmv\b",
}
CONTRACT_CLAUSE_RULES = {
    "termination": [r"\bterminat(?:e|ed|ion)\b"],
    "exclusivity": [r"\bexclusive\b", r"\bnon[-\s]?exclusive\b"],
    "governing_law": [r"\bgoverning law\b", r"\blaws of\b", r"\bjurisdiction\b"],
    "assignment": [r"\bassign(?:ment)?\b", r"\btransfer this agreement\b"],
    "liability_cap": [r"\bliability\b.*\b(?:cap|limit|limited|exceed)\b", r"\baggregate liability\b"],
    "indemnity": [r"\bindemnif(?:y|ies|ication)\b"],
    "payment_terms": [r"\bnet\s+\d+\b", r"\bpayment\b.*\b(?:due|within)\b"],
    "auto_renewal": [r"\bautomatic(?:ally)?\s+renew\b", r"\bauto[-\s]?renew\b", r"\brenewal\b"],
}
FINANCIAL_VALUE_RE = re.compile(
    r"""
    (?P<prefix>[$¥€]|USD|RMB|CNY|EUR|GBP)?\s*
    (?P<number>-?\d[\d,]*(?:\.\d+)?)
    \s*(?P<unit>%|percent|percentage|million|billion|thousand|mn|bn|m|b)?
    """,
    re.IGNORECASE | re.VERBOSE,
)
PERIOD_RE = re.compile(r"\b(?:20\d{2}|19\d{2}|Q[1-4]\s*20\d{2}|20\d{2}\s*Q[1-4])\b", re.IGNORECASE)


def scan_red_flags(project_id: str, limit: int = 20) -> dict:
    ensure_project(project_id)
    run_id = f"run_{uuid.uuid4().hex}"
    findings = _scan_chunks(project_id, limit)
    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "red_flag_scan",
        {
            "input.json": {"project_id": project_id, "limit": limit},
            "findings.json": findings,
        },
        logs=[{"type": "red_flag_scan_completed", "finding_count": len(findings)}],
    )
    write_audit(
        project_id,
        "red_flag_scan_completed",
        {"run_id": run_id, "finding_count": len(findings), "run_dir": str(run_dir)},
    )
    return {"run_id": run_id, "run_dir": str(run_dir), "findings": findings}


def scan_financial_consistency(project_id: str, limit: int = 20) -> dict:
    ensure_project(project_id)
    run_id = f"run_{uuid.uuid4().hex}"
    observations = _financial_observations(project_id)
    findings = _financial_inconsistencies(observations, limit)
    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "financial_consistency_scan",
        {
            "input.json": {"project_id": project_id, "limit": limit},
            "observations.json": observations,
            "findings.json": findings,
        },
        logs=[{"type": "financial_consistency_scan_completed", "finding_count": len(findings)}],
    )
    write_audit(
        project_id,
        "financial_consistency_scan_completed",
        {"run_id": run_id, "finding_count": len(findings), "run_dir": str(run_dir)},
    )
    return {"run_id": run_id, "run_dir": str(run_dir), "findings": findings, "observations": observations}


def scan_contract_clauses(project_id: str, limit: int = 20) -> dict:
    ensure_project(project_id)
    run_id = f"run_{uuid.uuid4().hex}"
    observations = _contract_clause_observations(project_id)
    findings = _contract_clause_mismatches(observations, limit)
    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "contract_clause_scan",
        {
            "input.json": {"project_id": project_id, "limit": limit},
            "observations.json": observations,
            "findings.json": findings,
        },
        logs=[{"type": "contract_clause_scan_completed", "finding_count": len(findings)}],
    )
    write_audit(
        project_id,
        "contract_clause_scan_completed",
        {"run_id": run_id, "finding_count": len(findings), "run_dir": str(run_dir)},
    )
    return {"run_id": run_id, "run_dir": str(run_dir), "findings": findings, "observations": observations}


def _scan_chunks(project_id: str, limit: int) -> list[dict]:
    rows = _chunk_rows(project_id)

    findings = []
    seen = set()
    for row in rows:
        chunk = dict(row)
        text = chunk["text"]
        for rule in RED_FLAG_RULES:
            match = _first_match(rule["patterns"], text)
            if not match:
                continue
            key = (chunk["id"], rule["category"])
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "id": f"flag_{uuid.uuid4().hex}",
                    "category": rule["category"],
                    "severity": rule["severity"],
                    "chunk_id": chunk["id"],
                    "document_id": chunk["document_id"],
                    "source_uri": chunk["source_uri"],
                    "quote": _quote_around(text, match.start(), match.end()),
                    "reason": f"Matched red flag signal: {match.group(0)}",
                }
            )
            if len(findings) >= limit:
                return findings
    return findings


def _financial_observations(project_id: str) -> list[dict]:
    observations = []
    for chunk in _chunk_rows(project_id):
        text = chunk["text"]
        for metric, pattern in FINANCIAL_METRIC_PATTERNS.items():
            metric_match = re.search(pattern, text, flags=re.IGNORECASE)
            if not metric_match:
                continue
            value = _nearest_financial_value(text, metric_match.start(), metric_match.end())
            if not value:
                continue
            period = _nearest_period(text, metric_match.start(), metric_match.end()) or "unspecified"
            value_text = value["text"]
            observations.append(
                {
                    "id": f"obs_{uuid.uuid4().hex}",
                    "metric": metric,
                    "period": period,
                    "value": _normalize_financial_value(value_text),
                    "value_text": value_text,
                    "chunk_id": chunk["id"],
                    "document_id": chunk["document_id"],
                    "source_uri": chunk["source_uri"],
                    "quote": _quote_around(
                        text,
                        min(metric_match.start(), value["start"]),
                        max(metric_match.end(), value["end"]),
                    ),
                }
            )
    return observations


def _financial_inconsistencies(observations: list[dict], limit: int) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for observation in observations:
        grouped.setdefault((observation["metric"], observation["period"]), []).append(observation)

    findings = []
    for (metric, period), rows in grouped.items():
        values = {row["value"] for row in rows}
        if len(values) <= 1:
            continue
        findings.append(
            {
                "id": f"fin_{uuid.uuid4().hex}",
                "category": "financial_inconsistency",
                "severity": "high",
                "metric": metric,
                "period": period,
                "values": sorted(values),
                "observations": rows,
                "reason": f"Conflicting {metric} values found for {period}.",
            }
        )
        if len(findings) >= limit:
            return findings
    return findings


def _contract_clause_observations(project_id: str) -> list[dict]:
    observations = []
    for chunk in _chunk_rows(project_id):
        text = chunk["text"]
        for clause_type, patterns in CONTRACT_CLAUSE_RULES.items():
            match = _first_match(patterns, text)
            if not match:
                continue
            variant = _contract_clause_variant(clause_type, text, match.start(), match.end())
            observations.append(
                {
                    "id": f"clause_{uuid.uuid4().hex}",
                    "clause_type": clause_type,
                    "variant": variant,
                    "chunk_id": chunk["id"],
                    "document_id": chunk["document_id"],
                    "source_uri": chunk["source_uri"],
                    "quote": _quote_around(text, match.start(), match.end()),
                }
            )
    return observations


def _contract_clause_mismatches(observations: list[dict], limit: int) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for observation in observations:
        grouped.setdefault(observation["clause_type"], []).append(observation)

    findings = []
    for clause_type, rows in grouped.items():
        variants = {row["variant"] for row in rows if row["variant"] != "present"}
        if len(variants) <= 1:
            continue
        findings.append(
            {
                "id": f"clause_mismatch_{uuid.uuid4().hex}",
                "category": "contract_clause_mismatch",
                "severity": "medium",
                "clause_type": clause_type,
                "variants": sorted(variants),
                "observations": [row for row in rows if row["variant"] in variants],
                "reason": f"Conflicting {clause_type} clause variants found.",
            }
        )
        if len(findings) >= limit:
            return findings
    return findings


def _chunk_rows(project_id: str) -> list[dict]:
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            """
            select id, document_id, text, source_uri
            from chunks
            order by rowid asc
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _nearest_financial_value(text: str, start: int, end: int) -> Optional[dict]:
    window_start = max(0, start - 80)
    window_end = min(len(text), end + 120)
    window = text[window_start:window_end]
    candidates = []
    for match in FINANCIAL_VALUE_RE.finditer(window):
        if _looks_like_period_value(match):
            continue
        absolute_start = window_start + match.start()
        absolute_end = window_start + match.end()
        signal_score = 0
        if match.group("prefix"):
            signal_score += 2
        if match.group("unit"):
            signal_score += 2
        candidates.append(
            {
                "start": absolute_start,
                "end": absolute_end,
                "text": match.group(0).strip(),
                "signal_score": signal_score,
            }
        )
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: (-candidate["signal_score"], abs(candidate["start"] - start)))


def _looks_like_period_value(match: re.Match[str]) -> bool:
    if match.group("prefix") or match.group("unit"):
        return False
    number = match.group("number").replace(",", "")
    if not number.isdigit():
        return False
    year = int(number)
    return 1900 <= year <= 2099


def _nearest_period(text: str, start: int, end: int) -> Optional[str]:
    window_start = max(0, start - 120)
    window_end = min(len(text), end + 120)
    window = text[window_start:window_end]
    candidates = list(PERIOD_RE.finditer(window))
    if not candidates:
        return None
    relative_anchor = start - window_start
    closest = min(candidates, key=lambda match: abs(match.start() - relative_anchor))
    return re.sub(r"\s+", "", closest.group(0).upper())


def _normalize_financial_value(value: str) -> str:
    value = value.strip().lower()
    value = value.replace(",", "")
    value = value.replace(" percentage", "%").replace(" percent", "%")
    value = value.replace("usd", "$").replace("cny", "rmb")
    value = re.sub(r"\s+", "", value)
    return value


def _contract_clause_variant(clause_type: str, text: str, start: int, end: int) -> str:
    window = text[max(0, start - 160) : min(len(text), end + 220)].lower()
    if clause_type == "termination":
        if re.search(r"\b(?:without cause|for convenience|any reason)\b", window):
            return "convenience"
        if re.search(r"\b(?:only for cause|for cause|material breach)\b", window):
            return "cause_only"
    if clause_type == "exclusivity":
        if re.search(r"\bnon[-\s]?exclusive\b", window):
            return "non_exclusive"
        if re.search(r"\bexclusive\b", window):
            return "exclusive"
    if clause_type == "governing_law":
        law_match = re.search(r"\blaws of\s+(?:the\s+)?([a-z][a-z\s]{1,40}?)(?:[.,;]|$)", window)
        if law_match:
            return re.sub(r"\s+", "_", law_match.group(1).strip())
    if clause_type == "assignment":
        if re.search(r"\b(?:may not|shall not|must not|cannot)\s+assign\b", window):
            return "assignment_prohibited"
        if re.search(r"\bmay\s+assign\b|\bassign\s+without\s+consent\b", window):
            return "assignment_permitted"
    if clause_type == "liability_cap":
        value = _nearest_financial_value(text, start, end)
        if value:
            return _normalize_financial_value(value["text"])
    if clause_type == "payment_terms":
        net_match = re.search(r"\bnet\s+(\d+)\b", window)
        if net_match:
            return f"net_{net_match.group(1)}"
        days_match = re.search(r"\bwithin\s+(\d+)\s+days\b", window)
        if days_match:
            return f"net_{days_match.group(1)}"
    if clause_type == "auto_renewal":
        if re.search(r"\b(?:will not|shall not|does not|no)\s+automatic(?:ally)?\s+renew", window):
            return "no_auto_renewal"
        if re.search(r"\bautomatic(?:ally)?\s+renew|auto[-\s]?renew", window):
            return "auto_renewal"
    if clause_type == "indemnity":
        if re.search(r"\bmutual\s+indemn", window):
            return "mutual"
        if re.search(r"\b(company|seller|vendor|customer|buyer)\s+(?:shall\s+)?indemnif", window):
            return "one_way"
    return "present"


def _first_match(patterns: list[str], text: str) -> Optional[re.Match[str]]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match
    return None


def _quote_around(text: str, start: int, end: int, window: int = 180) -> str:
    quote_start = max(0, start - window)
    quote_end = min(len(text), end + window)
    quote = re.sub(r"\s+", " ", text[quote_start:quote_end]).strip()
    if quote_start > 0:
        quote = "…" + quote
    if quote_end < len(text):
        quote = quote + "…"
    return quote
