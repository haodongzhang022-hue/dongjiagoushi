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
| Issue 版本管理 | Issue 声明头 + 版本线 | 模块能力可阶段性多次加强（init/update/fix/standalone） |
| 安全护栏 | AGENTS.md + CP1/CP2/CP3 | 人审批放行、敏感信息红线、风险显式暴露 |
| 测试信号灯 | tests + .cnb.yml test 阶段 | 功能未达成预期即红灯阻塞，机器强制不放行 |

## 三、文档地图（都在哪）

| 文档 | 位置 | 内容 |
|------|------|------|
| 顶层架构拓扑 | `docs/ARCHITECTURE.md` | 模块清单、数据流向、关键取舍 |
| 工程实践路线图 | `docs/ROADMAP.md` | 里程碑 M0-M10、下一阶段建议 |
| Issue 版本管理 | `docs/ISSUE_MANAGEMENT.md` | 声明头 + 模块版本线机制 |
| 架构八步模板 | `docs/templates/architect-report.md` | 八步产物产出模板 |
| Issue 声明模板 | `docs/templates/issue-template.md` | 声明头 front-matter 规范 |
| 验收清单 | `docs/templates/acceptance-checklist.md` | 测试信号灯 + 可勾选验收标准 |
| 测试脚本 | `tests/test_architect_system.sh`（静态断言） + `tests/test_functional_links.sh`（真实功能链路） | 五项关键链路 + 数据获取/看板呈现/RAG读取 真跑通（test 阶段） |
| 协作规则 | `AGENTS.md` | 全局协作规则 + 安全护栏 |
| 使用说明 | `README.md` | 快速开始 + 命令 |
| 真实场景产物 | `docs/arch-scenarios/` | 架构八步跑通的产物留痕 |

## 四、知识库入库机制

- 入库由 `.cnb.yml` 的 `knowledge:update` 任务完成，`main` 分支 push 时触发。
- `include: "**/*.md"` 覆盖 README / AGENTS / docs / 模板等全部 Markdown。
- `issueSyncEnabled: true` 同步 Issue 数据，供 agent 检索需求/决策上下文。
- 打 tag 触发 codewiki 生成 Wiki 并自动入库（`knowledge_enabled: true`）。

## 五、当前进度（能力成熟度）

- **模块 version 线**：详见各模块 Issue 声明头（`module/type/version/update/depends_on`）。
- **路线图**：M0-M8、M12（测试体系）已完成；M7/M10 真实场景验证、多角色补全、知识库充实为后续重点。
- **待办**：真实场景跑通验证、多角色人设补全、可视化看板自动化。

---

> 检索提示：问架构相关问题时，优先检索 `docs/ARCHITECTURE.md`、`docs/ROADMAP.md`、`docs/ISSUE_MANAGEMENT.md` 及对应 Issue。
