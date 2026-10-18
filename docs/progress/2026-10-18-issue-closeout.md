# Issue 大盘收口记录（2026-10-18 · Issue #170）

> 起因：Issue #170「还有很多 issue 开着，检查进度，已经做完的就记录好，然后关闭，现在同时开着太多 issue 了」。
> 本文是**关闭前的台账**：每条都给出可核验证据（PR 合并态 + `main` 上代码/文档实体），
> 不凭「自述已完成」关单。

## 一、核验口径（不采信自述）

1. **PR 真实合并**：`cnb pulls get` 读 `is_merged` / `mergeable_state`，不看 PR 自述；
2. **产物真在 main**：`git cat-file -e origin/main:<路径>` / `git merge-base --is-ancestor <sha> origin/main`；
3. 两者缺一 → **不关单**，只记「代码在分支、未进 main」。

## 二、关闭清单（已完成 · 24 条）

| Issue | 标题 | 证据 | 结论 |
|---|---|---|---|
| #142 | 更新介绍和进度 | PR #143 merged（base=main）+ PR #144 merged（回转全路径加固）；`origin/main:README.md` 含「协作主图」 | 已合并上线，无未收口项 |
| #150 | 减少cpu消耗 | PR #153 merged + PR #160 merged；`origin/main:local-agent/review_context/__init__.py`、`review_cycle/__init__.py` 均在 | 已交付并接线 |
| #121 | probe: entries.bridge 真实传输通道探测 | 探测用 Issue，通道已由 #131/#141 merged 落地 | 探针用完即弃 |
| #122 #123 | probe: cnb_live 真实通道探测 | 探测信号，通道已落地 | 同上 |
| #124 | 真实本地实测：entries.cnb_live 配合闭环 | 评论已有「结果回执 state: merged，align_local 回写完成」 | 闭环已完成 |
| #125 #127 #129 #135 #137 #139 #151 #154 #156 #158 | 聚合页控制动作演示 | bridge 自动建的 demo 锚点，`entries.dashboard` 已 merged（PR #113） | 演示锚点无待办 |
| #126 #128 #130 #136 #138 #140 #152 #155 #157 #159 | CLI控制台发起 | 同上，真实传输通道已 merged（PR #131/#141） | 演示锚点无待办 |

> demo/探针类合计 21 条，均为 bridge / dashboard 真实传输的**验证锚点**，
> 通道本身早已合并落地，锚点无后续工作 → 关闭并在评论中保留「因何关闭 + 证据」。

## 三、保留清单（真没做完 · 9 条）

| Issue | 当前深度 | 卡点 | 下一步 |
|---|---|---|---|
| #145 | 代码在分支未进 main | PR #146 `is_merged=True` 但 base 是 `auto/architect-framework-7a13`；`dsh-adapter/` 在 `origin/main` **不存在** | 从 main 重拉分支重提 PR（或把旧分支 rebase 到 main 再合） |
| #162 | L4 部分 | PR #163 merged、`scripts/feature-verify/modules.map` 在 main | 只剩标签 `merge/merge_ready` 需随关单转为 `merged`；关闭前置条件为人类 CP3 |
| #165 | L2 登记 | 5+1 项 🟡 未改（`tx_depth` 兜底 / `needs_m1` 断言 / 组10 方言 / ADR-0013 口径 / registry 死条目 / `db.query()` guard） | 等 CP3 后投 L3 唤醒开发 |
| #166 | L2 登记 | 统一「读评论流默认全量」入口未实现 | 低优先级（p5），机制加固 |
| #168 | L2 登记 | `map_registered` 三处内联未单点收口 / `Then-10d` no-op sed | 依赖 #162 关单后一并收 |
| #169 | 进行中 | 架构·评审唤醒出错 | 修 @ 召唤约束 + 测试信号灯 + PR |
| #170 | 本 Issue | Issue 大盘收口 | 本记录落盘 + 关单 |

## 四、本次收口附带发现（显式暴露，不事后兜底）

- **#145 的「已合并」是假象**：PR #146 合并进的是旧功能分支 `auto/architect-framework-7a13`，
  而该分支整体没有回到 `main` → `dsh-adapter/` 至今不在 `main`。按「模块独立 PR / base 一律 main」
  的解耦规则，这属于**违规路径**，须重做合并路径。
- **结论重复评论**：#124 同一结果回执写了两遍（bridge 回执幂等缺口）。
- **PR #160 挂着 Issue 号但 Issue 已 404**：PR 标题引用 `Issue #15x`（截断），实际对应单已不存在，
  不影响本清单，另行记录。

> 本记录为「关闭前留痕」，关闭动作在 PR 合并后进行。
