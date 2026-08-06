# FinOps Agent

FinOps Agent 是一个基于 FastAPI 的云成本查询服务，接收受信任的账单数据，按租户隔离查询，并提供预算、异常和工单能力。

## 功能

- 受信任账单来源和持久化仓储
- 租户隔离、RLS 配置和服务端身份校验
- 只读 AST 查询、预算、超时、取消和分页
- 查询溯源、缓存、审计、UNKNOWN 恢复
- Qwen 意图解析、异常检测和工单适配器

## 技术栈

Python 3.12、FastAPI、Pydantic。生产环境可接入 PostgreSQL、账单系统和工单系统；离线测试使用明确的本地适配器。

## 本地启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[server]"
python -m uvicorn app.finops.api:app --host 127.0.0.1 --port 8002
```

API 文档：<http://127.0.0.1:8002/docs>。健康检查：<http://127.0.0.1:8002/health>。业务请求需要服务端识别的 `X-Tenant-Id`。

## 主要接口

- `POST /billing-ingestions`
- `POST /queries`
- `DELETE /queries/{query_id}`
- `POST /findings/{finding_id}/tickets`

## 测试

```powershell
python -m pytest -q
python -m compileall -q app tests scripts
```

## 真实服务验证

```powershell
$env:FINOPS_BASE_URL = "http://127.0.0.1:8002"
python .\scripts\finops\live_smoke.py --component health
python .\scripts\finops\live_smoke.py --component model
```

模型验证需要 `QWEN_API_KEY` 和 `QWEN_CHAT_MODEL`。退出码 `0` 表示通过，`1` 表示服务可用但校验失败，`2` 表示缺少服务或授权。

## 使用边界

模型只能提出类型化查询意图，不能绕过租户校验或 AST 只读限制。请勿提交 `.env`、密钥或私有账单数据。

## License

MIT，见 [LICENSE](LICENSE)。
