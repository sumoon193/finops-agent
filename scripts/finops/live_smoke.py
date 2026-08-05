"""FinOps live smoke: 0 passed, 1 failed, 2 blocked."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", choices=("health", "model"), default="health")
    args = parser.parse_args(argv)
    if args.component == "model":
        return _model_smoke()
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
