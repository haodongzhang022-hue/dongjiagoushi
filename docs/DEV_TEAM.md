# 开发小组闭环机制（Dev Team · Issue #74 深化结构）

> 一句话：把「一个开发小组」（小组长 + N 个开发）作为**一个确定性编排的整体**，
> 一套循环 N 个开发（默认 2），全部产出通过客观验证后小组长才整合统一交付。
> 开发是真正持续推进度的核心，用确定性代码 + 进度北极星管住循环，防单 Agent 无限循环。

---

## 1. 背景与痛点

用户观察（Issue #74）：

- 开发是**真正持续推进度**的核心，辅助多则浪费——「一套 4 个」里真正干活推进度的
  是开发，辅助（评审/测试等）挤占名额就会让进度没多少、辅助很多。
- 开发没干完继续接开发 → 可能陷入循环；传统的「单 Agent 自己写码 + 自己判断是否
  完成」极易死循环、幻觉累积、目标漂移。
- 参考 Goose 等先进 Multi-Agent 框架：「执行-验证」必须分离、用确定性代码控制流程、
  设置硬性熔断，不信任单一模型自我纠错。

## 2. 设计目标

| 目标 | 落地 |
|------|------|
| 一套循环配 N 个开发 | `devs_per_team`（默认 **2**，可配 3/4） |
| 开发小组作为一个整体 | 小组长只在**全部 dev 产出 APPROVED** 后才整合交付 |
| 执行-验证分离 | dev 只负责做，合格与否由**客观验证器**（测试/lint）裁定 |
| 确定性状态机 | 不让 LLM 决定「下一步/是否结束」，`DevTeamEngine.decide()` 代码决定 |
| 硬性熔断 | 单 dev 重做超 `max_attempts` 上报 Leader；总迭代超 `max_iterations` 熔断；空闲超时判卡死 |
| 进度北极星监督 | 写 `goal_meters`，停滞/横跳/重复错误由监控哨兵拦截 |
| 记录优先于对话 | 过程只写进度留痕 + 存档，**不打断经理**；干完 `deliver_to_manager` 一次性交付 |

## 3. 架构分层

```
┌──────────────────────────────────────────────────────────────┐
│  DevTeamEngine（小组级确定性 Orchestrator）                    │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  小组长(team_lead)：拆解任务 / 整合产出                   │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │  dev[0] 开发闭环    dev[1] 开发闭环  ... N 个开发    │  │  │
│  │  │  execute→verify→rework(≤max_attempts)            │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  │  仅在「全部 dev 产出 APPROVED」后 → 小组长整合 → 统一交付  │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
  硬性熔断 + 进度北极星监督贯穿每一层
```

对照 Goose 四维闭环映射：

| Goose 角色 | 本体系落地 |
|:---|:---|
| Planner / Leader | 目标明确(goal>0)才进小组循环 + 小组长拆任务/定整合时机 |
| Coder / Executor | N 个「架构·开发」并行实现，只「做」不「判」 |
| Reviewer / Critic | 客观验证器（测试/lint 的 APPROVED/REJECTED） |
| Orchestrator / Router | **本引擎 `DevTeamEngine` 确定性状态机** |

## 4. 核心 API

### `local-agent/dev_team.py`

| 方法 | 作用 |
|------|------|
| `can_enter_loop()` | Planner 门控：goal>0 才允许进小组闭环 |
| `start_round(task_id)` | 小组长发起一轮（forming→executing），总迭代计数 |
| `developer_output(dev_id, ok, evidence)` | 某开发客观验证结果；REJECTED 重做计数，超 `max_attempts` 上报 |
| `decide()` | **确定性状态机决策**：全部 APPROVED→整合/DONE；否则 REWORK；超限→ESCALATED |
| `advance(delta)` | 推进小组进度（目标北极星），写 `goal_meters` |
| `check_idle_timeout()` | 空闲超时判定（卡死检测） |
| `deliver_to_manager()` | **一次性交付**给经理（进度回放 + 存档，经理零打扰） |
| `overview()` | 二级信息俯瞰（progress_pct / approved / devs 状态） |
| `run_single_round()` | 便捷函数：一轮确定性决策 |

### 确定性状态机判定规则

```
forming → executing（小组长发起一轮）
executing：按 dev 客观验证结果累计
  · 任一 dev REJECTED 且 attempts ≤ max_attempts → 继续 REWORK（该 dev 重做）
  · 任一 dev attempts > max_attempts → ESCALATED（上报 Leader 换方案）
  · 全部 dev APPROVED 且 remaining ≤ eps → DONE（可整合交付）
  · 全部 dev APPROVED 且 remaining > eps → INTEGRATE（进入整合阶段继续推进）
总迭代 > max_iterations → ESCALATED（硬性熔断）
```

## 5. 通用能力（全员挂载）

`DevTeamAbility`（`local-agent/dev_team_kit/`）挂载到**所有角色基类 `BaseRole`**，
任意 agent 直接可调：

- `create_dev_team(goal_total, devs_per_team=2)` → DevTeamEngine
- `run_dev_team_round(team, dev_outputs)` → 确定性决策
- `advance_dev_team(team, delta)` → 进度北极星推进
- `dev_team_overview(team)` → 二级信息俯瞰

`capability()` 返回 `dev_team_ability` 声明，`BaseRole.capability()` 自动汇总。

## 6. 防无效/防死循环三道防线

1. **哨兵判定**：`goal_meters` 进度尺，停滞/横跳/重复错误 → 命中即拦截。
2. **硬性熔断**：单 dev 重做超 `max_attempts`（默认3）上报 Leader 换方案；总迭代超
   `max_iterations`（默认20）熔断；空闲超 `max_idle_seconds`（默认1800s）判卡死。
3. **完成即止**：`remaining ≤ goal_eps` → DONE，建议交付。

## 7. 使用方式

```bash
# 信号灯测试
bash local-agent/tests/test_dev_team.sh

# 代码内
from dev_team import DevTeamEngine
team = DevTeamEngine(goal_total=10.0, devs_per_team=2)
team.start_round("登录模块")
team.developer_output("dev0", "登录模块", True, evidence="单测PASS")
team.developer_output("dev1", "登录模块", True, evidence="单测PASS")
decision = team.decide()          # DONE / INTEGRATE / REWORK / ESCALATED
team.advance(10.0)
team.deliver_to_manager(task_id="登录模块", summary="小组完成交付")
```

## 8. 测试覆盖（`test_dev_team.sh` 8 组信号灯）

1. 目标门控（goal<=0 拒绝 / goal>0 允许）
2. 一套循环 N 个开发（默认2 / 可配3 / 下限保护1）
3. 确定性状态机（未全APPROVED→REWORK / 全APPROVED→INTEGRATE / 未知dev拒绝）
4. 硬性熔断（重做超max_attempts→上报Leader / 总迭代超限→熔断）
5. 进度北极星监督（advance 推进 / goal_meters 落库 / remaining 收敛）
6. 记录优先于对话（统一交付 + 存档 + 经理零打扰）
7. 二级信息俯瞰（progress_pct / approved / devs 状态）
8. 通用能力挂载 + 透传（27 角色全员挂载 + 方法可用）

---

**一句话**：开发小组作为一个确定性编排的整体——一套循环 N 个开发，只做不判、
客观验证、超限熔断、进度北极星管住循环、干完统一交付给经理。

## 9. 接线驱动层（方案 A · 把 DevTeam 接成真实可跑链路）

> 能力已就绪但「流程缺失」——执行流水线此前没有任何一处调用 DevTeamEngine，
> 等于造了引擎没接线。本接线驱动层补齐总师方案 A 的 5 个接线点，让开发小组
> 闭环真正跑起来（Issue #74 深化）。

### 核心文件：`local-agent/dev_team_driver.py`

把 DevTeamEngine 接到真实执行流水线的**接线驱动层**。对外主入口 `DevTeamDriver`：

| 接线点 | 方法/位置 | 说明 |
|---|---|---|
| ① 建组入口 | `from_topology(topology, req, devs_per_team)` | 从拓扑 `lead`+`dev_N` 节点建 DevTeamEngine（dev 数取拓扑，默认 2） |
| ② 驱动循环 | `run_round(dev_outputs)` / `drive()` | 确定性状态机 execute→verify→decide，不让 LLM 决定 |
| ③ 进度北极星 | `advance(delta)` → `team.advance()` | 写 goal_meters，喂哨兵（停滞/横跳/重复错误拦截） |
| ④ 整合交付 | `deliver()` + `aggregate()` | 全部 APPROVED 后 deliver_to_manager + 收口信息 |
| ⑤ 路由/分形 | `orchestrator.run_pipeline` 的 lead 节点 hook | dev_enhanced 拓扑 lead 走驱动；agile/dag 不误触发 |

### 关键约定

- **dev 节点识别**：`dev_N` 必须严格匹配 `^dev_\d+$`（如 `dev_1`/`dev_2`）。
  单独的 `develop` 节点（id="develop"）**不算**开发小组成员，避免把 dag/agile
  的单个开发节点误判成小组成员。
- **目标门控**：goal<=0 拒绝进入闭环（目标未量化不空转）；未显式给定时
  `estimate_goal_total(req)` 按需求粗估。
- **消费防重**：驱动消费掉的 `dev_N` 节点被标记 `consumed_dev_nodes`，
  流水线跳过它们，避免下游重复 `_run_one`。

### 端到端验证

```bash
bash local-agent/tests/test_dev_team_driver.sh   # 6 组信号灯（建组/驱动/熔断/北极星/端到端/路由）
```

```text
▶ [DAG波次] [lead] 架构·小组长：任务细化/拆解（小组内 2 开发并行实现）
   [开发小组] 建组=2开发 目标=4.0 轮次=5 终态=DONE 进度=100.0% 交付=True
▶ [DAG波次] [dev_1] 架构·开发 …   [跳过] dev 节点 dev_1 已由开发小组闭环驱动消费
▶ [DAG波次] [dev_2] 架构·开发 …   [跳过] dev 节点 dev_2 已由开发小组闭环驱动消费
▶ [DAG波次] [review] 架构·评审 …  （仍执行）
▶ [DAG波次] [test]   架构·测试 …  （仍执行）
```

---

**一句话**：接线驱动层把「一套循环 N 个开发」从能力变成真实可跑链路——
经理派发 → 小组长 lead 节点建组驱动 → dev 确定性循环 → 全部 APPROVED 整合交付。
