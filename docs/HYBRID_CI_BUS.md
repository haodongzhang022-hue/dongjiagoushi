# 云端 CI 整批测试执行（Cloud CI Bus · Issue #93）

> 版本：v1.1 · 对应 Issue #93（v1.0 合入后再接评审门禁整批）「Bus 公交车式批量测试执行接入云端 CI（攒批一次构建省核时）」
> 承接：Issue #90（BusRunner 母体已落地 commit 5c3e285）→ 本 Issue 收尾候选 2「Bus→CI 接线」

## 一、为什么要有这一层

本地 BusRunner（`local-agent/hybrid/bus.py`）解决了**本地/攒批语义**：把测试请求攒批
入列、每 15 分钟且队列非空才发车、一班车把队列里**全部**测试作为一批计划在**同一进程/
同一构建环境**内整批跑完，跑完统一 sync 留痕 + cost 报表 + quota 记账。这一能力已被
`scripts/local-exec.sh` 一键链路（`bus tick`）调用。

但**云端 CI 每次 push/PR 都是独立冷启动构建环境**，Bus 的本地 JSON 队列
`.bus_queue.json` **跨 CI 构建不共享**——云端侧无法做"跨构建攒批"。如果 CI 里仍是
"每选一个测试就单独拉起一次构建 / 乒乓唤醒"，固定开销（docker 冷启动 + pip install +
环境初始化）×N 次 → 核时浪费依旧。

Issue #93 的结论（关键技术约束）是：**云端侧 Bus 的语义只能是「单次构建内的整批计划
执行」**——一次 CI 构建内，把本轮所选的一批测试作为【一个批次计划】在同一个进程/
同一个构建环境里整批跑完，并统一 sync + cost + quota 收尾。核时收益从"N 次单独构建
固定开销"收敛到"这一批摊到 1 次环境"。

## 二、接入方式（结合点）

### 新增云端 CI 整批执行入口：`scripts/ci-bus-batch.py`

纯标准库 + 复用 `hybrid.bus.BusRunner`，单进程内干一件事：**把传入的一批测试整批跑完
并统一收尾**。

```
python3 scripts/ci-bus-batch.py tests/test_a.sh tests/test_b.sh ...
python3 scripts/ci-bus-batch.py --dry tests/...     # 演练，不真跑
python3 scripts/ci-bus-batch.py --parallel 1 ...     # 并行度（默认 1=串行）
```

实现要点：
- 复用 `BusRunner(queue_file=<独立临时队列>, parallel=...).dispatch(extra_tests=整批)`：
  一次构建内整批执行 + `_finish`（sync + cost + quota）统一收尾，**不改动 BusRunner
  既有语义**（边界要求）。
- **独立临时队列文件**（`tempfile` 下的 `bus_queue_ci.json`）：云端 CI 批次与本地攒批
  队列 `.bus_queue.json` 完全隔离，互不串扰。
- **并行度默认 1（串行）**：云端 CI 构建并发由平台管控，bus 内部再开多线程并行可能与
  CI 环境冲突（Issue #93 约束需评估 DEFAULT_PARALLEL=4）。整批收益来自"一次环境摊全批
  + 统一收尾"，不依赖并行；需要并行时显式 `--parallel N`。
- **退出码即成败**：整批有任一失败 → 退出码 1（CI 判定该阶段失败）；全过 → 0；用法/
  空批次/模块不可用 → 明确报错退出（C01 不吞异常）。

### `.cnb.yml` 接线（pull_request · change aware test）

原实现"选到一批测试后逐脚本 `subprocess bash $t`"，改为：**选定批次后交给
`ci-bus-batch.py` 整批计划执行**（`subprocess python3 scripts/ci-bus-batch.py + selected`），
退出码直接映射为 CI 阶段结果。变更感知选择（IncrementalSelector）保持不变——只把
**执行方式**从"逐脚本独立构建"换成"一批跑完 + 统一收尾"。

```
选定测试(N 个)  →  ci-bus-batch.py <N 个测试>  →  整批跑完 + sync/cost/quota → 退出码
```

## 三、触发时机与改造范围

| CI 节点 | 现状 | 本次改动 |
|--------|------|---------|
| `main.push → architecture system acceptance test` | 已把 37 个 CPU 密集测试移交本地，只做轻量静态校验 + router 自检 | **不改动**（保持云端轻量，避免破坏已本地化架构） |
| `pull_request → change aware test` | IncrementalSelector 选中一批测试后**逐脚本独立跑** | **改造**：整批交给 `ci-bus-batch.py` 一批跑完 + 统一收尾（Issue #93 主战场：评审/PR 触发测试） |
| `pull_request → dev-standard check` | 开发规范 MCP 检查 | **不改动** |
| `pull_request.approved → review gate batch test` | （新增）评审动作触发时原"单发/逐测试冷启动"无收敛节点 | **新增**：`ci-review-batch.py` 变更感知选择 + 交给 `ci-bus-batch.py` 整批计划执行（评审触发核时收敛，Issue #93 后续增量） |

> 为什么只改 pull_request 测试阶段：Issue #90 起，云端 `main.push` 已把 CPU 密集测试
> 移交本地执行，云端核时大头在**评审触发的测试**（pull_request），故 Bus 整批语义接入
> 此节点收益最大、风险面可控。

## 三·补、评审触发整批（review gate batch test · Issue #93 后续增量）

Issue 关键技术约束指出"云端核时大头在**评审触发的测试**"。v1.0 只把 `pull_request`
节点整批化（主战场）；评审动作本身仍会"单发/逐测试冷启动"。本增量在 `pull_request.approved`
事件挂一个**评审门禁整批节点**，复用同一套 Bus 语义：

- `scripts/ci-review-batch.py`：解析 PR 目标/源 SHA（`CNB_PULL_REQUEST_TARGET_SHA` /
  `CNB_PULL_REQUEST_SOURCE_SHA`，无则 `origin/main..HEAD`，再退化为工作区增量），用
  `IncrementalSelector` 做变更感知选择；未命中任何测试 → 核心冒烟 `test_architect_system.sh`
  兜底。
- 选中批次整体交给 `scripts/ci-bus-batch.py`（BusRunner 单次构建内整批跑完 + 统一
  sync/cost/quota），**不逐测试单独拉起 / 不乒乓唤醒**。并行度默认 1 规避 CI 构建并发冲突。
- 退出码 0 = 整批通过；任一失败 → 门禁红（不静默放行）。

> 触发时机：PR 被**审批（approve）**时跑一轮受影响整批，给评审/合并前一道可核验的
> 质量闸门；边界上不引入常驻 cron，评审节点也只在有评审动作且确有受影响测试时才真正
> 发车（Bus"有需求才发车"语义在评审侧的落地）。

## 四、边界（Issue #93 声明）

- **不做**：不引入常驻定时 job / cron（除非确认 CNB 平台支持且低成本）；不引入跨构建
  共享队列（CNB 云构建间不共享本地文件，语义上只做单次构建内整批）。
- **不改动**本地 BusRunner 既有语义与既有模块（`bus.py` 仅被复用，不修改）。
- 并行度默认 1：云端 CI 构建并发由平台管控，bus 内不开多线程并行规避冲突。
- 退出码严谨：任一失败即 CI 红，不静默放行（"没达成不让通过"）。

## 五、自测

- 本仓库自带 `tests/test_ci_bus_batch.sh`（AC4，v1.0）与 `tests/test_ci_review_batch.sh`（v1.1 评审整批），在有 python3 的环境（CI / 本地）可跑，
  校验：脚本存在与可执行、`--help`、`--dry` 演练产出整批等效汇总、含失败测试时退出码
  非 0、空批次报错等。
- `.cnb.yml` 语法完整性由本次 PR 自身的 `pull_request → change aware test` 阶段验证
  （信号灯绿才算通过）。

## 六、关联

- Ref：Issue #90（BusRunner 母体）· Issue #93（本接线）
- 相关模块：`local-agent/hybrid/bus.py` / `parallel.py` / `worker.py` / `sync.py` /
  `cost.py` / `quota.py` / `router.py` / `registry.py`
