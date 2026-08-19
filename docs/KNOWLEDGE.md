# 知识库·架构上下文索引入口

> 本文档是 `dongjiagoushi`（架构师 Agent 框架）**知识库的检索入口**。
> 作用：让 `@CodeBuddy` / 架构师对话在 RAG 检索时，能快速定位「本仓库是谁、核心理念、关键机制、文档都放在哪、当前做到哪一步」。

---

## 一、这是什么仓库

- **定位**：架构师 Agent 框架，以 **AI 优先、人类俯瞰、主动规避风险** 为核心设计理念。
- **运行方式**：官方免费 `@CodeBuddy` 化身「架构师」，零积分执行，走完整的**架构八步**。
- **核心理念**：`AI 优先`（产出结构化可索引）· `人类俯瞰`（二级信息 + 看板）· `主动规避风险`（风险显式暴露 + CP 暂停确认点）· `模块化`（各模块独立演进）· `完整不残次`（拒绝半成品骨架）。

## 二、核心机制速览

| 机制 | 载体 | 说明 |
|------|------|------|
| 架构八步 | `.codebuddy/skills/architect/SKILL.md` | 调研→拓扑→可行性→方案→分工→协作→进度→索引→汇报 |
| 一库多角色 | `.cnb/settings.yml` | 架构·总师为主 + 架构·产品/开发/评审/测试扩展位 |
| 零积分架构师 | 官方 `@CodeBuddy` | 由 skill 自动加载，不扣积分 |
| 知识库 RAG | `knowledge:update` + codewiki | 架构师读信息条理全面，可直接检索 |
| 经验记忆库+语义触发 | `src/memory/` | 统一向量格式 + LanceDB/云端双后端兼容 + 持续积累经验 + 语义向量触发引擎（真实向量检索） |
| Issue 版本管理 | Issue 声明头 + 版本线 | 模块能力可阶段性多次加强（init/update/fix/standalone） |
| 安全护栏 | AGENTS.md + CP1/CP2/CP3 | 人审批放行、敏感信息红线、风险显式暴露 |
| 测试信号灯 | tests + .cnb.yml test 阶段 | 功能未达成预期即红灯阻塞，机器强制不放行 |

## 三、文档地图（都在哪）

| 文档 | 位置 | 内容 |
|------|------|------|
| 顶层架构拓扑 | `docs/ARCHITECTURE.md` | 模块清单、数据流向、关键取舍 |
| 经验记忆库+语义触发 | `docs/MEMORY.md` + `src/memory/` | 统一向量格式 + LanceDB/云端双兼容 + 持续积累经验 + 语义向量触发引擎 |
| 工程实践路线图 | `docs/ROADMAP.md` | 里程碑 M0-M10、下一阶段建议 |
| Issue 版本管理 | `docs/ISSUE_MANAGEMENT.md` | 声明头 + **模块/Agent 双版本线**（module_version + agent_version） |
| 架构八步模板 | `docs/templates/architect-report.md` | 八步产物产出模板 |
| Issue 声明模板 | `docs/templates/issue-template.md` | 声明头 front-matter 规范 |
| 验收清单 | `docs/templates/acceptance-checklist.md` | 测试信号灯 + 可勾选验收标准 |
| 测试脚本 | `tests/test_architect_system.sh`（静态断言） + `tests/test_functional_links.sh`（真实功能链路） + `tests/test_relay_workflow.sh`（接力链路可复现） + `tests/test_memory_store.sh`（经验记忆库+语义向量触发+双后端兼容） | 五项关键链路 + 数据获取/看板呈现/RAG读取 + 接力/回转/打断 + 记忆库/语义触发 真跑通（test 阶段） |
| 协作规则 | `AGENTS.md` | 全局协作规则 + 安全护栏 |
| 使用说明 | `README.md` | 快速开始 + 命令 |
| 真实场景产物 | `docs/arch-scenarios/` | 架构八步跑通的产物留痕 |

## 四、知识库入库机制

- 入库由 `.cnb.yml` 的 `knowledge:update` 任务完成，`main` 分支 push 时触发。
- `include: "**/*.md"` 覆盖 README / AGENTS / docs / 模板等全部 Markdown。
- `issueSyncEnabled: true` 同步 Issue 数据，供 agent 检索需求/决策上下文。
- 打 tag 触发 codewiki 生成 Wiki 并自动入库（`knowledge_enabled: true`）。

## 四b、入库验证记录（真实跑通）

> 已用真实 RAG 查询验证知识库可用，非纸面配置。

```
$ cnb knowledge-base get-knowledge-base-info
  embedding_model: hunyuan (1024维)   · 统计: 38 个文档块 / 约 540KB
  include: **/*.md · exclude: node_modules/**,dist/**,**/codewiki/**
  issue_sync_enabled: true

$ cnb knowledge-base query --query "架构师框架的核心设计理念是什么" --top-k 3
  status: 200 · 命中 3 条，相似度 0.99 / 0.99 / 0.92
  命中内容：项目概述（AI 优先·人类俯瞰·主动规避风险）、架构八步方法论、术语表
  结果带 url 元数据，可溯源回 codewiki
```

**验证结论**：知识库已入库且能被 `@CodeBuddy`/架构师 RAG 检索命中，链路真实可用。
合并 PR #10 后 `.cnb.yml` 的 `knowledge:update` 将随 main push 自动重跑，把双版本机制新文档（ISSUE_MANAGEMENT / DASHBOARD / ROADMAP）增量入库。

## 五、当前进度（能力成熟度）

- **模块/Agent 双版本线**：详见各模块/agent 的 Issue 声明头（`module/module_version/agent/agent_version/type/update/depends_on`）。版本强制，非整体版本，双维度独立升版。
- **路线图**：M0-M16 已完成（含测试体系、多角色补全、触发强制化+回转/打断、记忆库+语义向量触发、双版本管理、看板自动化）；M7/M11 真实场景验证与知识库充实为当前推进重点。
- **待办**：真实场景跑通验证（#4 CP2 待补充信息）、知识库随 PR#10 合并后自动重跑入库。

---

> 检索提示：问架构相关问题时，优先检索 `docs/ARCHITECTURE.md`、`docs/ROADMAP.md`、`docs/ISSUE_MANAGEMENT.md` 及对应 Issue。
