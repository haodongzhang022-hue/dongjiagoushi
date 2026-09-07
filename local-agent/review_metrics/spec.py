# -*- coding: utf-8 -*-
"""
有效性度量模型 · 维度与分档规范（spec · 唯一事实源）
=====================================================
对应 Issue #100 决策 ⑤（评审有效性度量细化分档）。用户拍板要点：

  - "有效性度量还需要进一步……牵扯程序的崩溃、稳定性、通用性、跨场景一致性
     之类需要更多指标评估" —— 故**多维**（不是单一"解决率"）；
  - "解决率太笼统……解决 90% 算解决率怎么样？10 个问题有的 30% 有的 60%
     算增加还是减少？应该更具体的判断" —— 故**概率 × 程度分档**，不用简单均值；
  - "给他分档位……10% 概率 99% 解决，20% 概率 98% 解决，类似这样，
     分档位可能还好一点" —— 故**profile = (概率, 解决程度) 分布**而非单点；
  - "最好是能量化评估的" + 决策 ④"以测试为准，不是以看法" —— 故判定基于
     客观观测（测试信号灯 / 回归 / 崩溃数据）留痕，确定性可核验。

本文件是**维度与分档的唯一规范来源**：维度注册表 + 档位划分 + 每个维度的
口径说明。引擎（engine.py）、能力（ability.py）、文档、测试都从这里对齐，
杜绝各角色"自造指标"。
"""
import json
import os

# ======================================================================
# ① 维度注册表（唯一事实源）：一个评审/交付干预从哪些维度度量有效性
# ======================================================================
# dim -> 规范信息：
#   name       维度中文名
#   direction  越高越好(1) / 越低越好(-1)，用于统一"有效度"口径
#   unit       量纲
#   what       度量什么（口径，供客观观测对照）
#   default    无观测时的兜底 degree（避免缺数据直接判失败，落到中性）
DIMENSIONS = {
    "resolution": {
        "name": "问题解决度",
        "direction": 1,        # 越高越好
        "unit": "degree",
        "what": "评审发现的问题最终被有效修复的程度（复评通过/测试信号灯通过），"
                "分档表达：p 概率达到 d 程度",
    },
    "bug_rate": {
        "name": "小八哥率",
        "direction": -1,       # 越低越好（引入缺陷的概率）
        "unit": "prob",
        "what": "每次交付引入缺陷的概率（回归测试新红 / 复评新发现 🔴），"
                "越低越好",
    },
    "stability": {
        "name": "稳定性",
        "direction": 1,
        "unit": "degree",
        "what": "程序崩溃 / 运行稳定性，如崩溃率、故障间隔、跑批成功率",
    },
    "generality": {
        "name": "通用性",
        "direction": 1,
        "unit": "rate",
        "what": "修复/方案能否在多场景复用（跨任务复用命中率）",
    },
    "consistency": {
        "name": "跨场景一致性",
        "direction": 1,
        "unit": "degree",
        "what": "同需求在多场景下表现是否一致（场景间结果方差越小越好），"
                "此处用一致度 1-方差表达",
    },
}

# 有效度口径说明：有效性 = 客观观测，不靠"看法"
EFFECTIVE_POLICY = (
    "有效性度量以『唯一事实源』为准（测试信号灯 / 回归红绿 / 崩溃数据 / "
    "复评通过与否），不以主观看法为准；每档可核验区间，供评审/测试客观复用。"
)

# ======================================================================
# ② 档位划分（概率 × 程度分档）—— 唯一规范来源
# ======================================================================
# 档位（grade）：把"程度 degree ∈ [0,1]"切成离散档，避免"90% 算不算解决"争议。
#   band_edges 每个维度的程度分档边界（左闭右开，末档含 1.0）。
# 档位结果给人类俯瞰 + 供概率分布归并（有多少概率质量落在哪个档）。
DEFAULT_BAND_EDGES = [
    (0.00, 0.60, "low",    "低档（基本没解决 / 质量差）"),
    (0.60, 0.85, "mid",    "中档（部分解决 / 部分达标）"),
    (0.85, 0.97, "high",   "高档（基本解决 / 基本达标）"),
    (0.97, 1.01, "full",   "满档（完全解决 / 完全达标）"),
]

# 每维度默认档位边界（方向为 -1 的维度会反向解释，见 engine.band_degree）
BAND_EDGES = {dim: DEFAULT_BAND_EDGES for dim in DIMENSIONS}

# 判定阈值（deterministic）：
#   达标判定只看"满档+高档"概率质量占比（weighted_high_mass）是否达到 threshold。
#   - review 有效性判定要更严（质量守门）
#   - 每个维度方向不同，engine 会先按 direction 归一化 degree 到"越高越好"
#     再做档位归并（bug_rate 越低越好 → 翻转成 1-rate）。
JUDGE_THRESHOLDS = {
    "resolution": 0.85,   # 解决度高档+满档质量占比需 ≥85%
    "bug_rate":   0.90,   # 无新增缺陷概率占比需 ≥90%（1-bug 高档）
    "stability":  0.90,
    "generality": 0.80,
    "consistency":0.85,
}

# 参与"总体有效度"加权聚合的维度权重（归一化用，供 overview 总评）
DIM_WEIGHTS = {
    "resolution":  0.35,   # 首要：到底解决了没
    "bug_rate":    0.25,   # 没制造新问题
    "stability":   0.20,
    "generality":  0.10,
    "consistency": 0.10,
}

# ======================================================================
# 留痕（trace）持久化目录（本地 SQLite 之外的文件留痕，配合 data/ archives）
# ======================================================================
_TRACE_STORE = {}
_TRACE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state", "review_metrics_trace.json",
)


def _ensure_dir():
    d = os.path.dirname(_TRACE_FILE)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def valid_dims():
    """返回全部规范维度。"""
    return list(DIMENSIONS)


def dim_spec(dim):
    """返回某维度的规范信息；未知维度抛 KeyError（防自造指标）。"""
    if dim not in DIMENSIONS:
        raise KeyError(
            f"INVALID_DIMENSION={dim}（规范维度见 spec.valid_dims()，"
            f"禁止自造指标，见 docs/REVIEW_METRICS.md）"
        )
    return DIMENSIONS[dim]


def band_edges(dim):
    """返回某维度的程度档位边界。"""
    return BAND_EDGES[dim]


def band_names():
    """返回全部档位名（文档/看板/测试对齐用）。"""
    return [e[2] for e in DEFAULT_BAND_EDGES]


def judge_threshold(dim):
    return JUDGE_THRESHOLDS[dim]


def weights():
    return DIM_WEIGHTS


def summary():
    """机器可读规范摘要（供文档/测试断言对齐，防漂移）。"""
    return {
        "dims": list(DIMENSIONS),
        "band_edges": {d: [(lo, hi, g) for lo, hi, g, _ in BAND_EDGES[d]]
                       for d in DIMENSIONS},
        "thresholds": JUDGE_THRESHOLDS,
        "weights": DIM_WEIGHTS,
        "effective_policy": EFFECTIVE_POLICY,
    }
