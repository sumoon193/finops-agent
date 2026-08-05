"""FinOps Agent 公开工程文档合同。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECTIONS = ["项目简介", "核心能力", "技术栈与架构", "本地启动", "主要 API", "离线测试", "真实服务验证", "安全与使用边界", "License"]
FORBIDDEN = ("面试", "简历", "履历", "问答话术", "学习材料", "完成证明", "Fake")


def test_readme_is_chinese_and_matches_runtime_contract() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert [line[3:].strip() for line in text.splitlines() if line.startswith("## ")] == SECTIONS
    for fragment in ("FastAPI", "Python 3.12", "http://127.0.0.1:8002", "/billing-ingestions", "/queries", "/findings/{finding_id}/tickets", "X-Tenant-Id", "FINOPS_BASE_URL", "QWEN_API_KEY", "QWEN_CHAT_MODEL", "live_smoke.py", "退出码 `0`", "退出码 `1`", "退出码 `2`"):
        assert fragment in text, fragment
    assert not re.search(r"[銆锛鈥�]", text)
    assert all(term.casefold() not in text.casefold() for term in FORBIDDEN)


def test_readme_links_resolve() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "#")):
            continue
        assert (ROOT / target.split("#", 1)[0]).exists(), target


def test_current_entries_keep_engineering_materials_only() -> None:
    expected = "仅保留工程实施、验证和运维资料"
    for path in (ROOT / "AGENTS.md", ROOT / ".agent-governance" / "AGENT-ENTRY.md"):
        text = path.read_text(encoding="utf-8")
        assert expected in text
        assert not any(term in text for term in FORBIDDEN[:-1])
