# -*- coding: utf-8 -*-
"""
缓存命中监控机制（Cache Monitor · 按 agent 量化效果 · 浪费判定）
==================================================================
用户 Issue #41 明确要求：
  "需要建立一个能监控缓存命中率的机制……监控每个 agent 的缓存命中，
   才能量化效果怎么样，确定是否有浪费。只要没浪费，消耗多少 token 都是没问题的。"

本模块把缓存命中监控做成**独立的可观测机制**，覆盖全链路 5 层
（llm / shell / orchestrator / node / 汇总）：
  - **按 agent 归因**：每个角色/agent 的缓存命中次数、未命中次数、命中率、节省 token；
  - **量化效果**：命中率 + 节省量 → 缓存复用充分 = 有效；命中率低且重复构造共享上下文 = 浪费；
  - **浪费判定**：给出可执行的「浪费」信号（命中率低于阈值 + 重复构造共享前缀），
    不主观，用数据说话（命中率高 = 无浪费 → token 消耗多点也没问题，正是用户诉求）；
  - **持久化留痕**：写入数据层 `cache_stats` 表，供「架构·数据管理员」统一统计与人类俯瞰。

数据来源：
  - 内存级：llm.cache 线程内累计的缓存事件（record_cache_event 写入）；
  - 持久层：data.cache_stats 表（CacheStatsSink.persist() 批量落库）。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

# 浪费判定阈值：命中率低于该值且存在可复用共享前缀 → 提示有浪费（可调）
WASTE_HIT_RATE_THRESHOLD = 30.0


def collect_from_memory(agent=None, layer=None):
    """从 llm.cache 内存级统计收集各 agent × 层缓存命中情况。"""
    try:
        from llm import cache as _cache
        return _cache.cache_hit_rate_for(agent=agent, layer=layer)
    except Exception:
        return []


def waste_check(agent_stats):
    """对单个 agent 的缓存统计做「是否有浪费」判定。

    判定逻辑（数据说话，不主观）：
      - total_events 过少（<3）→ 样本不足，不做浪费判定（避免误伤）；
      - cache_hit_rate < 阈值 且 存在可复用前缀的未命中（misses>0 且 prefix_chars>0）
        → 标记「有浪费」：共享前缀被重复构造而未复用；
      - 否则 → 「无浪费」：前缀复用充分，token 消耗属合理成本。

    返回 (verdict, reason)。
    """
    total = agent_stats.get("hits", 0) + agent_stats.get("misses", 0)
    if total < 3:
        return ("样本不足", f"仅 {total} 次缓存事件，不足以判定（避免误伤）")
    rate = agent_stats.get("cache_hit_rate", 0)
    misses = agent_stats.get("misses", 0)
    prefix_chars = agent_stats.get("prefix_chars", 0)
    if rate < WASTE_HIT_RATE_THRESHOLD and misses > 0 and prefix_chars > 0:
        return ("⚠️ 有浪费",
                f"命中率 {rate}% < 阈值 {WASTE_HIT_RATE_THRESHOLD}%，且 {misses} 次未命中"
                f"重复构造了 {prefix_chars} 字符共享前缀 → 建议聚合前缀（水龙头蔓延）")
    if rate >= 80:
        return ("✅ 无浪费",
                f"命中率 {rate}% 高，共享前缀复用充分 → token 消耗属合理成本（用户认可）")
    return ("🔶 可优化",
            f"命中率 {rate}% 中等，可进一步提升共享前缀复用（但非硬性浪费）")


def monitor(agent=None, layer=None, persist=False):
    """一站式缓存命中监控：收集 + 浪费判定 + 可选持久化。

    返回结构化报告（二级信息，供人类俯瞰与 benchmark 汇总）。
    """
    stats = collect_from_memory(agent=agent, layer=layer)
    if not stats:
        return {"agents": [], "overall_rate": None, "waste_flags": 0,
                "persisted": 0, "note": "暂无缓存事件"}

    flagged = 0
    for s in stats:
        verdict, reason = waste_check(s)
        s["waste_verdict"] = verdict
        s["waste_reason"] = reason
        if "有浪费" in verdict:
            flagged += 1

    # 总体命中率（按命中/总事件加权）
    total_hits = sum(s["hits"] for s in stats)
    total_events = sum(s["hits"] + s["misses"] for s in stats)
    overall_rate = round(total_hits / max(1, total_events) * 100, 1)

    persisted = 0
    if persist:
        try:
            from llm import cache as _cache
            sink = _cache.CacheStatsSink()
            persisted = sink.persist()
        except Exception:
            persisted = 0

    return {
        "agents": stats,
        "overall_rate": overall_rate,
        "waste_flags": flagged,
        "persisted": persisted,
        "note": "ok",
    }


def monitor_report(agent=None, layer=None, persist=False):
    """生成人类可读的缓存命中监控报告（二级信息）。"""
    r = monitor(agent=agent, layer=layer, persist=persist)
    lines = ["📊 缓存命中监控 · 按 agent × 层量化效果"]
    if not r.get("agents"):
        lines.append("  （暂无缓存事件，请先跑真实 LLM 或 benchmark）")
        return "\n".join(lines)
    lines.append(f"总体命中率: {r['overall_rate']}% | 浪费信号: {r['waste_flags']} 个"
                 f" | 持久化: {r['persisted']} 条")
    lines.append("")
    lines.append("| agent | 层 | 命中 | 未命中 | 命中率% | 节省token | 判定 |")
    lines.append("|-------|----|-----|--------|--------|----------|------|")
    for s in r["agents"]:
        lines.append(f"| {s['agent']} | {s['layer']} | {s['hits']} | {s['misses']} | "
                     f"{s['cache_hit_rate']} | {s['saved_tokens']} | {s['waste_verdict']} |")
    lines.append("")
    lines.append("💡 判定口径（用户 Issue #41）：")
    lines.append("  - ✅ 无浪费（命中率高）→ 前缀复用充分，token 消耗多点也没问题；")
    lines.append("  - ⚠️ 有浪费（命中率低 + 重复构造共享前缀）→ 应聚合前缀做水龙头蔓延。")
    return "\n".join(lines)


# CLI 入口：python3 local-agent/topology/cache_monitor.py [--agent X] [--layer Y] [--persist]
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="缓存命中监控（按 agent 量化效果/浪费判定）")
    ap.add_argument("--agent", default=None, help="限定 agent（如 架构·开发）")
    ap.add_argument("--layer", default=None, help="限定层（llm/shell/orchestrator/node）")
    ap.add_argument("--persist", action="store_true", help="持久化到 cache_stats 表")
    args = ap.parse_args()
    print(monitor_report(agent=args.agent, layer=args.layer, persist=args.persist))
