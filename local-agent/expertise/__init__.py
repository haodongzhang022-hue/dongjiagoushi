# -*- coding: utf-8 -*-
"""
专家级架构能力（expertise · 通用架构师的能力底座）
==================================================
「通用架构师」不等于「什么都会的架构师」。本包把「专家级」拆成**可执行的四个
组成部分**，缺任何一块都不成立：

  1. **专家层接入**（`experts`）：行业/岗位专家判定取自 hanghangchuzhuangyuan，
     架构师不凭空宣称「我懂所有行业」；
  2. **AI 前沿层**（`ai_frontier`）：明确「当前 AI 能做什么、下一步能解决什么」，
     能力边界带日期与来源，陈旧即失效；
  3. **帕累托前沿**（`pareto`）：多目标备选方案的显式比较与取舍解释；
  4. **七维评判 + 外部验证门禁**（`evaluator` / `external_validation`）：高度/深度/
     广度/资源/实现路径/帕累托最优/外部验证，其中外部验证**只认真实执行过的
     功能性代码验证**，不认自述。

另有 **时效性闸门**（`freshness`）：陈旧信息不得作为决策依据。

本包不依赖任何第三方库即可运行（pyyaml 缺失时走极简兜底），便于云端 CI 与
异构机器一致判定。

快速使用：
    from expertise import evaluate, IndustryExpertLayer, AIFrontier, run_check
    layer = IndustryExpertLayer()
    layer.resolve("给律所做一个合同审查系统")      # -> 行业/岗位专家判定
    ev = run_check("python3 -m pytest tests/test_x.py -q")   # 真实执行证据
    verdict = evaluate({"dimensions": {...}, "claims": [ev], "facts": [...]})
"""
from .spec import (
    DIMENSION_KEYS,
    DIMENSION_SPECS,
    DIMENSION_BY_KEY,
    EXPERT_SOURCES,
    FRESHNESS_SPECS,
    JUDGE_THRESHOLDS,
    QUALITY_TIERS,
    REQUIRED_DIMENSIONS,
    validate_specs,
)
from .experts import IndustryExpertLayer
from .ai_frontier import AIFrontier
from . import pareto
from . import freshness
from . import external_validation
from .evaluator import assess as evaluate, explain
from .external_validation import gate as validation_gate, is_functional, run_check, verify_claim
from .freshness import assess as freshness_assess, gate as freshness_gate

__all__ = [
    # 规范
    "DIMENSION_SPECS", "DIMENSION_KEYS", "DIMENSION_BY_KEY", "REQUIRED_DIMENSIONS",
    "JUDGE_THRESHOLDS", "QUALITY_TIERS", "FRESHNESS_SPECS", "EXPERT_SOURCES",
    "validate_specs",
    # 能力
    "IndustryExpertLayer", "AIFrontier", "pareto", "freshness",
    "external_validation", "evaluate", "explain",
    "run_check", "verify_claim", "validation_gate", "is_functional",
    "freshness_assess", "freshness_gate",
]

__version__ = "0.1.0"
