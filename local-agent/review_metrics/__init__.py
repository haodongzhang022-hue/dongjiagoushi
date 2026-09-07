# -*- coding: utf-8 -*-
"""
有效性度量模型模块（review-metrics · Issue #100 决策 ⑤）
=========================================================
把「评审/交付有效性度量」从"笼统解决率"升级为**多维 + 概率×程度分档 +
留痕**的确定性模型。用户拍板要点（Issue #100）：

  - 不要单一"解决率"（90% 算不算解决、10 个 30%/60% 怎么平均都有歧义）；
  - 要多维：问题解决度 / 小八哥率 / 稳定性 / 通用性 / 跨场景一致性；
  - 分档：profile = (概率, 解决程度) 分布，如"10% 概率 99% 解决"；
  - 可量化评估 + 以测试为准（唯一事实源），不靠主观看法。

对外公开接口：
  - spec                      维度/档位/阈值/权重 唯一事实源
  - engine.normalize_profile  归一化观测
  - engine.aggregate          多维归并 → 总体有效度
  - engine.judge              确定性达标判定
  - engine.trace              留痕
  - ReviewMetricsAbility      全员能力（BaseRole 已挂载）

用法（任意角色实例，BaseRole 已挂载）：
  role.metrics_dims()
  role.measure_review({...})
  role.metrics_aggregate([...])
  role.metrics_judge([...])

CLI：
  python -m review_metrics.cli dims
  python -m review_metrics.cli measure '{"dims":{...}}'
  python -m review_metrics.cli judge '[...观测列表...]'
  python -m review_metrics.cli trace
"""
from . import spec, engine
from .ability import ReviewMetricsAbility

__all__ = [
    "ReviewMetricsAbility",
    "spec",
    "engine",
    "normalize_profile",
    "aggregate",
    "judge",
    "trace",
]

# 便捷透传
normalize_profile = engine.normalize_profile
aggregate = engine.aggregate
judge = engine.judge
trace = engine.trace
