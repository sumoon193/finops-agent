"""可追溯内存仓储：实现契约要求的六张数据表的审计字段语义。

契约要求每张表「必须有主键、版本/幂等键、创建更新时间与审计来源」。
离线模式使用内存或 SQLite，配置 ``FINOPS_DATABASE_URL`` 后装配 PostgreSQL
和原生 RLS。所有实现保留同一审计语义：每条记录携带 ``id``（主键）、``idempotency_key``（幂等键）、
``version``（版本）、``created_at/updated_at`` 与 ``audit_source``。

跨模块不变量 #4：外部依赖必须有 Fake 或 Recorded adapter。这里的
``AuditRepository`` 就是被整个领域复用的「结果存储适配器」，action_id 与 effect_id
经 ledger 幂等去重，符合不变量 #2（副作用必须幂等并处理 UNKNOWN 对账）。

领域代码只依赖 ``RepositoryProtocol``，不会因存储实现切换而改变查询合同。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - optional for offline-only installs
    psycopg = None  # type: ignore[assignment]
    Jsonb = None  # type: ignore[assignment,misc]


_current_tenant: ContextVar[str] = ContextVar("finops_tenant", default="")


def set_current_tenant(tenant_id: str) -> None:
    """Bind the trusted request tenant to the current execution context."""
    _current_tenant.set(tenant_id)


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


class PostgresRepository:
    """PostgreSQL adapter with transaction-local tenant context and native RLS."""

    _allowed_tables: ClassVar[frozenset[str]] = frozenset({
        "billing_line_item",
        "semantic_version",
        "query_run",
        "result_artifact",
        "anomaly_finding",
        "governance_ticket",
    })
    _schema_ready: ClassVar[set[str]] = set()

    def __init__(self, database_url: str, table_name: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required when FINOPS_DATABASE_URL is configured")
        if table_name not in self._allowed_tables:
            raise ValueError(f"unsupported repository table: {table_name}")
        self.database_url = database_url
        self.table_name = table_name
        self._ensure_schema()

    def _connect(self):
        connection = psycopg.connect(self.database_url)
        tenant = _current_tenant.get()
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        return connection

    def _ensure_schema(self) -> None:
        if self.table_name in self._schema_ready:
            return
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    audit_source TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    tenant_id TEXT,
                    UNIQUE (tenant_id, idempotency_key)
                )
                """
            )
            connection.execute(f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS payload JSONB")
            connection.execute(f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS tenant_id TEXT")
            connection.execute(
                f"ALTER TABLE {self.table_name} DROP CONSTRAINT IF EXISTS "
                f"{self.table_name}_idempotency_key_key"
            )
            connection.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{self.table_name}_tenant_idempotency "
                f"ON {self.table_name} (tenant_id, idempotency_key)"
            )
            for column, sql_type in {
                "source_id": "TEXT",
                "currency": "TEXT",
                "unit": "TEXT",
                "amount": "NUMERIC",
                "watermark": "TEXT",
                "raw_ref": "TEXT",
                "version_name": "TEXT",
                "statement": "TEXT",
                "state": "TEXT",
                "query_id": "TEXT",
                "value": "JSONB",
                "provenance": "JSONB",
                "finding_id": "TEXT",
                "kind": "TEXT",
                "severity": "TEXT",
                "detail": "TEXT",
                "status": "TEXT",
            }.items():
                connection.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS {column} {sql_type}"
                )
            connection.execute(f"ALTER TABLE {self.table_name} ENABLE ROW LEVEL SECURITY")
            # Table owners bypass RLS unless FORCE is enabled.
            connection.execute(f"ALTER TABLE {self.table_name} FORCE ROW LEVEL SECURITY")
            policy = f"{self.table_name}_tenant_isolation"
            connection.execute(f"DROP POLICY IF EXISTS {policy} ON {self.table_name}")
            connection.execute(
                f"""
                CREATE POLICY {policy} ON {self.table_name}
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
                """
            )
        self._schema_ready.add(self.table_name)

    @staticmethod
    def _record(row: tuple[Any, ...]) -> Record:
        payload = row[6] if isinstance(row[6], dict) else json.loads(row[6])
        return Record(
            id=row[0],
            idempotency_key=row[1],
            version=row[2],
            created_at=row[3],
            updated_at=row[4],
            audit_source=row[5],
            payload=payload,
        )

    def put(self, record: Record) -> Record:
        tenant_id = record.payload.get("tenant_id") or _current_tenant.get()
        payload = record.payload
        projected = {
            "source_id": payload.get("source_id"),
            "currency": payload.get("currency"),
            "unit": payload.get("unit"),
            "amount": payload.get("amount"),
            "watermark": payload.get("watermark"),
            "raw_ref": payload.get("raw_ref"),
            "version_name": payload.get("version_name"),
            "statement": payload.get("statement"),
            "state": payload.get("state") or payload.get("status"),
            "query_id": payload.get("query_id"),
            "value": Jsonb(payload.get("value")) if Jsonb and payload.get("value") is not None else None,
            "provenance": Jsonb(payload.get("provenance")) if Jsonb and payload.get("provenance") is not None else None,
            "finding_id": payload.get("finding_id"),
            "kind": payload.get("kind"),
            "severity": payload.get("severity"),
            "detail": payload.get("detail"),
            "status": payload.get("status"),
        }
        projection_columns = ", ".join(projected)
        projection_values = ", ".join(["%s"] * len(projected))
        updates = ", ".join(
            f"{column} = COALESCE(EXCLUDED.{column}, {self.table_name}.{column})"
            for column in projected
        )
        with self._connect() as connection:
            row = connection.execute(
                f"""
                INSERT INTO {self.table_name}
                    (id, idempotency_key, version, created_at, updated_at, audit_source, payload, tenant_id, {projection_columns})
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, {projection_values})
                ON CONFLICT (tenant_id, idempotency_key) DO UPDATE SET
                    payload = {self.table_name}.payload || EXCLUDED.payload,
                    version = {self.table_name}.version + 1,
                    updated_at = EXCLUDED.updated_at,
                    {updates}
                RETURNING id, idempotency_key, version, created_at, updated_at, audit_source, payload
                """,
                (record.id, record.idempotency_key, record.version, record.created_at,
                 record.updated_at, record.audit_source, Jsonb(record.payload), tenant_id,
                 *projected.values()),
            ).fetchone()
            if row is None:
                raise RuntimeError("PostgreSQL repository upsert returned no row")
            return self._record(row)

    def _fetch_one(self, clause: str, value: str) -> Record | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT id, idempotency_key, version, created_at, updated_at, audit_source, payload "
                f"FROM {self.table_name} WHERE {clause} = %s",
                (value,),
            ).fetchone()
        return self._record(row) if row else None

    def get(self, record_id: str) -> Record | None:
        return self._fetch_one("id", record_id)

    def find_by_idempotency_key(self, key: str) -> Record | None:
        return self._fetch_one("idempotency_key", key)

    def all(self) -> list[Record]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id, idempotency_key, version, created_at, updated_at, audit_source, payload "
                f"FROM {self.table_name} ORDER BY created_at, id"
            ).fetchall()
        return [self._record(row) for row in rows]


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
        database_url = os.getenv("FINOPS_DATABASE_URL")
        if database_url:
            self.billing_line_item = PostgresRepository(database_url, "billing_line_item")
            self.semantic_version = PostgresRepository(database_url, "semantic_version")
            self.query_run = PostgresRepository(database_url, "query_run")
            self.result_artifact = PostgresRepository(database_url, "result_artifact")
            self.anomaly_finding = PostgresRepository(database_url, "anomaly_finding")
            self.governance_ticket = PostgresRepository(database_url, "governance_ticket")
            return
        database_path = os.getenv("FINOPS_DATABASE_PATH")
        if database_path:
            self.billing_line_item = SQLiteRepository(database_path, "billing_line_item")
            self.semantic_version = SQLiteRepository(database_path, "semantic_version")
            self.query_run = SQLiteRepository(database_path, "query_run")
            self.result_artifact = SQLiteRepository(database_path, "result_artifact")
            self.anomaly_finding = SQLiteRepository(database_path, "anomaly_finding")
            self.governance_ticket = SQLiteRepository(database_path, "governance_ticket")

    def next_id(self, prefix: str) -> str:
        if os.getenv("FINOPS_DATABASE_URL"):
            return f"{prefix}-{uuid.uuid4().hex}"
        Repositories._factory_id += 1
        return f"{prefix}-{Repositories._factory_id:08d}"

    @staticmethod
    def idempotency_key(*parts: str) -> str:
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
        return digest
