# generated-by: central-agent-governance
# finops-agent 项目模型执行入口

1. 先读取仓库根 `AGENTS.md`，再读取本文件。
2. 读取 `manifest.json`、`project-profile.json`、`module-contracts.json`、`implementation-plan.md`。
3. 当前分支必须精确匹配 `tasks/*.json` 中一张任务包。
4. 先运行 RED 并记录预期失败，再做最小实现、聚焦测试和回归。
5. 只能修改任务白名单；不得读取 read denylist；不得改写受保护未跟踪文件。
6. 可 commit 和普通 push；禁止 merge、force-push、自动合并。
7. 学习、面试、简历和项目总结文档必须等最终集成验证后生成。
