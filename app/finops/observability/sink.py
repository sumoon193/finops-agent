"""可观测性：把 kernel 审计事件导出为可观测 trace span。

FO-10「可观测、恢复与对账」的可观测部分。Recovery ledger 解决幂等恢复，
这里补充每个副作用/查询步骤的可观测事件导出：
- ``ObservabilitySink`` 收集 AuditRecord 转成带 trace_id 纳秒时间戳的 span。
- 不接真实 Prometheus/OTel exporter（外部依赖有 Fake 适配器，真实接入列为 unverified）。

跨模块不变量 #5：用户可见结论必须关联 provenance/citation。这里的 span 关联
correlation_id 与 provenance，使每个 Agent 步骤延迟、副作用、ticket 创建可观测。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.finops.kernel import AuditRecord


@dataclass(frozen=True)
class TraceSpan:
    """单个可观测 span：关联 correlation_id 与 provenance 链。"""

    span_id: str
    trace_id: str
    name: str
    started_at_ns: int
    provenance: tuple[str, ...]
    attributes: dict[str, Any] = field(default_factory=dict)


class ObservabilitySink:
    """把 AuditRecord 转为 TraceSpan 的离线 sink。

    真实 exporter（OTel/Prometheus）未接入时，span 停留在内存，可被测试断言。
    这里不调用真实网络，遵循跨模块不变量 #4（外部依赖必须有 Fake adapter）。
    """

    def __init__(self, clock_ns: Any = None) -> None:
        self._counter = 0
        self._clock_ns = clock_ns or (lambda: time.monotonic_ns())
        self.spans: list[TraceSpan] = []
        # 每个 kernel 的 audit_log 已导出的偏移，避免重复 drain。
        self._drained_offsets: dict[int, int] = {}

    def _next_span_id(self, trace_id: str) -> str:
        self._counter += 1
        return f"{trace_id}-{self._counter:04x}"

    def record(self, audit: AuditRecord) -> TraceSpan:
        span = TraceSpan(
            span_id=self._next_span_id(audit.correlation_id),
            trace_id=audit.correlation_id,
            name=audit.action,
            started_at_ns=self._clock_ns(),
            provenance=tuple(audit.provenance),
            attributes=dict(audit.details),
        )
        self.spans.append(span)
        return span

    def drain(self, kernel: Any) -> list[TraceSpan]:
        """把 kernel 尚未导出的 audit 记录追加导出为 span，重复 drain 不重复。"""
        key = id(kernel)
        offset = self._drained_offsets.get(key, 0)
        new_records = kernel.audit_log[offset:]
        produced: list[TraceSpan] = []
        for audit in new_records:
            produced.append(self.record(audit))
        self._drained_offsets[key] = offset + len(new_records)
        return produced

    def by_trace(self, trace_id: str) -> list[TraceSpan]:
        return [span for span in self.spans if span.trace_id == trace_id]