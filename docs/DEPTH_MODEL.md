# 七层协作深度模型（Depth Model · L1→L7）

> 本文件描述本仓库从「协作能走多深」的**七层递进深度模型**——回答一个核心问题：
> **路由是否真唤醒了对端、协作是否真的推进到了结果，还是只是"嘴上说在推进"。**
>
> 对应 ISSUE #47 用户拍板：秘书/很多 agent 其实只在"描述"（L1），并没有真正触发
> 对面角色过来工作；路由并没有真实现唤醒。需要一个**可量化、可核验**的深度阶梯，
> 逐层确认"真的在推进"而不是"嘴上说在推进"。这是**通用能力**，做好后以独立模块
> 能力存在，给每个 agent 对接并让其会用。

---

## 一、问题：协作"有"不等于"真唤醒"

用户原话要义（Issue #47）：

> "比如秘书角色，刚才测试发现他其实只在描述，并没有触发 @产品过来工作，
> 甚至不能确认是否给那边传达了足够的内容……路由其实并没有真实现唤醒。"

很多 agent 的协作只停留在"表述/传达"（L1），并没有真正唤醒对端角色过来工作，
也没有推进到结果。光"说"不是"做"——需要可量化的深度阶梯逐层核验。

---

## 二、七层递进深度阶梯

| 层次 | 名称 | 含义 | 默认档位 | 关键可核验留痕 |
|------|------|------|----------|----------------|
| **L1** | **表述层** | 到对应角色拿到信息（仅表述/传达） | 秘书/多数 agent 现状 | `express()` 投递消息 |
| **L2** | **任务对接层** | 到对应 Issue 接到任务、匹配到 agent | — | `connect()` 落 Issue + gid |
| **L3** | **开工层** | 接受任务开始工作（含**路由真实唤醒**确认） | — | `awake()` 校验目标 agent 回执 `[接单]` |
| **L4** | **成果交互层** | 成果能和当前 agent 双向交互 | — | `interact()` 产物归档 + 反馈 |
| **L5** | **进度可控层** | 进度可控、可来回轮次触发、**自动化规则维持流程** | **多数 agent 达标** | `track_round()` + `auto_guard()` |
| **L6** | **持续到结果层** | 一套自动化持续到结果（收尾确认后交付） | **秘书目标档位** | `persist_to_result()` |
| **L7** | **全自动到结果层** | 全自动持续到结果，无需人工中断 | **体系目标档位** | `auto_run_to_result()` |

> **结论**：秘书/多数 agent 默认停在 **L1/L5**；用户的诉求是——**秘书推到 L6**，
> **体系推进到 L7**，中间的每层都要能核验"真的在推进"。

---

## 三、各层能力与用法（任意 agent 直接调用）

本能力挂载在 **BaseRole 全员**（`DepthAbility`），任意角色实例直接调用：

```python
role = get_role("架构·秘书")   # 或任意角色

# L1 表述：到对应角色拿到信息
role.express(task_key, "架构·产品", "有个需求需要产品澄清")

# L2 任务对接：落到 Issue + 匹配到 agent
role.connect(task_key, issue_ref="#99", role="架构·产品", domain="需求域")

# L3 路由真实唤醒：投接力卡 + 校验目标是否真回执 [接单]（核心！）
result = role.awake(task_key, "架构·产品", context="请澄清需求")
assert result["awakened"], "目标 agent 未回执——路由未真实唤醒，须重触发或升级"

# L4 成果交互：产出交付 + 消费方反馈（双向）
role.interact(task_key, "架构·开发", {"需求": "登录模块"})

# L5 进度可控 + 自动化规则维持流程
role.track_round(task_key, "完成登录", goal_total=5, current=2)
role.auto_guard(task_key, rule="converge_check")   # 收敛检查 / 停滞升级 / 超时重触发

# L6 持续到结果（秘书目标档位）
role.persist_to_result(task_key, milestones, role="架构·产品", need_human_gate=True)

# L7 全自动到结果（体系目标档位）
role.auto_run_to_result(task_key, milestones, role="架构·产品")
```

---

## 四、核心设计：路由真实唤醒（awake）

用户 Issue #47 的核心痛点是"**路由其实并没有真实现唤醒**"。`awake()` 不只投递消息，
还**校验目标 agent 是否真回执**：

1. **投递带 `[触发:<角色>]` 的接力卡**（确保传递足够内容，含 Issue、任务、上下文）；
2. **定向唤醒**目标 agent（消息管线 `depth.wake.<目标>`）；
3. **校验回执**：目标 agent 须回 `[接单]` / `awake_ack`，否则 `awakened=False`。

```python
result = role.awake(task_key, "架构·产品", context="请澄清需求", issue_ref="#99")
if not result["awakened"]:
    # 路由未真实唤醒——不能当"已传达"就完事，须重触发或升级
    ...
```

被唤醒方回执：
```python
role.ack_wake(task_key, role="架构·产品", note="收到，接管需求澄清")
```

---

## 五、防跳层 + 自动化维持 + 持续到结果

### ① 防跳层（不跳层空谈）
某层操作前须已满足前置深度，否则显式报错（`require_depth`）：
- L2 任务对接 → 先完成 L1 表述；
- L3 开工 → 先完成 L2 任务对接；
- L4 成果交互 → 先完成 L3 开工；
- L5 进度可控 → 先完成 L4 成果交互；
- L6 持续到结果 → 先完成 L5 进度可控；
- L7 全自动到结果 → 先完成 L6 持续到结果。

### ② 自动化规则维持流程（L5，`auto_guard`）
- `converge_check`：检查到北极星距离是否为 0（收敛判定）；
- `timeout_retrigger`：超过 N 轮无进度 → 自动重触发目标 agent；
- `stall_escalate`：命中哨兵停滞判定 → 自动升级，避免无效努力循环。

### ③ 持续到结果（L6/L7）
- **L6 `persist_to_result`**：按里程碑有序推进到结果，收尾可设 `need_human_gate=True`
  （秘书目标档位——一套自动推进，收尾确认后交付）；
- **L7 `auto_run_to_result`**：无需人工/授权中断，全自动闭环到结果（体系目标档位）。

---

## 六、俯瞰（depth_overview · 二级信息）

`depth_overview()` 按七层统计所有任务，回答"哪些真正走到了深层"：

```python
role.depth_overview()
# => { total_tasks, by_depth, reached_L6, reached_L7, detail }
```

| 档位 | 目标 | 说明 |
|------|------|------|
| L5 | 多数 agent 达标档 | 进度可控 + 自动规则维持 |
| **L6** | **秘书目标档位** | 一套持续到结果（收尾确认） |
| **L7** | **体系目标档位** | 全自动到结果（无需人工中断） |

---

## 七、能力归属

- **承载引擎**：`local-agent/depth/engine.py`（L1-L7 可执行引擎）；
- **能力封装**：`local-agent/depth/ability.py`（`DepthAbility`，全员挂载）；
- **全员挂载**：`BaseRole` 默认加载（任意角色 `express/connect/awake/.../auto_run`）；
- **秘书专项收口**：`SecretaryRole.route_wake()`（路由真实唤醒）+ `persist_to_result()`（L6）。

> 本能力是**通用能力**（非秘书/经理专属）：任何 agent 需要与对端协作、路由、
> 唤醒、持续推进到结果时，都直接调用——做好后以独立模块能力存在，全员对接并会用。
