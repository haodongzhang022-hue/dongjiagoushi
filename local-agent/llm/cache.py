# -*- coding: utf-8 -*-
"""
LLM 层 · 上下文缓存（Context Caching）与缓存命中监控
=====================================================
用户 Issue #41 的核心诉求：
  1. "这一路从上到下都要" —— 从 LLM 调用层到角色壳、编排层、末端、数据层全链路缓存复用；
  2. "需要建立一个能监控缓存命中率的机制……监控每个 agent 的缓存命中，才能量化效果、
     确定是否有浪费。只要没浪费，消耗多少 token 都是没问题的。"

本模块承接第 ① 层（LLM 调用层）：
  - **context caching 参数透传**：OpenAI 兼容后端透传 `extra_headers: {"ep_ctxcache":"1"}`，
    命中相同前缀 tokens 时按增量计费（deepseek context caching / prompt prefix caching 机制）。
  - **generate() 别名修复**：`benchmark.py` 等调用 `llm.generate()` 而后端只有 `call()` 的断裂 bug，
    在基类补 `generate()`，统一走缓存感知调用。
  - **缓存命中监控（按 agent 归因）**：记录每个角色/agent 的缓存命中次数、命中率、节省 token，
    形成可量化的「是否浪费」判定依据 —— 命中率高 = 前缀复用充分 = 无浪费；命中率低且重复构造
    共享上下文 = 有浪费，应聚合前缀。

监控留痕写入数据层 `cache_stats` 表（M5），供「架构·数据管理员」统一统计、人类俯瞰二级信息。
"""

import os
import threading
from datetime import datetime

# 缓存命中开关（环境变量可全局关闭，默认开启）
CACHE_ENABLED = os.environ.get("LOCAL_AGENT_CACHE", "1") != "0"
# deepseek context caching 透传头
CTXCACHE_HEADER = os.environ.get(
    "LOCAL_AGENT_CTXCACHE_HEADER", '{"ep_ctxcache":"1"}'
)

# 线程安全的内存级命中统计（进程内累积；持久化走 cache_stats 表）
_local = threading.local()


def _record_store():
    """当前线程的缓存命中统计容器。"""
    store = getattr(_local, "cache_stats", None)
    if store is None:
        store = {}
        _local.cache_stats = store
    return store


def record_cache_event(agent, layer, cache_hit, prefix_chars, saved_tokens):
    """记录一次缓存事件（按 agent 归因）。

    agent:    角色/agent 标识（如「架构·开发」）
    layer:    缓存所在层（llm / shell / orchestrator / node）
    cache_hit: 1=命中缓存（前缀复用） / 0=未命中（首次构造/无前缀可复用）
    prefix_chars: 被复用的共享前缀字符数（cache_hit=1 时为命中前缀字节，否则为 0）
    saved_tokens: 因命中缓存而节省的 token 估算
    """
    store = _record_store()
    k = (agent, layer)
    rec = store.setdefault(k, {
        "agent": agent, "layer": layer,
        "hits": 0, "misses": 0, "prefix_chars": 0, "saved_tokens": 0,
        "first_ts": datetime.utcnow().isoformat(),
    })
    if cache_hit:
        rec["hits"] += 1
        rec["prefix_chars"] += prefix_chars
        rec["saved_tokens"] += saved_tokens
    else:
        rec["misses"] += 1
    return rec


def cache_hit_rate_for(agent=None, layer=None):
    """查询某 agent（可限定 layer）的缓存命中率 + 节省量（内存级，进程内）。"""
    store = _record_store()
    result = []
    for (ag, ly), rec in store.items():
        if agent and ag != agent:
            continue
        if layer and ly != layer:
            continue
        total = rec["hits"] + rec["misses"]
        rate = round(rec["hits"] / max(1, total) * 100, 1)
        result.append({**rec, "cache_hit_rate": rate, "total_events": total})
    return result


def cache_overview():
    """全部 agent × 层的缓存命中率概览（二级信息，供人类俯瞰是否浪费）。"""
    rows = cache_hit_rate_for()
    lines = ["📊 缓存命中率监控（按 agent × 层）"]
    if not rows:
        lines.append("  （暂无缓存事件，请先跑真实 LLM 或 benchmark）")
        return "\n".join(lines)
    lines.append("| agent | 层 | 命中 | 未命中 | 命中率% | 节省token |")
    lines.append("|-------|----|-----|--------|--------|----------|")
    for r in rows:
        lines.append(f"| {r['agent']} | {r['layer']} | {r['hits']} | "
                     f"{r['misses']} | {r['cache_hit_rate']} | {r['saved_tokens']} |")
    lines.append("")
    lines.append("💡 判定：命中率高 + 节省多 → 前缀复用充分，无浪费；"
                 "命中率低 + 共享上下文重复构造 → 有浪费，应聚合前缀。")
    return "\n".join(lines)


class CacheStatsSink:
    """把内存级缓存监控持久化到数据层 cache_stats 表（M5，由数据管理员负责）。"""

    def persist(self):
        """把当前线程累计的缓存事件批量写入 cache_stats 表。"""
        rows = cache_hit_rate_for()
        if not rows:
            return 0
        try:
            from data import db as _db
        except Exception:
            return 0
        written = 0
        for r in rows:
            try:
                _db.execute(
                    "INSERT INTO cache_stats "
                    "(agent, layer, cache_hits, cache_misses, cache_hit_rate, "
                    " prefix_chars, saved_tokens) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (r["agent"], r["layer"], r["hits"], r["misses"],
                     r["cache_hit_rate"], r["prefix_chars"], r["saved_tokens"]),
                )
                written += 1
            except Exception:
                continue
        return written


def build_cache_headers(enabled=None):
    """构造 context caching 透传头。

    返回 dict：enabled 为 True 时给 OpenAI 兼容后端透传 extra_headers。
    未启用时返回空 dict（不影响现有调用）。
    """
    if enabled is None:
        enabled = CACHE_ENABLED
    if not enabled:
        return {}
    try:
        import json
        return {"extra_headers": json.loads(CTXCACHE_HEADER)}
    except Exception:
        return {}


def split_prefix_suffix(system_prompt, user_input, shared_prefix=""):
    """把「稳定共享前缀」与「变化增量后缀」拆分，最大化前缀命中。

    - shared_prefix：可选，跨请求共享的稳定提示词头（角色壳/团队级系统提示/需求描述）。
    - 返回 (prefix, suffix)：构造 prompt 时把 prefix 放最前（稳定 → 命中缓存），
      suffix 放最后（变化部分，仅增量计费）。
    """
    prefix = (shared_prefix or system_prompt or "").strip()
    suffix = (user_input or "").strip()
    return prefix, suffix
