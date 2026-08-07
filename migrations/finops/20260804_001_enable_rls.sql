-- FO-03 身份、RLS 与行列策略
-- 数据库 RLS：billing_line_item 只允许访问当前租户行，跨租户读取被拒绝。
ALTER TABLE IF EXISTS billing_line_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS billing_line_item FORCE ROW LEVEL SECURITY;

CREATE POLICY billing_line_item_tenant_isolation
  ON billing_line_item
  USING (tenant_id = current_setting('app.tenant_id')::text)
  WITH CHECK (tenant_id = current_setting('app.tenant_id')::text);
