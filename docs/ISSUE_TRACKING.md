# 追踪问题 · agent-ready brief 链路（Issue #98 · 借鉴 mattpocock triage/to-tickets/wayfinder）

> **定位**：把本仓库的「追踪问题」从「有 Issue 声明头 + 双版本」升级为完整到可执行清晰度
> 的 **agent-ready brief 链路**——任何 agent 拿了 Issue 就能干，不被否的需求有记录防重复建议。
>
> **设计原则**（对齐 AGENTS.md「触发强制化/回转载断」）：
> 打磨 issue 到可执行清晰度；被否的需求显式记录（`.out-of-scope/`）；大块/未知工作用
> 「决策票地图」一次解一张探索。链路各环只做"把 issue 磨得更清楚 + 留痕"，不抢主流程。

## 一、链路总览：setup → triage → agent-ready brief → to-tickets → implement → wayfinder

```
  收到诉求
    │
    ▼
 [1 triage 分诊]  是谁的诉求？已否过？→ 用有限状态机打标
    │  ├─ wontfix（被否 / 不做）  → 记 .out-of-scope/（防重复建议）
    │  ├─ needs-info（信息不足）  → 回秘书/产品澄清（≤N 问），不猜测
    │  └─ ready（可执行）          → 进入 [2]
    ▼
 [2 agent-ready brief]  把 issue 磨到"任意 agent 拿了就能干"
    │   产出：一句话目标 + 明确做/不做边界 + 验收标准 + 前置依赖(depends_on) + 风险
    │   载体：Issue 声明头 + 正文（见 docs/templates/issue-template.md）
    ▼
 [3 to-tickets]（任务较大时）按示踪弹垂直切片拆票
    │   每张票声明阻塞边(blocking edges)→ 落 depends_on / DAG
    │   宽重构走 expand–contract（先扩接口再收敛）
    ▼
 [4 implement]  按架构·经理调度 → dev-standard → 评审 → 测试（主链路，本文档不复述）
    ▼
 [5 wayfinder]（超大/探索未知工作时）画一张"决策票地图"，一次解一张，直到路径清晰
```

## 二、triage：有限状态机（Issue 声明头 + 状态）

> 复用现有 Issue 声明头（`docs/templates/issue-template.md`）+ LabelAbility 的状态标签，
> 本链路只补 **wontfix / agent-ready brief** 两个缺口。

| 分诊态 | 含义 | 打标 | 去向 |
|---|---|---|---|
| needs-triage | 刚收到，待分诊 | LabelAbility `open` | 秘书/产品接 |
| needs-info | 信息不足 | `need_fix`+`blocked` | 回澄清（≤N 问，不猜测）|
| ready-for-agent | 已磨到可执行 | `at_node`+`ready` | 交给架构·开发/经理 |
| wontfix | 被否 / 明确不做 | `wontfix` | 记 `.out-of-scope/` |
| 分类（附加） | bug / enhancement | label | 辅助路由 |

**agent-ready brief（关键产出，任何 agent 拿了就能干）**：
- 一句话目标（target）；
- 做 / 明确不做（边界）；
- 验收标准（Given/When/Then 或可核验通过条件）；
- 前置依赖 `depends_on`（引用 issue 编号）；
- 风险与阻塞。

载体 = 复用现有 Issue 声明头 + 正文（见 `docs/templates/issue-template.md`），由
架构·秘书 / 架构·产品 在澄清阶段产出。

## 三、.out-of-scope/：记录被否需求（防重复建议）

> 模仿 mattpocock 的 `.out-of-scope/` 知识库：凡**被否 / 明确不做 / wontfix** 的需求，
> 在仓库 `.out-of-scope/<日期>-<简短slug>.md` 记一条，防未来再次建议做同一件事浪费周期。

条目模板：

```
# out-of-scope：<需求一句话>

- 日期：YYYY-MM-DD
- 提出：<来源>
- 为何否：<理由（成本/方向/已替代/超范围…）>
- 若未来重提应看：<替代方案 / 满足路径>
```

> 覆盖提醒：分诊到 wontfix 的 Issue，先把结论写进 `.out-of-scope/` 再打 wontfix 关闭，
> 形成闭环（防重复建议是 L2 分发的关键收益）。

## 四、to-tickets：垂直切片 + 阻塞边（任务较大时）

- **示踪弹垂直切片（tracer bullet）**：不是横铺全部功能，而是先打一条**端到端薄切片**
  验证技术可行性；一张票 = 一个最小可独立交付的垂直切片。
- **阻塞边（blocking edges）**：每张票声明它依赖哪些前置票，落 Issue 的 `depends_on`
  形成真实依赖链（复用 DAG / 分形引擎）。
- **宽重构走 expand–contract**：先扩出新接口（expand）让新旧并存，再收敛删旧（contract），
  避免一次性大改不可控。

## 五、wayfinder：超大 / 未知工作的决策票地图

- 当工作超过一次会话容量（超大块 / 探索未知而非执行已知）时，画一张**决策票地图**：
  节点=待决策的票，边=决策依赖；每次只解当前路径清晰的一张，解完刷新地图，直到路径清晰。
- 对应 AGENTS.md「wayfinder 探索未知」思路，落到本仓库 = 把一个超大 Issue 用 Issue 声明头
  + 分形小组拆成可独立解的票，由经理/小组长调度。

## 六、接进现有体系（不留孤儿）

- 声明头/双版本：`docs/templates/issue-template.md` + `docs/ISSUE_MANAGEMENT.md`；
- 状态标签：LabelAbility（`open/ready/done/wontfix/...`，见 `docs/LABEL_AUTOMATION.md`）；
- 依赖与并行：`depends_on` + DAG（`docs/FRAMEWORK_V2.md`）+ 分形（`docs/ROUTER.md`）；
- 澄清产出 brief：架构·秘书/产品（`roles/secretary.py` / `roles/product.py`）；
- 防重复建议：`.out-of-scope/`（本链路新增，已建目录留痕）。

## 七、与 mattpocock 对照表（差距收敛记录）

| mattpocock 能力 | 类别 | 我方升级前 | 我方升级后（本链路） |
|---|---|---|---|
| triage + agent-ready brief | 追踪问题 | 有声明头+双版本，无 brief 产出、无 wontfix 记录 | 声明头 + brief + wontfix/.out-of-scope 闭环 |
| to-tickets + blocking edges | 追踪问题 | 经理拆分 + DAG depends_on | 垂直切片 + 显式阻塞边 + expand-contract |
| wayfinder 决策票地图 | 追踪问题 | 无 | 决策票地图 + 分形小组承载超大未知工作 |
