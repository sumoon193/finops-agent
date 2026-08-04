"""查询预算控制器：超预算执行前拒绝，超时可取消。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable


@dataclass
class FO07Input:
    estimated_cost: Decimal
    budget_limit: Decimal
    deadline: float | None = None
    cancelled: bool = False


@dataclass
class FO07Result:
    state: str
    state_events: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


class IdentityContext:
    def __init__(self, now: Callable[[], float] | None = None) -> None:
        self._now = now or time.time

    def execute(self, input: FO07Input) -> FO07Result:
        events = ["planned"]
        if input.estimated_cost > input.budget_limit:
            events.append("budget-rejected")
            return FO07Result(
                state="rejected",
                state_events=events,
                audit={"estimated_cost": str(input.estimated_cost),
                       "budget_limit": str(input.budget_limit)},
            )
        events.extend(["authorized", "running"])
        if input.cancelled:
            events.append("cancelled")
            return FO07Result(
                state="cancelled",
                state_events=events,
                audit={"reason": "cancelled"},
            )
        if input.deadline is not None and self._now() > input.deadline:
            events.append("timed_out")
            return FO07Result(
                state="timed_out",
                state_events=events,
                audit={"deadline": input.deadline},
            )
        events.append("completed")
        return FO07Result(
            state="completed",
            state_events=events,
            audit={"estimated_cost": str(input.estimated_cost)},
        )
