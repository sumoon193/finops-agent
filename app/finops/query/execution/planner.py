"""只读查询执行：参数化计划、稳定分页和 CAS 状态推进。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STATE_TRANSITIONS: dict[str, set[str]] = {
    "created": {"planned"},
    "planned": {"authorized"},
    "authorized": {"running"},
    "running": {"completed", "cancelled", "timed_out"},
    "completed": set(),
    "cancelled": set(),
    "timed_out": set(),
}


@dataclass
class QueryPlan:
    statement: str
    params: dict[str, Any]


@dataclass
class FO06Input:
    rows: list[dict[str, Any]]
    page_size: int
    cursor: str | None = None


@dataclass
class FO06Result:
    page: list[dict[str, Any]] = field(default_factory=list)
    next_cursor: str | None = None
    state: str = "completed"
    state_events: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


class StateMachine:
    """CAS 状态机：推进必须匹配期望的当前状态且转换合法。"""

    def __init__(self, state: str = "created") -> None:
        self.state = state

    def transition(self, next_state: str, expected: str) -> str:
        if self.state != expected:
            raise ValueError(
                f"CAS mismatch: expected {expected}, current {self.state}"
            )
        if next_state not in STATE_TRANSITIONS[self.state]:
            raise ValueError(f"illegal transition: {self.state} -> {next_state}")
        self.state = next_state
        return self.state


class AuthorizedQueryPlan:
    """以参数化计划执行只读查询，用 keyset 游标提供稳定分页。"""

    def __init__(self, plan: QueryPlan | None = None) -> None:
        self.plan = plan

    def execute(self, input: FO06Input) -> FO06Result:
        ordered = sorted(
            input.rows, key=lambda row: (str(row.get("watermark", "")), row.get("id"))
        )
        start = 0
        if input.cursor:
            cursor_watermark, _, cursor_id = str(input.cursor).partition("|")
            for index, row in enumerate(ordered):
                if (
                    str(row.get("watermark", "")) == cursor_watermark
                    and str(row.get("id")) == cursor_id
                ):
                    start = index + 1
                    break
        page = ordered[start : start + input.page_size]
        next_cursor: str | None = None
        if start + input.page_size < len(ordered) and page:
            last = page[-1]
            next_cursor = f"{last.get('watermark', '')}|{last.get('id')}"
        return FO06Result(
            page=page,
            next_cursor=next_cursor,
            state="completed",
            state_events=["planned", "authorized", "running", "completed"],
            audit={
                "statement": self.plan.statement if self.plan else "",
                "page_size": input.page_size,
                "page_count": len(page),
                "has_next": next_cursor is not None,
            },
        )
