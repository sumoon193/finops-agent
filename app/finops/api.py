"""API 层：契约要求的四个 HTTP 端点。

契约 API：
- ``POST /billing-ingestions``：把原始 FOCUS 账单行规范化落库，凭证可追溯。
- ``POST /queries``：经意图 → AST 门禁 → 授权计划 → 预算/超时 → 结果存储执行查询。
- ``DELETE /queries/{id}`：取消正在运行的查询，触发恢复台账的 cancelled 处理。
- ``POST /findings/{id}/tickets``：异常 finding 经审批创建幂等人工工单。

实现计划「禁止把领域决策写入控制器」：本文件只做协议翻译 + 调度，
所有领域逻辑委托给各模块的执行器与 ``RuntimeKernel``。

跨模块不变量覆盖：
- #1 服务端身份由 ``resolve_identity`` 从受信头构造，客户端模型不可覆盖。
- #2 工单创建经 TicketService 幂等并记账。
- #3 查询状态推进经 kernel.advance + CAS 状态机。
- #4 外部依赖（模型、DB）以 Fake/Recorded adapter 实现，真实接入列为 unverified。
- #5 结果带 provenance，证据不足保持 blocked/review。
"""

from __future__ import annotations

from decimal import Decimal
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.finops.anomaly.attribution import AnomalyFinding
from app.finops.catalog.registry import SemanticCatalog
from app.finops.focus.canonical import QueryIntent as FocusQueryIntent, FO02Input as NormalizeInput
from app.finops.intent.model import IdentityContext as IntentIdentityContext, FO04Input as IntentInput
from app.finops.kernel import IdentityContext, RuntimeKernel, Command
from app.finops.persistence import Record, Repositories, set_current_tenant
from app.finops.intent.model import ModelUnavailableError, RealIntentModel
from app.finops.query.ast.guard import QueryIntent as AstGuard, FO05Input as AstInput
from app.finops.query.budget.controller import IdentityContext as BudgetContext, FO07Input as BudgetInput
from app.finops.query.execution.planner import AuthorizedQueryPlan as ExecPlan, FO06Input as ExecInput
from app.finops.results.store import QueryIntent as ResultsIntent, FO08Input as ResultsInput, ResultCache
from app.finops.security.rls import AuthorizedQueryPlan as RlsPlan, FO03Input as RlsInput
from app.finops.tickets.service import AuthorizedQueryPlan as TicketPlan, FO09Input as TicketInput, TicketService
from app.finops.observability.sink import ObservabilitySink

app = FastAPI(
    title="FinOps 云成本治理智能体",
    version="0.1.0",
    description="来源、身份、只读查询、预算、结果、异常工单、恢复与冻结评测的受控 API。",
)

# ---------------------------------------------------------------------------
# 受信身份解析 + 全局状态装配
# ---------------------------------------------------------------------------

CATALOG = SemanticCatalog(
    version="2024-07",
    allowed_kinds={"cost-breakdown", "trend", "anomaly", "cost-spike"},
)
repos = Repositories()
result_cache = ResultCache()
ticket_service = TicketService()
observability = ObservabilitySink()
# 查询生命周期 kernel 的 sink 保留在内存，可被测试 drain；真实 exporter 未接入。
_query_kernels: dict[str, RuntimeKernel] = {}


class ForbiddenIdentity(Exception):
    """客户端未携带可信身份头。"""


def resolve_identity(
    x_tenant_id: str | None,
    x_role: str | None = None,
    x_request_id: str | None = None,
) -> IdentityContext:
    if not x_tenant_id:
        raise ForbiddenIdentity("missing trusted X-Tenant-Id header")
    set_current_tenant(x_tenant_id)
    return IdentityContext(tenant_id=x_tenant_id, role=x_role or "analyst", request_id=x_request_id or "")


def envelope(result: Any, correlation_id: str, state: str = "ok") -> dict[str, Any]:
    return {"correlation_id": correlation_id, "state": state, "result": result}


# ---------------------------------------------------------------------------
# 请求/响应类型
# ---------------------------------------------------------------------------


class BillingIngestionRequest(BaseModel):
    watermark: str
    raw_lines: list[dict[str, Any]]


class BillingIngestionResponse(BaseModel):
    ingested: int
    watermark: str
    source_ids: list[str]


class QueryRequest(BaseModel):
    statement: str = Field(..., description="只读 SELECT，参数化占位以 :name 表示")
    params: dict[str, Any] = Field(default_factory=dict)
    page_size: int = 100
    cursor: str | None = None
    catalog_version: str = "2024-07"
    estimated_cost: Decimal = Decimal("0")
    budget_limit: Decimal = Decimal("10000")
    rows: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Deprecated compatibility field; client rows are never used as a data source.",
    )
    allowed_resources: list[str] = Field(default_factory=lambda: ["billing_line_item"])


class QueryResponse(BaseModel):
    query_id: str
    body: dict[str, Any]


class TicketRequest(BaseModel):
    approved: bool = True


# ---------------------------------------------------------------------------
# POST /billing-ingestions
# ---------------------------------------------------------------------------


@app.post("/billing-ingestions", status_code=status.HTTP_201_CREATED)
def billing_ingestions(
    payload: BillingIngestionRequest,
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(x_tenant_id, x_role, x_request_id)
    except ForbiddenIdentity as exc:
        raise HTTPException(status_code=400, detail={"error": "forbidden_identity", "message": str(exc)})
    kernel = RuntimeKernel(identity)
    kernel.audit(action="billing-ingestion-planned", provenance=[f"watermark:{payload.watermark}"])
    normalize = FocusQueryIntent()
    norm = normalize.execute(NormalizeInput(raw_lines=payload.raw_lines, watermark=payload.watermark))
    for item in norm.items:
        key = Repositories.idempotency_key("billing", item.source_id, item.watermark)
        repos.billing_line_item.put(
            Record(
                id=repos.next_id("bli"),
                idempotency_key=key,
                payload={
                    "source_id": item.source_id,
                    "currency": item.currency,
                    "unit": item.unit,
                    "amount": str(item.amount),
                    "watermark": item.watermark,
                    "raw_ref": item.raw_ref,
                    "tenant_id": identity.tenant_id,
                },
            )
        )
    kernel.audit(action="billing-ingestion-completed", provenance=[f"count:{len(norm.items)}"], details={"count": len(norm.items)})
    return envelope(
        BillingIngestionResponse(
            ingested=len(norm.items),
            watermark=payload.watermark,
            source_ids=[item.source_id for item in norm.items],
        ).model_dump(),
        correlation_id=identity.request_id,
    )


# ---------------------------------------------------------------------------
# POST /queries
# ---------------------------------------------------------------------------


@app.post("/queries", status_code=status.HTTP_201_CREATED)
def create_query(
    payload: QueryRequest,
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(x_tenant_id, x_role, x_request_id)
    except ForbiddenIdentity as exc:
        raise HTTPException(status_code=400, detail={"error": "forbidden_identity", "message": str(exc)})
    kernel = RuntimeKernel(identity)
    query_id = repos.next_id("qr")
    run_key = Repositories.idempotency_key("query", query_id, identity.tenant_id)
    repos.query_run.put(
        Record(
            id=query_id,
            idempotency_key=run_key,
            payload={"tenant_id": identity.tenant_id, "statement": payload.statement, "status": "running"},
        )
    )
    kernel.advance("planned", "created", "query-planned")

    # FO-04 意图：模型输出 typed intent，绑定语义目录版本。
    if os.getenv("FINOPS_AGENT_MODE", "offline").lower() == "live":
        try:
            live_intent = RealIntentModel().generate(payload.statement, CATALOG)
        except ModelUnavailableError as exc:
            raise HTTPException(status_code=503, detail={"error": "model_blocked", "message": str(exc)}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail={"error": "model_failed", "message": str(exc)}) from exc
        if live_intent.catalog_version != CATALOG.version:
            raise HTTPException(status_code=422, detail={"error": "catalog_version_mismatch"})
    else:
        intent = IntentIdentityContext(catalog=CATALOG, role=identity.role)
        intent.execute(IntentInput(raw={"kind": "cost-breakdown", "params": payload.params}, catalog_version=payload.catalog_version))
    kernel.advance("authorized", "planned", "query-authorized")

    # FO-05 AST 门禁：拒绝 DDL/DML、函数与非白名单资源。
    ast = AstGuard().execute(
        AstInput(statement=payload.statement, allowed_resources=payload.allowed_resources)
    )
    if not ast.allowed:
        raise HTTPException(status_code=422, detail={"error": "ast_violation", "violations": ast.violations})

    # FO-03 RLS：服务端身份过滤跨租户行。
    trusted_rows = [
        dict(record.payload)
        for record in repos.billing_line_item.all()
        if record.payload.get("tenant_id") == identity.tenant_id
    ]
    # Client-supplied rows are intentionally ignored. Billing data must come from
    # the trusted ingestion repository and be filtered by the server identity.
    rls = RlsPlan(tenant_id=identity.tenant_id).execute(RlsInput(rows=trusted_rows))
    kernel.advance("running", "authorized", "query-running")

    # FO-07 预算/超时/取消：超预算执行前拒绝。
    budget = BudgetContext().execute(
        BudgetInput(estimated_cost=payload.estimated_cost, budget_limit=payload.budget_limit)
    )
    if budget.state == "rejected":
        raise HTTPException(status_code=402, detail={"error": "budget_rejected", "audit": budget.audit})

    # FO-06 执行：参数化计划 + keyset 稳定分页 + CAS 状态。
    exec_result = ExecPlan().execute(
        ExecInput(rows=rls.allowed_rows, page_size=payload.page_size, cursor=payload.cursor)
    )

    # FO-08 结果存储：缓存键绑定 RLS/语义/watermark。
    query_hash = Repositories.idempotency_key("result", payload.statement, identity.tenant_id, payload.catalog_version)
    results = ResultsIntent(cache=result_cache).execute(
        ResultsInput(
            query_hash=query_hash,
            tenant_id=identity.tenant_id,
            semantic_version=payload.catalog_version,
            watermark=repos.billing_line_item.all()[-1].payload.get("watermark", "") if repos.billing_line_item.all() else "",
            compute=lambda: {"page": exec_result.page, "next_cursor": exec_result.next_cursor},
        )
    )
    artifact = results.artifact
    repos.result_artifact.put(
        Record(id=query_id, idempotency_key=query_hash, payload={"value": artifact.value, "provenance": artifact.provenance})
    )
    kernel.advance("completed", "running", "query-completed", details={"query_id": query_id})
    query_record = repos.query_run.get(query_id)
    if query_record is not None:
        query_record.payload["status"] = "completed"
    _query_kernels[query_id] = kernel
    observability.drain(kernel)
    return envelope(
        {"query_id": query_id, "page": exec_result.page, "next_cursor": exec_result.next_cursor, "provenance": artifact.provenance},
        correlation_id=identity.request_id,
    )


@app.get("/queries/{query_id}/trace", status_code=status.HTTP_200_OK)
def query_trace(
    query_id: str,
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> dict[str, Any]:
    """返回某查询生命周期的可观测 span 列表（FO-10 可观测性）。"""
    try:
        identity = resolve_identity(x_tenant_id, x_role, x_request_id)
    except ForbiddenIdentity as exc:
        raise HTTPException(status_code=400, detail={"error": "forbidden_identity", "message": str(exc)})
    record = repos.query_run.get(query_id)
    if not record:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if record.payload.get("tenant_id") != identity.tenant_id:
        raise HTTPException(status_code=403, detail={"error": "cross_tenant_denied"})
    kernel = _query_kernels.get(query_id)
    spans = [vars(span) for span in observability.by_trace(identity.request_id)] if kernel else []
    return envelope({"query_id": query_id, "spans": spans}, correlation_id=identity.request_id)


# ---------------------------------------------------------------------------
# DELETE /queries/{id}
# ---------------------------------------------------------------------------


@app.delete("/queries/{query_id}", status_code=status.HTTP_202_ACCEPTED)
def cancel_query(
    query_id: str,
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(x_tenant_id, x_role, x_request_id)
    except ForbiddenIdentity as exc:
        raise HTTPException(status_code=400, detail={"error": "forbidden_identity", "message": str(exc)})
    record = repos.query_run.get(query_id)
    if not record:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "query_id not found"})
    if record.payload.get("tenant_id") != identity.tenant_id:
        raise HTTPException(status_code=403, detail={"error": "cross_tenant_denied"})
    # 取消语义：经恢复账本的 cancelled 路径幂等推进，再标记 run。
    from app.finops.recovery.ledger import FO10Input as RecoverInput, IdentityContext as RecoverContext

    RecoverContext().execute(RecoverInput(items=[{"effect_id": query_id, "status": "cancelled"}]))
    current_status = str(record.payload.get("status", "completed"))
    if current_status != "running":
        raise HTTPException(
            status_code=409,
            detail={"error": "query_not_running", "status": current_status},
        )
    record.payload["status"] = "cancelled"
    return envelope({"query_id": query_id, "status": "cancelled"}, correlation_id=identity.request_id)


# ---------------------------------------------------------------------------
# POST /findings/{id}/tickets
# ---------------------------------------------------------------------------


@app.post("/findings/{finding_id}/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(
    finding_id: str,
    payload: TicketRequest,
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(x_tenant_id, x_role, x_request_id)
    except ForbiddenIdentity as exc:
        raise HTTPException(status_code=400, detail={"error": "forbidden_identity", "message": str(exc)})
    finding_record = repos.anomaly_finding.get(finding_id)
    if not finding_record:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "finding_id not found"})
    finding = AnomalyFinding(
        finding_id=finding_id,
        query_id=str(finding_record.payload.get("query_id", "")),
        kind=str(finding_record.payload.get("kind", "")),
        severity=str(finding_record.payload.get("severity", "")),
        detail=str(finding_record.payload.get("detail", "")),
    )
    plan = TicketPlan(service=ticket_service)
    kernel = RuntimeKernel(identity)
    kernel.audit(action="ticket-planned", provenance=[f"finding:{finding_id}"])
    result = plan.execute(TicketInput(finding=finding, approved=payload.approved))
    if result.status == "blocked":
        raise HTTPException(status_code=409, detail={"error": "approval_required", "state_events": result.state_events})
    kernel.audit(action="ticket-created", provenance=[f"ticket:{result.ticket.ticket_id if result.ticket else ''}"], details={"ticket_id": result.ticket.ticket_id if result.ticket else None})
    repos.governance_ticket.put(
        Record(
            id=(result.ticket.ticket_id if result.ticket else repos.next_id("tkt")),
            idempotency_key=Repositories.idempotency_key("ticket", finding_id),
            payload={"finding_id": finding_id, "status": result.status},
        )
    )
    return envelope(
        {"ticket_id": result.ticket.ticket_id if result.ticket else None, "finding_id": finding_id, "status": result.status},
        correlation_id=identity.request_id,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
