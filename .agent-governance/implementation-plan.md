# FinOps 云成本治理智能体 完整实施计划

> 本文是开发执行合同，不是学习材料或完成证明。每一模块必须由独立任务分支按依赖顺序实施，先观察失败测试，再做最小实现。

## 全局精确路径与边界

- 生产代码根：`app/finops`。
- 任务只能修改本模块 `source_paths/test_paths` 与任务包白名单；Runtime Kernel、秘密和其他模块默认只读或禁止。
- 接口签名、数据表、API、状态和错误语义以 `.agent-governance/module-contracts.json` 为机器真源。
- 每次激活任务时，主集成模型把任务 `base_sha` 重绑定为当前集成提交，再由实现模型创建精确分支。

## 公共接口签名、数据表与 API

### 接口签名
- `BillingSourcePort.read(watermark: DataWatermark) -> Iterable[BillingLineItem]`
- `QueryExecutor.execute(plan: AuthorizedQueryPlan) -> ResultArtifact`

### 数据表
- `billing_line_item`：必须有主键、版本/幂等键、创建更新时间与审计来源。
- `semantic_version`：必须有主键、版本/幂等键、创建更新时间与审计来源。
- `query_run`：必须有主键、版本/幂等键、创建更新时间与审计来源。
- `result_artifact`：必须有主键、版本/幂等键、创建更新时间与审计来源。
- `anomaly_finding`：必须有主键、版本/幂等键、创建更新时间与审计来源。
- `governance_ticket`：必须有主键、版本/幂等键、创建更新时间与审计来源。

### API
- `POST /billing-ingestions`：使用 typed request/response、稳定错误码、request/correlation ID 与权限校验。
- `POST /queries`：使用 typed request/response、稳定错误码、request/correlation ID 与权限校验。
- `DELETE /queries/{id}`：使用 typed request/response、稳定错误码、request/correlation ID 与权限校验。
- `POST /findings/{id}/tickets`：使用 typed request/response、稳定错误码、request/correlation ID 与权限校验。

## 模块逐项执行

### FO-01 来源、范围与许可证

- 依赖：`无`。
- 精确路径：`docs/audit/**`, `tests/finops/audit/**`。
- 接口签名：`IdentityContext.execute(input: FO01Input) -> FO01Result`。
- 数据表：`query_run`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_01`，失败原因只能是目标行为未实现。
- 可观察结果：账单、目录和模型/数据来源可追溯。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-02 FOCUS canonical 摄取

- 依赖：`FO-01`。
- 精确路径：`app/finops/ingestion/**`, `app/finops/focus/**`, `tests/finops/focus/**`。
- 接口签名：`QueryIntent.execute(input: FO02Input) -> FO02Result`。
- 数据表：`result_artifact`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_02`，失败原因只能是目标行为未实现。
- 可观察结果：账单规范化保留来源、货币、单位和watermark。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-03 身份、RLS 与行列策略

- 依赖：`FO-02`。
- 精确路径：`app/finops/security/**`, `migrations/finops/**`, `tests/finops/security/**`。
- 接口签名：`AuthorizedQueryPlan.execute(input: FO03Input) -> FO03Result`。
- 数据表：`query_run`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_03`，失败原因只能是目标行为未实现。
- 可观察结果：服务端身份和数据库RLS阻止跨租户读取。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-04 Intent、模型与语义目录

- 依赖：`FO-03`。
- 精确路径：`app/finops/intent/**`, `app/finops/catalog/**`, `tests/finops/intent/**`。
- 接口签名：`IdentityContext.execute(input: FO04Input) -> FO04Result`。
- 数据表：`result_artifact`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_04`，失败原因只能是目标行为未实现。
- 可观察结果：模型输出typed intent且绑定语义目录版本。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-05 AST 只读门禁

- 依赖：`FO-04`。
- 精确路径：`app/finops/query/ast/**`, `tests/finops/query/test_ast_*.py`。
- 接口签名：`QueryIntent.execute(input: FO05Input) -> FO05Result`。
- 数据表：`query_run`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_05`，失败原因只能是目标行为未实现。
- 可观察结果：AST拒绝DDL/DML、禁止函数和非白名单资源。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-06 只读查询、分页与状态

- 依赖：`FO-05`。
- 精确路径：`app/finops/query/execution/**`, `tests/finops/query/test_execution_*.py`。
- 接口签名：`AuthorizedQueryPlan.execute(input: FO06Input) -> FO06Result`。
- 数据表：`result_artifact`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_06`，失败原因只能是目标行为未实现。
- 可观察结果：查询使用参数化计划、稳定分页和CAS状态。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-07 预算、超时与取消

- 依赖：`FO-06`。
- 精确路径：`app/finops/query/budget/**`, `tests/finops/query/test_budget_*.py`。
- 接口签名：`IdentityContext.execute(input: FO07Input) -> FO07Result`。
- 数据表：`query_run`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_07`，失败原因只能是目标行为未实现。
- 可观察结果：超预算查询执行前拒绝且超时可取消。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-08 结果、缓存、审计与血缘

- 依赖：`FO-07`。
- 精确路径：`app/finops/results/**`, `tests/finops/results/**`。
- 接口签名：`QueryIntent.execute(input: FO08Input) -> FO08Result`。
- 数据表：`result_artifact`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_08`，失败原因只能是目标行为未实现。
- 可观察结果：缓存绑定RLS/语义/watermark且结果可追溯。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-09 异常归因与 GovernanceTicket

- 依赖：`FO-08`。
- 精确路径：`app/finops/anomaly/**`, `app/finops/tickets/**`, `tests/finops/tickets/**`。
- 接口签名：`AuthorizedQueryPlan.execute(input: FO09Input) -> FO09Result`。
- 数据表：`query_run`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_09`，失败原因只能是目标行为未实现。
- 可观察结果：异常finding只经审批创建幂等人工工单。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-10 可观测、恢复与对账

- 依赖：`FO-09`。
- 精确路径：`app/finops/observability/**`, `app/finops/recovery/**`, `tests/finops/recovery/**`。
- 接口签名：`IdentityContext.execute(input: FO10Input) -> FO10Result`。
- 数据表：`result_artifact`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_10`，失败原因只能是目标行为未实现。
- 可观察结果：worker崩溃、查询取消和工单UNKNOWN可恢复。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-11 冻结评测与真实模型受控试验

- 依赖：`FO-10`。
- 精确路径：`app/finops/eval/**`, `tests/finops/eval/**`。
- 接口签名：`QueryIntent.execute(input: FO11Input) -> FO11Result`。
- 数据表：`query_run`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_11`，失败原因只能是目标行为未实现。
- 可观察结果：RLS、AST、查询正确率和模型收益由冻结集验证。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-12 回滚、演练与数据层替换

- 依赖：`FO-11`。
- 精确路径：`scripts/finops/**`, `docs/finops/release/**`, `tests/finops/release/**`。
- 接口签名：`AuthorizedQueryPlan.execute(input: FO12Input) -> FO12Result`。
- 数据表：`result_artifact`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_12`，失败原因只能是目标行为未实现。
- 可观察结果：语义/FOCUS/数据库adapter可回滚替换。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

### FO-13 检索消融与发布审计

- 依赖：`FO-12`。
- 精确路径：`docs/finops/audit/**`, `tests/finops/ablation/**`。
- 接口签名：`IdentityContext.execute(input: FO13Input) -> FO13Result`。
- 数据表：`query_run`；迁移必须向前/向后兼容并保留审计事实。
- API：`/queries`；禁止把领域决策写入控制器。
- 状态：`created -> planned -> authorized -> running -> completed -> cancelled -> timed_out`，非法转换必须稳定拒绝。
- 失败测试：先创建/运行 `tests/finops/fo_13`，失败原因只能是目标行为未实现。
- 可观察结果：检索收益、发布门槛和未验证项有真实性报告。
- 回归命令：`python -m pytest tests/finops -q`。
- 交接：记录 RED/GREEN、实际改动、未运行项、风险、commit SHA；禁止 merge 和 force-push。

## 跨模块集成与真实性门禁

- 按依赖拓扑合并；每次合并后运行合同测试、全回归、构建、安全、故障恢复与回滚演练。
- 对数据库、消息、缓存、外部副作用执行崩溃点测试，核对幂等键、租约、Outbox/Inbox、SideEffect Ledger 和 UNKNOWN 对账。
- 远端分支保护、真实外部服务、真实模型或真实数据未执行时必须列为 unverified，不能以本地 Fake 结果替代。
- 所有模块构建、主集成优化、Bug 修复和最终验证前，禁止生成任何学习解释、项目总结、面试或简历文档。
