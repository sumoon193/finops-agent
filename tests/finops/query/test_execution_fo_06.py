"""FO-06 只读查询、分页与状态：参数化计划、稳定分页和 CAS 状态。"""

import pytest

from app.finops.query.execution.planner import (
    AuthorizedQueryPlan,
    FO06Input,
    FO06Result,
    QueryPlan,
    StateMachine,
)

ROWS = [
    {"id": index, "watermark": "2024-01-01", "value": index}
    for index in range(1, 7)
]


def test_plan_is_parameterized_without_literal_values():
    plan = QueryPlan(
        statement="SELECT * FROM billing WHERE tenant = :tenant AND month = :month",
        params={"tenant": "acme", "month": "2024-01"},
    )
    assert ":tenant" in plan.statement and ":month" in plan.statement
    assert plan.params == {"tenant": "acme", "month": "2024-01"}
    assert "acme" not in plan.statement
    assert "2024-01" not in plan.statement


def test_pagination_is_stable_across_mutations():
    plan = AuthorizedQueryPlan(plan=QueryPlan(statement="SELECT * FROM billing", params={}))
    first = plan.execute(FO06Input(rows=list(ROWS), page_size=3, cursor=None))
    assert isinstance(first, FO06Result)
    assert [row["id"] for row in first.page] == [1, 2, 3]
    assert first.next_cursor is not None

    # New rows appended after the first page was fetched must not shift later pages.
    mutated = list(ROWS) + [{"id": 7, "watermark": "2024-01-01", "value": 7}]
    second = plan.execute(FO06Input(rows=mutated, page_size=3, cursor=first.next_cursor))
    assert [row["id"] for row in second.page] == [4, 5, 6]


def test_cas_state_transition_succeeds_and_rejects_stale_expected():
    machine = StateMachine("running")
    assert machine.transition("completed", expected="running") == "completed"
    with pytest.raises(ValueError):
        machine.transition("cancelled", expected="running")


def test_illegal_state_transition_is_rejected_stably():
    machine = StateMachine("completed")
    with pytest.raises(ValueError):
        machine.transition("running", expected="completed")
