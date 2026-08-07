-- Idempotency is tenant scoped. The former global unique key caused valid
-- requests from different tenants to conflict and leaked key existence.
DO $$
DECLARE
  relation_name TEXT;
BEGIN
  FOREACH relation_name IN ARRAY ARRAY[
    'billing_line_item',
    'semantic_version',
    'query_run',
    'result_artifact',
    'anomaly_finding',
    'governance_ticket'
  ]
  LOOP
    EXECUTE format(
      'ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id TEXT',
      relation_name
    );
    EXECUTE format(
      'ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I',
      relation_name,
      relation_name || '_idempotency_key_key'
    );
    EXECUTE format(
      'CREATE UNIQUE INDEX IF NOT EXISTS %I ON %I (tenant_id, idempotency_key)',
      'ux_' || relation_name || '_tenant_idempotency',
      relation_name
    );
  END LOOP;
END $$;
