# -*- coding: utf-8 -*-
"""
monitor_bi · 异常监控（M4 · anomaly.py）
==========================================
「体系健康度异常检测」：识别三类异常并标出（⚠️ + 原因）。

复用 sentinel 引擎（停滞/横跳/重复错误三类已有判定）+ 新增分工失衡第 4 类：
  - **stagnation（停滞）**：读 sentinel_actions（reason=stagnation），口径与哨兵一致。
  - **oscillation（横跳）**：读 sentinel_actions（reason=oscillation）。
  - **repeated_error（重复错误）**：读 sentinel_actions（reason=repeated_error）。
  - **imbalance（分工失衡）**：新增判定——按四维统计工作量分布，
    单 agent 工作量占比 > 40% 或 同岗位量差 > 3 倍 即标失衡（阈值可配置）。

输出统一 Anomaly 结构：{entity, type, reason, severity}。
"""
from collections import defaultdict

from data import db
from monitor_bi import stats
from monitor_bi.token import token_share_imbalance

# 复用 sentinel 判定原因映射
SENTINEL_TYPE_MAP = {
    "stagnation": "停滞(没工作)",
    "oscillation": "横跳(反复回退)",
    "repeated_error": "重复错误(同一失败反复提交)",
}

# 分工失衡默认阈值（可配置）
DEFAULT_IMBALANCE = {
    "top_share_threshold": 0.40,   # 单 agent 工作量占比 > 40%
    "role_gap_ratio": 3.0,         # 同岗位量差 > 3 倍
}


def _read_sentinel_actions(limit=500):
    """读 sentinel_actions 表，返回异常动作列表。"""
    try:
        rows = db.query(
            "SELECT * FROM sentinel_actions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
    except Exception:
        # 表不存在或空库时返回空
        return []


def _read_sentinel_type(type_):
    """读指定类型的 sentinel 异常动作。"""
    try:
        rows = db.query(
            "SELECT * FROM sentinel_actions WHERE reason=? ORDER BY id DESC LIMIT 200",
            (type_,),
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


def sentinel_anomalies():
    """复用 sentinel 引擎：读三类异常（停滞/横跳/重复错误），口径与哨兵一致。"""
    result = []
    for reason, label in SENTINEL_TYPE_MAP.items():
        actions = _read_sentinel_type(reason)
        for act in actions:
            entity = act.get("agent_id") or act.get("task_id") or "(unknown)"
            result.append({
                "entity": entity,
                "type": reason,
                "reason": label,
                "severity": "high" if act.get("level") == 2 else "medium",
                "source": "sentinel",
                "detail": act.get("note") or act.get("detail") or "",
            })
    return result


def imbalance_anomalies(thresholds=None):
    """新增分工失衡判定（第 4 类异常检测）。

    依据四维统计的工作量分布，检测：
      1. 单 agent 工作量占比 > top_share_threshold（默认 40%）
      2. 同岗位量差 > role_gap_ratio 倍（默认 3 倍）
    """
    t = thresholds or DEFAULT_IMBALANCE
    anomalies = []

    # 1) 单 agent 工作量占比失衡（基于 token 消耗分布 + progress 事件分布）
    share = token_share_imbalance(threshold=t["top_share_threshold"])
    if share.get("imbalanced"):
        anomalies.append({
            "entity": share["top_agent"],
            "type": "imbalance",
            "reason": f"分工失衡：单 agent({share['top_agent']}) 工作量占比 {share['top_share']*100:.0f}% > 阈值 {t['top_share_threshold']*100:.0f}%",
            "severity": "medium",
            "source": "bi-imbalance",
            "detail": f"top_share={share['top_share']}, total={share['total']}",
        })

    # 2) 同岗位量差失衡（按 role 聚合工作量，取 max/min 比值）
    role_stats = stats.workload_4d("role")
    if len(role_stats) >= 2:
        max_w = role_stats[0]["total"]
        min_w = role_stats[-1]["total"]
        if min_w > 0 and max_w / min_w > t["role_gap_ratio"]:
            anomalies.append({
                "entity": "role",
                "type": "imbalance",
                "reason": f"分工失衡：岗位量差 {max_w/min_w:.1f} 倍 > 阈值 {t['role_gap_ratio']} 倍（max={role_stats[0]['key']}, min={role_stats[-1]['key']}）",
                "severity": "low",
                "source": "bi-imbalance",
                "detail": f"max_workload={max_w}, min_workload={min_w}",
            })

    return anomalies


def anomaly_scan(thresholds=None):
    """统一异常扫描入口：复用 sentinel + 新增分工失衡。返回统一 Anomaly 清单。"""
    return sentinel_anomalies() + imbalance_anomalies(thresholds)
