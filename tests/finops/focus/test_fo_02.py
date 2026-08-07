"""FO-02 FOCUS canonical 摄取：账单规范化保留来源、货币、单位和 watermark。"""

import pytest

from app.finops.focus.canonical import (
    FO02Input,
    FO02Result,
    QueryIntent,
    normalize_line,
)

RAW = {
    "source_id": "aws-billing-2024-01",
    "currency": "usd",
    "unit": "KWH",
    "amount": "120.50",
    "watermark": "2024-01-31T23:59:59Z",
    "raw_ref": "s3://bucket/line/0001",
}


def test_normalization_preserves_source_currency_unit_watermark():
    item = normalize_line(RAW)
    assert item.source_id == "aws-billing-2024-01"
    assert item.currency == "USD"
    assert item.unit == "kWh"
    assert item.watermark == "2024-01-31T23:59:59Z"
    assert item.raw_ref == "s3://bucket/line/0001"


def test_query_intent_returns_typed_result_with_state_events_and_audit():
    result = QueryIntent().execute(
        FO02Input(raw_lines=[RAW], watermark="2024-01-31T23:59:59Z")
    )
    assert isinstance(result, FO02Result)
    assert result.items and all(i.source_id == RAW["source_id"] for i in result.items)
    assert "planned" in result.state_events and "completed" in result.state_events
    assert result.audit["source_ids"] == [RAW["source_id"]]
    assert result.audit["watermark"] == RAW["watermark"]


def test_result_preserves_input_watermark():
    result = QueryIntent().execute(
        FO02Input(raw_lines=[RAW], watermark="2024-02-28T23:59:59Z")
    )
    assert result.watermark == "2024-02-28T23:59:59Z"


def test_invalid_input_fails_stably():
    broken = dict(RAW)
    del broken["currency"]
    with pytest.raises(ValueError):
        normalize_line(broken)
