# 工程实践路线图（ROADMAP）

本文件是「架构八步」中第 3~8 步的落地路线。当前阶段：**框架骨架第一版已完成（V0.1）**。

## 里程碑

| 阶段 | 内容 | 状态 | 交付物 |
|------|------|------|--------|
| M0 | 调研 | ✅ | 调研结论（见 Issue #1 评论） |
| M1 | 顶层架构拓扑 | ✅ | docs/ARCHITECTURE.md |
| M2 | 可行性验证 | ✅ | 参考仓库源码核验 + 官方文档核验 |
| M3 | 工程实施方案（第一版骨架） | ✅ | 本仓库目录结构 + 各模块文件 |
| M4 | 分工与协作规则 | ✅ | AGENTS.md + settings.yml 角色扩展位 |
| M5 | 进度对齐（暂停点） | ✅ | CP1/CP2/CP3 护栏 |
| M6 | 索引建立 | ✅ | docs/ 索引 + 产物索引 |
| M7 | 真实场景跑通验证 | ⏳ | 用架构师 skill 跑一个真实架构需求 |
| M8 | Issue 声明与模块版本管理机制 | ✅ | 声明头 + 类型表 + 版本线（见 docs/ISSUE_MANAGEMENT.md） |

## 架构八步模板

见 [docs/templates/architect-report.md](templates/architect-report.md)，每次做真实架构设计时按此模板产出。

## Issue 版本管理

Issue 采用「声明头 + 模块版本线」管理：每个 Issue 声明所属模块/类型/目标/版本/更新内容，通过 `depends_on` 形成模块能力演进线，支持能力阶段性、多次被加强。详见 [docs/ISSUE_MANAGEMENT.md](ISSUE_MANAGEMENT.md) 与模板 [docs/templates/issue-template.md](templates/issue-template.md)。

## 下一阶段（V0.2 建议）

1. **真实场景验证**：在仓库内或关联 Issue 中，用 architect skill 跑一个真实架构需求，验证八步流畅度。
2. **多角色补全**：按需完善 PM/DEV/CR/QA 人设（当前为扩展位）。
3. **知识库充实**：将架构文档、模板持续入库，供 agent 检索。
4. **可视化增强**：考虑引入进度看板/里程碑的自动化汇总。

## 索引

| 产物 | 位置 |
|------|------|
| 角色定义 | `.cnb/settings.yml` |
| 架构师方法论 | `.codebuddy/skills/architect/SKILL.md` |
| 流水线 | `.cnb.yml` |
| 协作规则 | `AGENTS.md` |
| 顶层架构 | `docs/ARCHITECTURE.md` |
| 路线图 | `docs/ROADMAP.md` |
| 八步模板 | `docs/templates/architect-report.md` |
| Issue 版本管理 | `docs/ISSUE_MANAGEMENT.md` |
| Issue 声明模板 | `docs/templates/issue-template.md` |
| 使用说明 | `README.md` |
