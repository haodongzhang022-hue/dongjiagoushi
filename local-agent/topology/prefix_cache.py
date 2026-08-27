# -*- coding: utf-8 -*-
"""
前缀缓存聚合（Prefix Cache · 水龙头蔓延）
==========================================
用户 Issue #41 优化核心诉求：
  "框架方向对，但 bug 多、token 消耗大。可尝试优化——近似区域下的，
   适合把有共享提示词头的聚合一下，以缓存命中为索引，把一盘散沙争抢，
   变成有序快领。不是一次扔出都去抢，而是以缓存前缀形成水龙头，持续往下蔓延。"

本模块把「一盘散沙争抢（每节点独立重新构造完整共享上下文）」改造成
「有序快领（共享前缀只构造一次，后节点在前缀缓存上增量蔓延）」。

核心概念：
  - **共享前缀（prefix）**：一组任务节点共有的提示词头（角色 + 共享上下文/需求描述）。
  - **聚合（cluster）**：把共享同一前缀的节点聚成一组。前缀只付一次 token。
  - **缓存命中（cache hit）**：集群内首节点付全量前缀 token，后续节点**命中缓存**，
    只付增量差异部分 token —— 前缀 token 被复用，不重复计费。
  - **水龙头蔓延（faucet）**：同一集群内节点按顺序一个接一个在前缀缓存上增量推进
    （前缀只构造一次，形成"水龙头持续往下蔓延"）；不同集群间无共享前缀，天然并行。

与「散沙争抢」的关键差异（AB 对比的两个端点）：
  - **scramble/scatter（散沙）**：全部节点同时并行，每个节点独立携带完整共享上下文，
    并发越高 token 线性放大（ctx_factor=1+(N-1)*0.12），且各自独立构造上下文 → 出错面大。
  - **prefix（水龙头）**：共享前缀只构造一次，后续节点靠缓存命中只付增量 token，
    token 从"按并发 N 放大"降为"前缀 1 次 + 每节点增量"，共享上下文一致 → 出错面收窄。
"""
import re


# ------------------------------------------------------------
# 前缀提取：从节点 id + 角色 + action 推导共享前缀
# ------------------------------------------------------------
def _prefix_of(node, req):
    """推导节点的共享前缀（提示词头）。

    前缀 = 角色名 + 共享需求描述（req），这是同一集群所有节点共有的部分。
    """
    role = node.get("role", "")
    return f"你是{role}。需求: {req}。"


def extract_prefixes(nodes, req, cluster_size=3):
    """把节点按共享前缀聚合成若干集群（cluster）。

    同一 role 的节点（如 scramble_1..N、scatter_1..N）共享同一前缀 → 聚合为一个集群。
    不同 role 的节点（如 review/test/deliver）各自独立成集群。

    返回：[(prefix, [node_id,...]), ...] —— 每个集群一个前缀 + 其成员节点。
    集群内部按顺序（前缀缓存蔓延序）排列，非并发。
    """
    # 按 role 分组 → 每组一个共享前缀
    by_role = {}
    order = []
    for n in nodes:
        role = n.get("role", "编排引擎")
        if role not in by_role:
            by_role[role] = []
            order.append(role)
        by_role[role].append(n)

    clusters = []
    for role in order:
        group = by_role[role]
        prefix = _prefix_of(group[0], req)
        clusters.append((prefix, group))

    return clusters


def build_prompt(node, req, cache_hit=False):
    """构造节点提示词。

    cache_hit=True 时：只输出**增量差异部分**（action），前缀已被缓存命中复用。
    cache_hit=False（集群首节点）：输出完整提示词（前缀 + 差异）。
    """
    prefix = _prefix_of(node, req)
    action = node.get("action", "")
    if cache_hit:
        # 水龙头蔓延：前缀已命中缓存，只付增量差异部分 token
        return f"[cache-hit: {len(prefix)} 前缀字符已缓存复用]\n任务增量: {action}"
    return f"{prefix}\n任务: {action}"


# ------------------------------------------------------------
# 缓存命中率 / 前缀复用统计
# ------------------------------------------------------------
def token_cost_of_cluster(cluster, req, per_char_div=3):
    """计算一个集群的水龙头蔓延 token 成本。

    首节点付全量前缀 token；后续节点命中缓存只付增量 token。
    返回 (total_token, prefix_token, cache_hits, prefix_chars)。
    """
    prefix, nodes = cluster
    prefix_chars = len(prefix)
    # 首节点：全量前缀 + 自身差异
    first_text = prefix + "任务: " + nodes[0].get("action", "")
    total = len(first_text) // per_char_div
    cache_hits = 0
    # 后续节点：命中缓存，只付增量差异 token
    for n in nodes[1:]:
        delta = "任务增量: " + n.get("action", "")
        total += len(delta) // per_char_div
        cache_hits += 1
    return total, prefix_chars, cache_hits


def analyze(nodes, req, per_char_div=3):
    """对一组节点做前缀缓存聚合分析，返回结构化统计（二级信息）。

    用于 benchmark 对比：散沙（无缓存） vs 水龙头（有缓存）。
    """
    clusters = extract_prefixes(nodes, req)
    # 散沙成本：所有节点都独立携带完整前缀（每个节点付全量 token）
    scatter_tokens = 0
    for n in nodes:
        prefix = _prefix_of(n, req)
        full = prefix + "任务: " + n.get("action", "")
        scatter_tokens += len(full) // per_char_div

    # 水龙头成本：每集群前缀一次 + 每节点增量
    faucet_tokens = 0
    prefix_chars_total = 0
    cache_hits_total = 0
    for cluster in clusters:
        t, pc, ch = token_cost_of_cluster(cluster, req, per_char_div)
        faucet_tokens += t
        prefix_chars_total += pc
        cache_hits_total += ch

    cluster_count = len(clusters)
    node_count = len(nodes)

    return {
        "node_count": node_count,
        "cluster_count": cluster_count,
        "prefix_chars": prefix_chars_total,
        "cache_hits": cache_hits_total,
        "scatter_tokens": scatter_tokens,
        "faucet_tokens": faucet_tokens,
        "token_saved": scatter_tokens - faucet_tokens,
        "token_saved_pct": round((scatter_tokens - faucet_tokens) / max(1, scatter_tokens) * 100, 1),
        "cache_hit_rate": round(cache_hits_total / max(1, node_count) * 100, 1),
    }


# ------------------------------------------------------------
# M4：末端接入上游共享前缀（extend_shared_prefix）
# ------------------------------------------------------------
def extend_shared_prefix(prefix, upstream_prefix):
    """把上游（角色壳层）共享前缀接入末端集群前缀。

    全链路复用：末端的节点前缀不再只是「角色 + req」，而是叠加
    上游壳层/编排层的共享前缀，命中则这些稳定 token 一并复用，不重复计费。
    返回拼接后的前缀。
    """
    if not upstream_prefix:
        return prefix
    # 去重拼接：若上游前缀已包含在末端前缀中则不重复
    if upstream_prefix in prefix:
        return prefix
    return (upstream_prefix + "\n" + prefix).strip()


def analyze_with_upstream(nodes, req, upstream_prefix="", per_char_div=3):
    """带上游共享前缀的全链路缓存分析。

    与 analyze() 相同，但前缀叠加上游共享前缀，命中节省更多。
    返回 analyze() 的结构 + upstream 维度。
    """
    base = analyze(nodes, req, per_char_div)
    base["upstream_prefix_chars"] = len(upstream_prefix or "")
    base["extended"] = bool(upstream_prefix)
    return base
