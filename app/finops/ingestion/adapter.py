"""来源适配器：读取一条来源的账单行并规范化为 FOCUS canonical，保留来源可追溯。"""

from __future__ import annotations

from typing import Any

from app.finops.focus.canonical import BillingLineItem, normalize_line


class FocusAdapter:
    """按来源绑定读取原始行并规范化，防止跨来源串行。"""

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id

    def read_line(self, raw: dict[str, Any]) -> BillingLineItem:
        item = normalize_line(raw)
        if item.source_id != self.source_id:
            raise ValueError("source_id mismatch")
        return item
