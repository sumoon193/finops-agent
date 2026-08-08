from __future__ import annotations

from fastapi.testclient import TestClient

from app.finops import api
from app.finops.persistence import Record, Repositories


def _headers(tenant: str, request_id: str) -> dict[str, str]:
    return {
        "X-Tenant-Id": tenant,
        "X-Role": "finops-operator",
        "X-Request-Id": request_id,
    }


def _ingest(client: TestClient, tenant: str, source_id: str, amount: str) -> None:
    response = client.post(
        "/billing-ingestions",
        headers=_headers(tenant, f"ingest-{source_id}"),
        json={
            "watermark": "2026-08-07T00:00:00Z",
            "raw_lines": [
                {
                    "source_id": source_id,
                    "currency": "CNY",
                    "unit": "yuan",
                    "amount": amount,
                    "watermark": "2026-08-07T00:00:00Z",
                    "raw_ref": f"focus://{source_id}",
                }
            ],
        },
    )
    assert response.status_code == 201


def test_query_plan_uses_a_trusted_template_before_execution(monkeypatch) -> None:
    monkeypatch.setenv("FINOPS_IDENTITY_MODE", "offline")
    monkeypatch.setenv("FINOPS_AGENT_MODE", "offline")
    monkeypatch.setattr(api, "repos", Repositories())
    client = TestClient(api.app)
    _ingest(client, "tenant-a", "line-a", "12.50")

    planned = client.post(
        "/query-plans",
        headers=_headers("tenant-a", "plan-1"),
        json={"question": "按月查看成本趋势", "budget_limit": "100"},
    )

    assert planned.status_code == 201
    plan = planned.json()["result"]
    assert plan["statement"].startswith("SELECT ")
    assert plan["ast_allowed"] is True
    assert plan["status"] == "planned"

    executed = client.post(
        f"/query-plans/{plan['plan_id']}/execute",
        headers=_headers("tenant-a", "execute-1"),
        json={"page_size": 20},
    )
    assert executed.status_code == 201
    assert executed.json()["result"]["page"][0]["source_id"] == "line-a"


def test_dashboard_and_query_list_are_tenant_scoped(monkeypatch) -> None:
    monkeypatch.setenv("FINOPS_IDENTITY_MODE", "offline")
    monkeypatch.setattr(api, "repos", Repositories())
    client = TestClient(api.app)
    _ingest(client, "tenant-a", "line-a", "10.00")
    _ingest(client, "tenant-b", "line-b", "999.00")

    dashboard = client.get(
        "/dashboard", headers=_headers("tenant-a", "dashboard-1")
    )
    queries = client.get("/queries", headers=_headers("tenant-a", "queries-1"))
    ingestions = client.get(
        "/billing-ingestions", headers=_headers("tenant-a", "ingestions-1")
    )

    assert dashboard.status_code == 200
    assert dashboard.json()["result"] == {
        "billing_lines": 1,
        "total_amount": "10.00",
        "query_runs": 0,
        "open_findings": 0,
        "tickets": 0,
    }
    assert queries.status_code == 200
    assert queries.json()["result"]["items"] == []
    assert ingestions.status_code == 200
    assert ingestions.json()["result"]["total"] == 1
    assert ingestions.json()["result"]["items"][0]["source_id"] == "line-a"
    assert "line-b" not in ingestions.text


def test_operational_read_models_expose_only_current_tenant_records(monkeypatch) -> None:
    monkeypatch.setenv("FINOPS_IDENTITY_MODE", "offline")
    repositories = Repositories()
    monkeypatch.setattr(api, "repos", repositories)
    repositories.query_run.put(
        Record(
            id="query-a",
            idempotency_key="query-a",
            payload={"tenant_id": "tenant-a", "status": "unknown", "statement": "SELECT 1"},
        )
    )
    repositories.query_run.put(
        Record(
            id="query-b",
            idempotency_key="query-b",
            payload={"tenant_id": "tenant-b", "status": "completed"},
        )
    )
    repositories.anomaly_finding.put(
        Record(
            id="finding-a",
            idempotency_key="finding-a",
            payload={
                "tenant_id": "tenant-a",
                "query_id": "query-a",
                "kind": "cost-spike",
                "severity": "high",
                "detail": "compute increase",
                "status": "open",
            },
        )
    )
    repositories.governance_ticket.put(
        Record(
            id="ticket-a",
            idempotency_key="ticket-a",
            payload={"tenant_id": "tenant-a", "finding_id": "finding-a", "status": "unknown"},
        )
    )
    client = TestClient(api.app)

    query = client.get("/queries/query-a", headers=_headers("tenant-a", "query-detail"))
    findings = client.get("/findings", headers=_headers("tenant-a", "findings"))
    tickets = client.get("/tickets", headers=_headers("tenant-a", "tickets"))
    recovery = client.get(
        "/recovery-status", headers=_headers("tenant-a", "recovery")
    )

    assert query.status_code == 200
    assert query.json()["result"]["query_id"] == "query-a"
    assert findings.json()["result"]["items"][0]["finding_id"] == "finding-a"
    assert tickets.json()["result"]["items"][0]["ticket_id"] == "ticket-a"
    assert recovery.json()["result"] == {
        "unknown_queries": 1,
        "unknown_tickets": 1,
        "requires_reconciliation": True,
    }

    denied = client.get("/queries/query-b", headers=_headers("tenant-a", "query-b"))
    assert denied.status_code == 404


def test_ticket_creation_enforces_finding_tenant_and_persists_ticket_tenant(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FINOPS_IDENTITY_MODE", "offline")
    repositories = Repositories()
    monkeypatch.setattr(api, "repos", repositories)
    repositories.anomaly_finding.put(
        Record(
            id="finding-b",
            idempotency_key="finding-b",
            payload={
                "tenant_id": "tenant-b",
                "query_id": "query-b",
                "kind": "cost-spike",
                "severity": "high",
                "detail": "private tenant finding",
            },
        )
    )
    repositories.anomaly_finding.put(
        Record(
            id="finding-a",
            idempotency_key="finding-a",
            payload={
                "tenant_id": "tenant-a",
                "query_id": "query-a",
                "kind": "cost-spike",
                "severity": "high",
                "detail": "tenant-a finding",
            },
        )
    )
    client = TestClient(api.app)

    denied = client.post(
        "/findings/finding-b/tickets",
        headers=_headers("tenant-a", "ticket-denied"),
        json={"approved": True},
    )
    assert denied.status_code == 404

    created = client.post(
        "/findings/finding-a/tickets",
        headers=_headers("tenant-a", "ticket-created"),
        json={"approved": True},
    )
    assert created.status_code == 201

    tickets = client.get("/tickets", headers=_headers("tenant-a", "ticket-list"))
    assert tickets.status_code == 200
    assert tickets.json()["result"]["total"] == 1
    assert tickets.json()["result"]["items"][0]["tenant_id"] == "tenant-a"


def test_oidc_identity_ignores_spoofed_tenant_headers(monkeypatch) -> None:
    monkeypatch.setenv("FINOPS_IDENTITY_MODE", "oidc")
    repositories = Repositories()
    monkeypatch.setattr(api, "repos", repositories)
    repositories.billing_line_item.put(
        Record(
            id="line-a",
            idempotency_key="line-a",
            payload={"tenant_id": "tenant-a", "amount": "10.00"},
        )
    )
    repositories.billing_line_item.put(
        Record(
            id="line-b",
            idempotency_key="line-b",
            payload={"tenant_id": "tenant-b", "amount": "999.00"},
        )
    )
    monkeypatch.setattr(
        api,
        "_verify_oidc_token",
        lambda token: {
            "sub": "user-a",
            "tenant_id": "tenant-a",
            "realm_access": {"roles": ["finops-analyst"]},
        },
    )
    client = TestClient(api.app)

    missing = client.get("/dashboard")
    assert missing.status_code == 401

    response = client.get(
        "/dashboard",
        headers={
            "Authorization": "Bearer signed-token",
            "X-Tenant-Id": "tenant-b",
            "X-Role": "finops-admin",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["billing_lines"] == 1
    assert response.json()["result"]["total_amount"] == "10.00"
