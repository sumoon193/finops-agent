"""语义目录注册表：绑定版本并校验模型意图。"""

from __future__ import annotations


class SemanticCatalog:
    def __init__(self, version: str, allowed_kinds: set[str]) -> None:
        self.version = version
        self.allowed_kinds = set(allowed_kinds)

    def supports(self, version: str) -> bool:
        return version == self.version

    def assert_version(self, version: str) -> None:
        if not self.supports(version):
            raise ValueError(f"unsupported catalog version: {version}")

    def assert_kind(self, kind: str) -> None:
        if kind not in self.allowed_kinds:
            raise ValueError(f"invalid intent kind: {kind}")
