# FO-12 回滚与数据层替换演练计划

## 目标

语义（semantic）、FOCUS（focus）与数据库（database）三类 adapter 必须可注册、可切换并可回滚到上一个已验证版本。任何切换必须通过 typed command 执行并记录审计事件。

## 回滚步骤

1. 在 `AdapterRegistry` 中注册每个 adapter 的当前基线版本。
2. 切换前把当前版本压入该类别回滚栈。
3. 执行切换后立即核对 `current(kind)` 与状态事件。
4. 发现问题时对同一类别执行 `rollback(kind)`，恢复栈顶版本并校验恢复结果。

## 演练范围

- 语义目录版本替换演练。
- FOCUS canonical 规范化 adapter 替换演练。
- 数据库访问 adapter（RLS 计划执行器）替换演练。

## 未验证项（unverified）

- 真实数据库、消息队列与外部服务的替换未执行，仅离线模拟。
- 分布式环境下的并发切换与租约语义未验证。
- 回滚在真实崩溃点上的故障恢复未演练（见 FO-10 恢复台账）。
