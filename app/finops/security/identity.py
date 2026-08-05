"""服务端身份：由服务端构造，客户端或模型不可覆盖。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IdentityContext:
    tenant_id: str
    role: str = "analyst"
