"""FO-07 预算、超时与取消：超预算执行前拒绝且超时可取消。"""

from decimal import Decimal

from app.finops.query.budget.controller import FO07Input, FO07Result, IdentityContext


def test_over_budget_query_is_rejected_before_execution():
    result = IdentityContext().execute(
        FO07Input(estimated_cost=Decimal(150), budget_limit=Decimal(100))
    )
    assert isinstance(result, FO07Result)
    assert result.state == "rejected"
    assert "budget-rejected" in result.state_events
    assert "running" not in result.state_events


def test_within_budget_query_completes():
    result = IdentityContext().execute(
        FO07Input(estimated_cost=Decimal(80), budget_limit=Decimal(100))
    )
    assert result.state == "completed"


def test_timeout_cancels_execution():
    ctx = IdentityContext(now=lambda: 200.0)
    result = ctx.execute(
        FO07Input(
            estimated_cost=Decimal(80),
            budget_limit=Decimal(100),
            deadline=100.0,
        )
    )
    assert result.state == "timed_out"


def test_explicit_cancellation_stops_running_query():
    result = IdentityContext().execute(
        FO07Input(
            estimated_cost=Decimal(80),
            budget_limit=Decimal(100),
            cancelled=True,
        )
    )
    assert result.state == "cancelled"
