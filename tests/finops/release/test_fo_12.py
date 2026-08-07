"""FO-12 回滚、演练与数据层替换：语义/FOCUS/数据库 adapter 可回滚替换。"""

from pathlib import Path

from scripts.finops.rollback import (
    AuthorizedQueryPlan,
    FO12Input,
    FO12Result,
)

ROOT = Path(__file__).resolve().parents[3]


def test_adapters_register_and_switch_per_kind():
    plan = AuthorizedQueryPlan()
    plan.registry.register("semantic", "sem-v1")
    plan.registry.register("focus", "focus-v1")
    plan.registry.register("database", "db-v1")
    assert plan.registry.current("semantic") == "sem-v1"
    result = plan.execute(FO12Input(action="switch", kind="focus", name="focus-v2"))
    assert isinstance(result, FO12Result)
    assert result.current == "focus-v2"
    result = plan.execute(FO12Input(action="switch", kind="database", name="db-v2"))
    assert result.current == "db-v2"


def test_rollback_restores_previous_adapter():
    plan = AuthorizedQueryPlan()
    plan.registry.register("database", "db-v1")
    plan.execute(FO12Input(action="switch", kind="database", name="db-v2"))
    result = plan.execute(FO12Input(action="rollback", kind="database"))
    assert result.rollback_performed is True
    assert result.current == "db-v1"


def test_rollback_with_no_history_is_stable():
    plan = AuthorizedQueryPlan()
    plan.registry.register("focus", "focus-v1")
    result = plan.execute(FO12Input(action="rollback", kind="focus"))
    assert result.rollback_performed is False
    assert result.current == "focus-v1"


def test_release_doc_declares_rollback_plan_and_unverified():
    doc = (ROOT / "docs" / "finops" / "release" / "rollback-plan.md").read_text(
        encoding="utf-8"
    )
    for token in ("语义", "FOCUS", "数据库", "回滚", "unverified", "演练"):
        assert token in doc, token
