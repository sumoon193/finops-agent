"""恢复台账：worker 崩溃、查询取消和工单 UNKNOWN 的可恢复与幂等对账。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class SideEffectLedger:
    """副作用台账：同一 effect 只执行一次，幂等防重。"""

    def __init__(self) -> None:
        self._done: set[str] = set()
        self._attempts: dict[str, int] = {}
        self._outcomes: dict[str, str] = {}

    def record(self, effect_id: str) -> bool:
        if effect_id in self._done:
            return False
        self._attempts[effect_id] = self._attempts.get(effect_id, 0) + 1
        self._done.add(effect_id)
        return True

    def attempts(self, effect_id: str) -> int:
        return self._attempts.get(effect_id, 0)

    def set_outcome(self, effect_id: str, outcome: str) -> None:
        self._outcomes[effect_id] = outcome

    def outcome(self, effect_id: str) -> str | None:
        return self._outcomes.get(effect_id)


@dataclass
class FO10Input:
    items: list[dict[str, Any]]
    reconcile: Callable[[str], str] = lambda effect_id: "resolved"


@dataclass
class FO10Result:
    recovered: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    status: str = "completed"
    state_events: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


class IdentityContext:
    def __init__(self, ledger: SideEffectLedger | None = None) -> None:
        self.ledger = ledger or SideEffectLedger()

    def execute(self, input: FO10Input) -> FO10Result:
        recovered: list[str] = []
        cancelled: list[str] = []
        resolved: list[str] = []
        for item in input.items:
            effect_id = str(item["effect_id"])
            status = str(item["status"])
            if status == "interrupted":
                self.ledger.record(effect_id)
                recovered.append(effect_id)
            elif status == "cancelled":
                self.ledger.record(effect_id)
                cancelled.append(effect_id)
            elif status == "unknown":
                if self.ledger.record(effect_id):
                    outcome = input.reconcile(effect_id)
                    self.ledger.set_outcome(effect_id, outcome)
                resolved.append(effect_id)
            else:
                raise ValueError(f"unknown recovery status: {status}")
        return FO10Result(
            recovered=recovered,
            cancelled=cancelled,
            resolved=resolved,
            status="completed",
            state_events=["planned", "completed"],
            audit={
                "recovered": len(recovered),
                "cancelled": len(cancelled),
                "resolved": len(resolved),
            },
        )
