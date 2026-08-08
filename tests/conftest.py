"""Windows 兼容的测试临时目录。"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

_RUNTIME_TEST_FILES = Path(__file__).resolve().parents[1] / "runtime_test_files"


@pytest.fixture()
def tmp_path() -> Path:
    """使用继承仓库 ACL 的目录，避免系统 TEMP 的 0700 权限映射问题。"""
    _RUNTIME_TEST_FILES.mkdir(parents=True, exist_ok=True)
    path = _RUNTIME_TEST_FILES / f"case_{uuid.uuid4().hex[:12]}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
