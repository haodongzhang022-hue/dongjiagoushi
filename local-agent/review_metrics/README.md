# 有效性度量模型（review-metrics）

> Issue #100 决策 ⑤ · 把"评审/交付有效性度量"从**笼统解决率**升级为
> **维度化 + 概率×程度分档 + 留痕**的确定性模型。

## 为什么

用户拍板（Issue #100）：

- **单一"解决率"太笼统**：解决 90% 算不算解决？10 个问题有的 30% 有的 60%，
  算"解决率增加还是减少"？——简单均值有歧义。
- **要多维**：不只解决率，还含缺陷率 / 稳定性 / 通用性 / 跨场景一致性。
- **要分档**：用 `profile = (概率, 解决程度)` 分布，如"10% 概率 99% 解决；
  20% 概率 98% 解决"，规避聚合歧义。
- **可量化评估 + 以测试为准**：有效性由"唯一事实源"（测试信号灯 / 回归红绿 /
  崩溃数据 / 复评通过与否）客观判定，不靠主观"看法"（决策 ②④）。

## 核心概念

### 维度（5 维 · spec.DIMENSIONS 唯一事实源）

| dim | 名称 | 方向 | 度量口径 |
|---|---|---|---|
| resolution | 问题解决度 | 越高越好 | 评审发现的问题最终被有效修复的程度（复评通过/测试通过） |
| bug_rate | 缺陷率 | 越低越好 | 每次交付引入缺陷的概率（回归新红/复评新发现 🔴） |
| stability | 稳定性 | 越高越好 | 崩溃率 / 故障间隔 / 跑批成功率 |
| generality | 通用性 | 越高越好 | 修复/方案跨任务复用命中率 |
| consistency | 跨场景一致性 | 越高越好 | 同需求多场景结果方差（一致度 1-方差） |

### 概率 × 程度分档

每个维度用一组 `(prob, degree)` 表达"以多少概率达到多高程度"：

```
resolution: [{prob:.1, degree:.99}, {prob:.9, degree:.3}]
  → 10% 概率完全解决(99%)，90% 概率只解决 30%
```

归并后给出每维的**档位质量分布**（low/mid/high/full 各占多少概率质量）、
**达标质量占比**（high+full 质量）、**加权程度**——避免用歧义均值。

档位（spec.DEFAULT_BAND_EDGES）：

| 档 | degree 区间 | 含义 |
|---|---|---|
| low | [0, 0.60) | 基本没解决 / 质量差 |
| mid | [0.60, 0.85) | 部分解决 / 部分达标 |
| high | [0.85, 0.97) | 基本解决 / 基本达标 |
| full | [0.97, 1.00] | 完全解决 / 完全达标 |

> 方向为"越低越好"的维度（如 bug_rate）会先翻转（有效度 = 1-degree）再做档位判定。

### 判定（确定性）

对照 spec.JUDGE_THRESHOLDS，按"高档+满档质量占比 ≥ 阈值"判定达标与否；
总体达标 = 已观测维度全部达标。同输入必然同输出。

## 用法

### 作为角色（BaseRole 已挂载 ReviewMetricsAbility）

```python
from roles.reviewer import ReviewerRole
r = ReviewerRole()
r.metrics_dims()                       # ['resolution','bug_rate',...]
r.measure_review(obs)                  # 提交一次观测，分档度量+留痕
r.metrics_aggregate([obs1, obs2])      # 多次归并 → 每维+总体有效度
r.metrics_judge([obs1, obs2])          # 确定性达标判定
r.metrics_trace_recent()               # 最近留痕
```

### CLI

```bash
cd local-agent
python -m review_metrics.cli dims
python -m review_metrics.cli spec
python -m review_metrics.cli measure '<obs-json>'     # 单次度量+留痕
python -m review_metrics.cli judge '<obs-list-json>'  # 多次归并+判定
python -m review_metrics.cli trace
```

## 目录结构

```
local-agent/review_metrics/
  spec.py      维度/档位/阈值/权重 唯一事实源
  engine.py    确定性引擎（归一化/分档/归并/判定/留痕）
  ability.py   ReviewMetricsAbility（BaseRole 全员挂载）
  cli.py       CLI（MCP 管线）
  README.md    本文件
local-agent/tests/test_review_metrics.sh   功能测试（7 组信号灯）
```
