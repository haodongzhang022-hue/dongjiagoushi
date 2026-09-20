# 评审效率 · 减 CPU 损耗（Review Efficiency · Issue #150）

> **用户痛点（Issue #150）**：
> 「现在的架构评审，如果项目较大，他其实每次复述项目是非常困难的，跑他的测试也非常困难，
> 而每次触发评审之后跑开发，然后评审，这样效率很慢，又触发大量的 CPU 构建和 CPU 开发的损耗。」
>
> **定位**：把「评审 ⇄ 开发」的**同步乒乓**改成**异步攒批 + 增量复用**，从三处砍掉损耗。
> 承载：`local-agent/review_context/` + `local-agent/review_cycle/` + `hybrid/bus.py`（攒批去重门）
> + `roles/reviewer.py`（主流程接线）。文档与引擎对齐，禁止漂移。
> **决策记录**：[`docs/adr/0011-review-incremental-coalesced-cycle.md`](adr/0011-review-incremental-coalesced-cycle.md)
> （为何选"增量上下文 + 攒批异步"、未选方案与代价）。

## 一、损耗到底在哪（先把账算清）

| 损耗 | 现状 | 根因 |
|---|---|---|
| **复述损耗** | 每轮评审把整个大项目的 spec/上下文重讲一遍 | 稳定骨架每轮重算，无冻结复用 |
| **构建损耗** | 每轮评审 → 跑开发 → 评审，各自拉起一次冷启动构建 | 同步乒乓，N 轮 = N 次构建冷启动；N 个测试各自单发 = N 次冷启动 |
| **重复损耗** | 同一份变更被多轮/多次重跑同样的测试与评审 | 无内容指纹判据，靠"人记得" |
| **乱序损耗**（打断补齐） | 开发还在跑，测试/评审就并发触发；同一阶段被重复触发 | **跨角色阶段链无门控**，触发不校验上游是否收口 |

四种损耗都是**乘性放大**：项目越大、轮次越多、测试越多，浪费越大。
「乱序损耗」还会**稀释进度基准**（同一件事多点并行 = 进度失衡），故单列一条规则处理（见 §二.④）。

## 二、三条优化（一一对应）

### ① 评审增量上下文 · 免逐轮复述（`review_context`）

把项目 spec/上下文拆两半：

- **稳定骨架（stable）**：目标 / 做·不做边界 / 验收标准 / 接口契约 / 既有决策——
  **构建一次即冻结**，之后每轮只携带**摘要引用行**；
- **变化片段（volatile）**：本轮 diff 摘要 / 测试信号 / 新增发现——**只有这部分逐轮传**。

`build(stable, volatile, prev)` 产出的 `context` 就是评审每轮真正要吃的最小上下文：

```
【稳定骨架（整块未变，已复用，勿复述）】
[goal] 项目北极星目标…（摘要）
[boundary] 做 · 不做边界…（摘要）
…
【本轮变化（增量，仅此即可评审）】
[diff_summary] 本轮只改了一行…
```

**失效判据是内容指纹**（`fingerprint()`，sha256 短摘要），不是主观判断：
- 骨架来源指纹一致 → `reuse.reusable=True`，零重算、零复述（`frozen=True`、`rebuilt=False`）；
- 指纹变了 → 指出**具体哪几段变了**（`changed_segments`），
  **变更段必须用新值重建、仅未变更段复用旧引用**（增量重建，不重讲全项目）；
  此时 `frozen=False`、`rebuilt=True`——**冻结语义专指"整块骨架未变、直接复用"**，
  不复用即为重算，避免"看起来冻结却吃了旧摘要"（评审会因此吃到过期骨架）。

> 铁律：`prev_refs.get(seg)` **绝不能无条件命中**——变更段旧引用一旦命中就掩盖了新值，
> 评审看到的是过期骨架。`tests/test_review_efficiency.sh` 组 1 已加信号灯：断言
> 变更段引用 ≠ 上轮旧引用、且 `context` 随骨架变更更新。

量化：`saved_ratio` = 相对"照旧复述整个项目"省下的比例；`estimate_saved_tokens()` 折算 token。

### ② 攒批触发 · 一次构建摊全批（`hybrid.BusRunner` + `review_cycle`）

沿用既有 **Bus 公交车模型**（Issue #90），但补上评审场景的两个关键点：

- **入列 0 成本**：受影响测试先 `enqueue`，**绝不立即拉起构建**；
- **一次发车整批跑完**：到点/调度点 `dispatch` 把整批作为**一个批次计划**，在**同一次构建**内跑完——
  N 个测试从 N 次冷启动收敛为 1 次（`summary.cold_start_saved = N-1`）；
- **攒批去重门（新增·本 Issue）**：`enqueue(tests, diff_fp=...)` 带变更指纹，
  **同一指纹已发过车 → 直接拦截**（`skipped_fp`），不再重复处 → 同 diff 永不重复触发构建。

**去重键控三条硬约束（返工 S1/S2/S3，缺一即 false green）**：

1. **键 = 真实变更内容指纹 + 任务/批次键**：评审段/评审角色算的 `diff_fp` 是
   `fingerprint({diff_summary, task_key})`——掺入 `task_key` 后，**同一变更内容在不同任务下
   不会被误判为"已处理"**（消除跨任务静默跳过）。`diff_summary` **缺省/空白 → 视为"无指纹"
   （`diff_fp=None`），不占门、不做去重**，绝**不得**退化为空串常量哈希（`sha256:e3b0c44298fc`）
   而让后续无关任务被静默跳过；
2. **演练不写穿**：`dry_run=True`（演练）发车**不写**持久化 `processed_fps`——
   演练没真跑测试，写门会让**后续真实执行被静默跳过**（`gate_written=False` 显式标注）；
3. **只记本批实际携带**：`dispatch` 只把**本批实际携带**的指纹（队列条目自带 ∪ 显式 `diff_fp`）
   写入去重门；**空队列提前返回不写任何门状态**。不再有"与发车无关的登记值"被误记
   （旧的 `set_pending_fp` 单标量预登记接口已移除，正是"登记值 ≠ 本批实际携带"的根因）。

### ③ 评审段调度器 · 增量收集而非乒乓（`review_cycle`）

评审段（review segment）= 一次「评审 → 开发增量 → 测试信号 → 回评审」的调度单位：

```
collect(提交增量，不立即唤醒)
   → coalesce(变更感知选测 + 入列 Bus，0 成本)
      → dispatch(整批发车，一次构建跑完一批)
         → review(增量上下文回评审：冻结骨架摘要 + 本轮变化)
```

确定性状态机（`spec.STATES` / `spec.STATE_TRANSITIONS` / `spec.TRIGGERS` /
`spec.TRIGGER_STATE`），**由 `cycle.advance_state()` 真读取驱动**（不是声明了不用），
不让 LLM 决定"下一步/是否结束"：

- **触发门控**：`diff_changed`（指纹变才真触发开发/构建）/ `batch_ready`（队列非空才发车）/
  `fingerprint_new`（指纹未被处理过才做评审处置）；
- **同指纹轮次复用**：`reused=True` → 本轮**零构建**，只引用上轮测试信号与结论；
- **以测试为准**：整批信号灯（🟢/🔴）决定处置标签（走 `collab.disposition`，不各自取名）。

**三条工程约束（缺一即"永不发车"，信号灯红灯拦）**：

1. `root_dir` 必须解析到**仓库根**（`os.path.dirname(_HERE)`，`_HERE=<repo>/local-agent`）——
   多 `dirname` 一次会解析到 `/`，`git diff` 与选测全部落空；
2. 选测器用 `IncrementalSelector(root_dir=…)` **显式实例化**——`default_selector` 是**实例**
   不是工厂函数，当函数调用会 `TypeError`（`hasattr(default_selector,"root_dir")` 恒 True 是
   **误导性判据**，实例本就带该属性）；
3. 选测失败**不静默吞**（对齐 dev-standard C01）：异常上抛/显式留痕到本轮 `select_error`，
   由调用方降级为"不拉构建"，避免"看起来没变更"掩盖真实故障。

`run()` 支持 `changed_files=[...]` 显式注入变更清单（替代工作区 `git diff`，供测试/调用方用）。
无注入时 `_changed_files()` 走**确定性回退链**，兼容本地开发与 CI/PR 两种场景：
工作区 diff → 暂存区 diff → `origin/main...HEAD` → `main...HEAD` → `HEAD~1..HEAD`（取首个非空）。
`tests/test_review_efficiency.sh` 组 4 断言**真实变更下 `dispatched=True` 且 `batched_runs>0`**，
组 5 断言 `dispatched_builds>0`——防"取 0 也算过"的过宽断言掩盖"永不发车"。

### ④ 阶段链门控 · 本该串行不得并行/重复触发（`review_cycle.gate` · 打断补齐）

> **用户痛点（Issue #150 追加）**：
> 「我们还在处理开发的时候，他就又在跑测试了，然后之后又触发了评审，但是这场开发还没完成，
> 也就是说中间本该以链条进行，往后运行的他一次触发了。开发和测试就乱了。
> 导致重复触发也会导致进度失衡。」

把「开发 → 测试 → 评审」从"一次触发就多点并发"改回**链式有序推进**。唯一事实源
`review_cycle/stage_spec.py`（`STAGE_ORDER` / `UPSTREAM` / `GATE_DECISIONS`），
引擎 `review_cycle/gate.py` 做**确定性判定**（不让 LLM 决定"现在该谁跑"）：

| 判决 | 含义 | 动作 |
|---|---|---|
| `allow` | 上游已收口 + 本阶段未在跑 | 链式往后推进（才允许起构建） |
| `blocked_active` | **本阶段已在跑**（重复触发） | **复用进行中的任务**，不新起、不冲进度 |
| `blocked_upstream` | **上游未收口**就发起本阶段（抢跑） | 拒绝，**零构建**，先让上游按链收口 |
| `blocked_switched` | 下游已跑过再回头补上游（乱序） | 拒绝，防止一条链被并行拆成两条 |

**为什么能"拦下且不假绿"**：
- 驳回 = **零构建**（`dispatched=False`），这正是"乱触发"里最贵的那部分；
- 驳回**不得给 `merge`/`proceed`** 之外假绿放行语义的标签——`_dispose_blocked` 统一映射到
  规范处置 `proceed`（含义："按序继续推进"，不是终局，不卡死链条）；
- `force=True` 是**显式逃生门**（"我知道在抢跑/复用"），判决留痕 `forced=True`，不静默绕过；
- 阶段活动登记表带**静默接管**（`DEFAULT_QUIET_SECONDS=1800`，可用 `REVIEW_STAGE_QUIET_SECONDS`
  覆盖）——某阶段打标残留不会被永久当作"在跑"卡死整条链。

**留痕与俯瞰**：每次判决写 `archives(kind='stage_gate')`；`gate_stats()` 统计放行/三类驳回次数；
`stats().blocked_retriggers` = 被拦下的乱触发总数（进度不失衡的可核验口径）。
俯瞰：`python local-agent/run.py --review-cycle gate` / `--dashboard review_cycle`。

## 三、接线（不是"就绪可调"，是主流程内必走）

评审角色 `ReviewerRole` 主流程内自动接线，可关可降级：

```python
from roles import get_role
r = get_role("架构·评审")

# ① 增量上下文（不再复述整个项目）
pack = r.build_review_context(stable_parts={...}, volatile_parts={...}, prev=prev_pack)
print(pack["context"], pack["saved_ratio"])       # 评审只吃 context

# ② 攒批跑测试（入列 0 成本 → 一次发车整批；同指纹不重复触发；阶段门驳回=零构建）
batch = r.prepare_review_batch("任务A", changed_files=[...],
                               extra_tests=[...], diff_summary="本轮 diff")
# batch {ok, skipped, diff_fp, selected, plan{summary{cold_start_saved}}, cost_note, gate}
# gate.decision ∈ allow / blocked_active / blocked_upstream / blocked_switched
#   驳回时 batch["skipped"]=True 且 plan=None（不起任何构建）

# ③ 主流程一次搞定（两者结果回写在返回值里，可核验）
rep = r.do_review("任务A", source="PR #xx", spec_ref="Issue #xx",
                  standards_axis={"🔴": [], "note": "ok"},
                  spec_axis={"faithful": True},
                  stable_parts={...}, volatile_parts={...},
                  extra_tests=[...], auto_route=False)
# rep["context_pack"] / rep["batch"] / rep["disposition"] / rep["axes_complete"]
```

CLI（**均可从仓库根直接跑通** · 返工 S9：所有 `python -m` 都带 `PYTHONPATH=local-agent`，
且已补 `__main__` 入口，不再"文档写了跑不通"）：

```bash
# 评审上下文增量复用（构建一次 → 复用）
PYTHONPATH=local-agent python3 -m review_context demo
PYTHONPATH=local-agent python3 -m review_context build \
       --stable '{"goal":"..."}' --volatile '{"diff_summary":"..."}'

# 评审段调度（run / overview / stats / demo · 已补 __main__）
PYTHONPATH=local-agent python3 -m review_cycle demo
PYTHONPATH=local-agent python3 -m review_cycle stats
PYTHONPATH=local-agent python3 -m review_cycle overview
PYTHONPATH=local-agent python3 -m review_cycle run --task-key 任务A \
       --stable '{"goal":"..."}' --volatile '{"diff_summary":"..."}'
# 阶段链门控（本该串行不得并行/重复触发）
PYTHONPATH=local-agent python3 -m review_cycle gate   # 放行/三类驳回统计
# 等价（run.py 接线，同一引擎）
python3 local-agent/run.py --review-cycle demo
python3 local-agent/run.py --review-cycle overview
python3 local-agent/run.py --review-cycle gate

# Bus 攒批 + 指纹去重门
PYTHONPATH=local-agent python3 -m hybrid.cli bus enqueue local-agent/tests/test_a.sh --diff-fp sha256:xxxx
PYTHONPATH=local-agent python3 -m hybrid.cli bus dispatch --diff-fp sha256:xxxx
PYTHONPATH=local-agent python3 -m hybrid.cli bus status   # status 含 processed_fps（去重门记忆）

# 跨端聚合控制页读评审段大盘
python3 local-agent/run.py --dashboard review_cycle
```

## 四、省了什么（可核验的口径）

| 指标 | 口径 | 出处 |
|---|---|---|
| `saved_ratio` | 相对"照旧复述整个项目"省下的上下文比例 | `review_context.build()` |
| `context_saved_tokens` | 省下的复述字符 / 3（保守 token 口径） | `estimate_saved_tokens()` |
| `cold_starts_naive → cold_starts_batched` | N 个测试单发 N 次冷启动 → 整批 1 次 | `hybrid.bus` `summary` |
| `batched_runs` | 真发车的批次数（每批 1 次构建） | `review_cycle.stats()` |
| `avoided_builds` | 被指纹复用拦下的构建次数（=省下的构建） | `review_cycle.stats()` |
| `reused_rounds` | 同指纹零构建的轮次数 | `review_cycle.stats()` |
| `blocked_rounds` | 被阶段门拦下的轮次数（抢跑/重复/乱序） | `review_cycle.stats()` |
| `blocked_retriggers` | 被拦下的"本该串行却并行/重复触发"总次数 | `review_cycle.stats()` |
| `stage_gates` | 放行 / 三类驳回各多少次（确定性判决分布） | `review_cycle.gate_stats()` |

报表可俯瞰：`run.py --review-cycle stats`、`dashboard review_cycle`。

## 五、与既有机制的关系（不重复造轮子）

| 既有机制 | 关系 |
|---|---|
| `hybrid.selector`（变更感知选测） | 本模块**复用**它做"只跑受影响测试"，不另写选测逻辑 |
| `hybrid.bus`（公交车攒批） | 本模块在其上加「**变更指纹攒批去重门**」+ 冷启动摊薄测算 |
| `hybrid.cache`（指纹缓存） | 缓存治"批内同测试重复跑"，本模块治"跨轮/跨次重复触发构建"，互补 |
| `review-context caching`（LLM 前缀缓存） | LLM 层治 token 前缀；本模块治"评审**上下文文本**逐轮复述"，作用在编排/角色层 |
| `review-metrics`（有效性度量） | 度量治"评审有没有效"，本模块治"评审**有多贵**"，正交 |
| `reviewer.do_review`（双轴+处置） | 本模块是 `do_review` 的**效率前置**（先攒批、先增量上下文，再双轴评审），不改双轴/处置契约 |
| `dev_team`（开发小组闭环） | DevTeam 管**小组内**开发执行-验证闭环；阶段门管**跨角色**链条先后（开发→测试→评审），互补不重叠 |
| `relay`/`relay_card`（接力卡） | 接力卡管"谁接谁的活"；阶段门管"此刻该谁跑"，两者正交 |

## 六、测试护栏

`local-agent/tests/test_review_efficiency.sh`（10 组信号灯，红灯即阻塞）：

1. 稳定骨架构建 → 复用 → 变更即失效（指纹判据）+ **变更段重建/未变更段复用/context 随骨架更新**；
2. 攒批去重门：整批一次构建 + 同指纹再入列被拦截；
3. 评审角色 `do_review` 内接线（context_pack + batch）；
4. 评审段调度：`root_dir` 指向仓库根 + **真实变更下真发车**（`dispatched=True`）+ 同指纹轮次复用；
5. 批量节省口径：10 轮 × 5 测试的构建次数显著下降，且**确认真发过车**（`dispatched_builds>0`）；
6. 增量上下文 token 量化 + 留痕可回溯；
7. 评审段大盘 + 控制页 `/review-cycle` 路由可读；
8. **阶段链门控**：抢跑/重复/乱序全拦、链式推进放行、`force` 逃生门留痕（唯一事实源断言）；
9. **拦截可核验**：被驳回**零构建**（`dispatched=False`）、不得假绿放行、大盘 `blocked_rounds`/
   `blocked_retriggers` 计数；
10. **false-green 红灯门（返工新增）**：① 跨任务同缺省指纹（无指纹）**不得**互相跳过、
    跨任务同内容指纹因 `task_key` 不同**不得**互相跳过；② **演练后真实执行不得被跳过**；
    ③ 空队列发车 + 无关发车**不得**误记指纹；④ 选测失败（`select_error`）→ `review_complete=False`
    且**不放行**；⑤ 状态机 `spec.STATES/TRIGGERS` 真被读取驱动 `Round.state`/`trigger`；
    ⑥ 仓库根解析唯一（评审角色 == 调度器）。

**测试隔离（可重复跑）**：测试通过 `BUS_QUEUE_FILE` / `QUOTA_LEDGER_FILE` 环境变量把攒批队列与
配额账本落到临时目录，不污染工作区共享状态（否则第二次跑会因去重门残留而假失败）。
