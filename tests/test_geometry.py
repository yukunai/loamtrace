from loamtrace.services.geometry import bbox_union, normalize_bbox


def test_normalize_bbox_uses_unit_coordinates() -> None:
    box = normalize_bbox(
        {"x0": 10, "top": 20, "x1": 50, "bottom": 80},
        width=100,
        height=200,
        page_number=3,
    )
    assert box == {"page": 3, "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.4}


def test_bbox_union_keeps_same_page_union() -> None:
    assert bbox_union(
        [
            {"page": 1, "x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4},
            {"page": 1, "x0": 0.2, "y0": 0.1, "x1": 0.6, "y1": 0.5},
        ]
    ) == {"page": 1, "x0": 0.1, "y0": 0.1, "x1": 0.6, "y1": 0.5}


def test_bbox_union_empty_returns_none() -> None:
    assert bbox_union([]) is None


def test_bbox_union_filters_different_pages() -> None:
    # Implementation currently takes the first page and filters others
    assert bbox_union(
        [
            {"page": 1, "x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.2},
            {"page": 2, "x0": 0.5, "y0": 0.5, "x1": 0.6, "y1": 0.6},
        ]
    ) == {"page": 1, "x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.2}
