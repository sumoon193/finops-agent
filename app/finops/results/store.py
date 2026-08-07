"""结果存储与缓存：键绑定 RLS/语义/watermark，结果携带可追溯血缘。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FO08Input:
    query_hash: str
    tenant_id: str
    semantic_version: str
    watermark: str
    compute: Callable[[], Any]


@dataclass
class ResultArtifact:
    query_hash: str
    value: Any
    provenance: list[str] = field(default_factory=list)
    cache_status: str = "computed"


@dataclass
class FO08Result:
    artifact: ResultArtifact
    state_events: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


class ResultCache:
    """以 (tenant, semantic, watermark, query) 复合键隔离的结果缓存。"""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str, str, str], Any] = {}

    @staticmethod
    def key(
        tenant_id: str, semantic_version: str, watermark: str, query_hash: str
    ) -> tuple[str, str, str, str]:
        return (tenant_id, semantic_version, watermark, query_hash)

    def contains(self, input: FO08Input) -> bool:
        return self.key(
            input.tenant_id, input.semantic_version, input.watermark, input.query_hash
        ) in self._store

    def get(self, input: FO08Input) -> Any:
        return self._store[
            self.key(
                input.tenant_id, input.semantic_version, input.watermark, input.query_hash
            )
        ]

    def put(self, input: FO08Input, value: Any) -> None:
        self._store[
            self.key(
                input.tenant_id, input.semantic_version, input.watermark, input.query_hash
            )
        ] = value


class QueryIntent:
    def __init__(self, cache: ResultCache | None = None) -> None:
        self.cache = cache or ResultCache()

    def execute(self, input: FO08Input) -> FO08Result:
        if self.cache.contains(input):
            value = self.cache.get(input)
            status = "cache-hit"
            provenance = [
                f"tenant:{input.tenant_id}",
                f"semantic:{input.semantic_version}",
                f"watermark:{input.watermark}",
                f"query:{input.query_hash}",
                "source:cache-hit",
            ]
        else:
            value = input.compute()
            self.cache.put(input, value)
            status = "computed"
            provenance = [
                f"tenant:{input.tenant_id}",
                f"semantic:{input.semantic_version}",
                f"watermark:{input.watermark}",
                f"query:{input.query_hash}",
                "source:computed",
            ]
        artifact = ResultArtifact(
            query_hash=input.query_hash,
            value=value,
            provenance=provenance,
            cache_status=status,
        )
        return FO08Result(
            artifact=artifact,
            state_events=["planned", "completed"],
            audit={"cache_status": status},
        )
