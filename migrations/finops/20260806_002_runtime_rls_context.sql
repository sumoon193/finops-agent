-- PostgreSQL runtime policy: the API sets this value with set_config(..., true)
-- for each transaction before repository reads and writes.
ALTER TABLE billing_line_item ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS billing_line_item_tenant_isolation ON billing_line_item;
CREATE POLICY billing_line_item_tenant_isolation
  ON billing_line_item
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
