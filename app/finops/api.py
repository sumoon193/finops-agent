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
- #4 外部依赖按运行模式显式装配；PostgreSQL 与真实模型失败时不得静默降级。
- #5 结果带 provenance，证据不足保持 blocked/review。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from contextvars import ContextVar
from decimal import Decimal
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.finops.anomaly.attribution import AnomalyFinding
from app.finops.catalog.registry import SemanticCatalog
from app.finops.focus.canonical import FO02Input as NormalizeInput
from app.finops.focus.canonical import QueryIntent as FocusQueryIntent
from app.finops.intent.model import FO04Input as IntentInput
from app.finops.intent.model import IdentityContext as IntentIdentityContext
from app.finops.intent.model import ModelUnavailableError, RealIntentModel
from app.finops.kernel import IdentityContext, RuntimeKernel
from app.finops.observability.sink import ObservabilitySink
from app.finops.persistence import Record, Repositories, set_current_tenant
from app.finops.query.ast.guard import FO05Input as AstInput
from app.finops.query.ast.guard import QueryIntent as AstGuard
from app.finops.query.budget.controller import FO07Input as BudgetInput
from app.finops.query.budget.controller import IdentityContext as BudgetContext
from app.finops.query.execution.planner import AuthorizedQueryPlan as ExecPlan
from app.finops.query.execution.planner import FO06Input as ExecInput
from app.finops.results.store import FO08Input as ResultsInput
from app.finops.results.store import QueryIntent as ResultsIntent
from app.finops.results.store import ResultCache
from app.finops.security.rls import AuthorizedQueryPlan as RlsPlan
from app.finops.security.rls import FO03Input as RlsInput
from app.finops.tickets.service import AuthorizedQueryPlan as TicketPlan
from app.finops.tickets.service import FO09Input as TicketInput
from app.finops.tickets.service import TicketService

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
_oidc_claims: ContextVar[dict[str, Any] | None] = ContextVar(
    "finops_oidc_claims", default=None
)


class ForbiddenIdentity(Exception):
    """客户端未携带可信身份头。"""


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> Any:
    from jwt import PyJWKClient

    return PyJWKClient(jwks_url, cache_keys=True, lifespan=300)


def _verify_oidc_token(token: str) -> dict[str, Any]:
    """使用 issuer JWKS 验证签名、受众和标准时效声明。"""
    import jwt

    issuer = os.getenv("FINOPS_OIDC_ISSUER_URL", "").rstrip("/")
    audience = os.getenv("FINOPS_OIDC_AUDIENCE", "")
    if not issuer or not audience:
        raise ForbiddenIdentity("OIDC issuer and audience are required")
    try:
        jwks_url = os.getenv(
            "FINOPS_OIDC_JWKS_URL",
            f"{issuer}/protocol/openid-connect/certs",
        )
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except (jwt.PyJWTError, OSError, ValueError) as exc:
        raise ForbiddenIdentity("OIDC token verification failed") from exc
    if not isinstance(claims, dict):
        raise ForbiddenIdentity("invalid OIDC claims")
    return claims


@app.middleware("http")
async def oidc_identity_context(request: Request, call_next):  # type: ignore[no-untyped-def]
    """在 OIDC 模式中只信任签名令牌，不接受浏览器伪造租户头。"""
    if os.getenv("FINOPS_IDENTITY_MODE", "offline").lower() != "oidc":
        return await call_next(request)
    if request.url.path == "/health":
        return await call_next(request)
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return JSONResponse(status_code=401, content={"detail": {"error": "missing_bearer_token"}})
    try:
        claims = _verify_oidc_token(token)
        tenant_id = claims.get("tenant_id")
        realm_access = claims.get("realm_access", {})
        roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
        allowed_roles = {"finops-analyst", "finops-operator", "finops-admin"}
        if not isinstance(tenant_id, str) or not tenant_id:
            raise ForbiddenIdentity("missing tenant_id claim")
        if (
            not isinstance(roles, list)
            or not all(isinstance(role, str) for role in roles)
            or not allowed_roles.intersection(roles)
        ):
            raise ForbiddenIdentity("missing FinOps role")
    except ForbiddenIdentity as exc:
        return JSONResponse(
            status_code=401,
            content={"detail": {"error": "invalid_bearer_token", "message": str(exc)}},
        )
    context_token = _oidc_claims.set(claims)
    try:
        return await call_next(request)
    finally:
        _oidc_claims.reset(context_token)


def resolve_identity(
    x_tenant_id: str | None,
    x_role: str | None = None,
    x_request_id: str | None = None,
    x_identity_signature: str | None = None,
    x_identity_timestamp: str | None = None,
) -> IdentityContext:
    if os.getenv("FINOPS_IDENTITY_MODE", "offline").lower() == "oidc":
        claims = _oidc_claims.get()
        if claims is None:
            raise ForbiddenIdentity("OIDC identity context is unavailable")
        tenant_id = str(claims["tenant_id"])
        realm_access = claims.get("realm_access", {})
        roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
        role_order = ("finops-admin", "finops-operator", "finops-analyst")
        role = next((candidate for candidate in role_order if candidate in roles), "")
        set_current_tenant(tenant_id)
        return IdentityContext(
            tenant_id=tenant_id,
            role=role,
            request_id=x_request_id or "",
        )
    if not x_tenant_id:
        raise ForbiddenIdentity("missing trusted X-Tenant-Id header")
    role = x_role or "analyst"
    request_id = x_request_id or ""
    if os.getenv("FINOPS_IDENTITY_MODE", "offline").lower() == "signed":
        secret = os.getenv("FINOPS_IDENTITY_SECRET", "")
        if not secret:
            raise ForbiddenIdentity("signed identity configuration is unavailable")
        if not request_id or not x_identity_signature or not x_identity_timestamp:
            raise ForbiddenIdentity("missing identity signature headers")
        try:
            signed_at = int(x_identity_timestamp)
        except ValueError as exc:
            raise ForbiddenIdentity("invalid identity signature timestamp") from exc
        max_age = int(os.getenv("FINOPS_IDENTITY_MAX_AGE_SECONDS", "300"))
        if max_age <= 0 or abs(int(time.time()) - signed_at) > max_age:
            raise ForbiddenIdentity("identity signature expired")
        message = f"{x_tenant_id}\n{role}\n{request_id}\n{x_identity_timestamp}"
        expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, x_identity_signature):
            raise ForbiddenIdentity("invalid identity signature")
    set_current_tenant(x_tenant_id)
    return IdentityContext(tenant_id=x_tenant_id, role=role, request_id=request_id)


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
    estimated_cost: Decimal = Decimal(0)
    budget_limit: Decimal = Decimal(10000)
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


class QueryPlanRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    catalog_version: str = "2024-07"
    estimated_cost: Decimal = Decimal(0)
    budget_limit: Decimal = Decimal(10000)


class ExecutePlanRequest(BaseModel):
    page_size: int = Field(default=100, ge=1, le=500)
    cursor: str | None = None


TRUSTED_QUERY_TEMPLATES: dict[str, str] = {
    "cost-breakdown": (
        "SELECT source_id, currency, unit, amount, watermark, raw_ref "
        "FROM billing_line_item"
    ),
    "trend": (
        "SELECT source_id, currency, unit, amount, watermark, raw_ref "
        "FROM billing_line_item"
    ),
    "anomaly": (
        "SELECT source_id, currency, unit, amount, watermark, raw_ref "
        "FROM billing_line_item"
    ),
    "cost-spike": (
        "SELECT source_id, currency, unit, amount, watermark, raw_ref "
        "FROM billing_line_item"
    ),
}


def _plan_kind(question: str) -> str:
    if os.getenv("FINOPS_AGENT_MODE", "offline").lower() == "live":
        intent = RealIntentModel().generate(question, CATALOG)
        if intent.catalog_version != CATALOG.version:
            raise HTTPException(
                status_code=422, detail={"error": "catalog_version_mismatch"}
            )
        return intent.kind
    normalized = question.lower()
    if "趋势" in question or "trend" in normalized or "monthly" in normalized:
        return "trend"
    if "异常" in question or "anomaly" in normalized or "spike" in normalized:
        return "anomaly"
    return "cost-breakdown"


@app.post("/query-plans", status_code=status.HTTP_201_CREATED)
def create_query_plan(
    payload: QueryPlanRequest,
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(
            x_tenant_id,
            x_role,
            x_request_id,
            x_identity_signature,
            x_identity_timestamp,
        )
    except ForbiddenIdentity as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "forbidden_identity", "message": str(exc)},
        ) from exc
    try:
        kind = _plan_kind(payload.question)
    except ModelUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail={"error": "model_blocked", "message": str(exc)}
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502, detail={"error": "model_failed", "message": str(exc)}
        ) from exc
    statement = TRUSTED_QUERY_TEMPLATES[kind]
    ast = AstGuard().execute(
        AstInput(statement=statement, allowed_resources=["billing_line_item"])
    )
    if not ast.allowed:
        raise HTTPException(
            status_code=500,
            detail={"error": "trusted_template_invalid", "violations": ast.violations},
        )
    budget = BudgetContext().execute(
        BudgetInput(
            estimated_cost=payload.estimated_cost, budget_limit=payload.budget_limit
        )
    )
    if budget.state == "rejected":
        raise HTTPException(
            status_code=402,
            detail={"error": "budget_rejected", "audit": budget.audit},
        )
    plan_id = repos.next_id("plan")
    expires_at = int(time.time()) + 300
    repos.query_run.put(
        Record(
            id=plan_id,
            # The request ID is the caller's idempotency scope. Without it,
            # simultaneous clients asking the same question receive an ID that
            # was never persisted when the repository de-duplicates the row.
            idempotency_key=Repositories.idempotency_key(
                "plan",
                identity.tenant_id,
                identity.request_id,
                payload.question,
                payload.catalog_version,
            ),
            payload={
                "tenant_id": identity.tenant_id,
                "kind": kind,
                "question": payload.question,
                "statement": statement,
                "allowed_resources": ["billing_line_item"],
                "catalog_version": payload.catalog_version,
                "estimated_cost": str(payload.estimated_cost),
                "budget_limit": str(payload.budget_limit),
                "status": "planned",
                "expires_at": expires_at,
            },
        )
    )
    return envelope(
        {
            "plan_id": plan_id,
            "kind": kind,
            "statement": statement,
            "ast_allowed": True,
            "estimated_cost": str(payload.estimated_cost),
            "budget_limit": str(payload.budget_limit),
            "status": "planned",
            "expires_at": expires_at,
        },
        correlation_id=identity.request_id,
    )


@app.post("/query-plans/{plan_id}/execute", status_code=status.HTTP_201_CREATED)
def execute_query_plan(
    plan_id: str,
    payload: ExecutePlanRequest,
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(
            x_tenant_id,
            x_role,
            x_request_id,
            x_identity_signature,
            x_identity_timestamp,
        )
    except ForbiddenIdentity as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "forbidden_identity", "message": str(exc)},
        ) from exc
    plan = repos.query_run.get(plan_id)
    if plan is None or plan.payload.get("tenant_id") != identity.tenant_id:
        raise HTTPException(status_code=404, detail={"error": "plan_not_found"})
    if plan.payload.get("status") != "planned":
        raise HTTPException(status_code=409, detail={"error": "plan_not_executable"})
    if int(plan.payload.get("expires_at", 0)) < int(time.time()):
        plan.payload["status"] = "expired"
        raise HTTPException(status_code=409, detail={"error": "plan_expired"})
    query_payload = QueryRequest(
        statement=str(plan.payload["statement"]),
        params={},
        page_size=payload.page_size,
        cursor=payload.cursor,
        catalog_version=str(plan.payload["catalog_version"]),
        estimated_cost=Decimal(str(plan.payload["estimated_cost"])),
        budget_limit=Decimal(str(plan.payload["budget_limit"])),
        allowed_resources=list(plan.payload["allowed_resources"]),
    )
    result = create_query(
        query_payload,
        x_tenant_id,
        x_role,
        x_request_id,
        x_identity_signature,
        x_identity_timestamp,
    )
    plan.payload["status"] = "completed"
    plan.payload["execution_query_id"] = result["result"]["query_id"]
    result["result"]["status"] = "completed"
    return result


@app.get("/dashboard")
def dashboard(
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(
            x_tenant_id,
            x_role,
            x_request_id,
            x_identity_signature,
            x_identity_timestamp,
        )
    except ForbiddenIdentity as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "forbidden_identity", "message": str(exc)},
        ) from exc
    billing = [
        record
        for record in repos.billing_line_item.all()
        if record.payload.get("tenant_id") == identity.tenant_id
    ]
    runs = [
        record
        for record in repos.query_run.all()
        if record.payload.get("tenant_id") == identity.tenant_id
        and not record.id.startswith("plan-")
    ]
    findings = [
        record
        for record in repos.anomaly_finding.all()
        if record.payload.get("tenant_id") == identity.tenant_id
        and record.payload.get("status", "open") != "closed"
    ]
    tickets = [
        record
        for record in repos.governance_ticket.all()
        if record.payload.get("tenant_id") == identity.tenant_id
    ]
    total = sum((Decimal(str(record.payload.get("amount", 0))) for record in billing), Decimal(0))
    return envelope(
        {
            "billing_lines": len(billing),
            "total_amount": f"{total:.2f}",
            "query_runs": len(runs),
            "open_findings": len(findings),
            "tickets": len(tickets),
        },
        correlation_id=identity.request_id,
    )


@app.get("/billing-ingestions")
def list_billing_ingestions(
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(
            x_tenant_id,
            x_role,
            x_request_id,
            x_identity_signature,
            x_identity_timestamp,
        )
    except ForbiddenIdentity as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "forbidden_identity", "message": str(exc)},
        ) from exc
    items = [
        {"billing_line_id": record.id, **record.payload}
        for record in repos.billing_line_item.all()
        if record.payload.get("tenant_id") == identity.tenant_id
    ]
    return envelope(
        {"items": items, "total": len(items)}, correlation_id=identity.request_id
    )


@app.get("/queries")
def list_queries(
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(
            x_tenant_id,
            x_role,
            x_request_id,
            x_identity_signature,
            x_identity_timestamp,
        )
    except ForbiddenIdentity as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "forbidden_identity", "message": str(exc)},
        ) from exc
    items = [
        {"query_id": record.id, **record.payload}
        for record in repos.query_run.all()
        if record.payload.get("tenant_id") == identity.tenant_id
        and not record.id.startswith("plan-")
    ]
    return envelope(
        {"items": items, "total": len(items)}, correlation_id=identity.request_id
    )


@app.get("/queries/{query_id}")
def query_detail(
    query_id: str,
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(
            x_tenant_id,
            x_role,
            x_request_id,
            x_identity_signature,
            x_identity_timestamp,
        )
    except ForbiddenIdentity as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "forbidden_identity", "message": str(exc)},
        ) from exc
    record = repos.query_run.get(query_id)
    if record is None or record.payload.get("tenant_id") != identity.tenant_id:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return envelope(
        {"query_id": record.id, **record.payload}, correlation_id=identity.request_id
    )


@app.get("/findings")
def list_findings(
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(
            x_tenant_id,
            x_role,
            x_request_id,
            x_identity_signature,
            x_identity_timestamp,
        )
    except ForbiddenIdentity as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "forbidden_identity", "message": str(exc)},
        ) from exc
    items = [
        {"finding_id": record.id, **record.payload}
        for record in repos.anomaly_finding.all()
        if record.payload.get("tenant_id") == identity.tenant_id
    ]
    return envelope(
        {"items": items, "total": len(items)}, correlation_id=identity.request_id
    )


@app.get("/tickets")
def list_tickets(
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(
            x_tenant_id,
            x_role,
            x_request_id,
            x_identity_signature,
            x_identity_timestamp,
        )
    except ForbiddenIdentity as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "forbidden_identity", "message": str(exc)},
        ) from exc
    items = [
        {"ticket_id": record.id, **record.payload}
        for record in repos.governance_ticket.all()
        if record.payload.get("tenant_id") == identity.tenant_id
    ]
    return envelope(
        {"items": items, "total": len(items)}, correlation_id=identity.request_id
    )


@app.get("/recovery-status")
def recovery_status(
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(
            x_tenant_id,
            x_role,
            x_request_id,
            x_identity_signature,
            x_identity_timestamp,
        )
    except ForbiddenIdentity as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "forbidden_identity", "message": str(exc)},
        ) from exc
    unknown_queries = sum(
        1
        for record in repos.query_run.all()
        if record.payload.get("tenant_id") == identity.tenant_id
        and str(record.payload.get("status", "")).lower() == "unknown"
    )
    unknown_tickets = sum(
        1
        for record in repos.governance_ticket.all()
        if record.payload.get("tenant_id") == identity.tenant_id
        and str(record.payload.get("status", "")).lower() == "unknown"
    )
    return envelope(
        {
            "unknown_queries": unknown_queries,
            "unknown_tickets": unknown_tickets,
            "requires_reconciliation": unknown_queries + unknown_tickets > 0,
        },
        correlation_id=identity.request_id,
    )


# ---------------------------------------------------------------------------
# POST /billing-ingestions
# ---------------------------------------------------------------------------


@app.post("/billing-ingestions", status_code=status.HTTP_201_CREATED)
def billing_ingestions(
    payload: BillingIngestionRequest,
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(x_tenant_id, x_role, x_request_id, x_identity_signature, x_identity_timestamp)
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
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(x_tenant_id, x_role, x_request_id, x_identity_signature, x_identity_timestamp)
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
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    """返回某查询生命周期的可观测 span 列表（FO-10 可观测性）。"""
    try:
        identity = resolve_identity(x_tenant_id, x_role, x_request_id, x_identity_signature, x_identity_timestamp)
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
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(x_tenant_id, x_role, x_request_id, x_identity_signature, x_identity_timestamp)
    except ForbiddenIdentity as exc:
        raise HTTPException(status_code=400, detail={"error": "forbidden_identity", "message": str(exc)})
    record = repos.query_run.get(query_id)
    if not record:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "query_id not found"})
    if record.payload.get("tenant_id") != identity.tenant_id:
        raise HTTPException(status_code=403, detail={"error": "cross_tenant_denied"})
    # 取消语义：经恢复账本的 cancelled 路径幂等推进，再标记 run。
    current_status = str(record.payload.get("status", "completed"))
    if current_status != "running":
        raise HTTPException(
            status_code=409,
            detail={"error": "query_not_running", "status": current_status},
        )
    from app.finops.recovery.ledger import FO10Input as RecoverInput
    from app.finops.recovery.ledger import IdentityContext as RecoverContext

    RecoverContext().execute(RecoverInput(items=[{"effect_id": query_id, "status": "cancelled"}]))
    record.payload["status"] = "cancelled"
    repos.query_run.put(record)
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
    x_identity_signature: str | None = Header(default=None),
    x_identity_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        identity = resolve_identity(x_tenant_id, x_role, x_request_id, x_identity_signature, x_identity_timestamp)
    except ForbiddenIdentity as exc:
        raise HTTPException(status_code=400, detail={"error": "forbidden_identity", "message": str(exc)})
    finding_record = repos.anomaly_finding.get(finding_id)
    if (
        not finding_record
        or finding_record.payload.get("tenant_id") != identity.tenant_id
    ):
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
            idempotency_key=Repositories.idempotency_key(
                "ticket", identity.tenant_id, finding_id
            ),
            payload={
                "tenant_id": identity.tenant_id,
                "finding_id": finding_id,
                "status": result.status,
            },
        )
    )
    return envelope(
        {"ticket_id": result.ticket.ticket_id if result.ticket else None, "finding_id": finding_id, "status": result.status},
        correlation_id=identity.request_id,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
