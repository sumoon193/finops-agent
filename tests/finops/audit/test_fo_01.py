"""FO-01 来源、范围与许可证：账单、目录和模型/数据来源可追溯。"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AUDIT_DIR = ROOT / "docs" / "audit"

REQUIRED_SOURCE_FAMILIES = {"billing", "catalog", "model"}
ALLOWED_STATUSES = {"active", "pending", "blocked"}

PROVENANCE_FIELDS = (
    "source_id",
    "source_family",
    "source_name",
    "origin",
    "license",
    "version",
    "status",
    "evidence_pointer",
)


def _load_registry() -> dict:
    return json.loads((AUDIT_DIR / "source-registry.json").read_text(encoding="utf-8"))


def test_source_registry_exists_and_covers_all_families():
    registry = _load_registry()
    assert registry["project_id"] == "finops-agent"
    assert registry["module"] == "FO-01"
    sources = registry["sources"]
    assert isinstance(sources, list) and sources
    families = {entry["source_family"] for entry in sources}
    assert REQUIRED_SOURCE_FAMILIES <= families


def test_every_source_is_traceable():
    for entry in _load_registry()["sources"]:
        for field in PROVENANCE_FIELDS:
            assert entry.get(field), f"{entry.get('source_id')} missing {field}"
        assert entry["status"] in ALLOWED_STATUSES, entry
        assert entry["evidence_pointer"], entry


def test_license_document_attributes_every_source():
    license_text = (AUDIT_DIR / "license.md").read_text(encoding="utf-8")
    for entry in _load_registry()["sources"]:
        assert entry["license"] in license_text, entry["source_id"]


def test_scope_document_declares_boundary_and_non_goals():
    scope_text = (AUDIT_DIR / "scope.md").read_text(encoding="utf-8")
    for token in (
        "FO-01",
        "docs/audit",
        "tests/finops/audit",
        "不修改任务白名单外模块",
        "不生成学习、面试、简历和项目总结文档",
        "不执行 merge 或 force-push",
    ):
        assert token in scope_text, token
