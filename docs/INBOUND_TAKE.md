# 云端承接侧（INBOUND_TAKE）

> module: **inbound-take** · 版本：**v0.1.0** · Issue #177 · 唯一事实源：`local-agent/intent/take.py`
>
> 一句话：**运行时在用户本地电脑，云端只负责「接得住」**——承接卡是承接凭证，
> 交接单是把活交给本地跑的契约，回传核对是按验收标准收口。云端不代跑、不假装跑过。

---

## 一、为什么要有这一层

Issue #177 是老链路（本地中控 → 评论触发 → 角色唤醒 → 接单回执）的联调。用户在这一轮把
定位说清楚了：

> "不用运行时，而是我本地的电脑负责运行时，你承接得住配合的部分就行，也就是说可能是分配的
> 任务过来，你承接之后才触发跟着任务做，而你现在做的接单的卡，其实是方便你接受的用的。"

这句话把云端角色从「执行者」改成「承接端」，也顺带指出接单卡的真正用途：
**它不是给别人看的回执仪式，是我接到活时把它收敛成可交付、可验收的凭证。**

此前这条链上的能力各管一段，没有一层管「交接内容本身」：

| 已有能力 | 管的是什么 | 管不到什么 |
|---|---|---|
| `relay_card` | 卡有没有 `@org/repo(角色)`、有没有 `[触发:角色]`（格式） | 交付形态、验收标准 |
| `entries.bridge` | 本地⇄云端异步开发的句柄与回传（跨对话/PR 定位） | 具体交什么算完 |
| `dispatch` / `dispatch_verify` | 派发四层深度、有没有真接单 | 接了以后交什么 |
| **`intent.inbound`（本模块）** | **交付形态 / 验收标准 / 本地运行时契约 / 回传核对** | 不做派发、不做格式校验 |

---

## 二、四件事（只做这四件）

### ① 承接判定 `judge(kind, runtime)` —— 接得住？半接？接不了

确定性映射表，不靠 LLM 感觉。任务类型 × 运行时归属 → 承接方式：

| 任务类型 | 本地跑 | 云端承接端 |
|---|---|---|
| `code` 写码 | 全套承接，交付 `patch` | **半承接**：只出未验证补丁 + 验收标准 |
| `test` 跑测试 | 全套承接，交付 `report` | **半承接**：只出测试计划，结果归本地 |
| `review` 评审 | 全套 | 全套（不需要真跑运行时）|
| `doc` 文档 | 全套 | 全套 |
| `design` 方案 | 全套 | 全套 |
| `research` 调研 | 全套 | 全套 |
| `ops` 派发编排 | 全套 | 全套 |
| 未知 | **拒接，必须给替代动作** | 同左 |

`mode` 三态：`full`（全套） / `partial`（半承接，只出方案+验收标准） / `reject`（接不了）。
**拒接必须带 `alternative`**——不静默吞件，也不空口接下做不了的活。

### ② 承接卡 `make_card(...)` —— 承了哪件活、按什么交、验什么算完

字段刻意对齐提交模板的习惯：

```
card_id     承接凭证号（同 origin+title 幂等，二次取回同一张，不漂移）
title       接的活（必填）
kind        任务类型（决定承接边界）
runtime     local / cloud（谁跑）
decision    {accept, mode, deliverable, reasons, alternative}
scope_done  做（边界内）
scope_not   不做（边界外）
acceptance  验收标准（必填：没有验收标准就不算承接得住）
ran_remotely 恒 False（云端从不假装跑过）
```

**`acceptance` 缺失直接 `ValueError` 拒建**——这是本模块的态度：承不住就别乱接。

### ③ 交接单 `handoff(card, runtime=local)` —— 把活交给本地跑

返回 `job`：

```
job_id           job-<card_id>
runtime          执行方（本地电脑）
steps            动作清单（含要保留完整 stdout，不许裁剪）
expect_receipt   {provide: [changed_files, test_output, evidence]}
ran_remotely     False
state            awaiting_local_run
```

已拒接的卡**不允许出交接单**（会被挡回，并回显替代动作）。

### ④ 回传核对 `collect(card, result)` —— 本地跑完按验收标准收口

`verify()` 是确定性的，逐条核对：

- 验收标准含「测试 / 信号灯 / 跑 / 回归」→ 必须有 `test_output`，且**失败计数为 0**；
- 含「文件 / 模块 / PR / 补丁 / 改动」→ 必须有 `changed_files`；
- 其他 → `evidence` 里要能命中该项关键词。

失败计数识别仓库信号灯的统一收尾 `N 通过 / M 失败`，取 **M**；正文出现「失败」二字不算失败
（否则 `0 失败` 这种全绿收尾会被误判）。真崩了（`Traceback` / `ERROR:`）另算硬错误。

结论走处置标签：通过 → `proceed` / `delivered`；不通过 → `fix_bug` / `stuck`。
**本模块不会给 `merge`**——运行时在本地，合并得等本地跑通。

---

## 三、三态批扫 `tally()`

```
total / delivered / awaiting_local_run / stuck / rejected / delivered_rate
```

- `delivered`：本地回传且验收通过；
- `awaiting_local_run`：接了，等本地跑；
- `stuck`：接了没交 / 交了没过；
- `rejected`：拒接（带替代动作）。

后两者分开，因为一个要催、一个要换承接方，混成一个总数就没法处置。

---

## 四、用法

```python
from intent import take

# 1. 接件 → 判定
take.judge(kind="code", runtime="cloud")
# {'accept': True, 'mode': 'partial', 'deliverable': 'patch（未验证，须本地跑通才算完）', ...}

# 2. 出承接卡（回评用 Markdown）
card = take.make_card(
    title="修唤醒链路", origin="issue#177", kind="code", runtime="local",
    acceptance=["信号灯脚本全绿", "改动落在独立分支"],
    scope_done=["实现承接侧模块"], scope_not=["云端代跑测试"])
print(take.render_md(card))

# 3. 交本地跑（云端不代跑）
job = take.handoff(card, entry_cmd="bash local-agent/tests/test_inbound_take.sh")

# 4. 本地回传 → 按验收核对
take.collect(card, {"test_output": "20 通过 / 0 失败",
                    "changed_files": ["local-agent/intent/take.py"],
                    "evidence": {"分支": "auto/inbound-take-xxxx"}})
```

CLI（`python -m intent`）：

```bash
python -m intent judge --kind code --runtime cloud
python -m intent new --title "活" --kind code --runtime local --accept "信号灯全绿" --md
python -m intent handoff --card ib-xxx --entry "bash tests/test_x.sh"
python -m intent collect --card ib-xxx --test-output "20 通过 / 0 失败" --changed-file a.py
python -m intent show --card ib-xxx
python -m intent tally
```

---

## 五、边界（不做的事）

- **不建云端运行时**，不启动流水线跑测试（云端 CPU 贵，见 `docs/CLOUD_LOCAL_COOP.md`）；
- **不代跑**：`ran_remotely` 恒 `False`，"已发卡"不等于"已跑过"；
- **不给 `merge`**：处置最多到 `proceed`，合并闸门归人类（CP3）；
- **不静默拒接**：拒接必须带替代动作。

---

## 六、信号灯

`local-agent/tests/test_inbound_take.sh` —— **20 通过 / 0 失败**：

judge 三态（本地/云端/未知）· 承接卡缺验收标准拒建 · 交接单 `ran_remotely=False` ·
拒接卡不出交接单 · 回传缺测试输出判不通过 · 含失败计数判不通过 · 齐全回传自 `proceed` ·
同输入两次结论一致（确定性）· Markdown 承接卡 · `tally` 四态分开 · 幂等不漂移 ·
`capability` 边界声明 · CLI 四项可调。

---

## 七、与相邻机制的接线位置

- 承接前：接力卡格式由 `relay_card` 校验（`@` + `[触发]`），本模块不重复；
- 承接后：交叉对话 / 跨 PR 的产出归集用 `entries.bridge` 的句柄，本模块只管单件交接内容；
- 拒接升级：连续拒接 / 承接后 `stuck` 超过预期 → 走 `sentinel` 上报，不静默放行。
