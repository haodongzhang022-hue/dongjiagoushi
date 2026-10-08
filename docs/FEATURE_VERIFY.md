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
[pending: ]<evidence-module>: <代表性实现源路径（自测探针）>: <实现源选择 ERE>
```
`pending:` 前缀 = **显式「待落地前置登记」**（证据目录暂由外部 PR 落地，如跨 PR 并发）。
- 新增 feature-verify 模块必须在 `modules.map` 登记，否则 `--check-map` 判 RED；
- 实现源路径变更须同步改该行 ERE，否则探针失配 → RED；
- 同一实现源命中多模块时全部选测（宁多跑，不漏跑）。

防退化断言（有牙齿）：
```bash
bash scripts/feature-verify.sh --check-map   # 未映射 / 映射失效 / 未标记目录缺失 → RED
```
① 证据库每模块须已登记 ② 探针路径须真实存在 ③ 模拟"改该模块实现源"须真被选中
④ 映射行指向暂无证据目录的模块 → **按是否显式 `pending:` 标记分流**（复评 T9）；
⑤ 目录已落地仍挂 `pending:` → ⚠️ 提示转正式登记。
CI 的 `feature-verify gate` 先跑它再跑 `--changed`。

**僵尸容忍为何必须收窄到显式 `pending:`（复评 T9）**：真正的漏跑方向是
①「目录有、映射无」（那才 RED）；而"映射有、目录无"必须区分两种成因——
- **跨 PR 中间态**（A PR 先登记映射、B PR 后落证据脚本）：正常顺序，须容忍，
  否则先合"登记映射"的 PR、再合"落脚本"的 PR，后合那个一落 main 就让主线判红；
- **证据目录被误删/改名/映射残留**：属 #162 要消灭的**静默假绿**形状（实现源变更
  既不被选测、也不落"未映射"告警 → `exit 0`），绝不能放过。

旧行为对两者一律 ⚠️ 放过 = 分不清成因、重开假绿。故容忍**只给显式标记**：
`pending: collab: …`（脚本由 PR #161 落地）才 ⚠️ 不阻断；**未标记**的目录缺失一律 RED，
且 `--changed` 命中该模块实现源时**硬失败**（不再「无可选脚本 → 通过」）。
本 PR 已用 `pending: collab:` 显式预登记，并在 selector 样例
Then-9/10/11 + `test_feature_verify` T16/T20/T21 双向锁死该行为。
### 变更范围回退链（防假绿 · Issue #162 复评 R1 + 🟡欠选）
`--changed` 确定变更范围时按**两级回退链**逐个来源尝试，判据是 **`git diff` 真成功
（`rc=0`）**，不是"来源存在"：

- **可靠来源**（给出**真实 PR 范围**）：注入变量 `FEATURE_VERIFY_CHANGED_FILES` →
  `CNB_PULL_REQUEST_TARGET_SHA` → `main...HEAD`。diff 成功即采信（成功且为空 = 权威
  "确无变更"）。
- **收窄来源**（只覆盖**最后一个提交**）：`HEAD~1..HEAD` → 多提交 PR 会欠选（漏跑），
  故**不静默收窄**，标记 `CHANGED_NARROWED=1` 转保守全量。

**为什么以 `rc=0` 为准**：旧实现只要来源被尝试就 `resolved=1`（"尝试"当"成功"），
于是「diff 失败但来源存在」→ `resolved=1` → 报「变更范围为空 → 跳过」→ `exit 0`
**假绿**。真实 CI feature-verify gate 必设 `CNB_COMMIT`，旧实现在此路径恒假绿
（`CNB_COMMIT` 分支条件 `HEAD = CNB_COMMIT` 在 CI 恒成立，随后 `HEAD~1..HEAD` 在浅
克隆/单提交下失败、`out` 为空，但 `resolved=1` 已无条件写入）。

**保守全量触发**：回退链全部落空（浅克隆单提交、target SHA 不可解析且无 `main`）**或**
仅剩收窄来源（可能欠选）→ 置 `CHANGED_KNOWN=0` → **保守全量回归**（不漏跑优先），
绝不跳过。回归断言见 `tests/test_feature_verify.sh` T14（含**带 `CNB_COMMIT`** 场景
T14c/T14d）+ T14e（收窄不欠选）+ T15（回退链不断）+ 功能级
`selector/映射全覆盖.sh` Then-7a/7b（含 `CNB_COMMIT` 场景）。

映射表 ERE 读取用**安全 trim**（只去首尾空白、不解释反斜杠）——旧实现用 `xargs` 会吞掉
ERE 里的 `\.` 转义，把 `scripts/x\.py` 变成 `scripts/x.py`（`.` 变通配，映射失真）。
回归断言见 `selector/映射全覆盖.sh` Then-8。

**测试前提钉死（复评 R2）**：T14/T14e/T15/Then-7 的 fixture 用 `git init -q -b work`
**显式指定非 `main` 分支名**，不依赖环境 `init.defaultBranch`——默认 `main` 的环境
（git ≥2.28 常见配置）下 fixture 会自带可解析 `main`，前提失效、测的不是目标路径。

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

## 云端真跑本自测（复评 🟡3 / 残留 B · 🔴必修 1 已清零）
`tests/test_feature_verify.sh` 已登记 `local-agent/hybrid/registry.json`。云端 CI 的变更感知
链路是 `.cnb.yml` → `IncrementalSelector`（`local-agent/hybrid/selector.py`，读 `registry.json`）。

**承重 covers（逐条真验，删任一条 → T12b 必红）**：

| 变更文件 | 含义 |
|---|---|
| `scripts/feature-verify.sh` | 闸门本体 |
| `scripts/feature-verify/modules.map` | 模块→实现源映射 |
| `local-agent/hybrid/selector.py` | 选择器本体 |
| `scripts/feature-regress.sh` | 回归诊断 |
| `scripts/change-aware-test.sh` | 变更感知手工入口 |
| `docs/FEATURE_VERIFY.md` | 模块文档 |
| `.cnb.yml` | CI 接线 |

**选择器过滤口径（🔴必修 1）**：`selector.py` 原先 `not f.endswith(".sh")` 把所有 `.sh` 变更
一并过滤，导致 `covers: ["scripts/xxx.sh"]` 成为永不命中的**死条目**——改闸门本体在云端不选中本自测。
已收窄为**只过滤测试脚本自身**（`tests/` / `local-agent/tests/` 前缀），`scripts/*.sh` 作为源码按
covers 真触发；"改测试脚本自身不触发其他测试"的原有语义保留。

- 断言：T12a（registry 登记）；T12b **逐条真验**——期望承重 covers 钉死在测试里，每条单独喂
  `IncrementalSelector.select([cf])` 断言命中本自测，**删任一条 → 必红**；无 python3 则计
  **SKIP**（不计入 PASS/FAIL），显式暴露"本机未验链路"，不假装通过。
- `scripts/change-aware-test.sh` 的手工入口映射保留，供本地/手动执行，**不再作为唯一判据**。
