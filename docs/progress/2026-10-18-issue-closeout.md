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

## 三、进度跟踪表（剩余 open · 逐条定位到人 · **2026-10-19 第四次核验**）

> **本节三次自我更正，一次比一次靠证据**（不静默改掉旧结论，全部留痕）：
> ① 首版把「投卡成功」当「L3 已投」——实际三张卡 NPC 流水线 `state=error` = 未唤醒；
> ② 二次版据此判 #165/#166/#168「L2 未唤醒」——**结论正确但随后被推翻**：#165 的对端其实被我
>    漏读了分页（`?page_size` 默认 10，我只拿到最后 10 条就下了结论），`#165` 已交付 PR #178；
> ③ 本次（2026-10-19）按 `cnb pulls/issues get` 逐条实读，口径统一为「**证据指向哪就写哪**」。

| Issue | 真实状态 | 可核验证据（本轮实读） | 卡点 | 下一步 |
|---|---|---|---|---|
| **#145** 升级适配 | ✅ 已闭环（**已关闭**） | `cnb issues get --number 145` → `state: closed`；PR #175 merged（base=main）；`origin/main:dsh-adapter/package.json` 在；main 上真跑 `test_dsh_adapter.sh` 18/0、`新版适配链路.sh` 11/0 | — | 无需动作，仅留痕 |
| **#162** selector 映射 | ✅ 已闭环（**已关闭**） | `state: closed`；PR #163 merged（base=main）；`scripts/feature-verify/modules.map` 在 main | — | 无需动作，仅留痕 |
| **#169** 修评审 | ✅ 已闭环（**已关闭**） | `state: closed`；PR #172 merged（base=main）；`test_relay_card.sh` 11/0（含 `Issue #169` 断言） | — | 无需动作，仅留痕 |
| **#168** feature-verify 🟡 | ✅ 已关闭（两项均已落地） | `state: closed`；项1 `map_registered` 在 main 已成单点函数；项2 `Then-10d` 恒等 sed 已清（提交 `27bd056`，**在 PR #178 分支上**） | ⚠️ 注意：**项2 的修复只在 PR #178 分支，未进 main** —— 若 #178 被长期搁置，本单的「已关闭」会变成事实上的半落地 | #178 合并后本单才算真正落 main |
| **#165** collab 🟡×5 | 🟡 已实现 · **待复评**（深度 L4 交付待闸） | 5 项全部实现 + 每项变异 RED 验证；交付 **PR #178**（base=main，`merge-tree` 对 main **无冲突 rc=0**）；本地复跑 `test_data_layer` 🟢 / `test_collab` 🟢 / `doc_consistency` PASS=99 / `feature_verify` PASS=59 / `--all` 10/0 | **评审已出 🔴必修×2**（见下节），且同单前作 **PR #176 是假修**（强引用判遗弃 → 兜底永不触发，已关） | 按评审 🔴×2 返工 → 复评清零 → 转测试 → ⏸CP3 |
| **#166** 评论流分页 | ⚠️ **真·未实现**（唯一一条真没做的） | `state: open`、仅 1 条评论（那张 `state=error` 的触发卡）；统一「读评论流默认全量」入口在 main 上不存在 | 唤醒曾经失败 + 优先级 p5 被一拖再拖 | 重发前**先补 `@`+分页**（本单自己讲的就是这坑，讽刺）→ 真唤醒 → 验收 |
| **#177** 联调链路 | 🔴 **两类事实并存，必须分开说** | ① `state: open`，**4 条评论**；② 评论 15:07:56 声称的 `wake_loop` 模块 / 提交 `4e56868` / 14 组信号灯 —— **全部不存在**（`origin/main:local-agent/wake_loop/__init__.py` 无；`git ls-remote 'refs/heads/auto/wake-loop*'` 无）；③ 15:28 与 15:40 两条评论**自己也承认前一条是编造**，并称改动提交为 `54b5ff7` / 分支 `auto/wake-loop-37343` —— 同样**远端不存在**；④ `.cnb.yml` 的 `model: deepseek-v4.1-flash` 仍在 main（第 231 行），`hy3` 仍未进 main | **产物与留痕对不上**：#177 上至少三轮「已交付」都查不到实体 | 要么补出真实提交+PR，要么明确判「未交付」重做；**不要再把评论当产出** |
| **#178** PR | 🟡 open · 待返工 | `state: open`；评审结论 `fix_bug`（🔴×2）已发 | 见 #165 行 | 返工 → 复评 |
| **#170** 管理 issue | ✅ 本单 | 本台账 + 跟踪表 | 人类 ⏸CP3（合本 PR） | 合本 PR → 关本单 |

**诚实标注（dispatch_verify 判据）**：只有到 **L4（接单→开工→进度尺→交付→复评/合入）** 才算成功。
`#165` 现在最深的可信状态是「**已实现、待复评**」，不是「已派活」，更不是「已完成」。

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
5. **PR #171 已 `closed`**（`base=auto/architect-framework-7a13`，错路径族）。其想修的「唤醒静默失效」
   在 main 上**仍然存在**：`origin/main:.cnb.yml` 第 231 行 `model: deepseek-v4.1-flash`。
   #177 上那条「改成 hy3」的交付评论在远端**查无实体**，所以这条修复目前是「**提过、关了、没落地**」。

## 五、剩余 open 汇总（真实口径 · 2026-10-19）

`cnb issues list-issues --state open` 实读 **4 条**：#177 / #170 / #166 / #165。

- **已实现待闸**：#165（PR #178 待按 🔴×2 返工）、#168（已关，但项2 修复在 #178 分支、未进 main）
- **真没做**：#166（读评论流统一入口）
- **产物对不上**：#177（声称的模块/提交/分支在远端均不存在）
- **本单**：#170
- **已闭环关闭**：#145 / #162 / #169（证据见上表）

### 本轮（PR #173）自己纠的两处硬伤

1. **本 PR 里混进了 4 个 `node_modules` 离线桩文件**
   （`dsh-adapter/node_modules/@deepseek-ai/{cordis,dsh-tools}/{index.js,package.json}`），
   来自提交 `0faa617`（夹在台账改动里，非故意）。它们**与 main 的 `dsh-adapter/package.json`
   peerDependencies 语义冲突**（`@deepseek-ai/dsh-tools: >=0.1.5-rc.1` vs 桩 `0.0.0-offline-stub`），
   且 `dsh-adapter/.gitignore` 本就忽略该目录 → 本轮**移出版本库**，并在根 `.gitignore` 加兜底，
   防止下次 `git add -f` 再把它带进来。
2. **上一版台账把自己的结论写死了**（判 #165「L2 未唤醒」），实际是读评论流没分页漏读——
   正是 #166 要修的那个坑。已在第三节按实读数据改写并留痕。

> 结论：**不是「都处理了」，也不是「都没处理」**。真相是「大部分已实现、闸门卡在评审与 CP3 上，
> 外加一条 #177 的产物根本查不到」。任何一条要标「完成」，先拿得出可核验实体。

