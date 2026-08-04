"""FO-13 检索消融与发布审计：检索收益、发布门槛和未验证项有真实性报告。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "docs" / "finops" / "audit" / "ablation-report.md"


def _load() -> str:
    return REPORT.read_text(encoding="utf-8")


def test_report_documents_retrieval_gain_release_gates_and_unverified():
    report = _load()
    assert "检索收益" in report
    assert "发布门槛" in report
    assert "未验证项" in report


def test_unverified_items_are_marked_not_claimed_verified():
    report = _load()
    assert "unverified" in report
    for token in ("真实模型", "真实数据库", "远端分支保护"):
        assert token in report, token
    # Model gain must be declared unverified, never positively claimed verified.
    assert "模型收益未验证" in report


def test_report_references_frozen_set_and_method():
    report = _load()
    assert "冻结集" in report
    assert "方法" in report


def test_retrieval_gain_is_tied_to_frozen_set_not_fabricated():
    report = _load()
    assert "消融" in report
    assert "基线" in report
