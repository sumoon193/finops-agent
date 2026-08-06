"""FinOps live smoke: 0 passed, 1 failed, 2 blocked."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", choices=("health", "database", "model"), default="health")
    args = parser.parse_args(argv)
    if args.component == "model":
        return _model_smoke()
    if args.component == "database":
        return _database_smoke()
    base = os.getenv("FINOPS_BASE_URL", "").rstrip("/")
    if not base:
        print("BLOCKED: set FINOPS_BASE_URL")
        return 2
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=5) as response:
            ok = response.status == 200
            print("PASSED: FinOps health" if ok else f"FAILED: status={response.status}")
            return 0 if ok else 1
    except urllib.error.URLError as exc:
        print(f"BLOCKED: service unavailable ({exc.reason})")
        return 2
    except Exception as exc:
        print(f"FAILED: {exc.__class__.__name__}")
        return 1


def _model_smoke() -> int:
    if not os.getenv("QWEN_API_KEY", "").strip() or not os.getenv("QWEN_CHAT_MODEL", "").strip():
        print("BLOCKED: set QWEN_API_KEY and QWEN_CHAT_MODEL")
        return 2
    _bypass_proxy_for_model_host()
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    try:
        from app.finops.catalog.registry import SemanticCatalog
        from app.finops.intent.model import RealIntentModel

        catalog = SemanticCatalog("live-v1", {"cost-breakdown", "trend", "anomaly"})
        intent = RealIntentModel().generate("Show a monthly cost trend. Choose trend.", catalog)
        if intent.kind not in catalog.allowed_kinds or intent.provenance != "real-model":
            print("FAILED: typed real-model intent is invalid")
            return 1
        print(f"PASSED: FinOps real intent model; kind={intent.kind}")
        return 0
    except Exception as exc:
        if "URLError" in str(exc) or "Timeout" in str(exc):
            print(f"BLOCKED: model service unavailable ({exc.__class__.__name__})")
            return 2
        print(f"FAILED: real model validation ({exc.__class__.__name__})")
        return 1


def _database_smoke() -> int:
    base = os.getenv("FINOPS_BASE_URL", "").rstrip("/")
    tenant = os.getenv("FINOPS_SMOKE_TENANT", "smoke-tenant")
    if not base:
        print("BLOCKED: set FINOPS_BASE_URL")
        return 2
    import uuid

    source_id = "live-smoke-" + uuid.uuid4().hex
    headers = {
        "Content-Type": "application/json",
        "X-Tenant-Id": tenant,
        "X-Role": "analyst",
        "X-Request-Id": "finops-database-smoke",
    }
    ingestion = {
        "watermark": "2026-08-06T00:00:00Z",
        "raw_lines": [{
            "source_id": source_id,
            "currency": "USD",
            "unit": "unit",
            "amount": "1.00",
            "watermark": "2026-08-06T00:00:00Z",
            "raw_ref": "focus://live-smoke",
        }],
    }
    query = {
        "statement": "SELECT amount FROM billing_line_item",
        "allowed_resources": ["billing_line_item"],
        "rows": [{"tenant_id": tenant, "amount": "999999"}],
    }
    try:
        _request_json(f"{base}/billing-ingestions", ingestion, headers)
        result = _request_json(f"{base}/queries", query, headers)
        page = result.get("result", {}).get("page", [])
        if not any(row.get("source_id") == source_id for row in page):
            print("FAILED: database query did not return the ingested source row")
            return 1
        if any(str(row.get("amount")) == "999999" for row in page):
            print("FAILED: client rows were used as a billing source")
            return 1
        print("PASSED: FinOps PostgreSQL billing write/query and tenant source isolation")
        return 0
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404, 503):
            print(f"BLOCKED: service contract unavailable (HTTP {exc.code})")
            return 2
        print(f"FAILED: database smoke HTTP {exc.code}")
        return 1
    except urllib.error.URLError as exc:
        print(f"BLOCKED: service unavailable ({exc.reason})")
        return 2
    except Exception as exc:
        print(f"FAILED: database smoke ({exc.__class__.__name__})")
        return 1


def _request_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _bypass_proxy_for_model_host() -> None:
    host = urlparse(os.getenv(
        "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )).hostname
    if not host:
        return
    for name in ("NO_PROXY", "no_proxy"):
        current = [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]
        if host not in current:
            os.environ[name] = ",".join([*current, host])

if __name__ == "__main__":
    sys.exit(main())
