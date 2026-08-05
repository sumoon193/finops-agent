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
