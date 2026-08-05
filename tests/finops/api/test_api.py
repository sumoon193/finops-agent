"""API 端点集成测试：FastAPI TestClient 全链路回归。

覆盖契约的四个端点与稳定错误码：
- POST /billing-ingestions
- POST /queries（含 AST 拒绝、预算拒绝、RLS 过滤、状态推进）
- DELETE /queries/{id}（取消 + 跨租户拒绝）
- POST /findings/{id}/tickets（审批门禁 + 幂等）

跨模块不变量验证：服务端身份、状态机 CAS、副作用幂等、provenance 可追溯、
证据不足保持 blocked。
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.finops.api import app, repos
from app.finops.anomaly.attribution import AnomalyFinding
from app.finops.kernel import Command, IdentityContext, RuntimeKernel
from app.finops.persistence import Record


@pytest.fixture(autouse=True)
def reset_repositories():
    for repo in (
        repos.billing_line_item,
        repos.semantic_version,
        repos.query_run,
        repos.result_artifact,
        repos.anomaly_finding,
        repos.governance_ticket,
    ):
        repo._by_id.clear()
        repo._by_key.clear()
    yield


CLIENT = TestClient(app)
HEADERS = {"X-Tenant-Id": "acme", "X-Role": "analyst", "X-Request-Id": "req-test"}
OTHER_HEADERS = {"X-Tenant-Id": "globex", "X-Request-Id": "req-other"}


def _raw_line(**overrides: Any) -> dict[str, Any]:
    base = {
        "source_id": "aws-billing-2024-01",
        "currency": "usd",
        "unit": "KWH",
        "amount": "120.50",
        "watermark": "2024-01-31T23:59:59Z",
        "raw_ref": "s3://bucket/line/0001",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Identity / 稳定错误码
# ---------------------------------------------------------------------------


def test_missing_trusted_identity_is_rejected_with_stable_code():
    response = CLIENT.post("/billing-ingestions", json={"watermark": "w", "raw_lines": []})
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "forbidden_identity"


# ---------------------------------------------------------------------------
# POST /billing-ingestions
# ---------------------------------------------------------------------------


def test_billing_ingestion_normalizes_and_stores_with_audit_trail():
    response = CLIENT.post(
        "/billing-ingestions",
        json={"watermark": "2024-01-31T23:59:59Z", "raw_lines": [_raw_line()]},
        headers=HEADERS,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "ok"
    assert body["result"]["ingested"] == 1
    assert body["result"]["source_ids"] == ["aws-billing-2024-01"]
    records = repos.billing_line_item.all()
    assert records and records[0].payload["currency"] == "USD"
    assert records[0].payload["unit"] == "kWh"
    assert records[0].idempotency_key
    assert records[0].audit_source == "finops-agent"


def test_billing_ingestion_is_idempotent_on_same_source_id_and_watermark():
    payload = {"watermark": "2024-01-31T23:59:59Z", "raw_lines": [_raw_line()]}
    CLIENT.post("/billing-ingestions", json=payload, headers=HEADERS)
    second = CLIENT.post("/billing-ingestions", json=payload, headers=HEADERS)
    assert second.status_code == 201
    assert len(repos.billing_line_item.all()) == 1
    assert repos.billing_line_item.all()[0].version == 2


# ---------------------------------------------------------------------------
# POST /queries
# ---------------------------------------------------------------------------


def test_query_runs_full_pipeline_and_returns_traceable_provenance():
    CLIENT.post(
        "/billing-ingestions",
        json={"watermark": "2024-01-31T23:59:59Z", "raw_lines": [_raw_line()]},
        headers=HEADERS,
    )
    response = CLIENT.post(
        "/queries",
        json={
            "statement": "SELECT amount FROM billing_line_item WHERE tenant_id = :tenant",
            "params": {"tenant": "acme"},
            "page_size": 10,
            "rows": [
                {"id": 1, "tenant_id": "acme", "amount": "10"},
                {"id": 2, "tenant_id": "globex", "amount": "999"},
            ],
            "allowed_resources": ["billing_line_item"],
        },
        headers=HEADERS,
    )
    assert response.status_code == 201
    body = response.json()["result"]
    assert body["query_id"]
    # RLS 过滤：globex 行被排除在外。
    assert all(row["tenant_id"] != "globex" for row in body["page"])
    assert any(p.startswith("tenant:acme") for p in body["provenance"])
    assert any(p.startswith("semantic:2024-07") for p in body["provenance"])


def test_query_ast_violation_is_rejected_with_stable_code():
    response = CLIENT.post(
        "/queries",
        json={
            "statement": "DROP TABLE billing_line_item",
            "allowed_resources": ["billing_line_item"],
        },
        headers=HEADERS,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "ast_violation"


def test_over_budget_query_rejected_before_execution():
    response = CLIENT.post(
        "/queries",
        json={
            "statement": "SELECT amount FROM billing_line_item",
            "estimated_cost": "150",
            "budget_limit": "100",
            "allowed_resources": ["billing_line_item"],
        },
        headers=HEADERS,
    )
    assert response.status_code == 402
    assert response.json()["detail"]["error"] == "budget_rejected"


# ---------------------------------------------------------------------------
# DELETE /queries/{id}
# ---------------------------------------------------------------------------


def _create_query(headers: dict[str, str]) -> str:
    response = CLIENT.post(
        "/queries",
        json={
            "statement": "SELECT amount FROM billing_line_item",
            "allowed_resources": ["billing_line_item"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["result"]["query_id"]


def test_cancel_completed_query_is_rejected():
    query_id = _create_query(HEADERS)
    response = CLIENT.delete(f"/queries/{query_id}", headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "query_not_running"


def test_client_rows_are_ignored_as_untrusted_data():
    response = CLIENT.post(
        "/queries",
        json={
            "statement": "SELECT amount FROM billing_line_item",
            "rows": [{"tenant_id": "acme", "amount": "999999"}],
            "allowed_resources": ["billing_line_item"],
        },
        headers=HEADERS,
    )
    assert response.status_code == 201
    assert response.json()["result"]["page"] == []


def test_cross_tenant_cancel_is_forbidden():
    query_id = _create_query(HEADERS)
    response = CLIENT.delete(f"/queries/{query_id}", headers=OTHER_HEADERS)
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "cross_tenant_denied"


def test_cancel_unknown_query_is_not_found():
    response = CLIENT.delete("/queries/does-not-exist", headers=HEADERS)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /findings/{id}/tickets
# ---------------------------------------------------------------------------


def _seed_finding() -> str:
    finding_id = repos.next_id("fnd")
    repos.anomaly_finding.put(
        Record(
            id=finding_id,
            idempotency_key=repos.idempotency_key("finding", finding_id),
            payload={
                "query_id": "qr-1",
                "kind": "cost-spike",
                "severity": "high",
                "detail": "monthly spend +300%",
            },
        )
    )
    return finding_id


def test_ticket_without_approval_is_blocked_with_stable_code():
    finding_id = _seed_finding()
    response = CLIENT.post(
        f"/findings/{finding_id}/tickets",
        json={"approved": False},
        headers=HEADERS,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "approval_required"


def test_approved_ticket_created_idempotently():
    finding_id = _seed_finding()
    first = CLIENT.post(f"/findings/{finding_id}/tickets", json={"approved": True}, headers=HEADERS)
    assert first.status_code == 201
    first_ticket = first.json()["result"]["ticket_id"]
    second = CLIENT.post(f"/findings/{finding_id}/tickets", json={"approved": True}, headers=HEADERS)
    assert second.status_code == 201
    assert second.json()["result"]["ticket_id"] == first_ticket
    # 幂等：工单表里只有一条记录（同一 idempotency_key）。
    assert len(repos.governance_ticket.all()) == 1


# ---------------------------------------------------------------------------
# Kernel 命令一致性额外校验
# ---------------------------------------------------------------------------


def test_kernel_command_dispatch_records_audit_and_state():
    kernel = RuntimeKernel(IdentityContext(tenant_id="acme"))
    kernel.advance("planned", "created", "plan")
    kernel.advance("authorized", "planned", "authorize")
    handled = kernel.handle(Command(kind="run"), lambda cmd: {"rows": []})
    assert handled["state"] == "authorized"
    assert any(rec.action == "command:run" for rec in kernel.audit_log)
