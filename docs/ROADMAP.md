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
| M9 | 多角色召唤协议（配合机制） | ✅ | 接力卡 + 各角色输出契约 + 接力纪律（见 SKILL.md） |
| M10 | 多角色协作真实跑通验证 | ✅ | 用总师召唤产品/开发/评审/测试跑一次完整接力（含回转/打断，见 `tests/test_relay_workflow.sh` T8） |
| M11 | 知识库充实 | ⏳ | 架构文档/模板/声明头批量入库 + 索引入口 docs/KNOWLEDGE.md（见 Issue #6） |
| M12 | 可视化看板自动化汇总 | ✅ | 基于 Issue 声明头自动生成 docs/DASHBOARD.md（见 scripts/generate-dashboard.py） |
| M13 | 测试体系落地（护栏） | ✅ | .cnb.yml 加 test 阶段 + tests/test_architect_system.sh（静态断言）+ tests/test_functional_links.sh（真实功能链路）+ tests/test_relay_workflow.sh（接力可复现）+ 验收清单（见 Issue #8） |
| M14 | 协作触发强制化 + 回转/打断协议 | ✅ | 三层触发（显式[触发]/语义/rules固定）+ [回转]/[打断] 协议，T8 端到端可复现（见本批任务） |
| M15 | 经验记忆库 + 语义向量触发（专业可靠落地） | ✅ | `src/memory/` 记忆库模块：统一向量格式 + LanceDB/云端双后端兼容 + 持续积累经验 + 语义向量触发引擎（T9 可复现，见本批任务） |
| M16 | Issue 双版本管理机制（模块版本 + agent 版本） | ✅ | 版本强制写明，非整体版本，双维度独立升版、以较小迭代单位推进（见 docs/ISSUE_MANAGEMENT.md + 看板） |

## 架构八步模板

见 [docs/templates/architect-report.md](templates/architect-report.md)，每次做真实架构设计时按此模板产出。

## Issue 版本管理

Issue 采用「声明头 + 模块/Agent 双版本线」管理：每个 Issue 声明所属模块/agent、目标、**模块版本 + agent 版本**、更新内容，通过 `depends_on` 形成模块/agent 能力演进线，支持能力阶段性、多次被加强。**版本强制写明，非整体版本，而是双维度独立推进**。详见 [docs/ISSUE_MANAGEMENT.md](ISSUE_MANAGEMENT.md) 与模板 [docs/templates/issue-template.md](templates/issue-template.md)。

## 模块/Agent 双版本演进线（版本强制 · 双维度独立推进）

> 依据 `docs/ISSUE_MANAGEMENT.md` 的声明头机制登记。**版本不是整体版本，而是模块版本 + agent 版本两个独立维度**，各自以较小的迭代单位独立升版。`depends_on` 串联前后置关系。
> **测试（testing）为护栏模块，放最前**：没有测试信号灯，后续模块无法客观验证"到底做没做对"。

```
模块版本演进线（V0.2 规划）          agent 版本演进线（V0.2 规划）

testing 模块（护栏，init）
    └── issue#8  type=init   module_version=v0.1.0   （测试体系：.cnb.yml 加 test 阶段 + 验收清单）

arch-skill 模块（update）
    └── issue#4  type=update module_version=v0.2.0   depends_on:#8（真实场景跑通验证，走八步）

multirole 模块（update）            架构·产品/开发/评审/测试（agent，本批补全人设+触发/回转/打断）
    └── issue#5  type=update module_version=v0.2.0  depends_on:#8（多角色协作人设补全）

memory 模块（init）
    └── issue#5  type=init   v0.1.0   模块根节点（经验记忆库+语义向量触发：统一格式 + LanceDB/云端双兼容 + 持续积累经验）

knowledge 模块（update）
    └── issue#6  type=update module_version=v0.2.0  depends_on:#8（知识库充实）

dashboard 模块（init）
    └── issue#7  type=init   module_version=v0.1.0  depends_on:#8（可视化/二级信息看板自动化）
```

> 依赖关系：`#4/#5/#6/#7` 均 depends_on 测试护栏 `#8`。测试（#8）落地后，其余模块按此标准验收。
> 双版本推进规则：一个 Issue 只在一个最小迭代单位（单一模块或单一 agent）上升版；跨维度改动需分别写明 `module_version` 与 `agent_version`，各升各的，不抢整体版本号，避免局部迭代并发合并冲突。

## 下一阶段（V0.2 建议）

1. **真实场景验证**：在仓库内或关联 Issue 中，用 architect skill 跑一个真实架构需求，验证八步流畅度。
1. ✅ **经验记忆库 + 语义向量触发**：已落地 `src/memory/` —— 统一向量格式 + LanceDB 本地持久化 + 云端 CNB 知识库同格式适配 + 双写兼容 + 持续积累经验 + 语义向量触发引擎（T9 可复现）。语义向量触发从"prompt/关键词层面"升级为"真实向量检索"。
2. ✅ **多角色补全**：已在 `.cnb/settings.yml` 补全 PM/DEV/CR/QA 人设，并落地三层触发强制化 + 回转/打断协议（T8 可复现，见本批任务）。
3. ✅ **协作触发与回转打断可复现**：`tests/test_relay_workflow.sh` 端到端复现接力卡传递/回转打回/中断续跑，纳入 `.cnb.yml` test 阶段信号灯。
3. **知识库充实**：将架构文档、模板持续入库，供 agent 检索。
4. ✅ **可视化看板自动化**：已落地 `scripts/generate-dashboard.py` → `docs/DASHBOARD.md`，并在 `.cnb.yml` 挂了 `issue.*` 自动刷新（见任务 D）。

## 可视化看板

模块版本演进看板 + 里程碑表已自动化生成，人类俯瞰决策直接看 [docs/DASHBOARD.md](DASHBOARD.md)（由 `scripts/generate-dashboard.py` 在 Issue 增改删时自动刷新）。

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
| 可视化看板 | `docs/DASHBOARD.md` + `scripts/generate-dashboard.py` |
| 使用说明 | `README.md` |
| 知识库索引入口 | `docs/KNOWLEDGE.md` |
| 测试信号灯/脚本 | `tests/test_architect_system.sh`（静态断言） + `tests/test_functional_links.sh`（数据获取/看板呈现/RAG读取 真实功能链路） + `tests/test_relay_workflow.sh`（接力卡/回转/打断/三层触发 可复现） + `tests/test_memory_store.sh`（经验记忆库+语义向量触发+双后端兼容 可复现） |
| 验收清单 | `docs/templates/acceptance-checklist.md` |
