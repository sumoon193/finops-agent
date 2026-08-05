"""AST 只读门禁：拒绝 DDL/DML、禁止函数调用和非白名单资源。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DDL_DML = {
    "CREATE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "GRANT",
    "REVOKE",
}
CLAUSE_KEYWORDS = {
    "SELECT",
    "FROM",
    "WHERE",
    "GROUP",
    "BY",
    "ORDER",
    "HAVING",
    "LIMIT",
    "OFFSET",
    "AND",
    "OR",
    "NOT",
    "IN",
    "AS",
    "ON",
    "JOIN",
    "LEFT",
    "RIGHT",
    "INNER",
    "OUTER",
    "CROSS",
    "DISTINCT",
    "TOP",
    "BETWEEN",
    "LIKE",
    "IS",
    "NULL",
    "ASC",
    "DESC",
}
FUNCTION_CALL = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_]*)\s*\(")
FROM_RESOURCE = re.compile(r"(?i)\bfrom\s+([A-Za-z_][A-Za-z0-9_.]*)")
JOIN_RESOURCE = re.compile(r"(?i)\bjoin\s+([A-Za-z_][A-Za-z0-9_.]*)")


@dataclass
class FO05Input:
    statement: str
    allowed_resources: list[str]


@dataclass
class FO05Result:
    allowed: bool = False
    violations: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    state_events: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


class QueryIntent:
    """对只读查询执行 AST 门禁校验，只允许 SELECT 且仅访问白名单资源。"""

    def execute(self, input: FO05Input) -> FO05Result:
        violations: list[str] = []
        upper = input.statement.upper()
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", upper)
        first = tokens[0] if tokens else ""
        if first != "SELECT":
            violations.append("statement must start with SELECT")
        for keyword in sorted(DDL_DML):
            if re.search(rf"\b{keyword}\b", upper):
                violations.append(f"DDL/DML forbidden: {keyword}")
        for name in FUNCTION_CALL.findall(input.statement):
            if name.upper() not in CLAUSE_KEYWORDS:
                violations.append(f"function call forbidden: {name}")
        resources = FROM_RESOURCE.findall(input.statement) + JOIN_RESOURCE.findall(
            input.statement
        )
        allowed = set(input.allowed_resources)
        for resource in resources:
            if resource not in allowed:
                violations.append(f"resource not whitelisted: {resource}")
        return FO05Result(
            allowed=not violations,
            violations=violations,
            resources=resources,
            state_events=["planned", "completed"],
            audit={
                "statement": input.statement,
                "violation_count": len(violations),
            },
        )
