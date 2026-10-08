# feature-verify —— 功能级校验机制（Issue #109 · module v0.1.0 init）

> 把"以测试为准"从**抽象机制通畅**落到**具体目标功能是否按可感知语义真正做完了**。
> 每个目标功能在开发前先建一份机器可判的校验脚本（Test-First），一个 PR 对应一份，
> 跑不过 = 功能没做完。

## 分层一句话
`tests/test_*.sh` 保框架/机制畅通 → **`feature-verify/*.sh` 保具体目标功能完成** →
崩了跑 `feature-regress.sh` 定位坏功能 → `review_metrics` 分档量化度量。

三者是**互补的三层**，不互相替代、不重叠：
| 层 | 保什么 | 判据 | 载体 |
|---|---|---|---|
| 信号灯 test_*.sh | 框架/机制是否畅通（静态断言 / 通畅） | 断言 / grep 存在性 | `local-agent/tests/`、`tests/` |
| **功能级 feature-verify** | **具体目标功能是否按可感知语义做完** | 真实跑功能 + 语义产物 | `scripts/feature-verify/<module>/<功能>.sh` |
| 量化 review_metrics | 解决度/稳定性/通用性等分档量化 | (prob, degree) 分布 | `local-agent/review_metrics/` |

## 机制要素
1. **Test-First**：开发 PR 前先写校验脚本，再写实现（先红后绿）。
2. **一 PR 一脚本**：`scripts/feature-verify/<module>/<功能名>.sh`。
3. **跑不过 = 功能没做完**：合并闸门跑之，红 → `blocked_on: feature_unverified` 阻断合并，
   不允许以"我完成了"标绿。
4. **脚本留存**：不删，即**功能支撑证据档案库**，随模块版本线留痕，供回归复现。
5. **回归定位**：崩了 / 升级后跑 `scripts/feature-regress.sh` 全量回归，输出哪个功能通过 /
   哪个崩，崩的即坏功能（恢复能力一部分）。

## 五要素（每份校验脚本头部声明的机器可读契约）
| 要素 | 含义 |
|---|---|
| Given | 前提 / 前置（需要什么才能跑） |
| When | 触发——实际执行什么动作 |
| Then | 断言——按可感知语义判"功能完成"的机器判据（不是"通畅"） |
| Evidence | 可核验产物——跑完落到哪个可 grep/可查的语义产物 |
| Why 功能级 | 说明纯 grep/通畅抓不到、本脚本如何真实判"功能做完" |

## 模块→实现源映射（唯一事实源 · Issue #162）
`--changed` 按变更选测受影响模块，映射**只在一处维护** = `scripts/feature-verify/modules.map`
（不再散落 `case "$srcmod"` 硬编码——原缺口：7 个证据模块只覆盖 3 个，未覆盖模块的实现源
变更**静默漏跑**，`exit 0` 假绿）。

格式（每行一条，`:` 分隔）：
```
<evidence-module>: <代表性实现源路径（自测探针）>: <实现源选择 ERE>
```
- 新增 feature-verify 模块必须在 `modules.map` 登记，否则 `--check-map` 判 RED；
- 实现源路径变更须同步改该行 ERE，否则探针失配 → RED；
- 同一实现源命中多模块时全部选测（宁多跑，不漏跑）。

防退化断言（有牙齿）：
```bash
bash scripts/feature-verify.sh --check-map   # 未映射 / 映射失效 / 僵尸条目 → RED
```
① 证据库每模块须已登记 ② 探针路径须真实存在 ③ 模拟"改该模块实现源"须真被选中
④ 映射表不得有指向不存在模块的僵尸条目。CI 的 `feature-verify gate` 先跑它再跑 `--changed`。

## 目录与命令
```
scripts/feature-verify/
  modules.map                     # ⭐ 模块→实现源映射（唯一事实源 · Issue #162）
  README.md                       # 使用说明 + 写脚本铁律
  _templates/verify.template.sh   # 新功能骨架（复制改名）
  <module>/<功能名>.sh             # 一处一功能（module=实现域）
scripts/feature-verify.sh          # 主执行器（all/module/feature/changed/check-map/list）
scripts/feature-regress.sh         # 回归诊断（--all 语义别名）
```
```bash
bash scripts/feature-verify.sh --all             # 全量回归
bash scripts/feature-verify.sh --changed         # 按变更自动选测（PR 门禁用）
bash scripts/feature-verify.sh --list            # 证据库盘点
bash scripts/feature-verify.sh --check-map       # 映射防退化断言（未映射/失效即 RED）
bash scripts/feature-regress.sh [--module X]     # 回归诊断定位坏功能
```

## 合并闸门（S05 功能级延伸）
- feature-verify 是 dev-standard **S05（每个 PR 自带测试+文档）的功能级延伸**：
  除了 test_*.sh + docs，每个目标功能还须自带一份 `feature-verify/<module>/<功能>.sh`。
- `.cnb.yml` 的 `pull_request` 流水线新增 `feature-verify gate` 阶段：按本 PR 变更选测受影响
  功能模块并真实跑其校验脚本。跑不过 → 硬失败 → `blocked_on: feature_unverified` 阻断合并，
  不以"断言/通畅"替代功能级判据。

## 真实样例（证明功能级 > 断言）
- `dashboard/看板呈现链路.sh`：校验看板呈现的**语义内容**（演进看板/里程碑/声明汇总真在），
  而非仅"文件存在"——缺语义段即判看板功能没做完。
- `dispatch/真实唤醒校验闸门.sh`：真实跑 dispatch 引擎，判无 [接单] 回执任务是否诚实落
  `awaiting_receipt`、不谎报全唤醒——纯 grep 查不到。

## 风险与规避
- 校验脚本写得像"断言"失去功能级意义 → 用真实功能样例 + 五要素卡质量，且要求给出
  "Why 功能级"说明。
- 与 change-aware 按变更选测需协调复用 → `feature-verify.sh --changed` 复用既有
  change-aware 思路（git diff 定变更范围 → 按模块映射选测）。
