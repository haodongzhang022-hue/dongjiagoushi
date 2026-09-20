# Hybrid 公交车式批量测试计划执行器（BusRunner）

> Issue #90 收尾 · 云/本地协同降核时 · 公交车（Bus）模型
> 模块：`local-agent/hybrid/bus.py` · 测试：`local-agent/tests/test_hybrid_bus.sh`

## 一、要解决的问题

测试"非常消耗核时"的根因，往往不是测试本身跑的 CPU 运算，而是 **每次单独拉起
一个测试都伴随一次冷启动构建**（docker + pip install + 环境初始化 = 固定开销）。
37 个测试若各自单独跑、各唤醒一次构建（尤其跨 Issue/PR 多次"跑 1 个关闭再唤醒
构建很久再跑"的串行乒乓），固定开销被 N 次放大 → 核时暴涨（37 测试约 696 核·分钟）。

## 二、方案：公交车（Bus）模型

把"测试运行请求"当作**乘客**，测试执行当作**班车**：

1. **入列（0 成本）**：测试需求先 `enqueue` 进队列，绝不立即拉起构建。
   —— 乘客在站台等车，车没来不空耗。
2. **定时发车**：按固定**发车间隔**（默认 15 分钟 = 900s）检查——
   - 队列**非空** → 发一班车：把队列里**全部**待跑测试作为**一批计划**，
     在**同一进程 / 同一构建环境**内整批跑完（一次冷启动摊到全批）。
   - 队列**为空** → **不发车**（没有空闲空转的构建浪费）。
3. **整批收尾**：一批跑完统一 sync 留痕 + cost 报表 + quota 记账，然后清空队列。

**核心收益**：无论多少个测试，只要攒到一起，一次构建全跑完；间隔内没需求就
不起任何构建。固定开销从「N 次单独构建」收敛到「每班车 1 次」，核时大幅下降，
也避免反复唤醒构建的等待。

```
乘客(测试需求) ──enqueue──▶ 站台队列 ──到点非空(15min)──▶ [一批计划]
                                                            │
                                         同一执行器整批跑完 ◀┘
                                                    │
                               sync留痕 + cost报表 + quota记账 → 清空队列
（空队列 → 不发车，不空转）
```

## 三、CLI 用法

```bash
# 0) 环境
export PYTHONPATH="$PWD/local-agent"

# 1) 把一批测试投进队列（0 成本，等发车）
python3 -m hybrid.cli bus enqueue local-agent/tests/test_scale.sh \
        local-agent/tests/test_engine.sh local-agent/tests/test_probe.sh

# 2) 看站台信息（队列/下一班车倒计时）
python3 -m hybrid.cli bus status

# 3) 定时哨兵（cron/CI 每 interval 调一次）：到点且非空才发车，空车不发
python3 -m hybrid.cli bus tick            # 演练(dry)
python3 -m hybrid.cli bus tick --real     # 真实跑

# 4) 立即整批发车（把队列全部作为一批计划，一次构建跑完）
python3 -m hybrid.cli bus dispatch --real
```

发车默认参数：`--interval 900`（15 分钟）、`--parallel 4`、`--timeout 600`。
`--dry` 演练模式不真跑，仅产出等效汇总（安全审计用）。

### 攒批去重门（`--diff-fp` · Issue #150 返工加固）

`--diff-fp <指纹>` 让"同一变更指纹"不重复触发构建。三条硬约束（缺一即 false green）：

1. **无指纹不占门**：不传 `--diff-fp`（或评审侧 `diff_summary` 缺省）→ 视为**无指纹**，
   不去重、不写门；**绝不**退化为空串常量哈希（`sha256:e3b0c44298fc`）而让无关任务被静默跳过；
2. **演练不写穿**：`--dry` 发车**不写**持久化去重门（`gate_written=False`）——
   演练没真跑测试，写门会让后续真实执行被静默跳过；
3. **只记本批实际携带**：只把**本批实际携带**的指纹（队列条目自带 ∪ `--diff-fp`）写入门；
   **空队列发车不写任何门状态**（返回 `carried_fps=[]` / `gate_written=False`）。

> 去重粒度是**测试粒度**：同一测试已在队列中不重复入列；**同指纹的不同测试仍各自入列**
> （指纹只作跨批次门，不吞掉别的测试）。

### 运行时状态不进版本库（Issue #150 返工 S11）

`.bus_queue.json`（攒批队列，含去重门记忆）/ `.quota_ledger.json`（配额账本）是**运行时状态**，
已纳入 `.gitignore` 并从版本库移除——否则去重门记忆会**跨机器"继承"**，导致本机真实测试被
别的机器留下的指纹静默跳过。

## 四、程序化接口

```python
from hybrid.bus import BusRunner, default_bus

b = BusRunner(interval=900)          # 默认 15 分钟一班
b.enqueue(["local-agent/tests/test_scale.sh",
           "local-agent/tests/test_probe.sh"])   # 入列（0 成本）
v = b.should_dispatch()              # 到点 + 非空 = True
plan = b.dispatch()                  # 整批发车：一批计划跑完 + 收尾 + 清空
# plan = {dispatched, summary{total/pass/fail/wall_seconds},
#         finish{synced, cost{net_save}, quota}, queued_cleared, history_count}

# 定时哨兵（云端 cron / CI 定时器每 interval 调一次）
result = b.tick()   # {"action": "wait", ...} 或 {"action": "dispatch", ...}
```

## 五、攒批收益如何体现到成本账本

- `dispatch()` 收尾阶段自动调 `CostMonitor` 出 `cost` 报表，把「本批本地化/整批跑
  完省下的云端核时」计入 `net_save`；
- 再把 `net_save` 汇入 `QuotaGuard.credit_localized()` **抵扣云端月度账本**，
  与 Issue #90 M6 quota-guard 口径（核·分钟）统一。
- 每班车的运行记录写入 `history`（时间 / 测试数 / pass / fail / 墙钟），供审计俯瞰。

## 六、与 M1-M6 / CloudBatch 的关系

| 机制 | 职责 | 与 Bus 的关系 |
|------|------|--------------|
| M4 build-cache | 变更指纹缓存，未变跳过 | Bus 整批跑时天然可跳过已缓存项，Bus 负责"批"调度、cache 负责"批内"去重 |
| M6 quota-guard | 月度核时账本 + 三态哨兵 | Bus 收尾把整批 net_save 汇入 quota 抵扣 |
| CloudBatch | 把**云端任务**攒批提交 Issue（防频繁唤醒 LLM） | Bus 把**测试运行**攒批为一次构建（防反复构建唤醒）——同为"攒批防浪费"，一个治云端 LLM 唤醒、一个治本地/云端测试构建 |
| M5 review-gate | 评审 ≤5 轮熔断 | 评审触发的多次测试也建议走 Bus 攒批，一次构建覆盖多轮评审回归 |
| M1-M3 station/replay | 站点锚定防版本漂移 | Bus 发车前可选做站点锚定，保证"跑在正确基线"上 |

## 七、文件

```
local-agent/hybrid/bus.py          公交车式批量测试计划执行器（核心）
local-agent/hybrid/cli.py          bus enqueue/status/dispatch/tick 子命令
local-agent/hybrid/__init__.py     导出 BusRunner / default_bus
local-agent/hybrid/.bus_queue.json 攒批队列（首次运行自动生成 · 已 gitignore，不进版本库）
local-agent/tests/test_hybrid_bus.sh  自含信号灯（19 项）
docs/HYBRID_BUS.md                 本文件
```

> 该模块是**纯逻辑 + 子进程执行**，不依赖数据层；状态落本地 JSON，与
> quota/batch/station 同目录习惯，可独立演进、跨项目抽取复用。
