from __future__ import annotations

import json
from typing import Optional


def normalize_bbox(raw: dict[str, float], width: float, height: float, page_number: int) -> dict[str, float]:
    return {
        "page": page_number,
        "x0": round(raw["x0"] / width, 6),
        "y0": round(raw["top"] / height, 6),
        "x1": round(raw["x1"] / width, 6),
        "y1": round(raw["bottom"] / height, 6),
    }


def bbox_union(boxes: list[dict]) -> Optional[dict]:
    if not boxes:
        return None
    page = boxes[0].get("page")
    same_page = [box for box in boxes if box.get("page") == page]
    if not same_page:
        return None
    return {
        "page": page,
        "x0": min(box["x0"] for box in same_page),
        "y0": min(box["y0"] for box in same_page),
        "x1": max(box["x1"] for box in same_page),
        "y1": max(box["y1"] for box in same_page),
    }


def dumps_bbox(box: Optional[dict]) -> Optional[str]:
    return json.dumps(box) if box else None
