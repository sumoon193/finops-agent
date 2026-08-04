"""模型意图：把模型原始输出解析为绑定语义目录版本的 typed intent。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.finops.catalog.registry import SemanticCatalog


@dataclass(frozen=True)
class Intent:
    kind: str
    params: dict[str, Any]
    catalog_version: str
    provenance: str = "model-output"


@dataclass
class FO04Input:
    raw: dict[str, Any]
    catalog_version: str


@dataclass
class FO04Result:
    intent: Intent | None = None
    state_events: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


class IdentityContext:
    def __init__(self, catalog: SemanticCatalog, role: str = "analyst") -> None:
        self.catalog = catalog
        self.role = role

    def execute(self, input: FO04Input) -> FO04Result:
        self.catalog.assert_version(input.catalog_version)
        kind = str(input.raw.get("kind", "")).strip()
        self.catalog.assert_kind(kind)
        intent = Intent(
            kind=kind,
            params=dict(input.raw.get("params", {})),
            catalog_version=input.catalog_version,
        )
        return FO04Result(
            intent=intent,
            state_events=["planned", "completed"],
            audit={"role": self.role, "catalog_version": input.catalog_version},
        )
