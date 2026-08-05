-- FO-31 集成 schema：契约要求的六张表的基础 DDL。
-- 每张表必须具备：主键、版本/幂等键、创建/更新时间、审计来源（FO-01 实施计划“数据表”契约）。
-- 默认离线：真实数据库接入列为 unverified（见 docs/finops/audit/ablation-report.md）。

CREATE TABLE IF NOT EXISTS billing_line_item (
  id              TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE NOT NULL,
  source_id       TEXT NOT NULL,
  tenant_id       TEXT NOT NULL,
  currency        TEXT NOT NULL,
  unit            TEXT NOT NULL,
  amount          NUMERIC NOT NULL,
  watermark       TEXT NOT NULL,
  raw_ref         TEXT,
  version         INTEGER NOT NULL DEFAULT 1,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  audit_source    TEXT NOT NULL DEFAULT 'finops-agent'
);

CREATE TABLE IF NOT EXISTS semantic_version (
  id              TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE NOT NULL,
  version_name    TEXT NOT NULL,
  status          TEXT NOT NULL,
  version         INTEGER NOT NULL DEFAULT 1,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  audit_source    TEXT NOT NULL DEFAULT 'finops-agent'
);

CREATE TABLE IF NOT EXISTS query_run (
  id              TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE NOT NULL,
  tenant_id       TEXT NOT NULL,
  statement       TEXT NOT NULL,
  state           TEXT NOT NULL DEFAULT 'created',
  version         INTEGER NOT NULL DEFAULT 1,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  audit_source    TEXT NOT NULL DEFAULT 'finops-agent'
);

CREATE TABLE IF NOT EXISTS result_artifact (
  id              TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE NOT NULL,
  query_id        TEXT NOT NULL,
  value           JSONB NOT NULL,
  provenance      JSONB NOT NULL,
  version         INTEGER NOT NULL DEFAULT 1,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  audit_source    TEXT NOT NULL DEFAULT 'finops-agent'
);

CREATE TABLE IF NOT EXISTS anomaly_finding (
  id              TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE NOT NULL,
  query_id        TEXT NOT NULL,
  kind            TEXT NOT NULL,
  severity        TEXT NOT NULL,
  detail          TEXT,
  status          TEXT NOT NULL DEFAULT 'open',
  version         INTEGER NOT NULL DEFAULT 1,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  audit_source    TEXT NOT NULL DEFAULT 'finops-agent'
);

CREATE TABLE IF NOT EXISTS governance_ticket (
  id              TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE NOT NULL,
  finding_id      TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'open',
  version         INTEGER NOT NULL DEFAULT 1,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  audit_source    TEXT NOT NULL DEFAULT 'finops-agent'
);