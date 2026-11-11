from fastapi.testclient import TestClient

from loamtrace.main import app
from loamtrace.services.mutation_risk import (
    claim_citation_review_plan,
    list_mutation_route_risks,
    mutation_route_risk_summary,
)


def test_mutation_route_risk_registry_marks_review_task_routes_enforced():
    routes = list_mutation_route_risks(category="review_workflow")

    assert {route["path"] for route in routes} == {
        "/api/review/tasks",
        "/api/review/tasks/{task_id}",
        "/api/review/tasks/{task_id}/comments",
    }
    assert all(route["guard_status"] == "enforced" for route in routes)
    assert all(route["permission"] == "review" for route in routes)


def test_mutation_route_risk_summary_counts_remaining_unguarded_routes():
    summary = mutation_route_risk_summary()

    assert summary["total_routes"] >= 40
    assert summary["by_guard_status"]["enforced"] == 53
    assert summary["by_guard_status"].get("unguarded", 0) == 0
    assert summary["by_guard_status"].get("admin_only", 0) == 0
    assert summary["by_risk"]["high"] > summary["by_risk"]["low"]
    assert summary["next_recommended_category"] == "none"


def test_mutation_route_risk_api_filters_by_guard_status():
    response = TestClient(app).get("/api/team/acl/mutation-risk", params={"guard_status": "enforced"})

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["by_guard_status"]["enforced"] == 53
    assert len(body["routes"]) == 53
    assert {route["category"] for route in body["routes"]} == {
        "analysis",
        "asset_library",
        "background_jobs",
        "chart_artifact",
        "citation_review",
        "claim_review",
        "evidence_gate",
        "export",
        "generation",
        "project_creation",
        "review_workflow",
        "run_artifact",
        "snapshot",
        "source_deletion",
        "source_ingestion",
        "source_processing",
        "sync",
        "team_admin",
        "project_preferences",
    }


def test_claim_citation_review_plan_orders_high_risk_review_mutations():
    plan = claim_citation_review_plan()

    assert plan["summary"]["total_routes"] == 4
    assert plan["summary"]["high_risk_routes"] == 3
    assert plan["summary"]["medium_risk_routes"] == 1
    assert plan["summary"]["unguarded_routes"] == 0
    assert plan["summary"]["enforced_routes"] == 4
    assert plan["summary"]["next_recommended_route"] is None
    assert plan["recommended_order"] == [
        "POST /api/claims/{claim_id}/judge-support",
        "POST /api/citations/{citation_id}/review",
        "POST /api/claims/{claim_id}/correct",
        "POST /api/citations/{citation_id}/replace",
    ]
    assert [route["category"] for route in plan["routes"]] == [
        "claim_review",
        "citation_review",
        "claim_review",
        "citation_review",
    ]


def test_review_mutation_plan_api_returns_claim_citation_scope():
    response = TestClient(app).get("/api/team/acl/review-mutation-plan")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_routes"] == 4
    assert body["summary"]["next_recommended_route"] is None
    assert {route["permission"] for route in body["routes"]} == {"review"}
