"""FO-10 可观测性：把 kernel 审计事件导出为 TraceSpan。"""

from __future__ import annotations

from app.finops.kernel import IdentityContext, RuntimeKernel
from app.finops.observability.sink import ObservabilitySink, TraceSpan


def test_audit_record_becomes_traceable_span():
    kernel = RuntimeKernel(IdentityContext(tenant_id="acme", request_id="trace-1"))
    kernel.audit(action="query-plan", provenance=["watermark:w1"], details={"rows": 3})
    sink = ObservabilitySink()
    produced = sink.drain(kernel)
    assert produced and all(isinstance(span, TraceSpan) for span in produced)
    span = produced[-1]
    assert span.trace_id == "trace-1"
    assert span.name == "query-plan"
    assert "watermark:w1" in span.provenance
    assert span.attributes == {"rows": 3}


def test_drain_is_idempotent_across_repeated_calls():
    kernel = RuntimeKernel(IdentityContext(tenant_id="acme", request_id="trace-2"))
    kernel.audit(action="a1", provenance=[])
    kernel.audit(action="a2", provenance=[])
    sink = ObservabilitySink()
    first = sink.drain(kernel)
    second = sink.drain(kernel)  # no new records
    assert len(first) == 2
    assert second == []
    kernel.audit(action="a3", provenance=[])
    third = sink.drain(kernel)
    assert len(third) == 1 and third[0].name == "a3"
    assert len(sink.spans) == 3


def test_spans_group_by_trace_id_for_query_lifecycle():
    kernel = RuntimeKernel(IdentityContext(tenant_id="acme", request_id="trace-3"))
    kernel.audit(action="plan", provenance=["state:created->planned"])
    kernel.audit(action="run", provenance=["state:planned->completed"])
    sink = ObservabilitySink()
    sink.drain(kernel)
    grouped = sink.by_trace("trace-3")
    assert [span.name for span in grouped] == ["plan", "run"]
    assert all(span.trace_id == "trace-3" for span in grouped)
    # cross-trace隔离：另一个 trace 不应被本 trace 命中。
    other = RuntimeKernel(IdentityContext(tenant_id="acme", request_id="trace-4"))
    other.audit(action="other", provenance=[])
    sink.drain(other)
    assert sink.by_trace("trace-3") == grouped


def test_span_clock_is_deterministic_under_injected_clock():
    kernel = RuntimeKernel(IdentityContext(tenant_id="acme", request_id="trace-5"))
    kernel.audit(action="tick", provenance=[])
    ticks = iter([1000, 2000, 3000])
    sink = ObservabilitySink(clock_ns=lambda: next(ticks))
    sink.drain(kernel)
    assert sink.spans[-1].started_at_ns == 1000