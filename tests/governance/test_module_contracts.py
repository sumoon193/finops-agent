"""项目模块契约的跨模块静态门禁。"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_module_contract_is_complete_and_acyclic():
    contract = json.loads((ROOT / ".agent-governance" / "module-contracts.json").read_text(encoding="utf-8"))
    modules = {item["module_id"]: item for item in contract["modules"]}
    assert modules
    for module_id, module in modules.items():
        assert re.fullmatch(r"[A-Z]{2}-[0-9]{2}", module_id)
        for field in ("source_paths", "test_paths", "interface_signatures", "data_tables", "api_contracts", "state_machine", "observable_result", "failure_test", "regression_command"):
            assert module[field], f"{module_id} missing {field}"
        assert set(module["dependencies"]) <= modules.keys()
    visiting, visited = set(), set()
    def visit(module_id):
        assert module_id not in visiting, f"cycle at {module_id}"
        if module_id in visited:
            return
        visiting.add(module_id)
        for dependency in modules[module_id]["dependencies"]:
            visit(dependency)
        visiting.remove(module_id)
        visited.add(module_id)
    for module_id in modules:
        visit(module_id)

def test_cross_module_invariants_cover_security_recovery_and_evidence():
    contract = json.loads((ROOT / ".agent-governance" / "module-contracts.json").read_text(encoding="utf-8"))
    combined = "\n".join(contract["cross_module_invariants"])
    for term in ("身份", "副作用", "状态", "Fake", "citation", "学习"):
        assert term in combined
