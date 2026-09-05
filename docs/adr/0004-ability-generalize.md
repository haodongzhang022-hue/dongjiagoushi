# ADR-0004：把「作业纪律」沉淀为全员通用能力，而非不断加新角色

- 状态：Accepted
- 决策日期：2026-09
- 相关：Issue #98（借鉴 mattpocock/skills）、AGENTS.md「派发/深度/@定位/标签/规范 全员化」

## 背景
mattpocock/skills 是「单工程师深度作业纪律」合集；我们骨架是「多角色编排框架」。
两者互补。若照搬他加一堆角色（triage/to-tickets/domain-modeling…），会让编排框架变臃肿、
职责混乱。

## 决策
把与工程现实最贴的作业纪律沉淀为**全员通用能力**挂到 `BaseRole`（如已做的 DispatchAbility /
DepthAbility / HandleAbility / LabelAbility / StandardAbility），各角色同源复用；
只在该处任务必须新增时才加角色，绝不为「借鉴」而加角色。

## 后果（权衡）
- 好处：能力可复用、全员可调用、不臃肿；比加角色更贴「工程师真的会干活」。
- 代价：需持续把零散纪律抽象为能力模块并接线（工作量在能力层而非角色层）。难反转，记 ADR。
