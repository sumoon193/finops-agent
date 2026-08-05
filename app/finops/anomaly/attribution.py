"""异常归因：对查询结果归因出可操作的 AnomalyFinding。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnomalyFinding:
    finding_id: str
    query_id: str
    kind: str
    severity: str
    detail: str
