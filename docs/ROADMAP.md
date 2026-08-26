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
| M17 | 本地 Agent 团队（无 @ 能力补齐 + 需求到交付自动编排） | ✅ | `local-agent/`：CLI 入口替代 @ + 8 角色团队 + 编排引擎 + 接力卡 + 多模型后端抽象（见 docs/LOCAL_AGENT.md，Issue #16） |
| M18 | 框架自升级闭环 + 智能化升级（memory 真实 embedding + 文档一致性 + 看板健康度） | ✅ | framework 模块版本线 + FRAMEWORK_UPGRADE.md + upgrade 类型 + memory 真实 embedding + test_doc_consistency + 看板框架健康度（见本批任务 / PR） |
| M19 | DAG 流水线引擎（非直线并行） | ✅ | `local-agent/graph.py` 拓扑排序 + 波次并行；经理可在架构明确后提前分工（plan 只依赖 architect），下游对齐/找工具/小组长与实现并行（见 Issue #18） |
| M20 | 开发分形扩展（多小组） | ✅ | `local-agent/fractal.py` 按项目规模分形多小组并行 + 小组长整合测试统一向上交付 + 可递归（见 Issue #18） |
| M21 | 默认入口 + 市场获客分层 | ✅ | `架构·秘书` 默认入口（产品经理/秘书优先，`@CodeBuddy` 主动切换身份）+ 市场·销售/客服/数据/渠道/工具 通用基建（见 Issue #18） |
| M22 | 跨平台适配（cnb.cool / deepseek harness / MCP 蜂群） | ✅ | 统一活动规则 + `docs/PLATFORM_ADAPTERS.md` 适配方案（cnb.cool 原生 / deepseek harness 本地 / MCP 工具化）（见 Issue #18） |
| M23 | 规模伸缩层 · 团队规模声明 | ✅ | `local-agent/scale/spec.py`：`--spec` 声明团队大小/分工层级/并发度/模式 + 自动分工拓扑 + 资源评估（见 Issue #20，docs/FRAMEWORK_V3.md） |
| M24 | 规模伸缩层 · 前置流程区分 | ✅ | `local-agent/scale/profile.py`：不同位置走不同流程模板（default/company/harness/acquisition/support）（见 Issue #20） |
| M25 | 规模伸缩层 · 角色插件化 | ✅ | `local-agent/scale/plugin.py` + `roles.d/`：放一个 .py 即自动加载新角色，灵活增减无需改核心代码（见 Issue #20） |
| M26 | 规模伸缩层 · 消息总线 + 状态分片 | ✅ | `local-agent/scale/{broker,store}.py`：agent 间发布/订阅/广播 + 按 agent 分片状态（替代单文件接力卡）（见 Issue #20） |
| M27 | 规模伸缩层 · 并发池 + 统一调度引擎 | ✅ | `local-agent/scale/{pool,engine}.py`：真并行波次 + 2500 级并发模拟 + `--scale` CLI 入口（见 Issue #20） |
| M28 | 规模伸缩层 · 测试与文档 | ✅ | `local-agent/tests/test_scale.sh` 7 组测试 + 主测试/本地测试全绿 + `docs/FRAMEWORK_V3.md`（见 Issue #20） |
| M29 | 上位机 · 定时器 + 状态机工程能力引擎 | ✅ | `local-agent/engine/`：状态机（合法转移表+强制校验+留痕）+ 定时器（周期/超时/心跳巡检）+ 上位机整合（HostEngine）+ `test_engine.sh` 7 组测试 + `docs/HOST_ENGINE.md`（见 Issue #26） |
| M30 | 调度中枢 · 事件驱动自动化调度层（dispatcher） | ✅ | `local-agent/dispatcher/`：事件源监听（本仓库+外部适配器插槽）+ 触发规则引擎 + Action 队列（自动优先+人工审核闸门，不卡进程）+ 防无效护栏（去重/频限/进度上限）+ 驳回迭代闭环（rejections 表按 gid 回派改进重提）+ sentinel 进度上限判定强化 + Web 可视化面板 + `test_dispatcher.sh` 8 组测试 + `docs/DISPATCHER.md`（见 Issue #26） |
| M31 | 外部事件源接入 · 多终端协同 + 秘钥/IP白名单安全 + 本地上位机辅助 | ✅ | `local-agent/dispatcher/{security,webhook,sources,host_helper}.py`：多终端源预设（本地电脑/手机/虚拟机/沙盒/上位机，不只一个源）+ 秘钥 key + IP 白名单 安全认证（deny-by-default）+ 多源 Webhook 接收端（POST /webhook/<source>，webhook 更合理）+ 认证审计留痕 + 本地上位机辅助角色预设（host_start/report/pull/ack/overview）+ `test_external_source.sh` 5 组测试 + `docs/EXTERNAL_SOURCE.md`（见 Issue #26） |
| M32 | 知识库充实（入库+索引入口） | ⏳ | 把 docs/、模板、Issue 声明头批量入库 + tag 触发 codewiki，让 @CodeBuddy 对话可 RAG 检索（Issue #6，T1） |
| M33 | 真实场景跑通验证（arch-skill） | ⏳ | 用 architect skill 跑一个真实架构需求，走完整八步留痕（Issue #4，T2） |
| M34 | 框架健康度审查 | ⏳ | 盘点 open issue，解决残留/关闭陈旧/整合双版本线（Issue #11，T3） |
| M35 | 测试环境依赖加固 | ⏳ | local-agent + functional-links 测试在云 CI 全绿；沙盒/云环境差异文档化（Issue #8，T4） |
| M36 | 看板/进度可视化持续维护 | ✅ | DASHBOARD.md 随 issue 变更自动刷新（Issue #7，T5） |
| M37 | 分发递进深度模型（L1→L4）+ 经理分发引擎 | ✅ | 设计：四层递进（L1声明→L2分发→L3触发→L3.5接单→L4工作交付），经理锁 L4 + 权限模型（docs/DISPATCH_DEPTH.md，总师）；落地：`local-agent/dispatch_engine.py`（L1声明/L2分发+投池+真实Issue/L3触发接力卡/L3.5接单回执/L4开工+goal_meters进度尺+交付）+ 差异化补强（深度俯瞰 by_depth + L4 action 路由执行 + 防跳层）+ `test_dispatch_engine.sh` 8 组测试，全绿（Issue #33）|
| M38 | 拓扑对比框架 · 多线路对比 + 长时间累积判断 | ✅ | `local-agent/topology/`：3 条拓扑（linear/dag/event）+ 对比执行器 + 指标持久化 + 长时间累积 + `test_topology_comparison.sh` 4 组测试 + `docs/TOPOLOGY_COMPARISON.md`（Issue #41）|
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

framework 模块（自升级，init）
    └── issue#11 type=upgrade module_version=v0.1.0  （框架自升级闭环：FRAMEWORK_UPGRADE.md + upgrade 类型 + 真实embedding + 文档一致性 + 看板健康度）

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

## 下一阶段（V0.3+ · 分工待办，见 Issue #33 分工卡）

框架 V0.3+ 壳已建（framework-shell / local-agent / scale / engine / data / collab / sentinel / dispatcher / probe / external-source / peer-collab / peer-closure）。当前真实待办按 T1~T5 分工派活：

- **T1 知识库充实**（🔴P0 / #6 / 架构·数据管理员+架构·开发）：docs/模板/声明头批量入库 + tag 触发 codewiki → RAG 检索可用（M32）。
- **T2 真实场景跑通验证**（🔴P0 / #4 / 架构·总师+架构·测试）：用 architect skill 跑真实需求，走完整八步留痕（M33）。依赖 T1。
- **T3 框架健康度审查**（🟠P1 / #11 / 架构·总师+架构·评审）：盘点 15 个 open issue，解决残留/关闭陈旧/整合双版本线（M34）。
- **T4 测试环境依赖加固**（🟠P1 / #8 / 架构·开发+架构·运维）：local-agent + functional-links 测试在云 CI 全绿；沙盒 vs 云环境差异文档化（M35）。
- **T5 看板/进度可视化持续维护**（🟡P2 / #7 / 架构·数据管理员）：DASHBOARD.md 随 issue 变更自动刷新（M36，已落地）。

> 依赖：`T1 → T2`；`T3/T4/T5` 相互独立可并行（DAG 非直线）。各任务带接力卡，仓库 agent 经 `@` 按 `[触发:角色]` 接单，成果按小组层层上报、看板自动可视化。
> **派活深度（Issue #33 拍板）**：派活须走「四层递进分发深度模型」（L1声明→L2分发→L3触发接单→L4工作交付），经理目标锁 L4——不只声明/分配/触发，要接单后**真正继续工作**（接单回执→开工→进度尺推进→交付）。详见 docs/DISPATCH_DEPTH.md。
> 环境提示：本沙盒缺 `python3` + cnb 云凭据，local-agent 12 项 + functional-links 13 项 + doc-consistency 2 项失败为**环境限制非代码缺陷**，须在云 CI 验证。
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
| 框架自升级闭环 | `docs/FRAMEWORK_UPGRADE.md` |
| 上位机定时器+状态机引擎 | `local-agent/engine/`（state_machine/timer/host/cli）+ `local-agent/tests/test_engine.sh` + `docs/HOST_ENGINE.md` |
| 调度中枢·事件驱动自动化调度 | `local-agent/dispatcher/`（source/rules/queue/router/guard/reject/webui/engine/cli）+ `local-agent/tests/test_dispatcher.sh` + `docs/DISPATCHER.md` |
| 外部事件源接入·多终端协同+安全 | `local-agent/dispatcher/`（security/webhook/sources/host_helper）+ `local-agent/tests/test_external_source.sh` + `docs/EXTERNAL_SOURCE.md` |
| 测试信号灯/脚本 | `tests/test_architect_system.sh`（静态断言） + `tests/test_functional_links.sh`（数据获取/看板呈现/RAG读取 真实功能链路） + `tests/test_relay_workflow.sh`（接力卡/回转/打断/三层触发 可复现） + `tests/test_memory_store.sh`（经验记忆库+语义向量触发+双后端兼容 可复现） + `tests/test_doc_consistency.sh`（文档-实现一致性 防漂移） |
| 分发递进深度模型（L1→L4）| 四层递进分发深度 + 权限模型 + 经理锁 L4 判定标准（见 `docs/DISPATCH_DEPTH.md`）|
| 验收清单 | `docs/templates/acceptance-checklist.md` |
