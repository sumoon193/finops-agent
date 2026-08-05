# FinOps Agent

## 项目简介

FinOps Agent 是基于 FastAPI 的云成本治理服务。系统从受信任的账单存储摄取 FOCUS 数据，在服务端完成租户隔离、语义目录校验、只读 AST 计划、预算控制、分页执行、结果血缘、异常归因和治理工单。默认离线运行，真实模型和外部账单/工单服务独立验证。

## 核心能力

- 账单来源适配器只接受服务端受信数据，客户端不能直接提交 rows 作为查询数据源。
- 服务端身份、租户隔离和 PostgreSQL RLS 阻止跨租户读取。
- Qwen 意图解析输出 typed intent，并绑定语义目录版本。
- AST 只读门禁拒绝 DDL、DML、非白名单资源和危险函数。
- 查询预算、超时、取消、CAS 状态、稳定分页和持久化恢复。
- 结果缓存绑定租户、语义版本和 watermark，审计与 provenance 可追溯。
- 异常 finding 只能经审批创建幂等 GovernanceTicket，UNKNOWN 支持恢复和对账。

## 技术栈与架构

- Python 3.12、FastAPI、Pydantic、pytest、compileall。
- PostgreSQL、RLS、持久化仓储和迁移位于 `migrations/`。
- FOCUS 账单来源、Qwen、异常检测和工单系统均通过可注入 adapter 接入。
- 查询链路为：账单摄取 -> 身份/RLS -> 意图 -> 语义目录 -> AST -> 授权计划 -> 预算/超时 -> 结果、缓存与审计。
- 离线路径使用固定测试数据和离线适配器，不访问真实网络。

## 本地启动

```powershell
Set-Location "D:\Code\agent study\managed-projects\finops-agent"
& "D:\py\py3.12\python.exe" -m uvicorn app.finops.api:app `
  --host 127.0.0.1 --port 8002
```

服务地址为 `http://127.0.0.1:8002`，OpenAPI 页面为 `http://127.0.0.1:8002/docs`，健康检查为 `http://127.0.0.1:8002/health`。业务请求必须携带服务端校验的 `X-Tenant-Id`。

## 主要 API

| 方法与路径 | 用途 |
| --- | --- |
| `POST /billing-ingestions` | 摄取并规范化受信任账单 |
| `POST /queries` | 创建受授权的只读查询 |
| `GET /queries/{query_id}/trace` | 查询执行状态、分页和血缘 |
| `DELETE /queries/{query_id}` | 取消持久化中的运行任务 |
| `POST /findings/{finding_id}/tickets` | 经审批创建治理工单 |
| `GET /health` | 返回服务健康状态 |

## 离线测试

```powershell
Set-Location "D:\Code\agent study\managed-projects\finops-agent"
& "D:\py\py3.12\python.exe" -m pytest tests -q -p no:cacheprovider
& "D:\py\py3.12\python.exe" -m compileall -q app tests scripts
```

离线测试不访问 Qwen、云账单、数据库或工单服务；固定测试数据不能代替真实服务验收。

## 真实服务验证

```powershell
$env:FINOPS_BASE_URL = "http://127.0.0.1:8002"

& "D:\py\py3.12\python.exe" ".\scripts\finops\live_smoke.py" --component health
& "D:\py\py3.12\python.exe" ".\scripts\finops\live_smoke.py" --component model
```

模型验证需要 `QWEN_API_KEY`、`QWEN_CHAT_MODEL`，可选 `QWEN_BASE_URL`。账单来源、PostgreSQL、异常检测和工单系统有独立适配器与 live smoke。

live smoke 退出码：退出码 `0` 表示真实验证通过，退出码 `1` 表示服务已连接但验证失败，退出码 `2` 表示缺少密钥、授权或服务而 blocked。

## 安全与使用边界

- 密钥只通过本机环境变量或未提交的 `.env` 注入，禁止提交 Cookie、Token、私有账单和云凭证。
- 模型只能产生 typed intent，不能绕过 RLS、语义目录、AST 只读校验或服务端授权。
- 取消只能作用于持久化中的运行任务，已完成任务不可伪造为 cancelled。
- 外部服务未配置时保持 blocked/unverified，不把离线结果标记为真实通过。
- 缓存、CAS、审计、provenance、UNKNOWN 和恢复演练必须可复核。

## License

本项目采用 MIT License，完整条款见 [LICENSE](LICENSE)。
