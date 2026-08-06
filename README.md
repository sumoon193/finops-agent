# FinOps Agent

## 项目简介与适用场景

FinOps Agent 是一个面向云成本分析和治理的 FastAPI 服务。它从受信任的账单入口接收数据，以租户身份执行只读查询，并把预算控制、分页、缓存、审计、异常分析和工单流程组织在同一条可追踪链路中。

模型只负责把自然语言转换为类型化意图。实际数据必须来自服务端账单仓储，查询必须通过语义目录、AST 白名单、租户过滤和预算校验，客户端提交的数据不能绕过这些限制。

## 功能清单

- 接收并规范化 FOCUS 风格账单数据，保留来源 ID、水位线和原始引用。
- 所有业务请求要求可信 `X-Tenant-Id`，查询结果按租户隔离。
- 支持语义目录版本、类型化意图和允许的查询类型。
- AST 门禁仅允许只读查询，拒绝 DDL、DML、函数和非白名单资源。
- 查询前执行成本预算检查，执行结果支持稳定分页和缓存。
- 查询运行、结果、异常和工单包含幂等键、版本、时间戳和审计来源。
- 已完成任务不能伪造为 cancelled；运行中的取消操作走持久化状态校验。
- 支持 UNKNOWN 副作用账本、恢复和回滚脚本。
- Qwen 意图解析和离线确定性解析相互独立，真实验证不会静默降级。

## 系统架构与核心流程

```text
账单来源 -> 受信任导入 -> FOCUS 规范化 -> 租户仓储/水位线
                                            |
自然语言 -> 类型化意图 -> 语义目录 -> AST 只读校验 -> RLS/租户过滤
                                            |
                         预算检查 -> 查询执行 -> 分页/缓存 -> 审计溯源
                                            |
                                异常发现 -> 审批 -> 工单适配器
```

默认仓储为内存实现，适合离线开发；设置 `FINOPS_DATABASE_PATH` 后使用 SQLite 持久化适配器。PostgreSQL/RLS 可以通过相同 Repository 契约接入，但在没有真实数据库验证时不会被标记为已通过。

## 技术栈与运行依赖

- Python 3.12、FastAPI、Pydantic
- SQLite 持久化适配器、Repository 契约
- FOCUS 账单规范、AST 只读校验、租户隔离
- Qwen/DashScope 兼容接口
- Pytest、Compileall

## 目录结构说明

```text
app/finops/api.py              HTTP API 和身份解析
app/finops/ingestion/          账单来源适配器
app/finops/focus/              FOCUS 规范化
app/finops/catalog/            语义目录和版本
app/finops/intent/             类型化模型意图
app/finops/query/              AST、预算和执行计划
app/finops/security/           租户身份和 RLS 语义
app/finops/persistence.py      内存与 SQLite 仓储
app/finops/anomaly/            异常归因
app/finops/tickets/            工单编排
app/finops/recovery/           UNKNOWN 与恢复账本
scripts/finops/                live smoke 和回滚脚本
tests/                         单元、契约和 API 测试
```

## 环境要求

- Python 3.12+
- 真实模型验证需要 `QWEN_API_KEY` 和 `QWEN_CHAT_MODEL`
- 可选 SQLite 文件用于跨进程持久化
- PostgreSQL、云账单和工单系统属于可替换外部适配器，需要单独部署和授权

## 本地快速启动

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[server]"
python -m pip install pytest
python -m uvicorn app.finops.api:app --host 127.0.0.1 --port 8002
```

Linux/macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[server]'
python -m pip install pytest
python -m uvicorn app.finops.api:app --host 127.0.0.1 --port 8002
```

接口文档地址为 <http://127.0.0.1:8002/docs>，健康检查为 <http://127.0.0.1:8002/health>。

## Docker 或中间件启动方式

当前服务不强制依赖 Docker。默认内存仓储和 SQLite 适配器可直接运行；真实 PostgreSQL、账单来源和工单系统应独立部署，再通过项目端口契约接入。

### 持久化与外部依赖

默认数据随进程结束清空。需要保留本地数据时：

```powershell
New-Item -ItemType Directory -Force .\runtime | Out-Null
$env:FINOPS_DATABASE_PATH = ".\runtime\finops.db"
python -m uvicorn app.finops.api:app --host 127.0.0.1 --port 8002
```

真实 PostgreSQL、账单来源和工单系统应实现项目中的 Repository、账单适配器和 Ticket Service 契约。未配置时仍可运行完整离线测试，但不代表这些外部系统已经验收。

## 配置项和环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FINOPS_BASE_URL` | 空 | live smoke 使用的服务地址 |
| `FINOPS_DATABASE_PATH` | 空 | SQLite 数据库路径；为空时使用内存仓储 |
| `QWEN_API_KEY` | 空 | Qwen API 密钥，不要提交 |
| `QWEN_CHAT_MODEL` | 空 | 文本模型名称 |
| `QWEN_BASE_URL` | DashScope 兼容地址 | OpenAI-compatible API 地址 |
| `X-Tenant-Id` | 无 | 必填的可信租户请求头 |
| `X-Role` | `analyst` | 调用方角色 |
| `X-Request-Id` | 空 | 请求关联 ID，用于审计和 Trace |

## 主要 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `POST` | `/billing-ingestions` | 导入受信任账单行 |
| `POST` | `/queries` | 创建只读成本查询 |
| `GET` | `/queries/{query_id}/trace` | 查询运行溯源 |
| `DELETE` | `/queries/{query_id}` | 取消仍在运行的查询 |
| `POST` | `/findings/{finding_id}/tickets` | 为异常发现创建工单 |

除健康检查外，请求均应携带 `X-Tenant-Id`。生产部署中该请求头应由认证网关或服务端身份组件写入，不能直接信任公网客户端。

## 请求示例与返回结果

### 导入账单

```powershell
curl.exe -X POST http://127.0.0.1:8002/billing-ingestions `
  -H "Content-Type: application/json" `
  -H "X-Tenant-Id: tenant-demo" `
  -H "X-Request-Id: request-001" `
  -d '{"watermark":"2026-08-01T00:00:00Z","raw_lines":[{"source_id":"aws-line-001","currency":"USD","unit":"cost","amount":"18.75","watermark":"2026-08-01T00:00:00Z","raw_ref":"s3://example-bucket/billing.csv#2"}]}'
```

响应包含导入数量、水位线和来源 ID。相同来源和水位线通过幂等键更新，不重复创建账单行。

### 创建只读查询

```powershell
curl.exe -X POST http://127.0.0.1:8002/queries `
  -H "Content-Type: application/json" `
  -H "X-Tenant-Id: tenant-demo" `
  -H "X-Request-Id: request-002" `
  -d '{"statement":"SELECT amount, currency FROM billing_line_item","params":{},"page_size":50,"catalog_version":"2024-07","estimated_cost":"2.50","budget_limit":"100.00","allowed_resources":["billing_line_item"]}'
```

响应包含 `query_id`、当前页、下一页游标和 provenance。兼容字段 `rows` 已废弃，即使客户端提交也不会成为查询数据源。

### 查询 Trace

```powershell
curl.exe http://127.0.0.1:8002/queries/{query_id}/trace `
  -H "X-Tenant-Id: tenant-demo" `
  -H "X-Request-Id: request-002"
```

## 离线测试

```powershell
python -m pytest -q
python -m compileall -q app tests scripts
```

离线测试使用本地账单、仓储和工单适配器，不访问云厂商、模型或真实工单平台。

## 真实服务验证

```powershell
$env:FINOPS_BASE_URL = "http://127.0.0.1:8002"
python .\scripts\finops\live_smoke.py --component health
python .\scripts\finops\live_smoke.py --component model
```

模型验证前设置：

```powershell
$env:QWEN_API_KEY = "本地密钥"
$env:QWEN_CHAT_MODEL = "qwen-plus"
```

当前 live smoke 覆盖 API 健康检查和真实模型意图解析。数据库、账单来源、异常系统和工单平台应由各自适配器的独立 smoke 验证。退出码 `0` 为通过，`1` 为连接后验证失败，`2` 为缺少服务或授权。

## 常见问题与故障排查

### API 返回 missing trusted X-Tenant-Id

在业务请求中添加 `X-Tenant-Id`。生产环境应由可信网关注入，不要把客户端自报的租户 ID 直接当作身份依据。

### 查询返回 AST violation

只允许 `SELECT` 和 `allowed_resources` 中的资源。删除 DDL、DML、函数调用或未授权表名后重试。

### 取消查询返回 409

只有持久化状态仍为 `running` 的任务可以取消。已经 `completed`、`cancelled` 或失败的任务不会被改写为 cancelled。

### 重启后找不到数据

设置 `FINOPS_DATABASE_PATH` 使用 SQLite 文件。默认内存仓储只用于本地和测试。

## 安全边界和生产注意事项

- 不提交 `.env`、API key、Cookie、Token、私有账单、工单内容或运行日志。
- 模型生成的意图必须经过目录版本和 AST 只读校验。
- 客户端提交的 `rows` 永远不能替代受信任账单仓储。
- 租户身份、RLS、预算和分页均由服务端执行。
- 离线适配器通过不代表真实云账单、数据库或工单系统已经连通。

## License

MIT，详见 [LICENSE](LICENSE)。
