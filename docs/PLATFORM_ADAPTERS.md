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

## 三.5 三入口归一化落地（Issue #105 · module platform-adapter v0.2.0）

> 背景：用户提出「网页对话 / cnb.cool / 本地 AI 三个，谁当入口」的架构疑问。结论：
> **三入口不是 3 个产品，是「入口 + 执行地」的组合**，收敛为「一套仓库 + 多层适配 +
> 配置管差异」，不拆 3 个仓库。

**主入口主从规则**：三入口都是「把话送到秘书面前」的通道，**主入口永远一个「架构·秘书」
（→路由）**，其余只是触达方式。`guard_entry` 强制护栏已落地——default/company/acquisition/
support 系模板强制经秘书；harness 内嵌因调用方已定角色允许直入产品。

**代码落地**：新增 `local-agent/entries/`（Issue #105 适配层模块）：
- `adapter.py`：宿主无关 `HostAdapter` 抽象 + 三入口具体适配器（`CnbAdapter` cnb.cool 原生 /
  `LocalAdapter` 本地 harness / `WebAdapter` 网页），各自实现最小宿主接口
  `trigger / read_card / write / run_dag / scale_swarm`（`run_dag`/`scale_swarm` 委托单份核心
  编排 orchestrator/fractal，核心仅一份、无入口 if 分支污染）；`ENTRY_LOCI` 配置承载
  入口→(适配器/执行地/profile)。
- `route.py`：入口归一化路由 `resolve_entry/entry_guard/route`——把任意入口别名
  （网页/cnb.cool/本地 run.py…）收敛为规范入口 web/cnb/local，经秘书主入口护栏后落位适配器；
  `overview()` 提供三入口归一化矩阵 + 主入口护栏二级俯瞰。
- `run.py` 新增 `--entry web|cnb|local` 与 `--platform-overview`：入口归一化后继续走单份核心编排。

**执行地分工**：本地 vs 云端执行走 `docs/CLOUD_LOCAL_COOP.md` 边界，由适配器 `locus` 配置承载
（web=hybrid / cnb=cloud / local=local），非逻辑硬编码。

### 三.6 本地⇄云端桥接闭环（最常用链路深化 · module platform-adapter v0.3.0）

> 背景：用户点名**最常用链路**是「本地 deepseek harness ⇄（网页/gemini 工具桥）⇄ cnb.cool
> 云端做异步开发 → 云端产出回传本地对齐 → **本地测试先行**（云端建环境贵，本地 CPU 便宜）」。
> v0.2.0 把三入口归一层做好了；本轮把**这条最常用闭环链路**做成可执行能力。

**落地**：新增 `local-agent/entries/bridge.py`（本地⇄云端桥接闭环能力），复用一个
「本地 ⇄ 云端桥」通道（cnb.cool=原生接力卡/Issue 评论；web/gemini 工具桥=同一套桥协议）：

- `request_cloud_dev(req, entry)`：本地/web 发卡 → 云端**异步开发**，返回**桥接句柄**
  （CloudDevHandle，带 gid，跨对话/跨 PR 稳定寻址、二次触发取回同一句柄不漂移）；
- `collect_cloud_result(handle_id, cloud_state, pr_ids)`：云端产出（merged/done/need_fix +
  PR 列表）**跨 PR 归集**收集；need_fix（评审打回）如实记录供续跑，不吞异常；
- `align_local(handle_id)`：云端产出**回写本地**（relay 接力卡 + data 归档 + messages 消息），
  双向对齐，本地 harness/网页桥读同一份本地对齐后状态；
- `local_test_first(handle_id)`：**本地测试先行门**——识别 CPU 密集/长耗时测试下放本地执行
  （skipped_cloud_build=True），降云端建环境成本（用户点名的主要成本点）；
- `loop_overview()`：闭环状态俯瞰（句柄按状态归集 + 四步闭环步骤）。
- `run.py` 新增 `--bridge request|collect|align|localtest|overview` + `--handle/--collect-state/
  --bridge-pr-ids`，全链 CLI 可调。

**成本模型**：云端建环境贵 → CPU 密集测试下放本地（对齐 `CLOUD_LOCAL_COOP.md`），云端只保留
LLM 强相关 + 评审；本地测试先行让长时云端开发（跨对话/跨 PR/跨仓库）的验收不等云端重复建环境。
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
- **当前落地状态（2026-08-30）**：适配插件 `@dsh-dongjiagoushi/adapter`（`dsh-dongjiagoushi-adapter/`，workspace 内）已装配为 DSH web profile bundle（含白名单注册），暴露 21 个工具：
  - dev-standard 6（standard.list/get/enforced/summary/check/report）+ label 13（progress/status/labels/apply/remove/propose/review/auto/depends/next/priority/node/specs）；
  - collab 协作层 10 个（新增）：`collab.roles/resolve`（角色目录）、`relay.write/read/list`（接力卡五要素，落盘 `state/relay/`）、`issue.list/read/comment`（本地 Issue 留痕）、`memory.store/query/keys`（跨会话记忆）。
  - Agent Directory：`dsh-collaboration-rules.yaml` 已注册 @架构·秘书/总师/经理/开发/评审/交付 6 个外部 agent（endpoint=local），DSH 会话可直接 @ 触发。
  - 协作范式映射：CNB「Issue 评论接力卡 + [触发:X]」→ DSH「relay.* + collab.roles + issue.comment」；跨文件夹 = 绝对根目录（DONGJIAGOUSHI_ROOT）下 repo/issues/state 三区；记忆 = memory.* 本地 KV（可后续接 LanceDB）；PR = git remote（cnb.cool）经 pwsh git 操作。
  - 待办：dispatch（四层分发）、depth（七层深度）、peer（同岗协作）、sentinel（哨兵）引擎尚在 Python local-agent，下一迭代接桥或移植。

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
| 三入口适配层（web/cnb/local） | `local-agent/entries/` |
