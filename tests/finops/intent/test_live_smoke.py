import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "finops" / "live_smoke.py"


def _module():
    spec = importlib.util.spec_from_file_location("finops_live_smoke", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_smoke_is_blocked_without_real_credentials(monkeypatch):
    module = _module()
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_CHAT_MODEL", raising=False)

    assert module.main(["--component", "model"]) == 2


def test_database_smoke_verifies_cross_tenant_rows_are_not_visible(monkeypatch):
    module = _module()
    monkeypatch.setenv("FINOPS_BASE_URL", "http://finops.test")
    monkeypatch.setenv("FINOPS_IDENTITY_MODE", "signed")
    monkeypatch.setenv("FINOPS_IDENTITY_SECRET", "smoke-signing-secret")
    ingested: dict[str, str] = {}
    calls: list[tuple[str, dict, dict]] = []

    def request_json(url, payload, headers):
        calls.append((url, payload, headers))
        tenant = headers["X-Tenant-Id"]
        if url.endswith("/billing-ingestions"):
            ingested[tenant] = payload["raw_lines"][0]["source_id"]
            return {"result": {"ingested": 1}}
        return {
            "result": {
                "page": [{"source_id": ingested["smoke-tenant"], "amount": "1.00"}]
            }
        }

    monkeypatch.setattr(module, "_request_json", request_json)

    assert module.main(["--component", "database"]) == 0
    assert set(ingested) == {"smoke-tenant", "smoke-tenant-other"}
    assert len(set(ingested.values())) == 1
    assert len(calls) == 3
    assert all(call[2].get("X-Identity-Signature") for call in calls)
    assert all(call[2].get("X-Identity-Timestamp") for call in calls)
