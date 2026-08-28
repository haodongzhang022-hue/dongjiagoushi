# 开发闭环引擎（Dev Loop Engine）· Goose 四维闭环适配

> 本模块把「开发自循环」从「单 Agent 自己写码 + 自己判断是否继续/结束」升级为
> **确定性代码控制流程**，参考 **Goose** 的「执行-验证-规划-监督」四维闭环，
> 避免陷入死循环、幻觉累积或目标漂移。

## 为什么需要（单 Agent 循环的固有缺陷）

传统「单 Agent 无限循环」（如早期 AutoGPT）有三大致命问题：

1. **回声室效应**：自己写码又自己 review，容易「自圆其说」，发现不了自己的错误。
2. **隐式循环失控**：依赖 LLM 自主决定「是否继续」，极易无限重试、目标漂移。
3. **上下文污染**：长上下文导致注意力分散、token 浪费、幻觉累积。

**Goose 的解法**：**不信任单一模型的自我纠错能力**，而是用结构化角色强制引入
外部反馈，并用**确定性代码**（Orchestrator）控制流转。

## Goose 四维闭环 ↔ 本体系映射

| Goose 角色 | 职责 | 本体系落地 |
|:---|:---|:---|
| **Planner/Leader** | 任务分解、优先级、全局状态追踪；不参与编码 | `dispatch_engine`（目标明确 goal>0 才进循环）+ Leader 根据验证反馈调整策略 |
| **Coder/Executor** | 代码生成、工具调用、文件修改；只「做」不「判」 | 架构·开发（`dev_loop.start_iteration` 产出 diff/commit） |
| **Reviewer/Critic** | 独立于 Coder 的客观验证；有「否决权」 | 架构·评审 + 客观测试/工具（`dev_loop.verify` 用 `objective_verdict`） |
| **Orchestrator/Router** | 非 LLM 的确定性控制流转、异常处理 | **`DevLoopEngine` 本身**（确定性状态机，不靠 LLM 自决） |

## 核心机制

### 1. 执行-验证分离（最小有效多智能体单元）

- **Coder** 只负责「做」，产出代码/diff/commit；
- **Reviewer** 独立运行，用**客观结果**（测试/lint/静态检查）判定 `APPROVED/REJECTED`；
- **Coder 绝不自行裁定「我完成了」**——只有验证器 `approved=True` 才算通过。

```python
from dev_loop import DevLoopEngine
eng = DevLoopEngine(goal_total=10.0)
eng.start_iteration(task_id, agent_id, target="实现登录", note="Coder产出")
eng.verify(approved=True, evidence="test 8/8 pass, eslint clean", by="objective_verifier")
d = eng.decide(task_id, agent_id)   # → {'verdict': 'approved', ...}
```

### 2. 确定性状态机（不让 LLM 决定下一步/是否结束）

`DevLoopEngine` 即 **Orchestrator**（非 LLM 的确定性代码），控制流转：

```
idle → plan → execute → verify → (REJECTED→rework→execute) → (APPROVED→plan/done)
                                        ↑ 最多 max_attempts 次，超出→escalate 上报 Leader
```

**关键**：只有 `verify()` 返回 `APPROVED` 才放行进下一阶段；否则**强制回退**给
Coder 重做，最多 `max_attempts`（默认 3）次后**上报 Leader**（Goose：最多 N 次后
上报，Leader 重新评估方案如换算法，而非让 Coder 无限重试）。

### 3. 硬性熔断（防资源耗尽）

| 熔断项 | 默认值 | 作用 |
|:---|:---|:---|
| `max_attempts` | 3 | 同一子任务最多重做次数，超过上报 Leader |
| `max_iterations` | 20 | 一次闭环最多总迭代轮数（硬性上限） |
| `max_idle_seconds` | 1800 | 单轮最长空闲秒数，超时判卡死 |

熔断后 `leader_escalated=True`，禁止自行继续，等 Leader 决策。

### 4. 进度北极星监督（接哨兵）

- 每次 `start_iteration`/`verify` 自动写 `goal_meters` 进度尺；
- 监控哨兵据此判定**停滞/横跳/重复错误**，命中即打断，不再单 Agent 自循环失控；
- 进度**不可回退**（`advance(delta>=0)`），横跳由哨兵判定。

### 5. 记录优先于对话，干完统一交付

- 过程中只写进度留痕（goal_meters + archives），**不打断经理**；
- 干完调 `deliver_to_manager()` 一次性交付（含完整进度回放）；
- 未通过客观验证（非 APPROVED）不可交付——防止「我觉得完成了就交」。

## 使用方式

### 直接调用（脚本/CI/确定性编排）

```python
from dev_loop import run_single_round
decision = run_single_round("task-1", "架构·开发", 10.0, 2.0,
                            approved=True, evidence="test pass")
```

### 通过角色能力（全员挂载）

```python
from roles.developer import DeveloperRole
role = DeveloperRole()
eng = role.create_dev_loop(goal_total=10.0)        # Planner 门控
role.run_dev_loop("task-1", "架构·开发", 10.0, 2.0, True, "test pass")
role.dev_loop_overview(eng)                        # 二级信息俯瞰
```

## 改动文件

| 文件 | 说明 |
|:---|:---|
| `local-agent/dev_loop.py` | ⭐ DevLoopEngine 确定性状态机 + 硬性熔断 + 进度北极星监督 |
| `local-agent/dev_loop_kit/` | DevLoopAbility 通用能力封装（全员挂载） |
| `local-agent/roles/base.py` | BaseRole 挂载 dev_loop_ability + 透传方法 |
| `local-agent/roles/developer.py` | 开发角色 SYSTEM_PROMPT 补充开发闭环纪律 |
| `docs/DEV_LOOP.md` | 本设计文档 |
| `local-agent/tests/test_dev_loop.sh` | 7 组信号灯测试 |
| `AGENTS.md` | 「开发闭环机制」固定规则 |

## 测试

```bash
bash local-agent/tests/test_dev_loop.sh
```

7 组信号灯全绿：目标门控 / 执行-验证分离 / 确定性状态机 / 硬性熔断 / 最大迭代上限 /
统一交付 / 进度北极星监督。
