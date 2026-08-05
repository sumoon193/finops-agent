"""FO-03 身份、RLS 与行列策略：服务端身份和数据库RLS阻止跨租户读取。"""

from pathlib import Path

import pytest

from app.finops.security.identity import IdentityContext
from app.finops.security.rls import FO03Input, FO03Result, AuthorizedQueryPlan

ROOT = Path(__file__).resolve().parents[3]

ROWS = [
    {"row_id": 1, "tenant_id": "acme", "amount": "10"},
    {"row_id": 2, "tenant_id": "acme", "amount": "20"},
    {"row_id": 3, "tenant_id": "globex", "amount": "999"},
]


def test_server_identity_cannot_be_overridden_by_client_or_model():
    ctx = IdentityContext(tenant_id="acme", role="analyst")
    assert ctx.tenant_id == "acme"
    with pytest.raises(AttributeError):
        ctx.tenant_id = "globex"


def test_cross_tenant_read_is_blocked():
    plan = AuthorizedQueryPlan(tenant_id="acme")
    result = plan.execute(FO03Input(rows=ROWS))
    assert isinstance(result, FO03Result)
    assert [row["row_id"] for row in result.allowed_rows] == [1, 2]
    assert [row["row_id"] for row in result.blocked_rows] == [3]
    assert any("cross-tenant-blocked" in event for event in result.state_events)
    assert result.audit["blocked_count"] == 1
    assert result.audit["tenant_id"] == "acme"


def test_same_tenant_read_is_allowed():
    plan = AuthorizedQueryPlan(tenant_id="globex")
    result = plan.execute(FO03Input(rows=ROWS))
    assert [row["row_id"] for row in result.allowed_rows] == [3]
    assert [row["row_id"] for row in result.blocked_rows] == [1, 2]


def test_migration_declares_rls_for_billing_line_item():
    migrations = sorted((ROOT / "migrations" / "finops").glob("*.sql"))
    assert migrations, "no finops migration"
    text = "\n".join(m.read_text(encoding="utf-8") for m in migrations)
    assert "billing_line_item" in text
    assert "tenant_id" in text
