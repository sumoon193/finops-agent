"""FOCUS canonical 模型：账单规范化保留来源、货币、单位和 watermark。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

REQUIRED_FIELDS = ("source_id", "currency", "unit", "amount", "watermark")
CURRENCY_ALIASES = {"usd": "USD", "eur": "EUR", "cny": "CNY", "aud": "AUD", "gbp": "GBP"}
UNIT_ALIASES = {"kwh": "kWh", "kw": "kW", "mwh": "MWh", "gb": "GB", "gb-mo": "GB-Mo"}


def _canonical_currency(value: str) -> str:
    code = CURRENCY_ALIASES.get(value.strip().lower(), value.strip().upper())
    if len(code) != 3 or not code.isalpha():
        raise ValueError(f"invalid currency: {value}")
    return code


def _canonical_unit(value: str) -> str:
    return UNIT_ALIASES.get(value.strip().lower(), value.strip())


@dataclass(frozen=True)
class BillingLineItem:
    source_id: str
    currency: str
    unit: str
    amount: Decimal
    watermark: str
    raw_ref: str


def normalize_line(raw: dict[str, Any]) -> BillingLineItem:
    missing = [name for name in REQUIRED_FIELDS if not str(raw.get(name, "")).strip()]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")
    return BillingLineItem(
        source_id=str(raw["source_id"]).strip(),
        currency=_canonical_currency(str(raw["currency"])),
        unit=_canonical_unit(str(raw["unit"])),
        amount=Decimal(str(raw["amount"])),
        watermark=str(raw["watermark"]).strip(),
        raw_ref=str(raw.get("raw_ref", "")).strip(),
    )


@dataclass
class FO02Input:
    raw_lines: list[dict[str, Any]]
    watermark: str


@dataclass
class FO02Result:
    items: list[BillingLineItem] = field(default_factory=list)
    watermark: str = ""
    state_events: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


class QueryIntent:
    """把原始账单行规范化为 FOCUS canonical 行，输出状态事件与审计信息。"""

    def execute(self, input: FO02Input) -> FO02Result:
        items = [normalize_line(raw) for raw in input.raw_lines]
        return FO02Result(
            items=items,
            watermark=input.watermark,
            state_events=["planned", "completed"],
            audit={
                "source_ids": [item.source_id for item in items],
                "watermark": input.watermark,
                "line_count": len(items),
            },
        )
