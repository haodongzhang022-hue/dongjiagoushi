# ADR-0002：架构师用官方 @CodeBuddy 化身、零积分执行

- 状态：Accepted
- 决策日期：2026-09
- 相关：.cnb/settings.yml、README

## 背景
调用 NPC / 商业化 LLM 角色会扣积分、成本不可控；且希望架构设计由能力足够的模型稳定承载。

## 决策
用官方 **`@CodeBuddy` 化身「架构师」** 执行架构八步，**零积分**；skill
（`.codebuddy/skills/architect/SKILL.md`）在仓库对话自动加载兜底人设。
平台 NPC 骨架仅作角色扩展位（settings.yml），不作为积分消耗主体。

## 后果（权衡）
- 好处：零积分、能力稳定、方法论随 skill 自动加载。
- 代价：依赖平台 `@CodeBuddy` 能力；需在 settings 保留 NPC 兜底人设防平台能力缺失。难反转，记 ADR。
