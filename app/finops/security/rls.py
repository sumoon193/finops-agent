"""RLS 行级门禁：授权计划只返回本租户行，跨租户读取被阻断并记录审计事件。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FO03Input:
    rows: list[dict[str, Any]]


@dataclass
class FO03Result:
    allowed_rows: list[dict[str, Any]] = field(default_factory=list)
    blocked_rows: list[dict[str, Any]] = field(default_factory=list)
    state_events: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


class AuthorizedQueryPlan:
    """绑定服务端租户身份的只读计划，镜像数据库 RLS 的行过滤语义。"""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id

    def execute(self, input: FO03Input) -> FO03Result:
        allowed: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for row in input.rows:
            if row.get("tenant_id") == self.tenant_id:
                allowed.append(row)
            else:
                blocked.append(row)
        state_events = ["planned", "completed"]
        if blocked:
            state_events.append("cross-tenant-blocked")
        return FO03Result(
            allowed_rows=allowed,
            blocked_rows=blocked,
            state_events=state_events,
            audit={
                "tenant_id": self.tenant_id,
                "allowed_count": len(allowed),
                "blocked_count": len(blocked),
            },
        )
