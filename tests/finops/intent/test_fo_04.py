"""FO-04 Intent、模型与语义目录：模型输出 typed intent 且绑定语义目录版本。"""

import pytest

from app.finops.catalog.registry import SemanticCatalog
from app.finops.intent.model import FO04Input, FO04Result, IdentityContext, Intent

CATALOG = SemanticCatalog(
    version="2024-07", allowed_kinds={"cost-breakdown", "trend", "anomaly"}
)


def test_model_output_becomes_typed_intent():
    ctx = IdentityContext(catalog=CATALOG, role="analyst")
    result = ctx.execute(
        FO04Input(
            raw={"kind": "cost-breakdown", "params": {"dimension": "service"}},
            catalog_version="2024-07",
        )
    )
    assert isinstance(result, FO04Result)
    assert isinstance(result.intent, Intent)
    assert result.intent.kind == "cost-breakdown"
    assert result.intent.params == {"dimension": "service"}


def test_intent_binds_semantic_catalog_version():
    ctx = IdentityContext(catalog=CATALOG, role="analyst")
    result = ctx.execute(
        FO04Input(
            raw={"kind": "trend", "params": {"metric": "amount"}},
            catalog_version="2024-07",
        )
    )
    assert result.intent.catalog_version == "2024-07"
    assert CATALOG.supports("2024-07")


def test_unknown_catalog_version_is_rejected_stably():
    ctx = IdentityContext(catalog=CATALOG, role="analyst")
    with pytest.raises(ValueError):
        ctx.execute(
            FO04Input(
                raw={"kind": "trend", "params": {"metric": "amount"}},
                catalog_version="2023-01",
            )
        )


def test_invalid_kind_is_rejected_stably():
    ctx = IdentityContext(catalog=CATALOG, role="analyst")
    with pytest.raises(ValueError):
        ctx.execute(
            FO04Input(raw={"kind": "drop-table", "params": {}}, catalog_version="2024-07")
        )
