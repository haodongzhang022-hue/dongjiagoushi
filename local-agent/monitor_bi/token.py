# -*- coding: utf-8 -*-
"""
monitor_bi · token 分析（M2 · token.py）
========================================
「token 消耗分析」：按四维口径 + 时间趋势统计 token。

口径设计（架构·总师已决策）：
  - **双模式**：默认「估算兜底」（按字数×系数，默认 1.5 字/token），
    预留「真实回传」（messages 带 token_usage 字段则用真实值）。
  - **防重复**：按 msg_id 唯一去重（upsert），每条消息只计一次。
  - **聚合**：按 agent/role/conversation/project 四维 + 时间趋势（按 ts 时间桶）。

复用现有 data 层 token_usage 表 + repository 接口，不重造。
"""
import json
from collections import defaultdict

from data import repository as repo
from data import db


# ---- 默认估算系数（可注入覆盖） ----
DEFAULT_CHAR_PER_TOKEN = 1.5   # 1.5 字 ≈ 1 token（中文估算口径）


def estimate_tokens(text, chars_per_token=DEFAULT_CHAR_PER_TOKEN):
    """按字数估算 token（估算兜底模式）。"""
    if not text:
        return 0
    return max(1, int(len(str(text)) / chars_per_token))


def record_estimate(msg_id, text, agent_id="", role="", topic="", project="",
                    chars_per_token=DEFAULT_CHAR_PER_TOKEN):
    """登记一条估算 token 记录（若已存在则跳过/更新）。"""
    token_count = estimate_tokens(text, chars_per_token)
    return repo.upsert_token_usage(
        msg_id, agent_id=agent_id, role=role, topic=topic, project=project,
        token_count=token_count, method="estimate",
    )


def record_real(msg_id, token_count, agent_id="", role="", topic="", project=""):
    """登记一条真实回传 token 记录（method=real）。"""
    return repo.upsert_token_usage(
        msg_id, agent_id=agent_id, role=role, topic=topic, project=project,
        token_count=token_count, method="real",
    )


def token_summary(dim="agent", trend=False):
    """按四维聚合 token 消耗。

    dim ∈ {agent, role, conversation, project}。
    trend=True 时附加按时间桶（日/小时）的趋势序列。
    返回 {total, breakdown: [...], trend: [...]}。
    """
    field_map = {
        "agent": "agent_id",
        "role": "role",
        "conversation": "topic",
        "project": "project",
    }
    field = field_map[dim]
    rows = _query(f"SELECT {field} AS key, SUM(token_count) AS tokens, COUNT(*) AS n "
                  f"FROM token_usage GROUP BY {field} ORDER BY tokens DESC")
    breakdown = [{"key": r["key"] or "(unknown)", "tokens": r["tokens"] or 0, "records": r["n"] or 0}
                 for r in rows]

    result = {
        "total": repo.token_total(),
        "breakdown": breakdown,
    }
    if trend:
        result["trend"] = token_trend()
    return result


def token_trend(bucket="hour"):
    """按时间桶统计 token 消耗趋势。bucket ∈ {hour, day}。"""
    if bucket == "day":
        q = "SELECT substr(ts,1,10) AS bucket, SUM(token_count) AS tokens FROM token_usage GROUP BY substr(ts,1,10) ORDER BY bucket"
    else:
        q = "SELECT substr(ts,1,13) AS bucket, SUM(token_count) AS tokens FROM token_usage GROUP BY substr(ts,1,13) ORDER BY bucket"
    rows = _query(q)
    return [{"bucket": r["bucket"], "tokens": r["tokens"] or 0} for r in rows]


def token_share_imbalance(threshold=0.4):
    """计算 token 分布是否失衡（供分工失衡判定参考）。

    返回：{"total": 总token, "top_agent": 最大贡献agent, "top_share": 占比, "imbalanced": bool}
    """
    breakdown = token_summary("agent")["breakdown"]
    total = sum(b["tokens"] for b in breakdown)
    if total == 0 or not breakdown:
        return {"total": 0, "top_agent": "", "top_share": 0, "imbalanced": False}
    top = breakdown[0]
    share = top["tokens"] / total
    return {
        "total": total,
        "top_agent": top["key"],
        "top_share": round(share, 3),
        "imbalanced": share > threshold,
    }


def _query(sql, args=None):
    rows = db.query(sql, args) if args else db.query(sql)
    return [dict(r) for r in rows]
