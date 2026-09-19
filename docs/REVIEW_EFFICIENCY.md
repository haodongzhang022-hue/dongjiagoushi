# 评审效率 · 减 CPU 损耗（Review Efficiency · Issue #150）

> **用户痛点（Issue #150）**：
> 「现在的架构评审，如果项目较大，他其实每次复述项目是非常困难的，跑他的测试也非常困难，
> 而每次触发评审之后跑开发，然后评审，这样效率很慢，又触发大量的 CPU 构建和 CPU 开发的损耗。」
>
> **定位**：把「评审 ⇄ 开发」的**同步乒乓**改成**异步攒批 + 增量复用**，从三处砍掉损耗。
> 承载：`local-agent/review_context/` + `local-agent/review_cycle/` + `hybrid/bus.py`（攒批去重门）
> + `roles/reviewer.py`（主流程接线）。文档与引擎对齐，禁止漂移。

## 一、损耗到底在哪（先把账算清）

| 损耗 | 现状 | 根因 |
|---|---|---|
| **复述损耗** | 每轮评审把整个大项目的 spec/上下文重讲一遍 | 稳定骨架每轮重算，无冻结复用 |
| **构建损耗** | 每轮评审 → 跑开发 → 评审，各自拉起一次冷启动构建 | 同步乒乓，N 轮 = N 次构建冷启动；N 个测试各自单发 = N 次冷启动 |
| **重复损耗** | 同一份变更被多轮/多次重跑同样的测试与评审 | 无内容指纹判据，靠"人记得" |

三种损耗都是**乘性放大**：项目越大、轮次越多、测试越多，浪费越大。

## 二、三条优化（一一对应）

### ① 评审增量上下文 · 免逐轮复述（`review_context`）

把项目 spec/上下文拆两半：

- **稳定骨架（stable）**：目标 / 做·不做边界 / 验收标准 / 接口契约 / 既有决策——
  **构建一次即冻结**，之后每轮只携带**摘要引用行**；
- **变化片段（volatile）**：本轮 diff 摘要 / 测试信号 / 新增发现——**只有这部分逐轮传**。

`build(stable, volatile, prev)` 产出的 `context` 就是评审每轮真正要吃的最小上下文：

```
【稳定骨架（冻结，已复用，勿复述）】
[goal] 项目北极星目标…（摘要）
[boundary] 做 · 不做边界…（摘要）
…
【本轮变化（增量，仅此即可评审）】
[diff_summary] 本轮只改了一行…
```

**失效判据是内容指纹**（`fingerprint()`，sha256 短摘要），不是主观判断：
- 骨架来源指纹一致 → `reuse.reusable=True`，零重算、零复述；
- 指纹变了 → 指出**具体哪几段变了**（`changed_segments`），只增量重建该段，不重讲全项目。

量化：`saved_ratio` = 相对"照旧复述整个项目"省下的比例；`estimate_saved_tokens()` 折算 token。

### ② 攒批触发 · 一次构建摊全批（`hybrid.BusRunner` + `review_cycle`）

沿用既有 **Bus 公交车模型**（Issue #90），但补上评审场景的两个关键点：

- **入列 0 成本**：受影响测试先 `enqueue`，**绝不立即拉起构建**；
- **一次发车整批跑完**：到点/调度点 `dispatch` 把整批作为**一个批次计划**，在**同一次构建**内跑完——
  N 个测试从 N 次冷启动收敛为 1 次（`summary.cold_start_saved = N-1`）；
- **攒批去重门（新增·本 Issue）**：`enqueue(tests, diff_fp=...)` 带变更指纹，
  **同一指纹已发过车 → 直接拦截**（`skipped_fp`），不再重复处 → 同 diff 永不重复触发构建。

### ③ 评审段调度器 · 增量收集而非乒乓（`review_cycle`）

评审段（review segment）= 一次「评审 → 开发增量 → 测试信号 → 回评审」的调度单位：

```
collect(提交增量，不立即唤醒)
   → coalesce(变更感知选测 + 入列 Bus，0 成本)
      → dispatch(整批发车，一次构建跑完一批)
         → review(增量上下文回评审：冻结骨架摘要 + 本轮变化)
```

确定性状态机（`spec.STATES` / `spec.NODES` / `spec.TRIGGERS`），不让 LLM 决定"下一步/是否结束"：

- **触发门控**：`diff_changed`（指纹变才真触发开发/构建）/ `batch_ready`（队列非空才发车）/
  `fingerprint_new`（指纹未被处理过才做评审处置）；
- **同指纹轮次复用**：`reused=True` → 本轮**零构建**，只引用上轮测试信号与结论；
- **以测试为准**：整批信号灯（🟢/🔴）决定处置标签（走 `collab.disposition`，不各自取名）。

## 三、接线（不是"就绪可调"，是主流程内必走）

评审角色 `ReviewerRole` 主流程内自动接线，可关可降级：

```python
from roles import get_role
r = get_role("架构·评审")

# ① 增量上下文（不再复述整个项目）
pack = r.build_review_context(stable_parts={...}, volatile_parts={...}, prev=prev_pack)
print(pack["context"], pack["saved_ratio"])       # 评审只吃 context

# ② 攒批跑测试（入列 0 成本 → 一次发车整批；同指纹不重复触发）
batch = r.prepare_review_batch("任务A", changed_files=[...],
                               extra_tests=[...], diff_summary="本轮 diff")
# batch {ok, skipped, diff_fp, selected, plan{summary{cold_start_saved}}, cost_note}

# ③ 主流程一次搞定（两者结果回写在返回值里，可核验）
rep = r.do_review("任务A", source="PR #xx", spec_ref="Issue #xx",
                  standards_axis={"🔴": [], "note": "ok"},
                  spec_axis={"faithful": True},
                  stable_parts={...}, volatile_parts={...},
                  extra_tests=[...], auto_route=False)
# rep["context_pack"] / rep["batch"] / rep["disposition"] / rep["axes_complete"]
```

CLI：

```bash
# 评审上下文增量复用（构建一次 → 复用）
python -m review_context.cli demo

# 评审段调度（run / overview / stats / demo）
python local-agent/run.py --review-cycle demo
python local-agent/run.py --review-cycle overview
python local-agent/run.py --review-cycle run --rc-task 任务A \
       --rc-stable '{"goal":"..."}' --rc-volatile '{"diff_summary":"..."}'

# Bus 攒批 + 指纹去重门
python -m hybrid.cli bus enqueue local-agent/tests/test_a.sh --diff-fp sha256:xxxx
python -m hybrid.cli bus dispatch --diff-fp sha256:xxxx
python -m hybrid.cli bus status          # status 含 processed_fps（去重门记忆）

# 跨端聚合控制页读评审段大盘
python local-agent/run.py --dashboard review_cycle
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

## 六、测试护栏

`local-agent/tests/test_review_efficiency.sh`（7 组信号灯，红灯即阻塞）：

1. 稳定骨架构建 → 复用 → 变更即失效（指纹判据）；
2. 攒批去重门：整批一次构建 + 同指纹再入列被拦截；
3. 评审角色 `do_review` 内接线（context_pack + batch）；
4. 评审段调度：同任务同指纹轮次复用，零重复构建；
5. 批量节省口径：10 轮 × 5 测试的构建次数显著下降；
6. 增量上下文 token 量化 + 留痕可回溯；
7. 评审段大盘 + 控制页 `/review-cycle` 路由可读。
