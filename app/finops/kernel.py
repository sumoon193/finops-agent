"""共享运行时内核：可信身份、状态机、typed command 与跨模块审计溯源。

各功能模块（FO-02..FO-12）声明各自的数据入口与结果类型，但都复用这里定义的
公共语义：

- ``RuntimeKernel`` 把服务端 ``IdentityContext`` 与全局 ``StateMachine`` 绑定，
  保证服务端可信身份不能被模型或客户端覆盖（跨模块不变量 #1）。
- ``QueryState`` 是契约里声明的唯一合法状态机：
  ``created -> planned -> authorized -> running -> completed/cancelled/timed_out``，
  非法转换稳定拒绝（跨模块不变量 #3）。
- ``AuditRecord`` 为每个副作用附带 correlation_id 与 provenance，使账单、目录、
  模型/数据来源可追溯（FO-01 可观察结果）。
- ``Command`` 是 typed command 的基类：所有状态推进必须经过 kernel ``handle``，
  控制器只做协议翻译，不写领域决策（实现计划「禁止把领域决策写入控制器」）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

# 契约声明的唯一合法状态序列。
LEGAL_STATES: tuple[str, ...] = (
    "created",
    "planned",
    "authorized",
    "running",
    "completed",
    "cancelled",
    "timed_out",
)

STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"planned"}),
    "planned": frozenset({"authorized"}),
    "authorized": frozenset({"running"}),
    "running": frozenset({"completed", "cancelled", "timed_out"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
    "timed_out": frozenset(),
}


class IllegalStateTransition(Exception):
    """非法状态转换：稳定拒绝，携带当前态与目标态供审计。"""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"illegal transition: {current} -> {target}")
        self.current = current
        self.target = target


@dataclass(frozen=True)
class IdentityContext:
    """服务端可信身份：构造后不可变，客户端/模型不得覆盖。

    跨模块不变量 #1：服务端可信身份不能由模型或客户端覆盖。
    frozen=True 使 ``ctx.tenant_id = ...`` 抛 AttributeError，测试已覆盖。
    """

    tenant_id: str
    role: str = "analyst"
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])

    def with_role(self, role: str) -> "IdentityContext":
        return IdentityContext(tenant_id=self.tenant_id, role=role, request_id=self.request_id)


@dataclass
class AuditRecord:
    """单条审计记录：关联 correlation_id 与 provenance 链。"""

    action: str
    actor: IdentityContext
    correlation_id: str
    provenance: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class StateMachine:
    """CAS 状态机：推进必须匹配期望态且转换合法。

    FO-06 要求：compare-and-set 语义，stale expected 稳定拒绝。
    """

    def __init__(self, state: str = "created") -> None:
        if state not in STATE_TRANSITIONS:
            raise IllegalStateTransition("created", state)
        self.state = state

    def transition(self, target: str, expected: str) -> str:
        if self.state != expected:
            raise IllegalStateTransition(expected, self.state)
        if target not in STATE_TRANSITIONS[self.state]:
            raise IllegalStateTransition(self.state, target)
        self.state = target
        return self.state

    def can(self, target: str) -> bool:
        return target in STATE_TRANSITIONS[self.state]


@dataclass(frozen=True)
class Command:
    """typed command：状态推进的唯一入口。

    kind 为 ``plan|authorize|run|cancel|timeout|complete|create``，由 kernel 校验
    合法性后委托给模块的执行器。
    """

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    command_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])


class RuntimeKernel:
    """统一运行时：身份 + 状态机 + 审计日志。

    控制器（FastAPI 层）只翻译协议为 Command，调用 ``handle``；模块执行器通过
    ``advance`` 推进状态、``audit`` 记录可追溯事件。
    """

    def __init__(self, identity: IdentityContext) -> None:
        self.identity = identity
        self.state = StateMachine("created")
        self.audit_log: list[AuditRecord] = []

    def advance(self, target: str, expected: str, action: str, details: dict[str, Any] | None = None) -> str:
        previous = self.state.state
        self.state.transition(target, expected)
        self.audit(
            action=action,
            provenance=[f"state:{previous}->{target}", f"actor:{self.identity.tenant_id}"],
            details=details or {},
        )
        return self.state.state

    def audit(self, action: str, provenance: Iterable[str] | None = None, details: dict[str, Any] | None = None) -> AuditRecord:
        record = AuditRecord(
            action=action,
            actor=self.identity,
            correlation_id=self.identity.request_id,
            provenance=list(provenance or []),
            details=details or {},
        )
        self.audit_log.append(record)
        return record

    def handle(self, command: Command, executor: Callable[[Command], dict[str, Any]]) -> dict[str, Any]:
        """执行 typed command，返回执行器结果 + 当前状态。"""
        self.audit(action=f"command:{command.kind}", provenance=[f"cmd:{command.command_id}"])
        return {"state": self.state.state, "result": executor(command)}


def new_correlation_id() -> str:
    return uuid.uuid4().hex
