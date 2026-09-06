# ADR-0003：架构方法论走 .codebuddy/skills 而非 npc:go

- 状态：Accepted
- 决策日期：2026-09
- 相关：.codebuddy/skills/architect/SKILL.md、.cnb.yml

## 背景
架构八步方法论若写死在 NPC prompt 或流水线脚本里，会与仓库文档/规则产生版本漂移，
且不易跨仓库复用。

## 决策
架构方法论承载在 **`.codebuddy/skills/architect/`（skill 化身身份）**，随仓库对话自动加载；
`.cnb.yml` 以 `npc:go` 兜底（非主承载）。方法论以可加载 skill 形式存在，正文唯一事实源。

## 后果（权衡）
- 好处：方法论与文档同源、可版本化、可复用；不写死平台人设。
- 代价：skill 跨库不自动加载（需显式引用）。难反转，记 ADR。
