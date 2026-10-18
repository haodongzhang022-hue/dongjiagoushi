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

## 三、进度跟踪表（剩余 open · 逐条定位到人 · 2026-10-18 二次核验）

> **本轮更正（不掩盖上一版虚报）**：上一版把 #165/#166/#168 写成 `awaiting_receipt（L3 已投）`、
> 把 #145/#169 写成「PR 已提/已提交」——**与实际不符**。本轮用对端证据逐条重核：
> 三张接力卡的 NPC 流水线**全部 `error`**（架构·开发未被真实唤醒），#175 当时**尚未合并**、
> #172 尚未合并。下表是核验后的真实状态。

| Issue | 深度（真实） | 现状（可核验证据） | 承接角色 | 卡点 | 下一步 |
|---|---|---|---|---|---|
| **#145** 升级适配 | ✅ L4 已收口 | PR #146 是**假合并**（base=`auto/architect-framework-7a13`）→ **PR #175 已 merged（base=main）**；`git cat-file -e origin/main:dsh-adapter/package.json` → 在；main 上真跑 `local-agent/tests/test_dsh_adapter.sh` **18/18** 🟢、`scripts/feature-verify/dsh-adapter/新版适配链路.sh` **11/11** 🟢、`scripts/feature-verify.sh --check-map` 🟢、`tests/test_feature_verify.sh` **56/56** 🟢（#175 的 4 红已清） | — | 只差人类 ⏸CP3 关单 | 人类确认 → 关闭 #145；旧分支 7a13 与 PR #171 一并清 |
| **#162** selector 映射 | ✅ L4 功能完成 | PR #163 merged（base=main）、`scripts/feature-verify/modules.map` 在 main | — | 只差人类 ⏸CP3 | 人类一句话 → 打 `merged` → 关闭 |
| **#165** collab 🟡×5 | ⚠️ **L2 · 唤醒失败** | 5 项 🟡 **全未改**；#165 唯一评论的 NPC 流水线 `state=error [6.6s]` → **对端没收到卡、无 `[接单]` 回执** | 架构·开发（未上岗） | **npc:go 唤醒链路打不通**，非「等回执」 | 修通唤醒链路后**重发**接力卡；在此之前不得报 L3 已达 |
| **#166** 评论流分页 | ⚠️ **L2 · 唤醒失败** | 统一「读评论流默认全量」入口未实现；同上 `state=error [4.3s]` | 架构·开发（未上岗） | 同上 | 同上（优先级 p5） |
| **#168** feature-verify 🟡 | ⚠️ **L2 · 唤醒失败** | `map_registered` 三处内联未收口 / `Then-10d` no-op sed 未清；同上 `state=error [4.9s]` | 架构·开发（未上岗） | 同上 | 同上 |
| **#169** 修评审 | ✅ L4 已收口 | 根因=评论漏 `@`（非代码 bug）；**PR #172 已 merged（base=main）**；`tests/test_relay_card.sh` 11/11 🟢（含 `Issue #169` 断言） | — | 只差人类 ⏸CP3 关单 | 人类确认 → 关闭 #169 |
| **#170** 管理 issue | ✅ L4 本单 | 本台账 + 跟踪表 | 架构·交付 | 人类 ⏸CP3（合本 PR） | 合本 PR → 按台账逐条收口 → 关本单 |

**诚实标注（dispatch_verify 判据）**：派发只有到 **L4（接单→开工→进度尺→交付）** 才算成功。
#165/#166/#168 当前**未过 L3**（真实唤醒失败），不是「已触发未确认」——更不是「已派活」。

## 四、假合并/错路径入账（显式暴露，不事后兜底）

1. **#145 · PR #146**：`is_merged=True` 但 base 是旧功能分支 `auto/architect-framework-7a13`，
   该分支整体未回 `main` → 曾出现「报完成但 main 找不到代码」。**已由 PR #175（base=main）收口并合并。**
2. **PR #171**（npc:go 模型改 hy3）：base 同为 `auto/architect-framework-7a13`，属同一错路径族。
   **上一版台账写的「其改动内容已在 main（`a250d20`）」是错的** —— 实核：
   `origin/main:.cnb.yml` 的 `model:` 仍是 `deepseek-v4.1-flash`，
   `git log --all -S"model: hy3" -- .cnb.yml` **无任何提交命中**。
   即：**hy3 从未进过 main**。该 PR 不该按现状合并，应**从 main 重提**再评估。
3. **PR #160 引用的 Issue 已 404**（编号截断），不影响台账。
4. **重复行清理**：上一版本节 2 与 3 是同一件事（PR #171）写了两遍，已合并为一条。

## 五、剩余 open 汇总（真实口径）

关闭 26 条后，open 由 **33 → 7**。截至 2026-10-18 二次核验：

- **已真正收口、只差人类 ⏸CP3 关单**：#145（PR #175 已 merged）、#162（PR #163 已 merged）、#169（PR #172 已 merged）
- **未收口**：#165 / #166 / #168 —— 三张接力卡的 NPC 流水线全部 `error`，
  **架构·开发从未被真实唤醒**（`state=error`，无 `[接单]` 回执）→ 仍是 **L2**
- **本单**：#170，合本 PR 后关闭

**上一版台账的错误更正**（不静默改掉，留痕）：
① 把「投卡成功」说成「L3 已投」，实际对端流水线 error = **未唤醒**；
② 把 #175/#172 说成「已提/已提交」，实际**本轮核验时仍未合并**；
③ 断言 hy3 已在 main，实际**从未进过 main**。

> 结论：**不是「都处理了」**。真正做完的是 #145/#162/#169 三条（等 CP3 关单），
> #165/#166/#168 三条**卡在唤醒链路**上，一张卡都没送到人。
