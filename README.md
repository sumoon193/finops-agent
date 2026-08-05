# FinOps Agent

FinOps Agent is a typed FastAPI service for trusted billing ingestion,
tenant-isolated cost queries, read-only planning, budget enforcement,
provenance, anomaly findings, governance tickets and recovery.

## Implemented capabilities

- Trusted billing-source adapter boundary; production requests cannot submit
  arbitrary billing rows as the data source.
- Server-owned tenant identity, RLS contracts and cross-tenant isolation.
- Typed model intent constrained by the semantic catalog.
- Read-only AST validation that the model cannot bypass.
- Query budgets, timeouts, cancellation, CAS state transitions and pagination.
- Result provenance, cache keys, audit trails and UNKNOWN reconciliation.
- Anomaly attribution and idempotent governance-ticket adapters.
- Persistent schema and rollback/recovery contracts.

## Run locally

```powershell
Set-Location "D:\Code\agent study\managed-projects\finops-agent"
& "D:\py\py3.12\python.exe" -m uvicorn app.finops.api:app `
  --host 127.0.0.1 --port 8002
```

Open:

- API documentation: <http://127.0.0.1:8002/docs>
- Health: <http://127.0.0.1:8002/health>

Business endpoints use the trusted `X-Tenant-Id` header. Swagger UI supports
interactive request bodies and headers.

## Main APIs

- `POST /billing-ingestions`
- `POST /queries`
- `DELETE /queries/{query_id}`
- `POST /findings/{finding_id}/tickets`
- `GET /health`

## Offline verification

```powershell
Set-Location "D:\Code\agent study\managed-projects\finops-agent"
& "D:\py\py3.12\python.exe" -m pytest -q
```

## Live verification

```powershell
$env:FINOPS_BASE_URL = "http://127.0.0.1:8002"

& "D:\py\py3.12\python.exe" ".\scripts\finops\live_smoke.py" --component health
& "D:\py\py3.12\python.exe" ".\scripts\finops\live_smoke.py" --component model
```

`QWEN_API_KEY` and `QWEN_CHAT_MODEL` are required only for the real intent-model
smoke. Offline tests remain network-free.

## Live-smoke exit codes

- `0`: real verification passed.
- `1`: connected, but validation failed.
- `2`: blocked by missing credentials, authorization or service availability.

## Security and authenticity

The model can propose typed intent but cannot bypass tenant authorization,
semantic-catalog constraints or AST validation. Fake sources are explicit
offline adapters and are never reported as real billing acceptance.

## Governance

Development follows `AGENTS.md`, `.agent-governance/`, contract migrations and
the active integration handoff.

## License

MIT. See [LICENSE](LICENSE).
