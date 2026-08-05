# FO-01 来源、范围与许可证

模块：FO-01（来源、范围与许可证）
可观察结果：账单、目录和模型/数据来源可追溯。

## 范围

- 允许路径：`docs/audit/**`、`tests/finops/audit/**`
- 只读路径：`AGENTS.md`、`.agent-governance/**`、`LICENSE`
- 禁止读取：`.env`、`data/billing-private/**`、`config/cloud-credentials/**`
- 本模块只交付审计文档与失败测试，不包含生产代码、迁移或 API。

## 边界与非目标

- 不修改任务白名单外模块。
- 范围外问题只记录不顺手修改。
- 未验证的外部服务保持 `pending`/`blocked`，不得写成通过。
- 不生成学习、面试、简历和项目总结文档。
- 不执行 merge 或 force-push。

## 接口契约声明

- 声明接口签名：`IdentityContext.execute(input: FO01Input) -> FO01Result`，由后续模块落地。
- 来源追溯见 `source-registry.json`，许可证归属见 `license.md`。
