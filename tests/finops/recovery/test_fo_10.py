"""FO-10 可观测、恢复与对账：worker 崩溃、查询取消和工单 UNKNOWN 可恢复。"""

from app.finops.recovery.ledger import (
    FO10Input,
    FO10Result,
    IdentityContext,
    SideEffectLedger,
)


def test_interrupted_worker_work_resumes():
    result = IdentityContext().execute(
        FO10Input(items=[{"effect_id": "e1", "status": "interrupted"}])
    )
    assert isinstance(result, FO10Result)
    assert result.recovered == ["e1"]
    assert result.status == "completed"


def test_cancelled_query_recovers_to_cancelled_not_stuck():
    result = IdentityContext().execute(
        FO10Input(items=[{"effect_id": "q9", "status": "cancelled"}])
    )
    assert result.cancelled == ["q9"]
    assert result.status == "completed"


def test_unknown_ticket_is_reconciled_idempotently():
    ledger = SideEffectLedger()
    ctx = IdentityContext(ledger=ledger)
    reconciled = []

    def reconcile(effect_id):
        reconciled.append(effect_id)
        return "resolved"

    target = FO10Input(
        items=[{"effect_id": "t1", "status": "unknown"}], reconcile=reconcile
    )
    first = ctx.execute(target)
    second = ctx.execute(target)
    assert first.resolved == ["t1"]
    assert second.resolved == ["t1"]
    assert len(reconciled) == 1  # reconciled exactly once


def test_side_effect_ledger_prevents_duplicate_effects():
    ledger = SideEffectLedger()
    assert ledger.record("e1") is True
    assert ledger.record("e1") is False  # already done, no duplicate side effect
    assert ledger.attempts("e1") == 1
