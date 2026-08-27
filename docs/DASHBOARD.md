# 📊 可视化 / 二级信息看板

> 本文件由 `scripts/generate-dashboard.py` **自动生成**，用于人类俯瞰决策。
> 数据源：仓库各 Issue 声明头（module / module_version / agent / agent_version / type / target / update / depends_on）。
> 版本强制：非整体版本，而是【模块版本 + agent 版本】双维度独立升版、以较小迭代单位推进（详见 docs/ISSUE_MANAGEMENT.md）。
> ⚠️ 请勿手动编辑本文件；刷新方式见文末「刷新指南」。

---

## 一、模块版本演进看板（module_version）

每个模块独立一条语义化版本线；看板显示「能力到哪版、当前待办是什么」。

### 模块 `arch-skill`

| Issue | type | 模块版本 | 目标 / 更新 | 状态 |
|-------|------|---------|-------------|------|
| [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) | 🔺 update | v0.2.0 | 拿一个真实架构需求，用 architect skill 完整跑通「调研→拓扑→可行性→方案→分工→协作→进度→索引→汇报」八步，验证链路流畅。 | 🟢 open |

### 模块 `dashboard`

| Issue | type | 模块版本 | 目标 / 更新 | 状态 |
|-------|------|---------|-------------|------|
| [#7](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/7) | 🆕 init | v0.1.0 | 基于每个 Issue 的声明头 | 🟢 open |

### 模块 `knowledge`

| Issue | type | 模块版本 | 目标 / 更新 | 状态 |
|-------|------|---------|-------------|------|
| [#6](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/6) | 🔺 update | v0.2.0 | 把 docs/、模板、关键决策文档入库 + 打 tag 触发 codewiki，让 @CodeBuddy/架构师对话能直接 RAG 检索到架构上下文。 | 🟢 open |

### 模块 `local-agent`

| Issue | type | 模块版本 | 目标 / 更新 | 状态 |
|-------|------|---------|-------------|------|
| [#16](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/16) | 🆕 init | v0.1.0 | 补齐本地 Agent 能力——无 @ 环境下用 CLI 承载云端触发，形成「需求→产品→架构→分工→协同→测试→交付」团队闭环 | 🟢 open |

### 模块 `memory`

| Issue | type | 模块版本 | 目标 / 更新 | 状态 |
|-------|------|---------|-------------|------|
| [#12](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/12) | 🆕 init | v0.1.0 | 将「经验记忆库 + 语义向量触发引擎」确立为独立模块，登记模块版本线 v0.1.0 根节点，纳入看板与版本管理闭环 | 🟢 open |

### 模块 `multirole`

| Issue | type | 模块版本 | 目标 / 更新 | 状态 |
|-------|------|---------|-------------|------|
| [#5](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/5) | 🔺 update | v0.2.0 | 把四个协作角色的人设补全为「可被架构·总师按接力卡召唤、各自按职责产出」的完整可执行人设 | 🟢 open |

### 模块 `testing`

| Issue | type | 模块版本 | 目标 / 更新 | 状态 |
|-------|------|---------|-------------|------|
| [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8) | 🆕 init | v0.1.0 | 建立测试体系，明确"信号灯"——只有功能真正达成预期才放行，否则不能过。建议覆盖： | 🟢 open |

---

## 二、Agent 角色版本演进看板（agent_version）

每个 agent 角色独立一条语义化版本线；看板显示「角色能力到哪版」。一个 Issue 只在一个最小迭代单位（单一模块 / 单一 agent）上升版。

### Agent `—`

| Issue | type | Agent版本 | 目标 / 更新 | 状态 |
|-------|------|----------|-------------|------|
| [#12](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/12) | 🆕 init | — | 将「经验记忆库 + 语义向量触发引擎」确立为独立模块，登记模块版本线 v0.1.0 根节点，纳入看板与版本管理闭环 | 🟢 open |

### Agent `架构·开发/架构·产品/架构·评审/架构·测试`

| Issue | type | Agent版本 | 目标 / 更新 | 状态 |
|-------|------|----------|-------------|------|
| [#5](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/5) | 🔺 update | v0.1.0 | 把四个协作角色的人设补全为「可被架构·总师按接力卡召唤、各自按职责产出」的完整可执行人设 | 🟢 open |

### Agent `架构·总师`

| Issue | type | Agent版本 | 目标 / 更新 | 状态 |
|-------|------|----------|-------------|------|
| [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) | 🔺 update | v0.2.0 | 拿一个真实架构需求，用 architect skill 完整跑通「调研→拓扑→可行性→方案→分工→协作→进度→索引→汇报」八步，验证链路流畅。 | 🟢 open |

### Agent `架构·总师 / 架构·产品 / 架构·开发 / 架构·评审 / 架构·测试`

| Issue | type | Agent版本 | 目标 / 更新 | 状态 |
|-------|------|----------|-------------|------|
| [#16](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/16) | 🆕 init | v0.1.0 | 补齐本地 Agent 能力——无 @ 环境下用 CLI 承载云端触发，形成「需求→产品→架构→分工→协同→测试→交付」团队闭环 | 🟢 open |

---

## 三、里程碑表（M0~M8）

> 里程碑状态需人工在 `docs/ROADMAP.md` 维护；此处根据已声明 Issue 的关键词自动标注落地线索。

| 阶段 | 内容 | 交付物 | 落地线索 |
|------|------|--------|----------|
| M0 | 调研 | 调研结论 | 状态 `调研结论（见 Issue #1 评论）` · 线索 [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) |
| M1 | 顶层架构拓扑 | docs/ARCHITECTURE.md | 状态 `docs/ARCHITECTURE.md` · 线索 [#7](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/7) |
| M2 | 可行性验证 | 参考仓库核验 + 官方文档核验 | 状态 `参考仓库源码核验 + 官方文档核验` · 线索 [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) |
| M3 | 工程实施方案（第一版骨架） | 目录结构 + 模块文件 | 状态 `本仓库目录结构 + 各模块文件` · 线索 — |
| M4 | 分工与协作规则 | AGENTS.md + settings.yml 扩展位 | 状态 `AGENTS.md + settings.yml 角色扩展位` · 线索 [#46](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/46), [#31](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/31), [#20](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/20), [#16](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/16), [#5](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/5), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) |
| M5 | 进度对齐（暂停点） | CP1/CP2/CP3 护栏 | 状态 `CP1/CP2/CP3 护栏` · 线索 [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) |
| M6 | 索引建立 | docs/ 索引 + 产物索引 | 状态 `docs/ 索引 + 产物索引` · 线索 [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8), [#6](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/6), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) |
| M7 | 真实场景跑通验证 | 用 architect skill 跑真实需求 | 状态 `用架构师 skill 跑一个真实架构需求` · 线索 [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) |
| M8 | Issue 声明与模块版本管理机制 | 声明头 + 类型表 + 版本线 | 状态 `声明头 + 类型表 + 版本线（见 docs/ISSUE_MANAGEMENT.md）` · 线索 [#20](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/20), [#16](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/16), [#12](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/12), [#7](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/7), [#6](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/6), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) |

---

## 四、Issue 声明汇总表（双版本）

| Issue | 模块 | 模块版本 | agent | agent版本 | type | 目标 | 依赖 | 状态 |
|-------|------|---------|-------|----------|------|------|------|------|
| [#51](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/51) | `—` | — | `—` | — | — | （未声明） | — | 🟢 open |
| [#46](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/46) | `—` | — | `—` | — | — | （未声明） | — | 🟢 open |
| [#42](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/42) | `—` | — | `—` | — | — | （未声明） | — | 🟢 open |
| [#39](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/39) | `—` | — | `—` | — | — | （未声明） | — | 🟢 open |
| [#31](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/31) | `—` | — | `—` | — | — | （未声明） | — | 🟢 open |
| [#26](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/26) | `—` | — | `—` | — | — | （未声明） | — | 🟢 open |
| [#25](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/25) | `—` | — | `—` | — | — | （未声明） | — | 🟢 open |
| [#23](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/23) | `—` | — | `—` | — | — | （未声明） | — | 🟢 open |
| [#20](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/20) | `—` | — | `—` | — | — | （未声明） | — | 🟢 open |
| [#18](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/18) | `—` | — | `—` | — | — | （未声明） | — | 🟢 open |
| [#16](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/16) | `local-agent` | v0.1.0 | `架构·总师 / 架构·产品 / 架构·开发 / 架构·评审 / 架构·测试` | v0.1.0 | init | 补齐本地 Agent 能力——无 @ 环境下用 CLI 承载云端触发，形成「需求→产品→架构→分工→协同→测试→交付」团队闭环 | #4 #15 | 🟢 open |
| [#12](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/12) | `memory` | v0.1.0 | `—` | — | init | 将「经验记忆库 + 语义向量触发引擎」确立为独立模块，登记模块版本线 v0.1.0 根节点，纳入看板与版本管理闭环 | #8 | 🟢 open |
| [#11](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/11) | `—` | — | `—` | — | — | （未声明） | — | 🟢 open |
| [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8) | `testing` | v0.1.0 | `—` | — | init | 建立测试体系，明确"信号灯"——只有功能真正达成预期才放行，否则不能过。建议覆盖： | 无 | 🟢 open |
| [#7](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/7) | `dashboard` | v0.1.0 | `—` | — | init | 基于每个 Issue 的声明头 | #8 | 🟢 open |
| [#6](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/6) | `knowledge` | v0.2.0 | `—` | — | update | 把 docs/、模板、关键决策文档入库 + 打 tag 触发 codewiki，让 @CodeBuddy/架构师对话能直接 RAG 检索到架构上下文。 | #8 | 🟢 open |
| [#5](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/5) | `multirole` | v0.2.0 | `架构·开发/架构·产品/架构·评审/架构·测试` | v0.1.0 | update | 把四个协作角色的人设补全为「可被架构·总师按接力卡召唤、各自按职责产出」的完整可执行人设 | #8 | 🟢 open |
| [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) | `arch-skill` | v0.2.0 | `架构·总师` | v0.2.0 | update | 拿一个真实架构需求，用 architect skill 完整跑通「调研→拓扑→可行性→方案→分工→协作→进度→索引→汇报」八步，验证链路流畅。 | #8 | 🟢 open |

---

## 五、待办 / 阻塞点扫描

当前 open Issue：**18** / 总 18。

| Issue | 标题 | 模块 | 阻塞线索 |
|-------|------|------|----------|
| [#51](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/51) | 标签增强，进度增强 | `—` | — |
| [#46](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/46) | 需要一个工作量可视化的功能 | `—` | — |
| [#42](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/42) | 高尔顿板 MVP 原型（Router+3Worker+Aggregator） | `—` | — |
| [#39](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/39) | 【测试】经理分配引擎测试 | `—` | — |
| [#31](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/31) | 层间协作 | `—` | — |
| [#26](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/26) | 引入状态机 上位机定时器 | `—` | — |
| [#25](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/25) | 防止系统无效努力 | `—` | — |
| [#23](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/23) | 数据架构升级 | `—` | — |
| [#20](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/20) | 继续用架构师，尝试优化本项目 | `—` | — |
| [#18](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/18) | 当前准备开发成一个体系，不只是一个agent就算完成本项目了 | `—` | — |
| [#16](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/16) | 支持本地agent和框架的明确 | `local-agent` | — |
| [#12](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/12) | 任务 F｜经验记忆库「孤儿模块」版本线补全（module: memory / init / v0.1.0） | `memory` | — |
| [#11](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/11) | 本项目几个issue已经提交了，你审核整合一下，看看还有没有问题 | `—` | — |
| [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8) | 任务 E｜测试体系落地（你强调的：功能正常才能过测试，没达成不让通过） | `testing` | ⏸ 暂停点 |
| [#7](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/7) | 任务 D｜可视化 / 二级信息看板自动化（人类俯瞰决策） | `dashboard` | — |
| [#6](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/6) | 任务 C｜知识库充实（让架构师"读信息条理全面"） | `knowledge` | — |
| [#5](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/5) | 多角色协作人设补全（协作角色从"占位"→"可执行"） | `multirole` | — |
| [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) | 真实场景跑通验证 | `arch-skill` | ⏸ 暂停点 |

---

## 六、版本合规 / 迭代冲突扫描（版本强制核查）

核查每张 Issue 是否满足「版本强制 + 双维度独立 + 较小迭代单位」：
- 未写明 `module_version`（模块维度）的 Issue；
- 涉及 agent 能力却未写明 `agent_version`（agent 维度）的 Issue；
- 疑似「跨维度/跨模块强推整体版本」、或依赖了未声明 Issue 的高合并冲突风险项。

| 核查项 | 缺省 Issue | 影响 |
|--------|-----------|------|
| 模块版本缺失（应写 `module_version`） | ✅ 无 | 看板无法显示模块版本线，无法版本管理 |
| agent 能力缺失 `agent_version` | ✅ 无 | agent 维度版本线缺失，无法追踪角色能力 |

---

## 六、框架健康度（framework 自升级维度）

> 框架整体 = AGENTS.md + .cnb.yml + SKILL.md + settings.yml + docs/ + src/memory/。
> 本维度把「框架自身」纳入版本演进，展示各模块/角色版本线 + 测试信号灯 + 待办升级项，供人类俯瞰框架健康（详见 docs/FRAMEWORK_UPGRADE.md）。

### 6.1 模块与角色版本线覆盖

| 维度 | 已覆盖版本线 | 说明 |
|------|-------------|------|
| 模块版本线 | `arch-skill`, `dashboard`, `knowledge`, `local-agent`, `memory`, `multirole`, `testing` | 各模块独立演进（module_version） |
| agent 版本线 | `—`, `架构·开发/架构·产品/架构·评审/架构·测试`, `架构·总师`, `架构·总师 / 架构·产品 / 架构·开发 / 架构·评审 / 架构·测试` | 各角色独立演进（agent_version） |
| 框架自升级线 | `framework` | 跨模块/方法论/测试红线整体升级（type=upgrade，见 FRAMEWORK_UPGRADE.md） |

### 6.2 测试信号灯

| 测试脚本 | 覆盖 | 状态(本地需自行运行) |
|---------|------|--------------------|
| test_architect_system.sh | 产物完整性/八步/CP护栏/触发强制化/回转打断 | ✅ 存在 |
| test_functional_links.sh | 真实功能链路（数据获取/看板/RAG） | ✅ 存在 |
| test_relay_workflow.sh | 接力/回转/打断 可复现 | ✅ 存在 |
| test_memory_store.sh | 记忆库+语义向量触发+双后端兼容 | ✅ 存在 |
| test_doc_consistency.sh | 文档-实现一致性（防漂移） | ✅ 存在 |

### 6.3 待办框架升级项

_当前无 open 的 framework 升级项。_

---

## 七、刷新指南

```bash
python3 scripts/generate-dashboard.py   # 重新生成 docs/DASHBOARD.md
```

可在 `.cnb.yml` 流水线中挂一个 job，在 `issue.comment@npc` / `issue` 事件后自动刷新本看板。
