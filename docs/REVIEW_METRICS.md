# 有效性度量模型（Review Metrics）· 设计文档

> Issue #100 决策 ⑤ · 主链路落地：评审/交付有效性"可量化、分档、留痕、以测试为准"。
> 承载：`local-agent/review_metrics/`（新模块）。能力全员挂载（BaseRole）。

## 一、问题（用户盲区指认）

用户（Issue #100）指出现行"解决率"度量三个盲区：

1. **单一解决率太笼统**：解决 90% 算不算解决？10 个问题有的 30% 有的 60%，
   平均算"解决率增加还是减少"——聚合口径有歧义。
2. **维度不足**：有效性还牵扯程序崩溃 / 稳定性 / 通用性 / 跨场景一致性，
   不止"解决了没"。
3. **判定不可核验**：不能靠"主观看法"，要"以测试为准"（唯一事实源）客观判定。

## 二、方案（对齐用户拍板）

**多维 + 概率×程度分档 + 留痕，确定性可核验。**

### ① 维度化
5 个正交维度（见 local-agent/review_metrics/spec.py · 唯一事实源）：
问题解决度 resolution / 小八哥率 bug_rate / 稳定性 stability /
通用性 generality / 跨场景一致性 consistency。方向、量纲、口径、权重均规范声明，
禁止角色自造指标（未知维度引擎直接拒绝）。

### ② 概率 × 程度分档
不用单点均值，用 `profile = (prob, degree)` 分布：每档 = "以 p 概率达到 d 程度"
（如"10% 概率 99% 解决；20% 概率 98% 解决"）。归并后输出：
- **档位质量分布**：low/mid/high/full 各占概率质量；
- **达标质量占比**：high+full 质量之和（供判定）；
- **加权程度**：Σ(p·d)（辅助看，判定仍以档位质量为准）。

这直接解决"10 个 30%/60% 平均是增是减"——不再平均，而是看**概率质量落在哪个档**。

### ③ 留痕 + 以测试为准
每次观测（review_intervention / direct_fix / deliverable）写 `review_metrics_trace`
（本地 state 文件 + 尽力同步 data/ archives），记录归一化观测 + 分档归并结果，
供监控/看板回溯。判定只认客观事实（测试信号灯/回归红绿/崩溃数据/复评通过），
不认主观"看法"——对齐决策 ④"固化以测试为准"。

## 三、判定口径

对照 spec.JUDGE_THRESHOLDS（每维 high+full 质量占比阈值），各已观测维达标则
总体达标；同输入必然同输出（确定性）。这与「评审双轴 do_review」「统一审查处置
标签」衔接：评审/测试在裁决"是否有效解决"时可用本模型给出客观依据，而非拍脑袋。

## 四、与既有机制关系

| 既有机制 | 关系 |
|---|---|
| do_review 双轴评审 | 双轴产出"发现项+严重级"；本模型把"修复是否有效"量化成客观依据 |
| disposition 处置标签 | 度量达标 → merge/proceed；不达标 → fix_bug/consult 的依据 |
| dev-standard / 测试信号灯 | 客观"唯一事实源"即来自测试/回归红绿，本模型读它们做判定 |
| sentinel 监控哨兵 | 本模型留痕可供哨兵发现"高未解决率/高小八哥率"并打断升级 |
| data/archives | trace 尽力同步到 archives 供回溯 |


### 深度集成已落地（接入评审主流程 do_review）

> **接线点**：review-metrics 从"就绪的独立能力"接到**评审主流程 do_review**
> （Issue #100 决策 ⑤ 深度集成，已合入）。

每次评审走 `do_review()`（双轴 → 处置 → 路由）时，**自动**对本次处置做一次
确定性观测留痕（`kind=review_disposition`），不再需要评审者记得去调度量方法：

- 双轴达标放行（merge/proceed）→ 记录放行处置观测；
- 双轴有必修 / spec 不忠实 → 记录 fix_bug 打回处置观测；
- 缺轴评审不完整 → 仍记录处置观测（不完整态，禁止放行）。

**处置语义确定性映射**（不虚报自判有效）：
- 评审当下只留"**处置观测**"（评审客观给出的分派状态），
  resolution 的"最终是否真解决"由**后续复评/测试回填**（复评环节用
  `measure_review(kind=review_settled)` 或 `metrics_judge` 提交实测），
  对齐"以测试为准/不靠看法"纪律——评审不冒充自己已经解决。

**落地物**：
- `ReviewerRole._record_review_disposition()`：确定性观测留痕（reviewer.py）；
- `do_review()` 返回新增 `effectiveness` 字段（含 trace_id / disposition /
  blocked / axes_complete），评审调用方可直接消费；
- 留痕落 `review_metrics_trace`，`engine.trace_recent()` 可读，供
  sentinel 哨兵 / 监控看板统计"评审处置分布"（多少次放行 / 打回 / 不完整）。
- 测试 `tests/test_review_effectiveness_integration.sh`（5 组信号灯）。

**用户原始诉求闭环**：要监控"多少次评审解决了问题 / 多少次没解决 / 多少次额外
创造了问题"——评审处置观测已自动留痕，再叠加复评回填 resolution 实测，即可
按 task_key 聚合出解决/未解决/回归分布，形成可回溯的评审有效性闭环。


## 五、接口速查

见 `local-agent/review_metrics/README.md`。CLI / BaseRole 透传 / 引擎三入口齐备，
测试 `tests/test_review_metrics.sh`（7 组信号灯）。
