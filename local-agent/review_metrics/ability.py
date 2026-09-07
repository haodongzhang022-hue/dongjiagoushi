# -*- coding: utf-8 -*-
"""
有效性度量全员能力（ReviewMetricsAbility · Issue #100 决策 ⑤）
================================================================
把「评审/交付有效性度量」封装为**每个 agent 可复用的通用能力**，默认挂载到
BaseRole，让任何评审/测试/经理/开发 agent 都能：
  - 查询有效性维度与分档规范（唯一事实源）；
  - 提交一次观测（干预/直改/交付）并做概率×程度分档度量；
  - 归并多次观测得到多维 + 总体有效度；
  - 得到确定性达标判定（对照测试信号灯等客观事实）；
  - 留痕供回溯与监控。

设计（对齐用户拍板）：
  - 独立模块（local-agent/review_metrics/）可各处引用；
  - 确定性（非 LLM 判断）：给定观测必然产出相同分档结果；
  - 维度化 + 概率×程度分档 + 留痕，不靠主观"看法"；
  - 能力挂载到 BaseRole（与 Dispatch/Handle/Depth/Label/Standard 一致）。

用法（任意角色实例，BaseRole 已挂载）：
  role.metrics_dims()                        # 列出有效性维度
  role.measure_review(observation)           # 提交一次观测并度量
  role.metrics_aggregate(observations)       # 归并多次观测 → 总体有效度
  role.metrics_judge(observations)           # 确定性达标判定
  role.metrics_trace_recent()                # 最近留痕（监控/看板）
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class ReviewMetricsAbility:
    """有效性度量全员能力。owner 绑定所属 agent（评审/测试/经理等）。"""

    def __init__(self, owner=None):
        self.owner = owner
        self._owner_name = getattr(owner, "name", "") or (owner if isinstance(owner, str) else "系统")

    # ---- 规范查询（全员开放）----
    def metrics_dims(self):
        """列出有效性维度（唯一事实源）。"""
        from review_metrics import spec
        return spec.valid_dims()

    def metrics_spec(self):
        """机器可读规范摘要（维度/档位/阈值/权重）。"""
        from review_metrics import spec
        return spec.summary()

    def metrics_band_names(self):
        """返回档位名清单。"""
        from review_metrics import spec
        return spec.band_names()

    # ---- 度量与判定（确定性）----
    def measure_review(self, observation, trace=True, meta=None):
        """提交一次观测，做分档度量并（可选）留痕。返回 {trace_id, result}。"""
        from review_metrics import engine
        n = engine.normalize_profile(observation)
        r = engine.aggregate([n])
        j = engine.judge(r)
        out = {"normalized": n, "result": r, "verdict": j}
        if trace:
            out["trace_id"] = engine.trace(observation, r, meta=meta or {"actor": self._owner_name})
        return out

    def metrics_aggregate(self, observations):
        """归并多次观测 → 每维 + 总体有效度。"""
        from review_metrics import engine
        return engine.aggregate(observations)

    def metrics_judge(self, observations):
        """归并并给确定性达标判定。"""
        from review_metrics import engine
        r = engine.aggregate(observations)
        return engine.judge(r)

    def metrics_trace_recent(self, limit=20):
        """最近留痕（监控/看板俯瞰）。"""
        from review_metrics import engine
        return engine.trace_recent(limit=limit)

    def capability(self):
        """返回能力声明（供 capability() 汇总）。"""
        return {
            "review_metrics_ability": {
                "version": "0.1.0",
                "dims": self.metrics_dims(),
                "policy": "维度化 + 概率×程度分档 + 留痕，以测试为准不靠看法",
            }
        }
