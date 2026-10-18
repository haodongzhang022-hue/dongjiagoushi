# Issue 大盘收口记录（2026-10-18 · Issue #170）

> 起因：Issue #170「还有很多 issue 开着，检查进度，已经做完的就记录好，然后关闭，现在同时开着太多 issue 了」。
> 本文是**关闭前台账 + 进度跟踪表**：每条给可核验证据（PR 合并态 + `main` 上产物实体 + 指派/触发评论），
> 不凭「自述已完成」关单。

## 一、核验口径（不采信自述）

1. **PR 真实合并**：`cnb pulls get` 读 `is_merged` / `mergeable_state`，**并且看 base**；
2. **产物真在 main**：`git cat-file -e origin/main:<路径>` / `git merge-base --is-ancestor <sha> origin/main`；
3. `is_merged=True` 但 base 不是 `main` → **不算完成**，判「假合并」入账；
4. 两者缺一 → **不关单**，只记「代码在分支、未进 main」。

## 二、已关闭清单（26 条 · 已完成）

| Issue | 标题 | 证据 | 结论 |
|---|---|---|---|
| #142 | 更新介绍和进度 | PR #143 merged（base=main）+ PR #144 merged；`origin/main:README.md` 含「协作主图」 | 已上线，无未收口项 |
| #150 | 减少cpu消耗 | PR #153 merged + PR #160 merged；`origin/main:local-agent/review_context/`、`review_cycle/` 均在 | 已交付并接线 |
| #121-124 | bridge / cnb_live 真实通道探测 | 通道由 PR #113/#131/#141 merged 落地；#124 评论已有 `state: merged` + `align_local` 回写回执 | 探针/演示锚点无后续工作 |
| #125-140 | 聚合页控制动作演示 | 同上 | 演示锚点无待办 |
| #151-159 | CLI 控制台发起 | 同上 | 演示锚点无待办 |

> demo/探针类合计 24 条，均为 bridge / dashboard 真实传输的**验证锚点**，通道本身早已合并落地。

## 三、进度跟踪表（剩余 open · 逐条定位到人）

| Issue | 深度 | 现状（核验） | 承接角色 | 触发/指派留痕 | 下一步 |
|---|---|---|---|---|---|
| **#145** 升级适配 | L3 已触发 → L4 进行中 | PR #146 是**假合并**（base=`auto/architect-framework-7a13`，`main` 无 `dsh-adapter/`）→ 已从 main 重提 **PR #175**（base=main），18 组信号灯 + 10 项功能级断言全绿 | 架构·开发（实现归位）· 架构·评审（复评） | #145 评论（指派 + 证据） | 等人类 ⏸CP3 → 合并 #175 → 关 #145；旧分支 7a13 与 PR #171 一并清 |
| **#162** selector 映射 | L4 功能已完成 | PR #163 merged（base=main）、`scripts/feature-verify/modules.map` 在 main；残留的 #168 已另立跟踪 | 架构·评审 → 人类 CP3 | #162 评论 77 条已知情；本轮补「等 CP3」结论 | 人类 ⏸CP3 一句话 → 打 `merged` → 关闭 |
| **#165** collab 🟡×5 | `awaiting_receipt`（L3 已投） | 5 项 🟡 全未改（`tx_depth` 兜底 / `needs_m1` 断言 / 组10 方言 / ADR-0013 口径 / registry 死条目） | 架构·开发 | #165 评论：本轮投 `[触发:架构·开发]` 全路径接力卡 | 等 `[接单]` 回执 → 开工 → 进度尺 → 交付复评 |
| **#166** 评论流分页 | `awaiting_receipt`（L3 已投） | 统一「读评论流默认全量」入口未实现（优先级 p5） | 架构·开发 | #166 评论：同上 | 同上（可低优先，机制加固） |
| **#168** feature-verify 🟡 | `awaiting_receipt`（L3 已投） | `map_registered` 三处内联未单点收口 / `Then-10d` no-op sed 未清 | 架构·开发 | #168 评论：同上 | 同上（与 #162 关单后一并收） |
| **#169** 修评审 | L4 待合并 | 根因=评论漏 `@`（非代码 bug）；PR #172（base=main）已提交，`test_relay_card.sh` 8/8 绿 | 架构·评审 → 人类 CP3 | #169 评论已留结论 | 合并 #172 → 关 #169 |
| **#170** 管理 issue | L4 本单 | 本台账 + 跟踪表；关单动作由架构·交付在 #175/#172 合并后执行 | 架构·交付 | 本评论 | 合本 PR → 按台账逐条收口 → 关本单 |

## 四、假合并/错路径入账（显式暴露，不事后兜底）

1. **#145 · PR #146**：`is_merged=True` 但 base 是旧功能分支 `auto/architect-framework-7a13`，
   该分支整体未回 `main` → `dsh-adapter/` 至今不在 `main`。已由 **PR #175**（base=main）重做合并路径。
2. **PR #171**（npc:go 模型换 hy3）：同样 base=`auto/architect-framework-7a13`，属同一错路径族。
   其改动内容已在 `main`（`a250d20`），**不应按现状合并**，随旧分支一并清理。
3. **PR #171「npc:go 模型换 hy3」**：同一错路径族（base=`auto/architect-framework-7a13`）。但其改动内容已在 `main`（`a250d20`）→ **不该按现状合并**，随旧分支清理。
4. **PR #160 引用的 Issue 已 404**（编号截断），不影响台账。

## 五、剩余 open 汇总

关闭 26 条后，open 由 **33 → 7**；本轮把 7 条逐条定位到角色与下一步（见第三节表）。
其中 **#165 / #166 / #168 三条本评论已投 L3 触发卡**（真实唤醒，待 `[接单]` 回执），
**#145 由 PR #175 承接**，**#162 / #169 卡在人类 ⏸CP3**，**#170 待以上收口后关闭**。
