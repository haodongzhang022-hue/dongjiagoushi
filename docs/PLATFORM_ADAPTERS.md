# 跨平台适配方案（PLATFORM_ADAPTERS）

> 本文件描述架构师体系的**跨宿主平台适配方案**：把核心协作抽象为「统一活动规则」，各宿主（cnb.cool / deepseek harness / MCP 蜂群）通过适配层接入，做到「一套体系，多宿主运行」。
> 背景：用户诉求"参考蜂群调度 agent / MCP 项目，通过提交 Issue 的形式适配 cnb.cool 和 deepseek harness，并有对应的活动规则适配"。

---

## 一、为什么需要统一活动规则

架构师体系的核心协作能力（角色团队 / 接力卡 / DAG 调度 / 分形扩展 / 触发协议）是**与宿主无关**的：

- **角色**：`架构·秘书 / 产品 / 总师 / 经理 / 小组长 / 开发 / 评审 / 对齐 / 找工具 / 测试` + `市场·销售/客服/数据/渠道/工具`——定义在 `settings.yml` + `roles/*.py`；
- **接力卡**：任务书 + 输入上下文 + 当前进度 + 下一步 + 接手角色 + 输出契约——`relay.py`；
- **DAG 调度**：节点 + 依赖 + 并行波次——`graph.py`；
- **分形扩展**：开发按规模分形多小组——`fractal.py`；
- **触发协议**：显式 `[触发]` / 语义 / rules 固定 + `[回转]`/`[打断]`。

把这些**与宿主解耦**后，任何宿主只需提供一个「触发 + 上下文 + 反馈」的适配层，即可复用整套体系。这借鉴了 **MCP（Model Context Protocol）**「统一协议 + 多实现」与**蜂群调度 agent**「统一编排 + 个体可扩展」的设计思想。

---

## 二、统一活动规则（各宿主共同遵守）

1. **同一套角色**：不因宿主不同而另起炉灶；`settings.yml` / `roles/*.py` 为唯一事实源。
2. **同一套接力卡**：五要素（任务书 / 输入上下文 / 当前进度 / 下一步 / 接手角色 + 输出契约）任一宿主可读。
3. **同一套 DAG 调度**：`graph.py` 拓扑排序 + 波次并行，跨宿主一致。
4. **同一套触发协议**：显式 `[触发:<角色>]` 优先 / 语义命中 / rules 兜底。
5. **同一套回转/打断**：`[回转] 退回:X / 原因 / 下一步要求` 打回重做；`[打断]` 留续跑点续跑。

---

## 三、宿主适配矩阵

| 宿主 | 触发形式 | 适配层 | 活动规则映射 |
|------|---------|--------|-------------|
| **cnb.cool（当前，原生）** | Issue/PR 评论 `@CodeBuddy` | 原生集成（当前路径，零额外） | 接力卡 = Issue 评论内嵌结构化卡片；`[触发]/[回转]/[打断]` = 评论标记 |
| **deepseek harness** | 本地 harness 驱动 agent | `local-agent/` 作为 harness 的 agent 团队；`run.py` 为入口脚本 | `team.yaml` DAG + 角色库直接被 harness 逐节点调度；接力卡落到 `state/relay_card.json` |
| **MCP（蜂群）** | MCP 工具调用 | 把团队流水线暴露为 MCP 工具（`dag_run` / `role_invoke` / `swarm_scale`） | 接力卡 → MCP 会话上下文；DAG/分形 → MCP 资源/工具；`[触发]` → 工具参数；蜂群 agent 通过标准协议调用 |

---

## 四、各宿主适配详解

### 4.1 cnb.cool（原生，当前）
- **现状**：本仓库已原生支持——`@CodeBuddy` 加载 architect skill，走架构八步；协作角色靠接力卡（Issue 评论内嵌卡片）+ 三层触发。
- **适配成本**：零（本就是宿主）。
- **扩展点**：Issue 声明头（module/agent 双版本）是 cnb.cool 特有的版本治理能力，其他宿主可借鉴但非必须。

### 4.2 deepseek harness
- **定位**：把 `local-agent/` 直接当作 harness 的一个「agent 团队」。
- **接入方式**：
  ```bash
  # 在 harness 中调用本地团队流水线（含 DAG + 分形 + 秘书入口）
  python local-agent/run.py --pipeline full --req "<需求>" --backend openai_compat
  ```
- **活动规则适配**：harness 逐节点调度时，读取 `team.yaml` 的 `dag`（或回退 `steps`），每个节点执行对应角色模块；接力卡持久化到 `state/`，支持 `--resume` 续跑（对应 `[打断]`）、`--role` 单角色触发（对应 `[触发]`）。
- **要点**：harness 的「任务分发 / 上下文传递」直接复用 `orchestrator.py` + `relay.py`，无需重写。

### 4.3 MCP（Model Context Protocol）蜂群调度
- **定位**：把体系能力包装成 MCP 服务器暴露的工具，供蜂群 agent（可多个并行）通过标准 MCP 协议调用。
- **建议暴露的 MCP 工具**：
  | 工具 | 作用 | 对应活动规则 |
  |------|------|-------------|
  | `role_invoke(role, task)` | 触发单角色执行 | `[触发:<角色>]` |
  | `dag_run(req)` | 跑完整 DAG 流水线 | DAG 调度 |
  | `swarm_scale(tasks, group)` | 分形扩展多小组并行 | 分形引擎 |
  | `card_read()/card_write()` | 接力卡读写 | 接力协议 |
  | `revert(card, to, reason)` / `interrupt(card, progress, next)` | 打回 / 续跑 | `[回转]` / `[打断]` |
- **要点**：MCP 把「接力卡」映射为「会话上下文 / 资源」，把「DAG / 分形」映射为「工具调用」，蜂群 agent 各司其职、通过工具协作，天然契合本体系的「多角色 + 并行 + 分形」。
- **落地节奏**：先统一活动规则（本文件），后续按需用官方 MCP SDK 包一层（作为 M19+ 迭代）。

---

## 五、适配层通用接口（供各宿主实现）

任何宿主只需实现以下最小接口即可接入：

```
trigger(role, task)      # 触发：把 任务 + 角色 交给团队
read_card() / write(card) # 接力卡读写（进度/回转/打断）
run_dag(req)             # 跑 DAG 流水线到交付
scale_swarm(tasks, n)    # 分形扩展到 n 个小组
```

---

## 六、索引

| 产物 | 位置 |
|------|------|
| 本适配方案 | `docs/PLATFORM_ADAPTERS.md`（本文件） |
| DAG 引擎 | `local-agent/graph.py` |
| 分形引擎 | `local-agent/fractal.py` |
| 本地入口（harness/CLI） | `local-agent/run.py` |
| 团队/DAG 配置 | `local-agent/team.yaml` |
| 角色库 | `local-agent/roles/*.py` |
| 接力卡 | `local-agent/relay.py` |
