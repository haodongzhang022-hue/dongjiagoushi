# 执行体槽位池 · NPC_SLOT_POOL（近因优先 + 长队列 + 领取后自愈）

> 对应用户原话（PR #247，2026-10-25）：
>
> > 「他不止一次这样了，这个池子让他有个近因效应吧，最新的优先领取，这样即使卡住也不会一直卡，
> > 最多卡一下，以及加长队列，然后领取一个后，尝试把其他接上，这样自动修了。」
>
> 承载：`local-agent/slot/pool.py`（module **slot-pool** v0.1.0）+ CLI `python -m slot.cli`
> + 信号灯 `local-agent/tests/test_slot_pool.sh`（8 组）。
> 配置单一事实源：`.cnb.yml` → `npc_task.slot_pool`。

---

## 一、病根：一个卡住的活把并发额度长期占住

上一轮实测（PR #247 评论）已经把「@ 了角色没反应」定位清楚了：

- 同一秒起两条 NPC 构建，两条都停在 `npc go` 的 `start`，`duration=0` —— 一次模型调用都没发生；
- 更早那条同类构建**跑完了，用了约 6 分钟**；
- 也就是说：**有活占着执行体，排队的活等位**。

这本来还算"排队"，真正让它变成"一直卡"的是**取件顺序**：

```
FIFO（旧行为）：  最早入队的最先被领
   [ 卡住的老任务 ] ← 一直占着并发额度
   [ 后来的活b ]  ← 永远等
   [ 后来的活c ]  ← 永远等
```

一个卡住的老任务，只要它不释放，后面的**一个都出不来**。这就是「他不止一次这样了」的机制层面原因
——不是态度，是**池子的取件顺序 + 队列太短**。

---

## 二、三条规则（都是确定性的，不靠自觉）

| # | 规则 | 治什么 | 为什么这么定 |
|---|------|--------|--------------|
| ① | **近因优先**（recency-first / LIFO）：取件取**最新入队** | 「卡住就一直卡」 | 卡住的活只卡**一次**：它被跨过后留在队里等自愈，池头永远是最新那件，出活不被老任务压住 |
| ② | **加长队列**（`queue_capacity`，默认 512） | 小队列 + 阻塞 = 池子立刻见底 | 跨过卡住的任务需要位置；队列长一点，后面才有地方排 |
| ③ | **领取后自愈**（`reserve()` 内建 `repair_rest`） | 「得人一个个去捞」 | 领走一件活后，顺带把同样 stuck 的其它活重新入队，自动接上 |

**这三条是一组的**：只做①，卡住的活会被跨过但没人管；只做②，池子变大但还是被压住；
只做③，卡住的活还在池头。合起来才是「最多卡一下，然后自动修」。

---

## 三、状态机（三类数字必须分开看）

```
queued ──pick──▶ picked ──reserve──▶ running
                                       │
                  ┌────────────────────┼────────────────────┐
                  ▼                    ▼                    ▼
              done(交付)         stuck(超时未释放)       dead(自愈超限)
                                       │
                             repair_rest 重新入队
                                       │
                                    queued（可再被取）
```

`overview()` 把状态分开报，**不混成一个"都挺好"**：

```json
{
  "stats": {"queued": 3, "running": 1, "stuck": 0, "dead": 0, "done": 12, "rejected_full": 0},
  "capacity_left": 509,
  "slots_free": 3,
  "needs_action": 0,
  "stuck_detail": [],
  "order_policy": "recency-first（最新入队优先，卡住的只卡一次）"
}
```

- `queued` = 还在等（正常）
- `running` = 在跑（正常）
- `stuck` / `dead` = **要处置的**（`needs_action`）
- `rejected_full` = 队列满被拒的件数（**显式计数，不静默丢件**）

---

## 四、接口（可被 dispatcher / 平台适配层调用）

```python
from slot import SlotPool, pool_from_config

pool = pool_from_config()          # 读 .cnb.yml 的 npc_task.slot_pool（CI/本地同源）
pool.enqueue("tk-8271", kind="npc")   # 入队（同 task_id 幂等，不重复占位）
r = pool.reserve()                 # 近因优先领一件 + 自动接回其它 stuck
#   → {"task": Task, "slot": 0, "repairs": ["tk-9090"], "blocked": False}
pool.release(r["task"].task_id, ok=True)      # 成功交付（释放槽位）
pool.mark_stuck("tk-8271")                    # 卡住（等下一次自愈接回）
pool.sweep_stuck()                            # 超时仍 running → 判 stuck（不静默挂着）
pool.overview()                               # 二级信息俯瞰
```

关键语义：

- `reserve()` **默认内建自愈**（`auto_repair=True`），不依赖调用方记得去调；
- 槽位满 → `blocked=True` + `task=None`，**显式暴露，不假装领到**；
- 队列满 → `enqueue()` 返回 `None` 并累加 `rejected_full`，**不静默丢件**；
- 自愈次数上限 `max_repairs` 兜底，超限标 `dead` 并写 `note`（要上报/换方案）。

---

## 五、配置（单一事实源在 `.cnb.yml`）

```yaml
.npc_task: &npc_task
  slot_pool:
    queue_capacity: 512         # 队列长度（加长，卡住的任务也放得下后面的活）
    slots: 4                    # 可同时占用的执行体槽位（≈ 云端 NPC 并发额度）
    stuck_after_seconds: 300    # 占用超时判 stuck 的门槛，秒
    max_repairs: 3              # 同一件活最多被自动接回几次，超限标 dead
```

CI（`.cnb.yml`）和本地引擎（`slot.pool.load_npc_pool_config()`）**读同一份**，不在代码里另写一套
——否则两边一改就漂移，测试测的是假的那套。读不到配置时**退化为默认并在 `source` 标 `defaults`**（不冒充读到）。

核验：

```bash
cd local-agent && python3 -m slot.cli config     # 看生效配置与来源
```

---

## 六、诚实边界（必须写清，不夸大）

| 能做 | 做不到 |
|------|--------|
| 池子里**取谁、卡住后怎么接回**——确定性实现，可单测 | **云端执行器的物理并发额度**改不了：`slots` 只是本层视角，真实排队仍受平台限制 |
| 队列加长、满则显式计数 | 队列也不是无限：满了就是满，会 `rejected_full++` |
| 卡住的活最多接回 `max_repairs` 次 | 反复卡死的活终究会 `dead`，需要**上报/换方案**（本层只负责把它显式暴露出来，不假装修好） |
| `overview()` 让"卡住的到底是谁"可见 | `stuck` 判定依赖 `stuck_after_seconds` 与真实释放回调，调用方不许"领了不 release" |

**这不是在说"排队问题解决了"**。它解决的是「一个卡住的活把整个池子长期堵死」这个具体病根，
把「一直卡」降级为「卡一下 + 自动接回 + 超限显式报警」。

---

## 七、信号灯

```bash
bash local-agent/tests/test_slot_pool.sh      # 8 组，全绿才算接上
```

1. 近因优先取件（`fifo` 仅作对照，证明顺序真的换了）
2. 卡住不堵：首件卡住后仍能继续领，且跨过了卡住的那件
3. 领取后自愈接回 + 超 `max_repairs` 显式 `dead`（不静默重试）
4. 长队列容量 + 满则显式拒绝计数 + 同 id 幂等入队
5. 槽位满显式 `blocked`（不假装领到）
6. 占用超时判 `stuck`（不静默挂着）
7. 配置同源：`.cnb.yml` 是唯一事实源 + 缺失时诚实退化
8. 端到端：10 件活 + 首件卡住，池子不空转

> 第 8 组的意义：它跑的是"卡一下之后还能继续出活"，而不是"FIFO 一定更差"——
> `test_slot_pool.sh` 不去编造「近因优先交付更多」这种不存在的优势（那取决于每件活卡多久）；
> 它证明的是**池头不被压住 + 卡住的活会被接回 + 超限会显式暴露**。
