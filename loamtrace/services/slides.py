from __future__ import annotations

import json
import re
import uuid
import zipfile
from html import escape
from pathlib import Path
from typing import Optional

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches, Pt

from loamtrace.db import connect
from loamtrace.services.audit import write_audit, write_run_artifacts
from loamtrace.services.paths import ensure_project, project_db_path, project_root
from loamtrace.services.verifier import list_claims

ALLOWED_CLAIM_STATUSES = {"verified", "approved"}

SLIDE_TEMPLATES = [
    {
        "id": "investment_committee",
        "name": "Investment Committee Memo",
        "description": "Verified investment narrative with metrics, risks, comparison, timeline, and evidence appendix.",
        "recommended_claims": 3,
        "layouts": [
            "title",
            "executive_summary",
            "metric_table",
            "red_flag_table",
            "comparison_matrix",
            "timeline",
            "claim_with_evidence",
            "evidence_appendix",
        ],
    },
    {
        "id": "market_diligence",
        "name": "Market Diligence Brief",
        "description": "Evidence-led market brief focused on key claims, metrics, comparisons, and source appendix.",
        "recommended_claims": 2,
        "layouts": [
            "title",
            "executive_summary",
            "metric_table",
            "comparison_matrix",
            "claim_with_evidence",
            "evidence_appendix",
        ],
    },
    {
        "id": "risk_review",
        "name": "Risk Review",
        "description": "Review-oriented deck that foregrounds red flags, timeline, and claim-level evidence.",
        "recommended_claims": 2,
        "layouts": [
            "title",
            "executive_summary",
            "red_flag_table",
            "timeline",
            "claim_with_evidence",
            "evidence_appendix",
        ],
    },
]


def list_slide_templates() -> list[dict]:
    return [dict(template) for template in SLIDE_TEMPLATES]


def generate_template_slide_deck(
    project_id: str,
    template_id: str,
    title: Optional[str] = None,
    claim_ids: Optional[list[str]] = None,
) -> dict:
    template = _get_slide_template(template_id)
    base = generate_slide_deck(project_id, title or template["name"], claim_ids)
    deck = base["deck"]
    deck["template_id"] = template["id"]
    deck["template_name"] = template["name"]
    deck["slides"] = _apply_slide_template(deck.get("slides", []), template)
    path = Path(base["path"])
    path.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")

    run_id = f"run_{uuid.uuid4().hex}"
    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "generate_template_slides",
        {
            "input.json": {
                "project_id": project_id,
                "template_id": template_id,
                "title": title,
                "claim_ids": claim_ids,
                "base_run_id": base["run_id"],
            },
            "template.json": template,
            "deck.slide.json": deck,
            "output.json": {"deck_id": deck["deck_id"], "path": str(path), "slide_count": len(deck["slides"])},
        },
        logs=[
            {
                "type": "template_slide_deck_generated",
                "deck_id": deck["deck_id"],
                "template_id": template["id"],
                "slide_count": len(deck["slides"]),
                "path": str(path),
            }
        ],
    )
    write_audit(
        project_id,
        "template_slide_deck_generated",
        {
            "run_id": run_id,
            "base_run_id": base["run_id"],
            "deck_id": deck["deck_id"],
            "template_id": template["id"],
            "slide_count": len(deck["slides"]),
            "path": str(path),
            "run_dir": str(run_dir),
        },
    )
    return {"deck_id": deck["deck_id"], "path": str(path), "deck": deck, "run_id": run_id, "run_dir": str(run_dir)}


def _get_slide_template(template_id: str) -> dict:
    for template in SLIDE_TEMPLATES:
        if template["id"] == template_id:
            return dict(template)
    raise KeyError("slide_template_not_found")


def _apply_slide_template(slides: list[dict], template: dict) -> list[dict]:
    layouts = list(template.get("layouts") or [])
    selected = []
    claim_slides = [slide for slide in slides if slide.get("layout") == "claim_with_evidence"]
    for layout in layouts:
        if layout == "claim_with_evidence":
            selected.extend(claim_slides)
            continue
        slide = next((item for item in slides if item.get("layout") == layout), None)
        if slide:
            selected.append(slide)
    seen = set()
    deduped = []
    for slide in selected:
        slide_id = slide.get("id")
        if slide_id in seen:
            continue
        seen.add(slide_id)
        deduped.append(slide)
    for index, slide in enumerate(deduped, start=1):
        slide["id"] = f"slide_{index:03d}"
    return deduped


def generate_slide_deck(project_id: str, title: str, claim_ids: Optional[list[str]] = None) -> dict:
    ensure_project(project_id)
    claims = list_claims(project_id, claim_ids)
    if claim_ids:
        claim_order = {claim_id: index for index, claim_id in enumerate(claim_ids)}
        claims.sort(key=lambda claim: claim_order.get(claim["id"], len(claim_order)))
    blocked = [claim for claim in claims if claim["status"] not in ALLOWED_CLAIM_STATUSES]
    if blocked:
        blocked_ids = ", ".join(claim["id"] for claim in blocked)
        raise ValueError(f"blocked_claims_in_deck:{blocked_ids}")

    deck_id = f"deck_{uuid.uuid4().hex}"
    slides = [
        {
            "id": "slide_001",
            "layout": "title",
            "title": title,
            "main_claim_id": None,
            "elements": [{"type": "text", "role": "title", "text": title, "claim_id": None}],
            "speaker_notes": [],
        }
    ]

    if len(claims) > 1:
        slides.append(_executive_summary_slide(claims, len(slides) + 1))
        metric_slide = _metric_table_slide(claims, len(slides) + 1)
        if metric_slide:
            slides.append(metric_slide)
        red_flag_slide = _red_flag_table_slide(claims, len(slides) + 1)
        if red_flag_slide:
            slides.append(red_flag_slide)
        comparison_slide = _comparison_matrix_slide(claims, len(slides) + 1)
        if comparison_slide:
            slides.append(comparison_slide)
        timeline_slide = _timeline_slide(claims, len(slides) + 1)
        if timeline_slide:
            slides.append(timeline_slide)

    for claim in claims:
        citation = claim["citations"][0] if claim["citations"] else None
        slides.append(
            {
                "id": f"slide_{len(slides) + 1:03d}",
                "layout": "claim_with_evidence",
                "title": _slide_title(claim["text"]),
                "main_claim_id": claim["id"],
                "elements": [
                    {
                        "type": "text",
                        "role": "headline",
                        "text": claim["text"],
                        "claim_id": claim["id"],
                    },
                    {
                        "type": "text",
                        "role": "evidence",
                        "text": citation["quote"] if citation else "",
                        "claim_id": claim["id"],
                    },
                ],
                "speaker_notes": [
                    {
                        "claim_id": claim["id"],
                        "source_uri": citation["source_uri"] if citation else "",
                        "quote": citation["quote"] if citation else "",
                    }
                ],
            }
        )
    if claims:
        slides.append(_evidence_appendix_slide(claims, len(slides) + 1))

    deck = {"deck_id": deck_id, "title": title, "slides": slides}
    path = _deck_json_path(project_id, deck_id)
    path.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    run_id = f"run_{uuid.uuid4().hex}"
    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "generate_slides",
        {
            "input.json": {"project_id": project_id, "title": title, "claim_ids": claim_ids},
            "deck.slide.json": deck,
            "output.json": {"deck_id": deck_id, "path": str(path), "slide_count": len(slides)},
        },
        logs=[
            {
                "type": "slide_deck_generated",
                "deck_id": deck_id,
                "slide_count": len(slides),
                "path": str(path),
            }
        ],
    )
    write_audit(
        project_id,
        "slide_deck_generated",
        {
            "run_id": run_id,
            "deck_id": deck_id,
            "slide_count": len(slides),
            "path": str(path),
            "run_dir": str(run_dir),
        },
    )
    return {"deck_id": deck_id, "path": str(path), "deck": deck, "run_id": run_id, "run_dir": str(run_dir)}


def generate_chart_deck(project_id: str, title: str, chart: dict) -> dict:
    ensure_project(project_id)
    chart_element = dict(chart)
    chart_element.setdefault("type", "chart")
    deck_id = f"deck_{uuid.uuid4().hex}"
    deck = {
        "deck_id": deck_id,
        "title": title,
        "slides": [
            {
                "id": "slide_001",
                "layout": "title",
                "title": title,
                "main_claim_id": None,
                "elements": [{"type": "text", "role": "title", "text": title, "claim_id": None}],
                "speaker_notes": [],
            },
            {
                "id": "slide_002",
                "layout": "source_table_chart",
                "title": title,
                "main_claim_id": None,
                "elements": [
                    {"type": "text", "role": "headline", "text": title, "claim_id": None},
                    chart_element,
                ],
                "speaker_notes": [
                    {
                        "claim_id": None,
                        "source_uri": _chart_source_note(chart_element),
                        "quote": "Chart data generated from parsed source table cells.",
                    }
                ],
            },
        ],
    }
    assert_deck_claims_allowed(project_id, deck)
    path = _deck_json_path(project_id, deck_id)
    path.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    run_id = f"run_{uuid.uuid4().hex}"
    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "generate_chart_deck",
        {
            "input.json": {"project_id": project_id, "title": title, "chart": chart},
            "deck.slide.json": deck,
            "output.json": {"deck_id": deck_id, "path": str(path), "slide_count": len(deck["slides"])},
        },
        logs=[
            {
                "type": "chart_deck_generated",
                "deck_id": deck_id,
                "slide_count": len(deck["slides"]),
                "path": str(path),
            }
        ],
    )
    write_audit(
        project_id,
        "chart_deck_generated",
        {
            "run_id": run_id,
            "deck_id": deck_id,
            "slide_count": len(deck["slides"]),
            "path": str(path),
            "run_dir": str(run_dir),
        },
    )
    return {"deck_id": deck_id, "path": str(path), "deck": deck, "run_id": run_id, "run_dir": str(run_dir)}


def generate_table_deck(
    project_id: str,
    table_id: str,
    title: str = "Source Table Deck",
    max_rows: int = 8,
    max_cols: int = 6,
) -> dict:
    ensure_project(project_id)
    table, cells = _load_source_table_cells(project_id, table_id)
    rows, cell_ids = _source_table_rows(cells, max_rows, max_cols)
    if not rows or not cell_ids:
        raise ValueError("table_has_no_cells")

    deck_id = f"deck_{uuid.uuid4().hex}"
    source_label = table.get("caption") or table.get("sheet_name") or table.get("id") or table_id
    table_element = {
        "type": "table",
        "role": "source_table",
        "rows": rows,
        "data_source": {"table_id": table_id, "cell_ids": cell_ids},
    }
    deck = {
        "deck_id": deck_id,
        "title": title,
        "slides": [
            {
                "id": "slide_001",
                "layout": "title",
                "title": title,
                "main_claim_id": None,
                "elements": [{"type": "text", "role": "title", "text": title, "claim_id": None}],
                "speaker_notes": [],
            },
            {
                "id": "slide_002",
                "layout": "source_table",
                "title": str(source_label),
                "main_claim_id": None,
                "elements": [
                    {"type": "text", "role": "headline", "text": str(source_label), "claim_id": None},
                    table_element,
                ],
                "speaker_notes": [
                    {
                        "claim_id": None,
                        "source_uri": f"table:{table_id}",
                        "quote": "Table slide generated from parsed source table cells.",
                    }
                ],
            },
        ],
    }
    assert_deck_claims_allowed(project_id, deck)
    path = _deck_json_path(project_id, deck_id)
    path.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    run_id = f"run_{uuid.uuid4().hex}"
    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "generate_table_deck",
        {
            "input.json": {
                "project_id": project_id,
                "table_id": table_id,
                "title": title,
                "max_rows": max_rows,
                "max_cols": max_cols,
            },
            "table.json": table,
            "deck.slide.json": deck,
            "output.json": {"deck_id": deck_id, "path": str(path), "slide_count": len(deck["slides"])},
        },
        logs=[
            {
                "type": "table_deck_generated",
                "deck_id": deck_id,
                "table_id": table_id,
                "cell_count": len(cell_ids),
                "path": str(path),
            }
        ],
    )
    write_audit(
        project_id,
        "table_deck_generated",
        {
            "run_id": run_id,
            "deck_id": deck_id,
            "table_id": table_id,
            "cell_count": len(cell_ids),
            "path": str(path),
            "run_dir": str(run_dir),
        },
    )
    return {"deck_id": deck_id, "path": str(path), "deck": deck, "run_id": run_id, "run_dir": str(run_dir)}


def _executive_summary_slide(claims: list[dict], index: int) -> dict:
    primary_claim = claims[0]
    elements = [
        {
            "type": "text",
            "role": "headline",
            "text": "Key verified claims",
            "claim_id": primary_claim["id"],
        }
    ]
    speaker_notes = []
    for claim in claims[:5]:
        citation = claim["citations"][0] if claim["citations"] else None
        elements.append(
            {
                "type": "text",
                "role": "summary_bullet",
                "text": f"- {claim['text']}",
                "claim_id": claim["id"],
            }
        )
        speaker_notes.append(
            {
                "claim_id": claim["id"],
                "source_uri": citation["source_uri"] if citation else "",
                "quote": citation["quote"] if citation else "",
            }
        )
    return {
        "id": f"slide_{index:03d}",
        "layout": "executive_summary",
        "title": "Executive summary",
        "main_claim_id": primary_claim["id"],
        "elements": elements,
        "speaker_notes": speaker_notes,
    }


def _evidence_appendix_slide(claims: list[dict], index: int) -> dict:
    primary_claim = claims[0]
    elements = [
        {
            "type": "text",
            "role": "headline",
            "text": "Evidence appendix",
            "claim_id": primary_claim["id"],
        }
    ]
    speaker_notes = []
    for claim in claims[:5]:
        citation = claim["citations"][0] if claim["citations"] else None
        source_uri = citation["source_uri"] if citation else ""
        quote = citation["quote"] if citation else ""
        elements.append(
            {
                "type": "text",
                "role": "evidence_appendix_item",
                "text": f"- {claim['id']}: {quote} ({source_uri})",
                "claim_id": claim["id"],
            }
        )
        speaker_notes.append(
            {
                "claim_id": claim["id"],
                "source_uri": source_uri,
                "quote": quote,
            }
        )
    return {
        "id": f"slide_{index:03d}",
        "layout": "evidence_appendix",
        "title": "Evidence appendix",
        "main_claim_id": primary_claim["id"],
        "elements": elements,
        "speaker_notes": speaker_notes,
    }


def _metric_table_slide(claims: list[dict], index: int) -> Optional[dict]:
    metric_rows = [["Claim", "Metrics", "Source"]]
    speaker_notes = []
    metric_claims = []
    for claim in claims:
        metrics = _claim_metrics(claim["text"])
        if not metrics:
            continue
        citation = claim["citations"][0] if claim["citations"] else None
        source_uri = citation["source_uri"] if citation else ""
        quote = citation["quote"] if citation else ""
        metric_rows.append([_slide_title(claim["text"]), ", ".join(metrics), source_uri])
        metric_claims.append(claim)
        speaker_notes.append(
            {
                "claim_id": claim["id"],
                "source_uri": source_uri,
                "quote": quote,
            }
        )
    if not metric_claims:
        return None
    primary_claim = metric_claims[0]
    return {
        "id": f"slide_{index:03d}",
        "layout": "metric_table",
        "title": "Verified metrics",
        "main_claim_id": primary_claim["id"],
        "elements": [
            {
                "type": "text",
                "role": "headline",
                "text": "Verified metrics",
                "claim_id": primary_claim["id"],
            },
            {
                "type": "table",
                "role": "metric_table",
                "rows": metric_rows[:6],
                "claim_id": primary_claim["id"],
            },
        ],
        "speaker_notes": speaker_notes[:5],
    }


def _timeline_slide(claims: list[dict], index: int) -> Optional[dict]:
    timeline_items = []
    speaker_notes = []
    for claim in claims:
        years = _claim_years(claim["text"])
        if not years:
            continue
        citation = claim["citations"][0] if claim["citations"] else None
        source_uri = citation["source_uri"] if citation else ""
        quote = citation["quote"] if citation else ""
        for year in years[:2]:
            timeline_items.append({"year": year, "claim": claim, "source_uri": source_uri})
        speaker_notes.append({"claim_id": claim["id"], "source_uri": source_uri, "quote": quote})
    if not timeline_items:
        return None
    timeline_items.sort(key=lambda item: (item["year"], item["claim"]["id"]))
    primary_claim = timeline_items[0]["claim"]
    elements = [
        {
            "type": "text",
            "role": "headline",
            "text": "Evidence timeline",
            "claim_id": primary_claim["id"],
        }
    ]
    for item in timeline_items[:5]:
        claim = item["claim"]
        elements.append(
            {
                "type": "text",
                "role": "timeline_item",
                "text": f"- {item['year']}: {claim['text']} ({item['source_uri']})",
                "claim_id": claim["id"],
            }
        )
    return {
        "id": f"slide_{index:03d}",
        "layout": "timeline",
        "title": "Evidence timeline",
        "main_claim_id": primary_claim["id"],
        "elements": elements,
        "speaker_notes": speaker_notes[:5],
    }


def _red_flag_table_slide(claims: list[dict], index: int) -> Optional[dict]:
    red_flags = [claim for claim in claims if _is_red_flag_claim(claim["text"])]
    if not red_flags:
        return None
    primary_claim = red_flags[0]
    rows = [["Red flag", "Evidence source"]]
    speaker_notes = []
    for claim in red_flags[:5]:
        citation = claim["citations"][0] if claim["citations"] else None
        source_uri = citation["source_uri"] if citation else ""
        rows.append([_slide_title(claim["text"]), source_uri])
        speaker_notes.append(
            {
                "claim_id": claim["id"],
                "source_uri": source_uri,
                "quote": citation["quote"] if citation else "",
            }
        )
    return {
        "id": f"slide_{index:03d}",
        "layout": "red_flag_table",
        "title": "Red flags",
        "main_claim_id": primary_claim["id"],
        "elements": [
            {
                "type": "text",
                "role": "headline",
                "text": "Red flags",
                "claim_id": primary_claim["id"],
            },
            {
                "type": "table",
                "role": "red_flag_table",
                "rows": rows,
                "claim_id": primary_claim["id"],
            },
        ],
        "speaker_notes": speaker_notes,
    }


def _comparison_matrix_slide(claims: list[dict], index: int) -> Optional[dict]:
    if len(claims) < 2:
        return None
    rows = [["Claim", "Metrics", "Years", "Source"]]
    speaker_notes = []
    for claim in claims[:5]:
        citation = claim["citations"][0] if claim["citations"] else None
        source_uri = citation["source_uri"] if citation else ""
        rows.append(
            [
                _slide_title(claim["text"]),
                ", ".join(_claim_metrics(claim["text"])) or "-",
                ", ".join(_claim_years(claim["text"])) or "-",
                source_uri,
            ]
        )
        speaker_notes.append(
            {
                "claim_id": claim["id"],
                "source_uri": source_uri,
                "quote": citation["quote"] if citation else "",
            }
        )
    primary_claim = claims[0]
    return {
        "id": f"slide_{index:03d}",
        "layout": "comparison_matrix",
        "title": "Comparison matrix",
        "main_claim_id": primary_claim["id"],
        "elements": [
            {
                "type": "text",
                "role": "headline",
                "text": "Comparison matrix",
                "claim_id": primary_claim["id"],
            },
            {
                "type": "table",
                "role": "comparison_matrix",
                "rows": rows,
                "claim_id": primary_claim["id"],
            },
        ],
        "speaker_notes": speaker_notes,
    }


def _claim_metrics(text: str) -> list[str]:
    return re.findall(
        r"(?<![\w.])(?:[$¥€]|USD|RMB|CNY|EUR|GBP)?\s*-?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|percentage|million|billion|thousand|mn|bn|x)?(?!\w)",
        text,
        re.IGNORECASE,
    )


def _claim_years(text: str) -> list[str]:
    return re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text)


def _is_red_flag_claim(text: str) -> bool:
    return bool(
        re.search(
            r"\b(risk|red flag|declin(?:e|ed|ing)|decrease(?:d)?|loss|churn|concentration|customer concentration|default|breach)\b",
            text,
            re.IGNORECASE,
        )
    )


def load_slide_deck(project_id: str, deck_id: str) -> dict:
    path = _deck_json_path(project_id, deck_id)
    if not path.exists():
        raise KeyError("deck_not_found")
    return json.loads(path.read_text(encoding="utf-8"))


def export_pptx(project_id: str, deck_id: str) -> dict:
    run_id = f"run_{uuid.uuid4().hex}"
    deck = load_slide_deck(project_id, deck_id)
    assert_deck_claims_allowed(project_id, deck)
    out_path = project_root(project_id) / "slides" / f"{deck_id}.pptx"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_pptx(deck, out_path)
    run_dir = write_run_artifacts(
        project_id,
        run_id,
        "export_pptx",
        {
            "input.json": {"project_id": project_id, "deck_id": deck_id},
            "deck.slide.json": deck,
            "output.json": {"path": str(out_path), "status": "exported"},
        },
        logs=[
            {
                "type": "pptx_exported",
                "deck_id": deck_id,
                "slide_count": len(deck.get("slides", [])),
                "path": str(out_path),
            }
        ],
    )
    write_audit(
        project_id,
        "pptx_exported",
        {"run_id": run_id, "deck_id": deck_id, "path": str(out_path), "run_dir": str(run_dir)},
    )
    return {"deck_id": deck_id, "path": str(out_path), "status": "exported", "run_id": run_id, "run_dir": str(run_dir)}


def assert_deck_claims_allowed(project_id: str, deck: dict) -> None:
    annotate_chart_review_status(project_id, deck)
    annotate_table_review_status(project_id, deck)
    chart_blocked = [
        slide.get("id") or "unknown_slide"
        for slide in deck.get("slides", [])
        for element in slide.get("elements", [])
        if element.get("type") == "chart" and element.get("review_status") == "needs_review"
    ]
    if chart_blocked:
        raise ValueError("chart_needs_review:" + ",".join(chart_blocked))
    table_blocked = [
        slide.get("id") or "unknown_slide"
        for slide in deck.get("slides", [])
        for element in slide.get("elements", [])
        if element.get("type") == "table" and element.get("review_status") == "needs_review"
    ]
    if table_blocked:
        raise ValueError("table_needs_review:" + ",".join(table_blocked))

    missing_claim_slides = [
        slide.get("id") or "unknown_slide"
        for slide in deck.get("slides", [])
        if slide.get("layout") != "title"
        and not slide.get("main_claim_id")
        and not _slide_has_verified_chart(slide)
        and not _slide_has_verified_source_table(slide)
    ]
    if missing_claim_slides:
        raise ValueError("slide_claim_missing:" + ",".join(missing_claim_slides))

    claim_ids = [
        slide.get("main_claim_id")
        for slide in deck.get("slides", [])
        if slide.get("main_claim_id")
    ]
    if not claim_ids:
        return
    claims = {claim["id"]: claim for claim in list_claims(project_id, claim_ids)}
    blocked = [
        claim_id
        for claim_id in claim_ids
        if claims.get(claim_id, {}).get("status") not in ALLOWED_CLAIM_STATUSES
    ]
    if blocked:
        raise ValueError("blocked_claims_in_deck:" + ",".join(blocked))


def _slide_has_verified_chart(slide: dict) -> bool:
    return any(
        element.get("type") == "chart" and element.get("review_status") == "verified"
        for element in slide.get("elements", [])
    )


def _slide_has_verified_source_table(slide: dict) -> bool:
    return any(
        element.get("type") == "table" and element.get("review_status") == "verified"
        for element in slide.get("elements", [])
    )


def _chart_source_note(chart: dict) -> str:
    data_source = _chart_data_source(chart)
    table_id = data_source.get("table_id")
    cell_ids = data_source.get("cell_ids") or []
    if table_id:
        return f"table:{table_id}"
    if cell_ids:
        return "cells:" + ",".join(str(cell_id) for cell_id in cell_ids[:8])
    return "chart:source-missing"


def annotate_chart_review_status(project_id: str, deck: dict) -> dict:
    cell_ids = sorted(
        {
            cell_id
            for slide in deck.get("slides", [])
            for element in slide.get("elements", [])
            if element.get("type") == "chart"
            for cell_id in _chart_data_source(element).get("cell_ids", [])
        }
    )
    table_ids = sorted(
        {
            table_id
            for slide in deck.get("slides", [])
            for element in slide.get("elements", [])
            if element.get("type") == "chart"
            for table_id in _chart_table_ids(_chart_data_source(element))
        }
    )
    table_cells = _table_cell_ids(project_id, table_ids)
    resolved_table_cell_ids = {
        cell_id
        for table_id in table_ids
        for cell_id in table_cells.get(table_id, set())
    }
    cell_lookup = _cell_lookup(project_id, sorted(set(cell_ids) | resolved_table_cell_ids))
    existing = set(cell_lookup)
    for slide in deck.get("slides", []):
        for element in slide.get("elements", []):
            if element.get("type") != "chart":
                continue
            data_source = _chart_data_source(element)
            element["data_source"] = data_source
            source_ids = data_source.get("cell_ids") or []
            source_tables = _chart_table_ids(data_source)
            has_source = bool(source_ids or source_tables)
            cells_ok = not source_ids or set(source_ids).issubset(existing)
            tables_ok = not source_tables or all(table_cells.get(table_id) for table_id in source_tables)
            if has_source and cells_ok and tables_ok:
                if source_tables:
                    resolved_ids = sorted(
                        {
                            cell_id
                            for table_id in source_tables
                            for cell_id in table_cells.get(table_id, set())
                        }
                        | set(source_ids)
                    )
                    data_source["cell_ids"] = resolved_ids
                values_ok = _chart_values_match(element, cell_lookup)
                if not values_ok:
                    element["review_status"] = "needs_review"
                    element["failure_reason"] = "chart_cell_value_mismatch"
                    continue
                element["review_status"] = "verified"
                element.pop("failure_reason", None)
            else:
                element["review_status"] = "needs_review"
                element["failure_reason"] = "chart_cell_source_missing"
    return deck


def annotate_table_review_status(project_id: str, deck: dict) -> dict:
    cell_ids = sorted(
        {
            cell_id
            for slide in deck.get("slides", [])
            for element in slide.get("elements", [])
            if element.get("type") == "table" and _table_data_source(element)
            for cell_id in _table_data_source(element).get("cell_ids", [])
        }
    )
    table_ids = sorted(
        {
            table_id
            for slide in deck.get("slides", [])
            for element in slide.get("elements", [])
            if element.get("type") == "table" and _table_data_source(element)
            for table_id in _table_table_ids(_table_data_source(element))
        }
    )
    table_cells = _table_cell_ids(project_id, table_ids)
    resolved_table_cell_ids = {
        cell_id
        for table_id in table_ids
        for cell_id in table_cells.get(table_id, set())
    }
    cell_lookup = _cell_lookup(project_id, sorted(set(cell_ids) | resolved_table_cell_ids))
    existing = set(cell_lookup)
    for slide in deck.get("slides", []):
        for element in slide.get("elements", []):
            if element.get("type") != "table":
                continue
            data_source = _table_data_source(element)
            if not data_source:
                continue
            element["data_source"] = data_source
            source_ids = data_source.get("cell_ids") or []
            source_tables = _table_table_ids(data_source)
            has_source = bool(source_ids or source_tables)
            cells_ok = not source_ids or set(source_ids).issubset(existing)
            tables_ok = not source_tables or all(table_cells.get(table_id) for table_id in source_tables)
            if has_source and cells_ok and tables_ok:
                if source_tables:
                    resolved_ids = sorted(
                        {
                            cell_id
                            for table_id in source_tables
                            for cell_id in table_cells.get(table_id, set())
                        }
                        | set(source_ids)
                    )
                    data_source["cell_ids"] = resolved_ids
                values_ok = _table_values_match(element, cell_lookup)
                if not values_ok:
                    element["review_status"] = "needs_review"
                    element["failure_reason"] = "table_cell_value_mismatch"
                    continue
                element["review_status"] = "verified"
                element.pop("failure_reason", None)
            else:
                element["review_status"] = "needs_review"
                element["failure_reason"] = "table_cell_source_missing"
    return deck


def _chart_data_source(element: dict) -> dict:
    data_source = element.get("data_source")
    return data_source if isinstance(data_source, dict) else {}


def _table_data_source(element: dict) -> dict:
    data_source = element.get("data_source")
    return data_source if isinstance(data_source, dict) else {}


def _chart_table_ids(data_source: dict) -> list[str]:
    table_ids = []
    table_id = data_source.get("table_id")
    if table_id:
        table_ids.append(table_id)
    table_ids.extend(data_source.get("table_ids") or [])
    return [str(value) for value in table_ids if value]


def _table_table_ids(data_source: dict) -> list[str]:
    table_ids = []
    table_id = data_source.get("table_id")
    if table_id:
        table_ids.append(table_id)
    table_ids.extend(data_source.get("table_ids") or [])
    return [str(value) for value in table_ids if value]


def _load_source_table_cells(project_id: str, table_id: str) -> tuple[dict, list[dict]]:
    with connect(project_db_path(project_id)) as conn:
        table = conn.execute(
            """
            select
              t.*,
              d.filename as document_filename,
              d.mime_type as document_mime_type,
              min(c.sheet_name) as sheet_name
            from tables t
            left join documents d on d.id = t.document_id
            left join cells c on c.table_id = t.id
            where t.id = ?
            group by t.id
            """,
            (table_id,),
        ).fetchone()
        if not table:
            raise KeyError("table_not_found")
        cells = conn.execute(
            """
            select * from cells
            where table_id = ?
            order by row_index asc, col_index asc
            """,
            (table_id,),
        ).fetchall()
    return dict(table), [dict(cell) for cell in cells]


def _source_table_rows(cells: list[dict], max_rows: int, max_cols: int) -> tuple[list[list[str]], list[str]]:
    grid: dict[int, dict[int, dict]] = {}
    for cell in cells:
        row_index = cell.get("row_index") or 0
        col_index = cell.get("col_index") or 0
        grid.setdefault(row_index, {})[col_index] = cell
    if not grid:
        return [], []
    columns = sorted({col_index for row in grid.values() for col_index in row.keys()})[:max_cols]
    rows = []
    cell_ids = []
    for row_index in sorted(grid.keys())[:max_rows]:
        row = grid[row_index]
        values = []
        for col_index in columns:
            cell = row.get(col_index)
            values.append(str(cell.get("text") or "") if cell else "")
            if cell and cell.get("id"):
                cell_ids.append(str(cell["id"]))
        rows.append(values)
    return rows, sorted(set(cell_ids))


def _existing_cell_ids(project_id: str, cell_ids: list[str]) -> set[str]:
    if not cell_ids:
        return set()
    placeholders = ",".join("?" for _ in cell_ids)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            f"select id from cells where id in ({placeholders})",
            cell_ids,
        ).fetchall()
    return {row["id"] for row in rows}


def _table_cell_ids(project_id: str, table_ids: list[str]) -> dict[str, set[str]]:
    if not table_ids:
        return {}
    placeholders = ",".join("?" for _ in table_ids)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            f"select table_id, id from cells where table_id in ({placeholders})",
            table_ids,
        ).fetchall()
    result: dict[str, set[str]] = {table_id: set() for table_id in table_ids}
    for row in rows:
        result[row["table_id"]].add(row["id"])
    return result


def _cell_lookup(project_id: str, cell_ids: list[str]) -> dict[str, dict]:
    if not cell_ids:
        return {}
    placeholders = ",".join("?" for _ in cell_ids)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            f"select * from cells where id in ({placeholders})",
            cell_ids,
        ).fetchall()
    return {row["id"]: dict(row) for row in rows}


def _chart_values_match(element: dict, cell_lookup: dict[str, dict]) -> bool:
    for series in element.get("series") or []:
        for point in series.get("points") or []:
            cell_id = point.get("cell_id")
            if not cell_id:
                continue
            cell = cell_lookup.get(str(cell_id))
            if not cell:
                return False
            if "value" in point and not _cell_value_matches(point.get("value"), cell):
                return False
    return True


def _table_values_match(element: dict, cell_lookup: dict[str, dict]) -> bool:
    data_source = _table_data_source(element)
    source_ids = [str(cell_id) for cell_id in data_source.get("cell_ids") or []]
    if not source_ids:
        return True
    rendered_values = [_rendered_value(value) for row in element.get("rows") or [] for value in row]
    for cell_id in source_ids:
        cell = cell_lookup.get(cell_id)
        if not cell:
            return False
        expected = _rendered_value(cell.get("text") or "")
        if expected and expected not in rendered_values:
            return False
    return True


def _cell_value_matches(value: object, cell: dict) -> bool:
    candidates = [cell.get("text") or ""]
    try:
        parsed = json.loads(cell.get("value_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        parsed = {}
    if isinstance(parsed, dict):
        candidates.extend(str(item) for item in parsed.values() if item is not None)
    return any(_values_equivalent(value, candidate) for candidate in candidates)


def _values_equivalent(left: object, right: object) -> bool:
    left_text = _rendered_value(left)
    right_text = _rendered_value(right)
    try:
        return abs(float(left_text) - float(right_text)) < 1e-9
    except ValueError:
        return left_text == right_text


def _rendered_value(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def _deck_json_path(project_id: str, deck_id: str) -> Path:
    root = project_root(project_id) / "slides"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{deck_id}.slide.json"


def _slide_title(text: str) -> str:
    return text if len(text) <= 72 else text[:69].rstrip() + "..."


def _write_pptx(deck: dict, out_path: Path) -> None:
    slides = deck.get("slides", [])
    _write_pptx_native(deck, out_path)
    _inject_speaker_notes(out_path, slides)


def _write_pptx_native(deck: dict, out_path: Path) -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]
    for slide in deck.get("slides", []):
        ppt_slide = prs.slides.add_slide(blank_layout)
        _add_text_box(ppt_slide, slide.get("title") or "", 0.75, 0.45, 11.8, 0.75, 28)
        body = "\n\n".join(
            element.get("text", "")
            for element in slide.get("elements", [])
            if element.get("type") == "text" and element.get("role") != "title"
        )
        if body:
            _add_text_box(ppt_slide, body, 0.9, 1.35, 11.4, 2.0, 17)
        extra_top = 2.65
        for element in slide.get("elements", []):
            if element.get("type") == "table":
                rows = _table_rows(element)
                if rows:
                    _add_native_table(ppt_slide, rows, 0.9, extra_top, 11.4, min(3.6, 0.38 * len(rows)))
                    extra_top += min(3.8, 0.42 * len(rows)) + 0.25
            elif element.get("type") == "chart" and _chart_series(element):
                _add_native_chart(ppt_slide, element, 0.9, extra_top, 11.4, 3.7)
                extra_top += 3.95
    prs.save(out_path)


def _add_text_box(slide, text: str, left: float, top: float, width: float, height: float, font_size: int) -> None:
    shape = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    text_frame = shape.text_frame
    text_frame.clear()
    lines = text.splitlines() or [""]
    for index, line in enumerate(lines):
        paragraph = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
        paragraph.text = line
        for run in paragraph.runs:
            run.font.name = "Arial"
            run.font.size = Pt(font_size)


def _add_native_table(slide, rows: list[list[str]], left: float, top: float, width: float, height: float) -> None:
    row_count = len(rows)
    col_count = max(len(row) for row in rows)
    table = slide.shapes.add_table(
        row_count,
        col_count,
        Inches(left),
        Inches(top),
        Inches(width),
        Inches(height),
    ).table
    for row_index, row in enumerate(rows):
        for col_index in range(col_count):
            cell = table.cell(row_index, col_index)
            cell.text = row[col_index] if col_index < len(row) else ""
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.name = "Arial"
                    run.font.size = Pt(11)


def _add_native_chart(slide, element: dict, left: float, top: float, width: float, height: float) -> None:
    series = _chart_series(element)
    labels = [
        str(point.get("label", ""))
        for point in series[0].get("points", [])
        if isinstance(point, dict)
    ]
    chart_data = CategoryChartData()
    chart_data.categories = labels
    for item in series:
        values = [
            float(point.get("value", 0) or 0)
            for point in item.get("points", [])
            if isinstance(point, dict)
        ]
        chart_data.add_series(str(item.get("name", "Series")), values)
    chart_type = XL_CHART_TYPE.LINE if element.get("chart_type") == "line" else XL_CHART_TYPE.COLUMN_CLUSTERED
    chart = slide.shapes.add_chart(
        chart_type,
        Inches(left),
        Inches(top),
        Inches(width),
        Inches(height),
        chart_data,
    ).chart
    chart.has_legend = True


def _inject_speaker_notes(out_path: Path, slides: list[dict]) -> None:
    if not slides:
        return
    with zipfile.ZipFile(out_path, "r") as source:
        entries = [(item, source.read(item.filename)) for item in source.infolist()]
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for item, data in entries:
            name = item.filename
            if name == "[Content_Types].xml":
                data = _add_notes_content_types(data.decode("utf-8"), len(slides)).encode("utf-8")
            elif name == "ppt/_rels/presentation.xml.rels":
                data = _add_relationship(
                    data.decode("utf-8"),
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster",
                    "notesMasters/notesMaster1.xml",
                ).encode("utf-8")
            elif name.startswith("ppt/slides/_rels/slide") and name.endswith(".xml.rels"):
                match = re.search(r"slide(\d+)\.xml\.rels$", name)
                if match:
                    index = int(match.group(1))
                    data = _add_relationship(
                        data.decode("utf-8"),
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide",
                        f"../notesSlides/notesSlide{index}.xml",
                    ).encode("utf-8")
            archive.writestr(item, data)
        archive.writestr("ppt/notesMasters/notesMaster1.xml", _notes_master_xml())
        archive.writestr("ppt/notesMasters/_rels/notesMaster1.xml.rels", _notes_master_rels())
        for index, slide in enumerate(slides, start=1):
            archive.writestr(f"ppt/notesSlides/notesSlide{index}.xml", _notes_slide_xml(slide, index))
            archive.writestr(f"ppt/notesSlides/_rels/notesSlide{index}.xml.rels", _notes_slide_rels(index))


def _add_notes_content_types(content_types: str, slide_count: int) -> str:
    additions = [
        '<Override PartName="/ppt/notesMasters/notesMaster1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"/>'
    ]
    additions.extend(
        f'<Override PartName="/ppt/notesSlides/notesSlide{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>'
        for i in range(1, slide_count + 1)
    )
    return content_types.replace("</Types>", "".join(additions) + "</Types>")


def _add_relationship(rels_xml: str, rel_type: str, target: str) -> str:
    ids = [int(match) for match in re.findall(r'Id="rId(\d+)"', rels_xml)]
    rel_id = f"rId{max(ids, default=0) + 1}"
    relationship = f'<Relationship Id="{rel_id}" Type="{rel_type}" Target="{target}"/>'
    return rels_xml.replace("</Relationships>", relationship + "</Relationships>")


def _write_pptx_legacy(deck: dict, out_path: Path) -> None:
    slides = deck.get("slides", [])
    chart_refs = _chart_refs_by_slide(slides)
    chart_count = sum(len(refs) for refs in chart_refs.values())
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(slides), chart_count))
        archive.writestr("_rels/.rels", _root_rels())
        archive.writestr("ppt/presentation.xml", _presentation_xml(len(slides)))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(len(slides)))
        archive.writestr("ppt/theme/theme1.xml", _theme_xml())
        archive.writestr("ppt/slideMasters/slideMaster1.xml", _slide_master_xml())
        archive.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _slide_master_rels())
        archive.writestr("ppt/slideLayouts/slideLayout1.xml", _slide_layout_xml())
        archive.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _slide_layout_rels())
        archive.writestr("ppt/notesMasters/notesMaster1.xml", _notes_master_xml())
        archive.writestr("ppt/notesMasters/_rels/notesMaster1.xml.rels", _notes_master_rels())
        archive.writestr("docProps/core.xml", _core_props(deck.get("title", "Deck")))
        archive.writestr("docProps/app.xml", _app_props(len(slides)))
        for index, slide in enumerate(slides, start=1):
            refs = chart_refs.get(index, [])
            archive.writestr(f"ppt/slides/slide{index}.xml", _slide_xml(slide, refs))
            archive.writestr(f"ppt/slides/_rels/slide{index}.xml.rels", _slide_rels(index, refs))
            archive.writestr(f"ppt/notesSlides/notesSlide{index}.xml", _notes_slide_xml(slide, index))
            archive.writestr(
                f"ppt/notesSlides/_rels/notesSlide{index}.xml.rels",
                _notes_slide_rels(index),
            )
            for ref in refs:
                archive.writestr(f"ppt/charts/chart{ref['chart_index']}.xml", _chart_xml(ref["element"]))


def _chart_refs_by_slide(slides: list[dict]) -> dict[int, list[dict]]:
    refs: dict[int, list[dict]] = {}
    chart_index = 1
    for slide_index, slide in enumerate(slides, start=1):
        for element in slide.get("elements", []):
            if element.get("type") != "chart" or not _chart_series(element):
                continue
            refs.setdefault(slide_index, []).append(
                {
                    "rel_id": f"rId{3 + len(refs.get(slide_index, []))}",
                    "chart_index": chart_index,
                    "element": element,
                }
            )
            chart_index += 1
    return refs


def _content_types(slide_count: int, chart_count: int = 0) -> str:
    slide_overrides = "\n".join(
        f'<Override PartName="/ppt/slides/slide{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, slide_count + 1)
    )
    notes_overrides = "\n".join(
        f'<Override PartName="/ppt/notesSlides/notesSlide{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>'
        for i in range(1, slide_count + 1)
    )
    chart_overrides = "\n".join(
        f'<Override PartName="/ppt/charts/chart{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>'
        for i in range(1, chart_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/notesMasters/notesMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  {slide_overrides}
  {notes_overrides}
  {chart_overrides}
</Types>"""


def _root_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""


def _presentation_xml(slide_count: int) -> str:
    slide_ids = "\n".join(
        f'<p:sldId id="{255 + i}" r:id="rId{i}"/>' for i in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId{slide_count + 1}"/></p:sldMasterIdLst>
  <p:sldIdLst>{slide_ids}</p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000" type="wide"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>"""


def _presentation_rels(slide_count: int) -> str:
    rels = [
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>'
        for i in range(1, slide_count + 1)
    ]
    rels.append(
        f'<Relationship Id="rId{slide_count + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
    )
    rels.append(
        f'<Relationship Id="rId{slide_count + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster" Target="notesMasters/notesMaster1.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels)
        + "</Relationships>"
    )


def _slide_xml(slide: dict, chart_refs: Optional[list[dict]] = None) -> str:
    title = slide.get("title") or ""
    elements = slide.get("elements", [])
    body = "\n\n".join(
        element.get("text", "")
        for element in elements
        if element.get("type") == "text" and element.get("role") != "title"
    )
    extra_shapes = _slide_extra_shapes(elements, chart_refs or [])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
    {_text_box(2, "Title", 700000, 450000, 10800000, 900000, title, 3200)}
    {_text_box(3, "Body", 850000, 1500000, 10400000, 4200000, body, 2000)}
    {extra_shapes}
  </p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""


def _text_box(shape_id: int, name: str, x: int, y: int, cx: int, cy: int, text: str, font_size: int) -> str:
    paragraphs = "".join(
        f'<a:p><a:r><a:rPr lang="en-US" sz="{font_size}"/><a:t>{escape(line)}</a:t></a:r><a:endParaRPr lang="en-US" sz="{font_size}"/></a:p>'
        for line in (text.splitlines() or [""])
    )
    return f"""<p:sp>
      <p:nvSpPr><p:cNvPr id="{shape_id}" name="{name}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
      <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>
      <p:txBody><a:bodyPr wrap="square" rtlCol="0"><a:spAutoFit/></a:bodyPr><a:lstStyle/>{paragraphs}</p:txBody>
    </p:sp>"""


def _table_frame(shape_id: int, element: dict) -> str:
    rows = _table_rows(element)
    if not rows:
        return ""
    col_count = max(len(row) for row in rows)
    col_width = 10400000 // col_count
    row_height = 450000
    grid = "".join(f'<a:gridCol w="{col_width}"/>' for _ in range(col_count))
    table_rows = "".join(_table_row(row, col_count, row_height) for row in rows)
    return f"""<p:graphicFrame>
      <p:nvGraphicFramePr><p:cNvPr id="{shape_id}" name="Table"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>
      <p:xfrm><a:off x="850000" y="2550000"/><a:ext cx="10400000" cy="{row_height * len(rows)}"/></p:xfrm>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">
        <a:tbl><a:tblPr firstRow="1" bandRow="1"/><a:tblGrid>{grid}</a:tblGrid>{table_rows}</a:tbl>
      </a:graphicData></a:graphic>
    </p:graphicFrame>"""


def _table_rows(element: dict) -> list[list[str]]:
    rows = element.get("rows")
    if rows is None:
        rows = element.get("data", {}).get("rows", []) if isinstance(element.get("data"), dict) else []
    normalized = []
    for row in rows or []:
        if isinstance(row, dict):
            normalized.append([str(value) for value in row.values()])
        elif isinstance(row, list):
            normalized.append([str(value) for value in row])
    return [row for row in normalized if row]


def _table_row(row: list[str], col_count: int, height: int) -> str:
    cells = "".join(_table_cell(row[index] if index < len(row) else "") for index in range(col_count))
    return f'<a:tr h="{height}">{cells}</a:tr>'


def _table_cell(text: str) -> str:
    return (
        '<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>'
        f'<a:p><a:r><a:rPr lang="en-US" sz="1200"/><a:t>{escape(text)}</a:t></a:r></a:p>'
        '</a:txBody><a:tcPr/></a:tc>'
    )


def _chart_frame(shape_id: int, rel_id: str) -> str:
    return f"""<p:graphicFrame>
      <p:nvGraphicFramePr><p:cNvPr id="{shape_id}" name="Chart"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>
      <p:xfrm><a:off x="850000" y="2450000"/><a:ext cx="10400000" cy="3600000"/></p:xfrm>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">
        <c:chart r:id="{rel_id}"/>
      </a:graphicData></a:graphic>
    </p:graphicFrame>"""


def _chart_xml(element: dict) -> str:
    chart_tag = "c:lineChart" if element.get("chart_type") == "line" else "c:barChart"
    grouping = '<c:grouping val="standard"/>'
    bar_dir = '<c:barDir val="col"/>' if chart_tag == "c:barChart" else ""
    series_xml = "".join(_chart_series_xml(index, series) for index, series in enumerate(_chart_series(element)))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <c:chart><c:plotArea><c:layout/>
    <{chart_tag}>{grouping}{bar_dir}{series_xml}<c:axId val="1"/><c:axId val="2"/></{chart_tag}>
    <c:catAx><c:axId val="1"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="b"/><c:tickLblPos val="nextTo"/><c:crossAx val="2"/></c:catAx>
    <c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="l"/><c:majorGridlines/><c:tickLblPos val="nextTo"/><c:crossAx val="1"/></c:valAx>
  </c:plotArea><c:legend><c:legendPos val="r"/><c:layout/></c:legend><c:plotVisOnly val="1"/></c:chart>
</c:chartSpace>"""


def _chart_series(element: dict) -> list[dict]:
    series = element.get("series")
    if series is None and isinstance(element.get("data"), dict):
        series = element["data"].get("series")
    return [item for item in (series or []) if isinstance(item, dict)]


def _chart_series_xml(index: int, series: dict) -> str:
    points = [point for point in series.get("points", []) if isinstance(point, dict)]
    labels = [str(point.get("label", "")) for point in points]
    values = [point.get("value", 0) for point in points]
    return f"""<c:ser><c:idx val="{index}"/><c:order val="{index}"/>
      <c:tx><c:v>{escape(str(series.get("name", f"Series {index + 1}")))}</c:v></c:tx>
      <c:cat>{_chart_string_literal(labels)}</c:cat>
      <c:val>{_chart_number_literal(values)}</c:val>
    </c:ser>"""


def _chart_string_literal(values: list[str]) -> str:
    points = "".join(
        f'<c:pt idx="{index}"><c:v>{escape(value)}</c:v></c:pt>' for index, value in enumerate(values)
    )
    return f'<c:strLit><c:ptCount val="{len(values)}"/>{points}</c:strLit>'


def _chart_number_literal(values: list[object]) -> str:
    points = "".join(
        f'<c:pt idx="{index}"><c:v>{_chart_number_value(value)}</c:v></c:pt>'
        for index, value in enumerate(values)
    )
    return f'<c:numLit><c:formatCode>General</c:formatCode><c:ptCount val="{len(values)}"/>{points}</c:numLit>'


def _chart_number_value(value: object) -> str:
    try:
        return str(float(value))
    except (TypeError, ValueError):
        return "0"


def _slide_extra_shapes(elements: list[dict], chart_refs: list[dict]) -> str:
    chart_refs_by_element_id = {id(ref["element"]): ref for ref in chart_refs}
    shapes = []
    shape_id = 4
    for element in elements:
        if element.get("type") == "table":
            frame = _table_frame(shape_id, element)
            if frame:
                shapes.append(frame)
                shape_id += 1
        elif element.get("type") == "chart":
            ref = chart_refs_by_element_id.get(id(element))
            if ref:
                shapes.append(_chart_frame(shape_id, ref["rel_id"]))
                shape_id += 1
    return "\n".join(shapes)


def _slide_rels(index: int, chart_refs: Optional[list[dict]] = None) -> str:
    chart_relationships = "".join(
        f'<Relationship Id="{ref["rel_id"]}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart{ref["chart_index"]}.xml"/>'
        for ref in (chart_refs or [])
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide{index}.xml"/>
  {chart_relationships}
</Relationships>"""


def _notes_slide_xml(slide: dict, index: int) -> str:
    title = slide.get("title") or f"Slide {index}"
    notes = "\n".join(_speaker_note_line(note) for note in slide.get("speaker_notes", []))
    if not notes:
        notes = title
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
    <p:sp>
      <p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder"/><p:cNvSpPr/><p:nvPr><p:ph type="sldImg" idx="1"/></p:nvPr></p:nvSpPr>
      <p:spPr><a:xfrm><a:off x="685800" y="457200"/><a:ext cx="5486400" cy="3086100"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>
      <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
    </p:sp>
    {_text_box(3, "Speaker Notes", 685800, 3886200, 5486400, 3657600, notes, 1200)}
  </p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:notes>"""


def _speaker_note_line(note: dict) -> str:
    claim_id = note.get("claim_id") or ""
    quote = note.get("quote") or ""
    source_uri = note.get("source_uri") or ""
    return f"{claim_id}: {quote} ({source_uri})"


def _notes_slide_rels(index: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="../slides/slide{index}.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster" Target="../notesMasters/notesMaster1.xml"/>
</Relationships>"""


def _notes_master_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<p:notesMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
  </p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:notesStyle/>
</p:notesMaster>"""


def _notes_master_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""


def _slide_master_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
  <p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>
</p:sldMaster>"""


def _slide_master_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""


def _slide_layout_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank">
  <p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""


def _slide_layout_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""


def _theme_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="LoamTrace">
  <a:themeElements><a:clrScheme name="LoamTrace">
    <a:dk1><a:srgbClr val="1F2933"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
    <a:dk2><a:srgbClr val="24343D"/></a:dk2><a:lt2><a:srgbClr val="F6F7F8"/></a:lt2>
    <a:accent1><a:srgbClr val="176C7A"/></a:accent1><a:accent2><a:srgbClr val="147D52"/></a:accent2>
    <a:accent3><a:srgbClr val="F59E0B"/></a:accent3><a:accent4><a:srgbClr val="697586"/></a:accent4>
    <a:accent5><a:srgbClr val="B42318"/></a:accent5><a:accent6><a:srgbClr val="4B5563"/></a:accent6>
    <a:hlink><a:srgbClr val="176C7A"/></a:hlink><a:folHlink><a:srgbClr val="697586"/></a:folHlink>
  </a:clrScheme><a:fontScheme name="LoamTrace"><a:majorFont><a:latin typeface="Arial"/></a:majorFont><a:minorFont><a:latin typeface="Arial"/></a:minorFont></a:fontScheme><a:fmtScheme name="LoamTrace"/></a:themeElements>
</a:theme>"""


def _core_props(title: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{escape(title)}</dc:title></cp:coreProperties>"""


def _app_props(slide_count: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>LoamTrace</Application><Slides>{slide_count}</Slides>
</Properties>"""
