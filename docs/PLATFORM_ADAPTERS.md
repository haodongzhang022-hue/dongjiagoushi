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

### 三.6.1 句柄自足 + 脑区判定（Issue #232 · module platform-adapter v0.3.1）

> 症状（用户实测）：本地发起的云开发请求，交付时**只带了一个桥接句柄 id**；本地服务一关，
> 云端**只剩 id，等于空手**——不知道在哪干活、做到哪算完、能不能动手。

**根因（三条，都不是"设计如此"）**：
1. **桥不是纯投递**：`request_cloud_dev` 的 docstring 写"一句话/多行均可"，但跨端实际传输的
   只有 `handle_id` + 首行 40 字的 `req_key`；上下文（目的/边界/验收/仓库/PR）全留在本地
   `_bridge_state/`，而该目录**本就不进版本库** → 云端读代码也读不到。
2. **假绿灯**：`local_test_first` 默认执行器是 mock，`run()` 恒返 `{"ok": True}`，且脚本不存在
   也不报错 → 云端会把"本地没跑"当"本地过了"。
3. **脑区是空话**：只有"本地/云端/hybrid"一个 `locus` 标签，没有按**动作**判定，云端不知道
   哪些做了算有效、哪些做了等于没做、哪些必须人工。

**落地**（`entries/bridge.py`）：
- `render_handle_card(handle, purpose/acceptance/scope_not/next_step/relaunch/role)`：
  **一个 id 重建全部上下文**的自足卡——含目的 / 验收 / 不做边界 / 所在仓库/entry/issue/PR /
  脑区（云端可做、必须本地、必须人工）/ 证据缺口 / 自检清单；**卡自带合规接力卡标记**
  （完整 `@org/repo(角色)` + `[触发:角色全称]`，直接过 `relay_card.check`），交付即合规不靠自觉。
- `verify_handle_card(text, handle_id)`：核验卡是否真自足（目的/验收/不做/仓库/句柄 id/触发标记），
  残卡逐项列缺——把用户遇到的"信息不全"变成**机器可拦**。
- `analyze_locus(actions, local_reachable)`：**脑区判定表**（`LOCUS_ACTION_TABLE` 唯一事实源）——
  按动作判「云端能做 / 必须本地 / 必须人工」，未知动作宁拦不放；并做**证据保全**：本地不可达时
  `evidence_available=False` + 缺口清单，绝不把"没数据"误读成"没问题"。
- `local_test_first(..., run=False)`：默认只出计划不假跑；`run=True` 走真实 `_shell_executor`，
  **rc 非 0 / 脚本不存在如实 `ok=False`**；本地不可达时 `cost_note` 明说"本轮无本地测试证据（≠通过）"。
- `mark_relaunch(handle_id)`：本地可达后翻正脑区与证据。
- CLI：`--bridge render|verify|relaunch`（+ `--to-role` / `--card-file` / `--bridge-run`）。
- 测试 `local-agent/tests/test_bridge_handle_selfcontained.sh`（10 项信号灯）。

**交付形态结论（回答"第一次交付要不要带全信息"）**：
**要**。但"带全"不等于"带很多"——带的是**能重建上下文的骨架**（目的/边界/验收/在哪/脑区），
10 行左右、可机器校验；不是把整段对话搬过去。桥只负责"投递"时，一次断链就全断；
句柄自足后云端**不只可以操作，还能判断该不该操作、在哪操作**。
### 三.7 跨端聚合控制页（最常用链路深化 · module platform-adapter v0.4.0）

> 背景：用户（Issue #105）点名「做一个方便控制的聚合，类似于 fastapi 聚合页包括状态显示，
> 然后每个端我都尝试建立一个，这样跨端交互的就会更加顺畅」。v0.3.0 桥接闭环已跑通；
> 本轮给**跨端交互加一块聚合控制面**——像 FastAPI /docs 那样一个地址看到各端状态 +
> 一键控制，不用逐个入口翻状态、不用记每条 CLI。

**落地**：新增 `local-agent/entries/dashboard.py`（跨端聚合控制页能力），宿主无关、统一
从三端适配器（web/cnb/local）+ 本地⇄云端桥接句柄 + 接力卡 + 成本模型聚合出一张控制台：

- `snapshot()`：全端聚合大盘（三端适配器矩阵 + 句柄按状态归集 + 接力卡 + 成本模型），
  FastAPI 风格路由键 + 健康状态灯（🟢/🔴），`health/overview/handles/relay/entry/{e}/
  control/{action}` 可读；
- `panel(entry)`：**每端一个面板**（web/cnb/local）——同一聚合器按端过滤出「本端视角」：
  本端适配器 + 本端发起的桥接句柄 + 本端可用控制动作（local 端含 localtest/align，
  cnb 端含 request/collect…），跨端则看 total 大盘；
- `all_panels()`：三端面板并列（跨端顺畅交互总览，每端都建一个）；
- `control(action,...)`：**一键控制动作**（request / collect / align / localtest / handles /
  overview…）——复用 bridge 真实状态机流转，非假状态（control 不只是一块看板，能真操作）；
- `html_page(entry=None)`：**人可读 HTML 聚合控制页**（状态灯 + 适配器矩阵表 + 句柄状态表 +
  一键控制表单），供人类浏览器俯瞰 / 网页桥嵌入；
- `run.py` 新增 `--dashboard action` + `--dashboard-html` + `--dashboard-pr-ids`，全链 CLI 可调。

**与「一套核心 + 每端适配层」同构**：聚合不另起数据，三端都从同一份 snapshot 过滤，跨端
交互顺畅、不散点状态；「每个端一个面板」延续三入口每端适配器思路，每端只维护本端视角。
测试 `local-agent/tests/test_dashboard.sh`（12 项信号灯）。

### 三.8 真实本地实测通道（v0.5.0 · entries.cnb_live — 模拟数据不可信 → 真实传输）

> 背景：用户（Issue #105）明确点破 mock 的局限——「**使用模拟数据的我们一般认为是不可信的**，
> 所以你开发完成这一部分之后，下一步就要尝试去用**本地实测**了。**发送信号尝试做配合**，
> 看看能不能达成好的效果，不行的话，然后去做适配。」v0.3.0 bridge / v0.4.0 dashboard 默认走
> **本地模拟传输（mock transport）**，只能证明「协议/状态机对」，不能证明「真实跨端配合能达成」。
> 本轮把默认传输从 mock 升级为**真实 cnb.cool 通道**（cnb CLI / git remote 驱动），发真实信号做配合。

**落地**：新增 `local-agent/entries/cnb_live.py`（真实 cnb.cool 传输通道），可注入 bridge /
dashboard 的 transport 抽象，把「云开发请求 → 云端异步开发 → 产出回传」从**模拟**提升为**真实信号配合**：

- `live_transport()`：真实通道字典 `{name:'live-cnb', send, poll, ack}`，可注入 `bridge.request_cloud_dev`
  与 `collect_cloud_result`；
- `send()`：真实发信号——request 时在目标仓库**真实创建云开发请求 Issue** 作 cloud_ref 锚
  （复用既有 issue_id 则发真实信号评论），走真实 `cnb issues create-issue / post-issue-comment`；
- `poll()`：真实读云端——`cnb issues get-issue` 读真实 Issue state/comment_count，据此判
  `done`（云端收尾/有回执）/ `in_progress`（云端仍在异步开发），**不臆造 PR 列表**（真实 PR
  关联由 collect 时开发者显式填）；
- `ack()`：真实回执——collect 完成后给云端 Issue 发真实**结果回执评论**（留痕、闭环）；
- `probe()`：**通道探测**（用户要的「发送信号尝试配合」落点）——默认只读（list-issues + list-pulls，
  证明通道可达、**不污染仓库**），`send_signal=True` 才真实建一次信号 Issue；
- `default_transport()`：**默认真实**——有真实 cnb CLI → live-cnb（用户：模拟数据不可信），
  无 cnb CLI → mock 兜底（单测/本地无 cnb 环境），mock 显式标注不骗人；
- `cli_live()`：`run.py --live probe / probe-send / transport` 语义入口。

**与 mock 的取舍（用户诉求优先）**：
- **默认真实**：`bridge.request_cloud_dev(..., live=True)` / run.py `--bridge request`（默认 live）/
  dashboard `control('request')`（自动探测真实）都走真实通道；
- **单测保留 mock**：`live=False`（bridge 函数默认）仍走 mock，保单测确定性、不污染真实仓库
  （test_cnb_live.sh 6 项全绿）；真实信号由 CLI/dashboard 的真实使用发出。

**跨端聚合页真实化**：dashboard `snapshot()` health 现含 `live_transport`（真实通道可达性探测），
`transport_default` 显示 live-cnb/mock——控制台不再是「看起来 ok 的假状态」，health 红灯即真实
通道不可达（诚实暴露，不假装成功）。

**常驻 HTTP 服务（上轮 PR #113 点名的候选）**：`run.py --serve <port>` 把聚合控制页挂可常驻
HTTP 服务（标准库 http.server，FastAPI /docs 式，零重依赖）——`GET /` HTML 大盘、`GET /entry/{e}`
某端面板、`GET /api` JSON 快照、`GET /api/health`、`POST /api/control` 一键控制，浏览器直接开。

**真实信号配合实证（本地实测，2026-09-07）**：在本工作区（有真实 cnb CLI）完整跑通真实闭环——
真实 request 在 dongdongxiaozu/dongjiagoushi **真实创建 Issue #124** 作 cloud_ref 锚（transport=
live-cnb）→ 真实 poll 读云端 #124（open+comment=2）判 done → collect collected/merged →
真实 ack 给 #124 发结果回执评论 → align_local 本地 relay/data 双向对齐。**真实通道达成配合**；
channel 受限则 probe 如实降级暴露，不假装成功。

测试 `local-agent/tests/test_cnb_live.sh`（6 项信号灯）+ 注册进 hybrid BUILTIN_CPU_SCRIPTS。

### 三.9 三宿主真实传输注册表（v0.6.0 · entries.host_transport — 最常用闭环真实宿主两端补齐）

> 背景：用户最常用闭环 = **本地 deepseek harness ⇄ 网页/gemini 工具桥 ⇄ cnb.cool 云端异步开发**。
> v0.3~v0.5 把 cnb.cool 云端端做成真实通道（cnb_live），但闭环另两端仍只有 mock 假"投递到云端"。
> 本轮补齐——形成**三宿主传输注册表**，全程**真实机制不 mock 假装**，每宿主实现同一
> `{send, poll, ack}` 传输契约，可注入 `bridge.request_cloud_dev` / dashboard：

**落地**：新增 `local-agent/entries/host_transport.py`：
- `hosts()`：三宿主清单（cnb-live/local-harness/web-bridge）；
- `resolve_host(alias)`：别名归一到三端之一——网页/gemini/web→`web-bridge`；本地/deepseek/harness/
  dsh→`local-harness`；cnb/云端→`cnb-live`（不写死、别名收敛）；
- `host_transport(name)`：返回对应宿主真实 transport——**cnb-live**（真实 cnb CLI，复用 cnb_live）/
  **local-harness**（真实 relay 接力卡落盘+可续跑可回放）/ **web-bridge**（真实 HTTP 通道：本仓
  `run.py --serve` 的 `/api`+`/api/control` 即网页桥可达端点）；未知宿主如实报错不静默 mock；
- `overview()`：三宿主真实可达性矩阵（cnb CLI 在→cnb-live🟢；relay 可读写→local-harness🟢；
  --serve /api 可探测→web-bridge🟢）；
- `bridge_via(req, via)`：经指定真实宿主发起云开发请求，得真实桥接句柄。

**接入**：
- `run.py --bridge via-overview`：看三宿主可达矩阵；`--bridge request --bridge-via <host>`：经指定
  真实宿主发起云开发；
- dashboard `snapshot()` 增 `hosts` 三宿主真实矩阵，与既有三端适配器/桥接句柄同盘聚合；
- 测试 `local-agent/tests/test_host_transport.sh`（10 项信号灯）+ 注册进 hybrid BUILTIN_CPU_SCRIPTS。

**真实不 mock**：local-harness `send` 真实写 relay 接力卡（含 relay.save 落盘）、`poll` 真实读卡状态、
`ack` 真实落回执历史——本地 deepseek harness 发的云开发请求可续跑、可回放，不再是假"投到云端"。

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
- **当前落地状态（Issue #171 · module mcp-hub v0.1.0）**：本仓已有的四个 MCP 面
  （`dsh-adapter` 桥 / `dev_standard/host.py` / `dispatcher/webhook.py` 的 roster / `label`、
  `relay_card` 的 CLI 管线）已收口到 `local-agent/mcp_hub/`——**一张端点登记表 + 一个统一入口**：
  `catalog()` 说清「哪个端点、哪些工具、跑没跑起来」，`launch()` 一次调用拉起服务并回探活回执，
  服务同时提供三前端（`POST /message` / `GET /sse` / `POST /jsonrpc`）而**能力集合完全一致**。
  未接线的能力如实返回 `not_wired` / `http_only` / `external_host` / `operator_required`，
  不代调、不回假绿。详见 `docs/MCP_HUB.md`。

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
| 真实 cnb.cool 传输通道（live） | `local-agent/entries/cnb_live.py` |
| 跨端聚合控制页（含 --serve） | `local-agent/entries/dashboard.py` |
| 三宿主真实传输注册表（v0.6.0） | `local-agent/entries/host_transport.py` |
| MCP 汇聚注册表（端点+h工具统一入口） | `local-agent/mcp_hub/specs.py` + `docs/MCP_HUB.md` |
