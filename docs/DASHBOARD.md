# 📊 可视化 / 二级信息看板

> 本文件由 `scripts/generate-dashboard.py` **自动生成**，用于人类俯瞰决策。
> 数据源：仓库各 Issue 声明头（module / type / version / target / update / depends_on）。
> ⚠️ 请勿手动编辑本文件；刷新方式见文末「刷新指南」。

---

## 一、模块版本演进看板

每个模块独立一条语义化版本线；看板显示「能力到哪版、当前待办是什么」。

### 模块 `arch-skill`

| Issue | type | 版本 | 目标 / 更新 | 状态 |
|-------|------|------|-------------|------|
| [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) | 🔺 update | — | 拿一个真实架构需求，用 architect skill 完整跑通「调研→拓扑→可行性→方案→分工→协作→进度→索引→汇报」八步，验证链路流畅。 | 🟢 open |

### 模块 `dashboard`

| Issue | type | 版本 | 目标 / 更新 | 状态 |
|-------|------|------|-------------|------|
| [#7](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/7) | 🆕 init | — | 基于每个 Issue 的声明头（module/type/version）自动汇总出模块版本演进看板 + 里程碑表，让人类一眼看到"各模块能力到哪版、卡在哪"。 | 🟢 open |

### 模块 `knowledge`

| Issue | type | 版本 | 目标 / 更新 | 状态 |
|-------|------|------|-------------|------|
| [#6](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/6) | 🔺 update | — | 把 docs/、模板、关键决策文档入库 + 打 tag 触发 codewiki，让 @CodeBuddy/架构师对话能直接 RAG 检索到架构上下文。 | 🟢 open |

### 模块 `multirole`

| Issue | type | 版本 | 目标 / 更新 | 状态 |
|-------|------|------|-------------|------|
| [#5](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/5) | 🔺 update | — | 把四个协作角色的人设补全为「可被架构·总师按接力卡召唤、各自按职责产出」的完整可执行人设（参考架构·总师的人设深度），并验证角色间能传接力卡、上下文不偏差。 | 🟢 open |

### 模块 `testing`

| Issue | type | 版本 | 目标 / 更新 | 状态 |
|-------|------|------|-------------|------|
| [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8) | 🆕 init | — | 建立测试体系，明确"信号灯"——只有功能真正达成预期才放行，否则不能过。建议覆盖： | 🟢 open |

---

## 二、里程碑表（M0~M8）

> 里程碑状态需人工在 `docs/ROADMAP.md` 维护；此处根据已声明 Issue 的关键词自动标注落地线索。

| 阶段 | 内容 | 交付物 | 落地线索 |
|------|------|--------|----------|
| M0 | 调研 | 调研结论 | 状态 `调研结论（见 Issue #1 评论）` · 线索 [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4), [#1](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/1) |
| M1 | 顶层架构拓扑 | docs/ARCHITECTURE.md | 状态 `docs/ARCHITECTURE.md` · 线索 [#7](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/7), [#1](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/1) |
| M2 | 可行性验证 | 参考仓库核验 + 官方文档核验 | 状态 `参考仓库源码核验 + 官方文档核验` · 线索 [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4), [#1](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/1) |
| M3 | 工程实施方案（第一版骨架） | 目录结构 + 模块文件 | 状态 `本仓库目录结构 + 各模块文件` · 线索 — |
| M4 | 分工与协作规则 | AGENTS.md + settings.yml 扩展位 | 状态 `AGENTS.md + settings.yml 角色扩展位` · 线索 [#5](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/5), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4), [#1](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/1) |
| M5 | 进度对齐（暂停点） | CP1/CP2/CP3 护栏 | 状态 `CP1/CP2/CP3 护栏` · 线索 [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4), [#1](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/1) |
| M6 | 索引建立 | docs/ 索引 + 产物索引 | 状态 `docs/ 索引 + 产物索引` · 线索 [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4), [#1](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/1) |
| M7 | 真实场景跑通验证 | 用 architect skill 跑真实需求 | 状态 `用架构师 skill 跑一个真实架构需求` · 线索 [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) |
| M8 | Issue 声明与模块版本管理机制 | 声明头 + 类型表 + 版本线 | 状态 `声明头 + 类型表 + 版本线（见 docs/ISSUE_MANAGEMENT.md）` · 线索 [#7](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/7), [#6](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/6), [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) |

---

## 三、Issue 声明汇总表

| Issue | 模块 | type | 版本 | 目标 | 依赖 | 状态 |
|-------|------|------|------|------|------|------|
| [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8) | `testing` | init | — | 建立测试体系，明确"信号灯"——只有功能真正达成预期才放行，否则不能过。建议覆盖： | — | 🟢 open |
| [#7](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/7) | `dashboard` | init | — | 基于每个 Issue 的声明头（module/type/version）自动汇总出模块版本演进看板 + 里程碑表，让人类一眼看到"各模块能力到哪版、卡在哪"。 | — | 🟢 open |
| [#6](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/6) | `knowledge` | update | — | 把 docs/、模板、关键决策文档入库 + 打 tag 触发 codewiki，让 @CodeBuddy/架构师对话能直接 RAG 检索到架构上下文。 | — | 🟢 open |
| [#5](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/5) | `multirole` | update | — | 把四个协作角色的人设补全为「可被架构·总师按接力卡召唤、各自按职责产出」的完整可执行人设（参考架构·总师的人设深度），并验证角色间能传接力卡、上下文不偏差。 | — | 🟢 open |
| [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) | `arch-skill` | update | — | 拿一个真实架构需求，用 architect skill 完整跑通「调研→拓扑→可行性→方案→分工→协作→进度→索引→汇报」八步，验证链路流畅。 | — | 🟢 open |
| [#1](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/1) | `—` | — | — | （未声明） | — | 🟢 open |

---

## 四、待办 / 阻塞点扫描

当前 open Issue：**6** / 总 6。

| Issue | 标题 | 模块 | 阻塞线索 |
|-------|------|------|----------|
| [#8](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/8) | 任务 E｜测试体系落地（你强调的：功能正常才能过测试，没达成不让通过） | `testing` | ⏸ 暂停点 |
| [#7](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/7) | 任务 D｜可视化 / 二级信息看板自动化（人类俯瞰决策） | `dashboard` | — |
| [#6](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/6) | 任务 C｜知识库充实（让架构师"读信息条理全面"） | `knowledge` | — |
| [#5](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/5) | 多角色协作人设补全（协作角色从"占位"→"可执行"） | `multirole` | — |
| [#4](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/4) | 真实场景跑通验证 | `arch-skill` | ⏸ 暂停点 |
| [#1](https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/1) | 探索架构师能力，和设计方向 | `—` | — |

---

## 五、刷新指南

```bash
python3 scripts/generate-dashboard.py   # 重新生成 docs/DASHBOARD.md
```

可在 `.cnb.yml` 流水线中挂一个 job，在 `issue.comment@npc` / `issue` 事件后自动刷新本看板。
