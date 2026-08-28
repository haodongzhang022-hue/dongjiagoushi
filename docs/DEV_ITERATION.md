# 开发持续推进机制（Dev Iteration · 自循环推进）

> 本文件描述本仓库的「开发没开发完 → 继续接开发（自循环推进）」机制 ——
> 让开发在有明确任务目标时**持续推进、记录进度**，而不是每次回传都触发评审或经理
> 重新处理跟进；过程中只**存档记录**（非对话），干完**统一交付**给经理。
>
> 对应 Issue #74 用户原话；可执行载体 `local-agent/dev_iteration.py`。

---

## 一、问题：开发后只能接评审/经理，无法持续推进

用户原话要义：

> "开发后面不一定接的是评审或者经理，可能是没开发完，继续接开发，
> 但这里可能会导致陷入循环，我们有那个进度北极星的，不确定能不能管得住，
> 尝试一下，得有任务明确的情况下，持续的开发推进度，
> 不一定要触发经理，回传信息可能是记录，不一定得对话，先存起来，
> 干完一起给经理可能比较好，就像是过程中记录进度，而不是每次汇报都经理重新处理跟进。"

| 现状缺陷 | 本机制补什么 |
|----------|--------------|
| 开发没完成 → 只能交回评审/经理，无法自循环 | **开发自循环**：任务明确时可持续推进，不触发评审/经理 |
| 每次推进都汇报 → 经理反复被打扰 | **记录优先**：写 goal_meters + archives，不对话，经理不被打扰 |
| 自循环可能无限循环 | **哨兵拦截**：停滞/横跳/重复错误 → 打断，防失控 |
| 干完才交付 → 经理看零星产出 | **统一交付**：完成时一次性给经理完整进度记录 |

---

## 二、总体设计（开发自循环拓扑）

```
┌─────────────────────────────────────────────────────────────┐
│  人类 / 架构·总师 / 架构·经理（俯瞰 + 最终决策）               │
│         ↑ 干完统一交付（一次性通知，含完整进度记录）            │
└───────────────────────────┬─────────────────────────────────┘
                            │ deliver_to_manager()
┌───────────────────────────▼─────────────────────────────────┐
│        架构·开发（自循环推进）                                 │
│                                                             │
│  continue_dev()  开发自循环入口                               │
│    ├─ record_progress()  写 goal_meters + archives（非对话）  │
│    ├─ sentinel_check()   哨兵判定（停滞/横跳/重复错误）        │
│    ├─ can_continue()     判断是否可继续（任务明确+未完成+未拦截）│
│    └─ 完成 → deliver_to_manager() 统一交付                   │
└───────────────────────────┬─────────────────────────────────┘
                            │ 读 goal_meters / 写 archives
┌───────────────────────────▼─────────────────────────────────┐
│   data 数据层 + sentinel 哨兵（复用后端 + 统一口径）            │
│  goal_meters / archives / messages（新增复用，无新表）         │
└─────────────────────────────────────────────────────────────┘
```

### 模块清单

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `dev_iteration.can_continue()` | 判断是否可自循环（任务明确/未完成/未拦截） | task_key, goal_total, current | {can_continue, reason, distance} |
| `dev_iteration.record_progress()` | 记录一次推进（goal_meters + archives + 哨兵判定） | task_key, agent, target, goal_total, current, note | {record, sentinel} |
| `dev_iteration.continue_dev()` | 开发自循环入口（记录 + 判定 + 判断继续） | 同上 | {iteration, can_continue, sentinel, record} |
| `dev_iteration.run_iterations()` | 批量多轮自循环（供脚本/测试/自动化） | steps 列表 | 每轮 continue_dev 结果 |
| `dev_iteration.deliver_to_manager()` | 完成统一交付（归档 + 标记 done + 一次性通知经理） | task_key, agent, output | {status, progress_history} |
| `dev_iteration.handle_sentinel_hit()` | 哨兵命中处置（1级打断 / 2级上报） | task_key, agent, sentinel | {handled, level, action} |
| `dev_iteration.progress_history()` | 进度记录回放（供交付时给经理） | task_key | goal_meters 序列 |
| `dev_iteration.iteration_overview()` | 迭代俯瞰（二级信息） | — | 各任务进度/距离/状态 |
| `local-agent/tests/test_dev_iteration.sh` | 机制功能测试 | — | 信号灯 |

---

## 三、核心机制

### 1. 自循环前提：任务明确（北极星目标）

开发**只有任务明确时**才能自循环推进。判断标准：
- **goal_total > 0**：有北极星目标（如"10 步完成登录"）；
- **current < goal_total**：还未完成（还有剩余距离）；
- **哨兵未拦截**：无停滞/横跳/重复错误。

三者都满足 → 可 `continue_dev()` 自循环推进。
任一不满足 → `can_continue()` 返回 false，不能自循环：
- `goal_total <= 0` → 须先澄清北极星目标（不能盲目自循环）；
- `current >= goal_total` → 任务已完成，应交付而非继续开发；
- `sentinel_*` → 哨兵已拦截，须处置（打断/上报）。

### 2. 记录优先于对话（过程中不打扰经理）

每次推进，开发只做两件事：
- **写 goal_meters 进度尺**（`distance`/`delta`，供哨兵收敛判定）；
- **存 archives 记录**（`kind=dev_progress`，含本轮说明/细节/时间戳）。

**不投递对话消息**给经理/评审。经理在开发完成前**零打扰**。
记录先存起来，干完一起回放给经理看。

### 3. 哨兵拦截：防无限循环

自循环不会失控——靠哨兵判定（`sentinel.detect`）三类无效努力：

| 信号 | 判定 | 处置 |
|------|------|------|
| **stagnation 停滞** | 连续 N 次距离无变化 | 1级打断 + 重规划 |
| **oscillation 横跳** | 距离来回摆动不收敛 | 1级打断 + 重规划 |
| **repeated_error 重复错误** | 同一失败 note 重复 N 次 | 1级打断 + 重规划 |
| **progress_cap_stall** | 最大完成度封顶不再提升 | 1级打断 + 重规划 |

命中 1 级 → `handle_sentinel_hit()` 执行打断（发 `[打断]` + 依据剩余距离重规划）。
命中 2 级（同任务二度命中）→ 上报「架构·总师助理」评估局部调整，标 blocked。

**多道防线**：
- 哨兵判定拦截（核心，机器量化）；
- `max_iterations` 上限（单轮 continue_dev 最多 20 次，防脚本失控）；
- 完成即止（current >= goal_total → 建议交付）。

### 4. 完成统一交付给经理

开发完成（`current >= goal_total`）时，调用 `deliver_to_manager()`：
- **归档交付产物**（`kind=deliverable`）；
- **标记任务 done**；
- **投递一次性交付消息**给经理：含交付描述 + **完整进度记录回放**（progress_history）；
- **留痕交付事件**。

经理收到的是**干完一起给的完整交付**，而不是开发过程中的反复汇报。

---

## 四、与既有机制的关系

| 既有机制 | 本机制与它的衔接 |
|----------|------------------|
| 目标进度尺（docs/SENTINEL.md） | 复用 goal_meters 进度尺做收敛判定，本机制是它的"自循环推进"落地场景 |
| 分发四层深度（docs/DISPATCH_DEPTH.md） | 本机制是 L4 工作执行层的"持续推进"实现：开发接单后不是一次性交付，而是可持续推进 |
| 七层协作深度（docs/DEPTH_MODEL.md） | 本机制让开发在 L5（进度可控·自动维持）上能持续推进，不被"必须交回评审"阻断 |
| 回转/打断协议（AGENTS.md） | 哨兵命中打断复用 `[打断]` 协议，依据剩余距离重规划 |
| 数据管理层（docs/DATA_ARCHITECTURE.md） | 复用 archives/goal_meters/messages 表，无新表 |
| 防无效努力（docs/SENTINEL.md） | 本机制是"防无效努力"在开发自循环场景的显式应用 |

---

## 五、使用方法

```python
import dev_iteration

# ① 判断能否自循环
check = dev_iteration.can_continue("登录模块", goal_total=10, current=3)
# => {can_continue: True, reason: "ready", distance: 7}

# ② 开发自循环推进（每次调用记录一次进度）
res = dev_iteration.continue_dev(
    "登录模块", "ag-xxx", target="实现登录功能",
    goal_total=10, current=8, note="完成核心逻辑",
    archive_detail="实现了账号密码校验，通过了接口自测",
)
# => {can_continue: True, record: {distance: 2, ...}, sentinel: {hit: False, ...}}

# ③ 批量自循环（脚本/自动化）
results = dev_iteration.run_iterations(
    "登录模块", "ag-xxx", target="实现登录功能",
    goal_total=5, steps=[1, 2, 3, 4, 5],
    notes=["需求分析", "建表", "核心逻辑", "接口", "自测通过"],
)

# ④ 完成统一交付给经理
dev_iteration.deliver_to_manager(
    "登录模块", "ag-xxx", output="登录功能已实现，自测通过",
    issue_ref="#40",
)
# => {status: "delivered", progress_history: [...完整进度记录...]}

# ⑤ 哨兵命中处置
dev_iteration.handle_sentinel_hit("登录模块", "ag-xxx", res["sentinel"])
# => {handled: True, level: 1, action: "打断重规划（依据剩余距离重新分配）"}
```

---

## 六、落地清单

| 产物 | 位置 |
|------|------|
| 开发自循环引擎 | `local-agent/dev_iteration.py` |
| 功能测试 | `local-agent/tests/test_dev_iteration.sh` |
| 本文档 | `docs/DEV_ITERATION.md` |
| 规则落地 | `AGENTS.md`「开发持续推进机制」固定规则 |

---

## 七、一句话总结

**任务明确 → 开发自循环持续推进（记录进度不对话）→ 哨兵拦截防失控 → 干完统一交付给经理。**
让开发"没干完就继续干"，而不是每次回传都打断经理重处理；进度北极星管得住循环。
