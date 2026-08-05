"""FO-11 冻结评测与真实模型受控试验：RLS、AST、查询正确率和模型收益由冻结集验证。"""

import pytest

from app.finops.eval.runner import FO11Input, FO11Result, FrozenCase, QueryIntent

CASES = [
    FrozenCase("rls-1", "rls", "block cross-tenant read", True),
    FrozenCase("ast-1", "ast", "reject DDL/DML", True),
    FrozenCase("query-1", "query", "stable pagination", False),
]


def test_frozen_set_evaluates_rls_ast_and_query_correctness():
    result = QueryIntent().execute(
        FO11Input(cases=CASES, scorer=lambda case: case.expected, model_backend=None)
    )
    assert isinstance(result, FO11Result)
    assert result.total == 3
    assert result.passed == 2
    assert result.accuracy == pytest.approx(2 / 3)
    assert result.by_category["rls"] == 1.0
    assert result.by_category["ast"] == 1.0
    assert result.by_category["query"] == 0.0


def test_real_model_backend_is_required_for_gain():
    result = QueryIntent().execute(
        FO11Input(cases=CASES[:1], scorer=lambda case: case.expected, model_backend=None)
    )
    assert result.model_gain == "blocked"
    assert any("未接入" in item for item in result.unverified)


def test_recorded_backend_measures_model_gain():
    result = QueryIntent().execute(
        FO11Input(
            cases=CASES[:1],
            scorer=lambda case: case.expected,
            model_backend="recorded-fixture",
        )
    )
    assert result.model_gain == "measured"
    assert result.unverified == []


def test_frozen_evaluation_is_deterministic():
    first = QueryIntent().execute(
        FO11Input(cases=CASES, scorer=lambda case: case.expected, model_backend="recorded-fixture")
    )
    second = QueryIntent().execute(
        FO11Input(cases=CASES, scorer=lambda case: case.expected, model_backend="recorded-fixture")
    )
    assert first.accuracy == second.accuracy
    assert first.by_category == second.by_category
    assert first.scores == second.scores
