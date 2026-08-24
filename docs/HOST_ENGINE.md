# 上位机 · 定时器 + 状态机工程能力引擎（HOST_ENGINE）

> 对应 Issue #26「引入定时器和状态机，上位机的这些机器的角色，提升项目工程能力」。
> 模块归属：`host-engine`（`local-agent/engine/`），模块版本 `v0.1.0`。

## 一、为什么需要（背景）

此前，架构师 agent 体系的「接力链路状态流转」（`[触发]→产出→[回转]→返工→复评→…→🟢通过→回传`）
在 AGENTS.md / SKILL.md 里只是**文档约定**，靠 agent 自觉遵守；超时、卡死、续跑、状态机流转
都停留在「文字描述 + 静态测试断言」层面，**没有可运行的时序与状态内核**：

- 一个机器角色卡住了，没有**定时器**去巡检、超时报警、自动打断；
- 状态从「进行中」跳到「已通过」是否合法，没有**机器强制校验**；
- 「上位机（调度主控）」无法一眼俯瞰所有机器角色当前处于什么状态。

本模块把这两样东西落地为**可运行的工程组件**，让「上位机管理机器角色」具备真实的
时序调度 + 状态管控能力，工程能力从「约定」升级为「强制」。

## 二、核心概念

| 概念 | 说明 |
|------|------|
| **上位机（host）** | 调度主控台，统一管理其下每一台机器角色的时序与状态（`HostEngine`） |
| **机器角色（agent）** | 各协作角色实例（架构·秘书/产品/总师/经理/开发/评审/测试…）及其任务 |
| **状态机（state machine）** | 每台机器角色任务的状态卡，在**合法转移表**内流转，非法转移被拒 |
| **定时器（timer）** | 周期心跳巡检 / 超时检测 / 定时触发，驱动时序能力 |

## 三、状态机

### 3.1 状态集（机器角色生命周期）

| 状态 | 含义 | 对应协议 |
|------|------|----------|
| `pending` | 已创建待启动（调度主控分配） | — |
| `in_progress` | 正在执行（角色接手） | `[触发]` |
| `done` | 正常完成（信号灯通过 / 放行） | `[通过]` |
| `reverted` | 被打回，等待返工 | `[回转]` |
| `retry` | 返工重跑中 | 被打回角色重新触发 |
| `interrupted` | 被打断，留有续跑点（当前进度） | `[打断]` |
| `paused` | CP 闸门暂停，等待人类放行 | ⏸CP1/CP2/CP3 |
| `blocked` | 阻塞（回转超 3 次 / 超时未续跑），上报 | 上报总师/人类 |

### 3.2 合法转移表（机器强制，非法即拒）

```
pending      -> in_progress, blocked
in_progress  -> done, reverted, interrupted, paused, blocked
reverted     -> retry, blocked
retry        -> in_progress, done, reverted
interrupted  -> in_progress, paused, blocked
paused       -> in_progress, blocked
blocked      -> in_progress, paused
done         -> in_progress, reverted
```

任何不在表内的转移（如 `pending -> done`、`pending -> interrupted`）会直接抛出
`ValueError` 拒绝，杜绝"乱跳状态"。

### 3.3 语义化动作封装（对齐接力协议）

`StateMachine` 提供 `start / complete / revert / retry / interrupt / resume / pause / block`
语义方法，内部走合法转移表 + 每次转移自动留痕（谁/何时/从哪到哪/原因），供测试复现与人工俯瞰。

## 四、定时器

| 能力 | 说明 |
|------|------|
| 周期任务 `schedule(job, interval, fn)` | 每 interval 秒执行一次（心跳、周期刷新） |
| 一次性触发 `repeat=False` | 到点执行一次后自动移除 |
| 超时检测 `watch(card, sec, on_timeout)` | 状态卡超时未完成 → 自动 `[打断]` 或 `[阻塞]` |
| 心跳巡检 `tick()` / 后台线程 `start()` | 同步 tick 便于测试；守护线程模式供规模场景 |

超时是定时器与状态机的**关键联动**：机器角色卡在 `in_progress` 超过 deadline，
定时器自动把状态转移为 `interrupted`（留续跑点）或 `blocked`（上报），从"等人发现"升级为"机器主动告警"。

## 五、上位机整合（HostEngine）

把状态机 + 定时器统一装配到上位机：

```python
host = HostEngine()
host.start_role("架构·开发", card_id="dev_1")      # 机器角色上场
host.timeout_watch("dev_1", 0.02, reason="开发卡死") # 设超时
host.machine("dev_1").start(actor="上位机")          # [触发] 接手
for _ in range(50): host.tick()                     # 上位机统一巡检
print(host.overview())                              # 俯瞰所有机器角色状态
```

- `start_role`：让机器角色带任务状态卡上场；
- `tick()`：上位机统一巡检，把定时器（到期任务 + 超时）作用到所有机器角色；
- `overview()` / `summary()`：生成状态总表/统计摘要，供人工俯瞰（二级信息）。

## 六、目录与文件

```
local-agent/engine/
  ├── __init__.py         # 包导出（StateMachine / TimerEngine / HostEngine）
  ├── state_machine.py    # 状态机引擎：状态集 + 合法转移表 + 强制校验 + 留痕
  ├── timer.py            # 定时器引擎：周期/一次性任务 + 超时检测 + 心跳巡检
  ├── host.py             # 上位机运行内核：统一管理各机器角色状态与时序
  └── cli.py              # CLI：demo / transitions / state
local-agent/tests/test_engine.sh   # 7 组功能测试（纳入本地测试信号灯）
docs/HOST_ENGINE.md                # 本文档
```

## 七、与既有模块的对接

| 既有模块 | 对接方式 |
|----------|----------|
| `scale/store.py` 状态分片 | 状态卡默认复用 `scale.store`，落 `state/{card_id}.json`，与接力卡协议对齐 |
| 接力协议（AGENTS.md / SKILL.md） | 语义动作（start/complete/revert/interrupt…）一一映射到 `[触发]/[回转]/[打断]/[续跑]/[放行]` |
| 测试信号灯 | `test_engine.sh` 纳入 local-agent 测试体系 |
| 双版本管理 | 本模块独立 `module_version` 演进（见 ROADMAP 版本线） |

## 八、后续演进（roadmap）

- [ ] 与 `scale/pool.py` 并发池联动：超时回收卡死 worker；
- [ ] 定时看板刷新：用定时器驱动 `generate-dashboard.py` 周期更新；
- [ ] 超时策略可配置化（按角色不同 deadline / 重试次数自动升级为 blocked）。
