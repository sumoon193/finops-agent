"""数据层替换与回滚：语义/FOCUS/数据库 adapter 可注册、切换并回滚。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ADAPTER_KINDS = ("semantic", "focus", "database")


class AdapterRegistry:
    """按 adapter 类别维护当前版本与回滚栈。"""

    def __init__(self) -> None:
        self._current: dict[str, str] = {}
        self._history: dict[str, list[str]] = {}

    def register(self, kind: str, name: str) -> None:
        if kind not in ADAPTER_KINDS:
            raise ValueError(f"unknown adapter kind: {kind}")
        self._current[kind] = name
        self._history[kind] = [name]

    def current(self, kind: str) -> str | None:
        return self._current.get(kind)

    def switch(self, kind: str, name: str) -> None:
        if kind not in self._current:
            raise ValueError(f"adapter kind not registered: {kind}")
        stack = self._history.setdefault(kind, [])
        stack.append(self._current[kind])
        self._current[kind] = name

    def rollback(self, kind: str) -> bool:
        stack = self._history.get(kind, [])
        if len(stack) < 2:
            return False
        stack.pop()
        self._current[kind] = stack[-1]
        return True


@dataclass
class FO12Input:
    action: str
    kind: str
    name: str | None = None


@dataclass
class FO12Result:
    current: str | None = None
    rollback_performed: bool = False
    state_events: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


class AuthorizedQueryPlan:
    """以 typed command 执行 adapter 切换或回滚。"""

    def __init__(self, registry: AdapterRegistry | None = None) -> None:
        self.registry = registry or AdapterRegistry()

    def execute(self, input: FO12Input) -> FO12Result:
        if input.action == "switch":
            if not input.name:
                raise ValueError("switch requires a name")
            self.registry.switch(input.kind, input.name)
            return FO12Result(
                current=self.registry.current(input.kind),
                rollback_performed=False,
                state_events=["planned", "completed"],
                audit={"action": "switch", "kind": input.kind, "name": input.name},
            )
        if input.action == "rollback":
            performed = self.registry.rollback(input.kind)
            return FO12Result(
                current=self.registry.current(input.kind),
                rollback_performed=performed,
                state_events=["planned", "completed"],
                audit={"action": "rollback", "kind": input.kind, "performed": performed},
            )
        raise ValueError(f"unknown action: {input.action}")
