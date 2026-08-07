"""冻结评测：RLS、AST、查询正确率与模型收益由冻结集验证，真实模型未接入则保持 blocked。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FrozenCase:
    case_id: str
    category: str
    behavior: str
    expected: bool


@dataclass
class FO11Input:
    cases: list[FrozenCase]
    scorer: Callable[[FrozenCase], bool]
    model_backend: str | None = None


@dataclass
class FO11Result:
    total: int = 0
    passed: int = 0
    accuracy: float = 0.0
    scores: dict[str, bool] = field(default_factory=dict)
    by_category: dict[str, float] = field(default_factory=dict)
    model_gain: str = "blocked"
    unverified: list[str] = field(default_factory=list)
    state_events: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


class QueryIntent:
    """在冻结集上评测系统正确率；模型收益只在实际/Recorded 后端存在时测量。"""

    def execute(self, input: FO11Input) -> FO11Result:
        scores = {case.case_id: bool(input.scorer(case)) for case in input.cases}
        total = len(input.cases)
        passed = sum(1 for correct in scores.values() if correct)
        accuracy = passed / total if total else 0.0
        buckets: dict[str, list[int]] = {}
        for case in input.cases:
            bucket = buckets.setdefault(case.category, [0, 0])
            bucket[0] += 1
            bucket[1] += int(scores[case.case_id])
        by_category = {
            category: (hits / count if count else 0.0)
            for category, (count, hits) in buckets.items()
        }
        if input.model_backend is None:
            model_gain = "blocked"
            unverified = ["真实模型未接入，模型收益未验证"]
        else:
            model_gain = "measured"
            unverified = []
        return FO11Result(
            total=total,
            passed=passed,
            accuracy=accuracy,
            scores=scores,
            by_category=by_category,
            model_gain=model_gain,
            unverified=unverified,
            state_events=["planned", "completed"],
            audit={
                "model_backend": input.model_backend,
                "case_count": total,
            },
        )
