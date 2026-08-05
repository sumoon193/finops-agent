"""共享内核与持久层不变量测试。

验证跨模块不变量在集成层落地：
- #1 服务端身份不可被模型/客户端覆盖（frozen IdentityContext）。
- #2 副作用经 SideEffectLedger 幂等去重。
- #3 状态机 CAS + 非法转换稳定拒绝。
- 审计来源可追溯（AuditRecord.correlation_id / provenance）。
- 持久层幂等键去重 + 版本递增 + 审计来源字段齐全。
- Schema 迁移声明全部六张表与 RLS。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.finops.kernel import (
    Command,
    IdentityContext,
    IllegalStateTransition,
    RuntimeKernel,
    StateMachine,
)
from app.finops.persistence import InMemoryRepository, Record, Repositories

ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# 不变量 #1：服务端可信身份不可覆盖
# ---------------------------------------------------------------------------


def test_server_identity_is_immutable():
    ctx = IdentityContext(tenant_id="acme", role="analyst", request_id="r1")
    with pytest.raises(AttributeError):
        ctx.tenant_id = "globex"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        ctx.role = "admin"  # type: ignore[misc]


def test_with_role_returns_new_immutable_identity():
    ctx = IdentityContext(tenant_id="acme", role="analyst", request_id="r1")
    promoted = ctx.with_role("approver")
    assert ctx.role == "analyst"  # 原身份不变
    assert promoted.role == "approver"
    assert promoted.tenant_id == "acme"
    assert promoted.request_id == "r1"  # correlation_id 保留


# ---------------------------------------------------------------------------
# 不变量 #3：状态机 CAS + 非法转换稳定拒绝
# ---------------------------------------------------------------------------


def test_state_machine_all_transitions():
    machine = StateMachine("created")
    assert machine.state == "created"
    machine.transition("planned", expected="created")
    machine.transition("authorized", expected="planned")
    machine.transition("running", expected="authorized")
    machine.transition("completed", expected="running")
    assert machine.state == "completed"


def test_state_machine_rejects_illegal_target():
    machine = StateMachine("created")
    with pytest.raises(IllegalStateTransition):
        machine.transition("running", expected="created")  # skipping planned/authorized
    with pytest.raises(IllegalStateTransition):
        machine.transition("completed", expected="created")


def test_state_machine_cas_rejects_stale_expected():
    machine = StateMachine("created")
    machine.transition("planned", expected="created")
    with pytest.raises(IllegalStateTransition):
        machine.transition("authorized", expected="created")  # stale expected


def test_state_machine_rejects_terminal_advance():
    machine = StateMachine("completed")
    assert not machine.can("running")
    with pytest.raises(IllegalStateTransition):
        machine.transition("running", expected="completed")


# ---------------------------------------------------------------------------
# 审计可追溯
# ---------------------------------------------------------------------------


def test_kernel_audit_records_correlation_and_provenance():
    ctx = IdentityContext(tenant_id="acme", request_id="corr-1234")
    kernel = RuntimeKernel(ctx)
    kernel.audit(action="probe", provenance=["source:billing", "watermark:w1"], details={"k": "v"})
    assert kernel.audit_log
    record = kernel.audit_log[-1]
    assert record.correlation_id == "corr-1234"
    assert record.provenance == ["source:billing", "watermark:w1"]
    assert record.details == {"k": "v"}
    assert record.actor.tenant_id == "acme"


def test_kernel_advance_emits_state_provenance():
    ctx = IdentityContext(tenant_id="acme")
    kernel = RuntimeKernel(ctx)
    kernel.advance("planned", "created", "plan")
    assert any("state:created->planned" in record.provenance for record in kernel.audit_log)


def test_kernel_handle_dispatches_command_with_audit():
    kernel = RuntimeKernel(IdentityContext(tenant_id="acme"))
    kernel.advance("planned", "created", "plan")
    result = kernel.handle(Command(kind="run", payload={"x": 1}), lambda cmd: cmd.payload)
    assert result["result"] == {"x": 1}
    assert any(record.action == "command:run" for record in kernel.audit_log)


# ---------------------------------------------------------------------------
# 不变量 #2：副作用幂等（经 SideEffectLedger）
# ---------------------------------------------------------------------------


def test_side_effect_ledger_idempotency_via_kernel_indirectly():
    from app.finops.recovery.ledger import SideEffectLedger

    ledger = SideEffectLedger()
    assert ledger.record("e1") is True
    assert ledger.record("e1") is False  # 幂等去重
    assert ledger.attempts("e1") == 1


# ---------------------------------------------------------------------------
# 持久层：幂等键 + 版本递增 + 审计来源
# ---------------------------------------------------------------------------


def test_inmemory_repository_idempotent_put_increments_version():
    repo = InMemoryRepository("query_run")
    record = Record(id="q1", idempotency_key="key-1", payload={"v": 1})
    repo.put(record)
    repo.put(Record(id="q1", idempotency_key="key-1", payload={"v": 2}))  # same key -> update
    records = repo.all()
    assert len(records) == 1
    assert records[0].version == 2
    assert records[0].audit_source == "finops-agent"


def test_repository_find_by_idempotency_key():
    repo = InMemoryRepository("result_artifact")
    repo.put(Record(id="r1", idempotency_key="key-x", payload={"rows": []}))
    found = repo.find_by_idempotency_key("key-x")
    assert found and found.id == "r1"
    assert repo.find_by_idempotency_key("missing") is None


def test_repositories_idempotency_key_is_deterministic():
    a = Repositories.idempotency_key("billing", "src", "w1")
    b = Repositories.idempotency_key("billing", "src", "w1")
    c = Repositories.idempotency_key("billing", "src", "w2")
    assert a == b
    assert a != c
    assert len(a) == 24


def test_repositories_exposes_all_six_contract_tables():
    repos = Repositories()
    for table_name in (
        "billing_line_item",
        "semantic_version",
        "query_run",
        "result_artifact",
        "anomaly_finding",
        "governance_ticket",
    ):
        repo = getattr(repos, table_name)
        assert repo.table_name == table_name
        # 审计字段齐全（主键、幂等键、版本、时间戳、审计来源）。
        sample = Record(id="x", idempotency_key="k", payload={})
        repo.put(sample)
        record = repo.get("x")
        assert record
        assert record.id and record.idempotency_key
        assert record.version >= 1
        assert record.created_at and record.updated_at
        assert record.audit_source == "finops-agent"


# ---------------------------------------------------------------------------
# Schema 迁移：六张表 + RLS 字段声明
# ---------------------------------------------------------------------------


def test_migration_files_declare_all_six_tables_and_idempotency_fields():
    migrations = sorted((ROOT / "migrations" / "finops").glob("*.sql"))
    assert migrations, "no finops migration"
    text = "\n".join(m.read_text(encoding="utf-8") for m in migrations)
    for table in (
        "billing_line_item",
        "semantic_version",
        "query_run",
        "result_artifact",
        "anomaly_finding",
        "governance_ticket",
    ):
        assert table in text, f"table missing in schema: {table}"
    for field in ("idempotency_key", "version", "created_at", "updated_at", "audit_source"):
        assert field in text, f"audit field missing in schema: {field}"
    assert "ROW LEVEL SECURITY" in text and "tenant_id" in text