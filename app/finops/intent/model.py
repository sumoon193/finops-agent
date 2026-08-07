"""模型意图：把模型原始输出解析为绑定语义目录版本的 typed intent。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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


class ModelUnavailableError(RuntimeError):
    """Real intent parsing is blocked until explicit model credentials exist."""


class RealIntentModel:
    """OpenAI-compatible model adapter that returns a typed intent object."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        self.api_key = (api_key or os.getenv("QWEN_API_KEY", "")).strip()
        self.model = model or os.getenv("QWEN_CHAT_MODEL", "")
        self.base_url = (base_url or os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")).rstrip("/")
        if not self.api_key or not self.model:
            raise ModelUnavailableError("QWEN_API_KEY and QWEN_CHAT_MODEL are required")

    def generate(self, question: str, catalog: SemanticCatalog) -> Intent:
        payload = json.dumps({
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{
                "role": "user",
                "content": f"Return JSON with kind and params for: {question}. Allowed kinds: {sorted(catalog.allowed_kinds)}",
            }],
        }).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"intent model request failed: {exc.__class__.__name__}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            kind = str(parsed["kind"])
            params = dict(parsed.get("params", {}))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("intent model response is invalid") from exc
        catalog.assert_kind(kind)
        return Intent(kind=kind, params=params, catalog_version=catalog.version, provenance="real-model")
