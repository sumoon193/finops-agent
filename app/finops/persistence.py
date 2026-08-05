"""可追溯内存仓储：实现契约要求的六张数据表的审计字段语义。

契约要求每张表「必须有主键、版本/幂等键、创建更新时间与审计来源」。
本项目默认离线、不接入真实数据库（FO-13 unverified），因此用内存仓储落地
同一审计语义：每条记录携带 ``id``（主键）、``idempotency_key``（幂等键）、
``version``（版本）、``created_at/updated_at`` 与 ``audit_source``。

跨模块不变量 #4：外部依赖必须有 Fake 或 Recorded adapter。这里的
``AuditRepository`` 就是被整个领域复用的「结果存储适配器」，action_id 与 effect_id
经 ledger 幂等去重，符合不变量 #2（副作用必须幂等并处理 UNKNOWN 对账）。

真实数据库连接替换时（FO-12），只需实现 ``RepositoryProtocol`` 并注入即可，
领域代码不变。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass
class Record:
    """审计记录基类：统一具备主键、幂等键、版本、时间戳与审计来源。"""

    id: str
    idempotency_key: str
    version: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    audit_source: str = "finops-agent"
    payload: dict[str, Any] = field(default_factory=dict)


class RepositoryProtocol(Protocol):
    def put(self, record: Record) -> Record: ...
    def get(self, record_id: str) -> Record | None: ...
    def find_by_idempotency_key(self, key: str) -> Record | None: ...
    def all(self) -> list[Record]: ...


class InMemoryRepository:
    """内存仓储：幂等键去重、版本递增、审计来源可追溯。"""

    def __init__(self, table_name: str) -> None:
        self.table_name = table_name
        self._by_id: dict[str, Record] = {}
        self._by_key: dict[str, str] = {}

    def put(self, record: Record) -> Record:
        existing_id = self._by_key.get(record.idempotency_key)
        if existing_id is not None:
            existing = self._by_id[existing_id]
            existing.payload.update(record.payload)
            existing.version += 1
            existing.updated_at = time.time()
            return existing
        self._by_id[record.id] = record
        self._by_key[record.idempotency_key] = record.id
        return record

    def get(self, record_id: str) -> Record | None:
        return self._by_id.get(record_id)

    def find_by_idempotency_key(self, key: str) -> Record | None:
        record_id = self._by_key.get(key)
        return self._by_id.get(record_id) if record_id else None

    def all(self) -> list[Record]:
        return list(self._by_id.values())


class SQLiteRepository:
    """Durable repository adapter with the same contract as the offline store."""

    def __init__(self, database_path: str | Path, table_name: str) -> None:
        self.table_name = table_name
        self._conn = sqlite3.connect(str(database_path), check_same_thread=False)
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table_name} ("
            "id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL, version INTEGER NOT NULL, "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL, audit_source TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        self._conn.commit()

    def put(self, record: Record) -> Record:
        existing = self.find_by_idempotency_key(record.idempotency_key)
        if existing:
            existing.payload.update(record.payload)
            existing.version += 1
            existing.updated_at = time.time()
            self._conn.execute(
                f"UPDATE {self.table_name} SET payload=?, version=?, updated_at=? WHERE id=?",
                (json.dumps(existing.payload), existing.version, existing.updated_at, existing.id),
            )
            self._conn.commit()
            return existing
        self._conn.execute(
            f"INSERT INTO {self.table_name} VALUES (?,?,?,?,?,?,?)",
            (record.id, record.idempotency_key, record.version, record.created_at,
             record.updated_at, record.audit_source, json.dumps(record.payload)),
        )
        self._conn.commit()
        return record

    def get(self, record_id: str) -> Record | None:
        row = self._conn.execute(
            f"SELECT id,idempotency_key,version,created_at,updated_at,audit_source,payload FROM {self.table_name} WHERE id=?",
            (record_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def find_by_idempotency_key(self, key: str) -> Record | None:
        row = self._conn.execute(
            f"SELECT id,idempotency_key,version,created_at,updated_at,audit_source,payload FROM {self.table_name} WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        return self._from_row(row) if row else None

    def all(self) -> list[Record]:
        rows = self._conn.execute(
            f"SELECT id,idempotency_key,version,created_at,updated_at,audit_source,payload FROM {self.table_name}"
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> Record:
        return Record(
            id=row[0], idempotency_key=row[1], version=row[2], created_at=row[3],
            updated_at=row[4], audit_source=row[5], payload=json.loads(row[6]),
        )


@dataclass
class Repositories:
    """契约声明的六张表统一装配点。"""

    billing_line_item: InMemoryRepository = field(default_factory=lambda: InMemoryRepository("billing_line_item"))
    semantic_version: InMemoryRepository = field(default_factory=lambda: InMemoryRepository("semantic_version"))
    query_run: InMemoryRepository = field(default_factory=lambda: InMemoryRepository("query_run"))
    result_artifact: InMemoryRepository = field(default_factory=lambda: InMemoryRepository("result_artifact"))
    anomaly_finding: InMemoryRepository = field(default_factory=lambda: InMemoryRepository("anomaly_finding"))
    governance_ticket: InMemoryRepository = field(default_factory=lambda: InMemoryRepository("governance_ticket"))

    _factory_id: int = 0

    def __post_init__(self) -> None:
        database_path = os.getenv("FINOPS_DATABASE_PATH")
        if database_path:
            self.billing_line_item = SQLiteRepository(database_path, "billing_line_item")
            self.semantic_version = SQLiteRepository(database_path, "semantic_version")
            self.query_run = SQLiteRepository(database_path, "query_run")
            self.result_artifact = SQLiteRepository(database_path, "result_artifact")
            self.anomaly_finding = SQLiteRepository(database_path, "anomaly_finding")
            self.governance_ticket = SQLiteRepository(database_path, "governance_ticket")

    def next_id(self, prefix: str) -> str:
        Repositories._factory_id += 1
        return f"{prefix}-{Repositories._factory_id:08d}"

    @staticmethod
    def idempotency_key(*parts: str) -> str:
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
        return digest
