from __future__ import annotations

from typing import Optional


_REVIEW_MUTATION_CATEGORIES = {"claim_review", "citation_review"}
_REVIEW_MUTATION_ORDER = [
    ("POST", "/api/claims/{claim_id}/judge-support"),
    ("POST", "/api/citations/{citation_id}/review"),
    ("POST", "/api/claims/{claim_id}/correct"),
    ("POST", "/api/citations/{citation_id}/replace"),
]


_ROUTES = [
    ("POST", "/api/projects", "admin", "high", "enforced", "project_creation", "enforced in server mode by explicit actor owner role"),
    ("POST", "/api/documents/import", "write", "high", "enforced", "source_ingestion", "enforced in server mode after owner bootstrap"),
    ("GET", "/api/projects/{project_id}/documents/{document_id}/delete-preview", "delete", "medium", "enforced", "source_deletion", "enforced in server mode after owner bootstrap"),
    ("DELETE", "/api/projects/{project_id}/documents/{document_id}", "delete", "high", "enforced", "source_deletion", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/documents/{document_id}/parse", "write", "medium", "enforced", "source_processing", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/documents/{document_id}/manual-text", "write", "medium", "enforced", "source_processing", "enforced in server mode after owner bootstrap"),
    ("PUT", "/api/projects/{project_id}/ui-preferences", "write", "low", "enforced", "project_preferences", "enforced in server mode after owner bootstrap"),
    ("PUT", "/api/projects/{project_id}/retrieval-preferences", "write", "medium", "enforced", "project_preferences", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/search", "read", "low", "enforced", "run_artifact", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/verify/run", "write", "high", "enforced", "evidence_gate", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/generate/memo", "write", "high", "enforced", "generation", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/memo/render", "write", "high", "enforced", "generation", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/claims/{claim_id}/correct", "review", "high", "enforced", "claim_review", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/claims/{claim_id}/judge-support", "review", "medium", "enforced", "claim_review", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/review/tasks", "review", "low", "enforced", "review_workflow", "enforced in server mode after owner bootstrap"),
    ("PATCH", "/api/review/tasks/{task_id}", "review", "low", "enforced", "review_workflow", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/review/tasks/{task_id}/comments", "review", "low", "enforced", "review_workflow", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/analysis/red-flags", "write", "medium", "enforced", "analysis", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/analysis/financial-consistency", "write", "medium", "enforced", "analysis", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/analysis/contract-clauses", "write", "medium", "enforced", "analysis", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/charts/generate-data", "write", "high", "enforced", "chart_artifact", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/slides/generate", "export", "high", "enforced", "export", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/slides/from-template", "export", "high", "enforced", "export", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/slides/chart-deck", "export", "high", "enforced", "export", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/slides/table-deck", "export", "high", "enforced", "export", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/export/pptx", "export", "high", "enforced", "export", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/export/research-package", "export", "high", "enforced", "export", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/export/project-snapshot", "export", "high", "enforced", "snapshot", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/import/project-snapshot", "admin", "high", "enforced", "snapshot", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/sync/push-snapshot", "export", "high", "enforced", "sync", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/sync/pull-snapshot", "admin", "high", "enforced", "sync", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/sync/delete-snapshot", "delete", "high", "enforced", "sync", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/sync/provider/push-snapshot", "export", "high", "enforced", "sync", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/sync/provider/pull-snapshot", "admin", "high", "enforced", "sync", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/sync/provider/delete-snapshot", "delete", "high", "enforced", "sync", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/citations/{citation_id}/review", "review", "high", "enforced", "citation_review", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/citations/{citation_id}/replace", "review", "high", "enforced", "citation_review", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/assets/from-document", "write", "medium", "enforced", "asset_library", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/assets/import", "write", "medium", "enforced", "asset_library", "enforced in server mode after owner bootstrap"),
    ("PUT", "/api/assets/{asset_id}/tags", "write", "medium", "enforced", "asset_library", "enforced in server mode after owner bootstrap"),
    ("DELETE", "/api/assets/{asset_id}", "delete", "high", "enforced", "asset_library", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/team/bootstrap-admin", "admin", "high", "bootstrap_only", "team_admin", "bootstrap route; keep separate from project ACL enforcement"),
    ("POST", "/api/team/users", "admin", "high", "enforced", "team_admin", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/team/teams", "admin", "high", "enforced", "team_admin", "enforced in server mode after owner bootstrap"),
    ("PUT", "/api/team/members", "admin", "high", "enforced", "team_admin", "enforced in server mode after owner bootstrap"),
    ("DELETE", "/api/team/members/{team_id}/{user_id}", "admin", "high", "enforced", "team_admin", "enforced in server mode after owner bootstrap"),
    ("PUT", "/api/team/acl", "admin", "high", "enforced", "team_admin", "enforced in server mode after owner bootstrap"),
    ("DELETE", "/api/team/acl", "admin", "high", "enforced", "team_admin", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/jobs", "write", "medium", "enforced", "background_jobs", "enforced in server mode after owner bootstrap"),
    ("PATCH", "/api/jobs/{job_id}", "admin", "medium", "enforced", "background_jobs", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/jobs/{job_id}/cancel", "write", "medium", "enforced", "background_jobs", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/jobs/run-next", "admin", "medium", "enforced", "background_jobs", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/jobs/run-worker", "admin", "medium", "enforced", "background_jobs", "enforced in server mode after owner bootstrap"),
    ("POST", "/api/jobs/recover-stale-running", "admin", "medium", "enforced", "background_jobs", "enforced in server mode after owner bootstrap"),
    ("PUT", "/api/settings/api", None, "high", "local_settings", "settings", "local app secret settings; do not project-guard directly"),
    ("POST", "/api/settings/api/test", None, "low", "local_settings", "settings", "non-mutating provider test; keep local settings scoped"),
    ("PUT", "/api/sync/settings", None, "high", "local_settings", "settings", "local sync secret settings; do not project-guard directly"),
    ("POST", "/api/sync/settings/test", None, "low", "local_settings", "settings", "non-mutating provider test; keep local settings scoped"),
    ("POST", "/api/sync/provider/test-live", None, "low", "local_settings", "settings", "non-mutating provider test; keep local settings scoped"),
]


def list_mutation_route_risks(category: Optional[str] = None, guard_status: Optional[str] = None) -> list[dict]:
    routes = [_route_dict(*route) for route in _ROUTES]
    if category:
        routes = [route for route in routes if route["category"] == category]
    if guard_status:
        routes = [route for route in routes if route["guard_status"] == guard_status]
    return routes


def mutation_route_risk_summary() -> dict:
    routes = list_mutation_route_risks()
    return {
        "total_routes": len(routes),
        "by_risk": _count_by(routes, "risk"),
        "by_guard_status": _count_by(routes, "guard_status"),
        "next_recommended_category": "none",
        "next_recommended_action": "all classified project and team mutation routes are enforced; bootstrap and local settings routes remain intentionally separate",
    }


def claim_citation_review_plan() -> dict:
    routes = [
        route
        for route in list_mutation_route_risks()
        if route["category"] in _REVIEW_MUTATION_CATEGORIES
    ]
    ordered_routes = sorted(routes, key=_review_mutation_sort_key)
    next_route = next((route for route in ordered_routes if route["guard_status"] == "unguarded"), None)
    return {
        "summary": {
            "total_routes": len(ordered_routes),
            "high_risk_routes": sum(1 for route in ordered_routes if route["risk"] == "high"),
            "medium_risk_routes": sum(1 for route in ordered_routes if route["risk"] == "medium"),
            "unguarded_routes": sum(1 for route in ordered_routes if route["guard_status"] == "unguarded"),
            "enforced_routes": sum(1 for route in ordered_routes if route["guard_status"] == "enforced"),
            "next_recommended_route": (
                f"{next_route['method']} {next_route['path']}" if next_route else None
            ),
            "next_recommended_action": (
                next_route["next_action"]
                if next_route
                else "claim/citation review mutations are fully enforced"
            ),
        },
        "recommended_order": [
            f"{method} {path}" for method, path in _REVIEW_MUTATION_ORDER
        ],
        "routes": ordered_routes,
    }


def _route_dict(method: str, path: str, permission: Optional[str], risk: str, guard_status: str, category: str, next_action: str) -> dict:
    return {
        "method": method,
        "path": path,
        "permission": permission,
        "risk": risk,
        "guard_status": guard_status,
        "category": category,
        "next_action": next_action,
    }


def _count_by(routes: list[dict], key: str) -> dict:
    counts: dict[str, int] = {}
    for route in routes:
        value = route[key]
        counts[value] = counts.get(value, 0) + 1
    return counts


def _review_mutation_sort_key(route: dict) -> int:
    try:
        return _REVIEW_MUTATION_ORDER.index((route["method"], route["path"]))
    except ValueError:
        return len(_REVIEW_MUTATION_ORDER)
