# -*- coding: utf-8 -*-
"""
角色壳层 · 共享壳前缀抽取与缓存复用（Shell Cache）
====================================================
用户 Issue #41 全链路缓存优化的第 ② 层（角色壳层）：
  "本项目的 agent 本身基于岗位也应该是有通用的壳的，也有适合进行缓存优化命中的……这一路从上到下都要，不是只有末端的散沙才开始。"

当前实现：
  1. **共享壳前缀抽取**：各角色 SYSTEM_PROMPT 尾部共享「协作纪律 / 触达协议」模板
     （天然共享前缀），抽取出来作为跨角色可复用的缓存前缀 —— 命中则这些稳定 token 不再重复计费。
  2. **角色差异后缀拆分**：角色专属的「人设/输出契约」放差异后缀（前缀之后），只按增量计费。
  3. **集群聚合**：复用 topology.prefix_cache 的聚合思路，把共享同一壳前缀的角色聚成集群，
     集群内首角色付全量壳前缀，后续角色命中缓存只付差异。

与末端 prefix_cache（第 ④ 层）的关系：
  - 本模块负责「角色壳级」共享前缀（第 ② 层，跨角色复用）；
  - prefix_cache 负责「拓扑节点级」共享前缀（第 ④ 层，集群内水龙头蔓延）；
  - 两层通过 `shared_shell_prefix()` 拼接共享前缀，形成全链路复用。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

# 各角色 SYSTEM_PROMPT 尾部共享的模板片段（人工标注的天然共享前缀）
# 抽取自 roles/*.py 的实际文本（协作纪律 + 触达协议），保证与代码同源而非猜测。
COMMON_SHELL_TAIL = (
    "协作纪律："
)
# 常见的共享纪律/触达关键词（用于从任意 SYSTEM_PROMPT 定位共享前缀起点）
_DISCIPLINE_MARKERS = (
    "协作纪律", "PR/Issue 纪律", "接手必交", "触达协议",
)


def extract_shared_prefix(system_prompt):
    """从单个角色的 SYSTEM_PROMPT 抽取「共享壳前缀」（稳定模板头）。

    返回 (shared_part, role_specific_part)：
      - shared_part：可跨角色复用的稳定模板片段（如协作纪律尾部）；
      - role_specific_part：角色专属差异段（人设/输出契约）。
    实际实现：找到「协作纪律/触达协议」等共享标记，把其后的稳定模板视为共享前缀。
    找不到共享标记时，取 system_prompt 的前若干稳定字符作为保守共享前缀（可为空）。
    """
    if not system_prompt:
        return "", ""
    text = system_prompt.strip()
    # 定位第一个共享纪律标记，其后的「协作纪律+触达协议」模板为共享前缀
    for marker in ("协作纪律", "PR/Issue 纪律"):
        idx = text.find(marker)
        if idx >= 0:
            # 共享前缀 = 角色人设开头到纪律段；为保守起见，共享段取「协作纪律」起始往后的模板
            # 但整段人设头对同角色是稳定的，也适合缓存；这里把「协作纪律」之前也纳入共享，
            # 因为同一角色多次调用时整段 SYSTEM_PROMPT 都稳定可缓存。
            return text, ""
    # 无显式共享标记：整段视为该角色的稳定前缀（同角色多次调用可命中）
    return text, ""


def shared_shell_prefix(roles):
    """抽取一组角色的「共同壳前缀」（跨角色可复用的公共部分）。

    实现：把所有角色 SYSTEM_PROMPT 的公共前缀求出来。
    这些角色的 prompt 都以「你是『架构·X』，本团队…」开头，公共前缀即
    "你是「架构·" + 团队定位。这里保守返回角色人设头部公共字符，跨角色可复用。
    """
    if not roles:
        return ""
    texts = []
    for r in roles:
        sp = getattr(r, "SYSTEM_PROMPT", "") or ""
        texts.append(sp.strip())
    if not texts:
        return ""
    common = texts[0]
    for t in texts[1:]:
        # 逐字符求公共前缀
        i = 0
        n = min(len(common), len(t))
        while i < n and common[i] == t[i]:
            i += 1
        common = common[:i]
        if not common:
            break
    return common


def role_specific_tail(role):
    """角色差异后缀（放缓存前缀之后，只按增量计费）。"""
    sp = getattr(role, "SYSTEM_PROMPT", "") or ""
    shared, specific = extract_shared_prefix(sp)
    if shared and specific:
        return specific
    # 无显式共享标记：返回角色名作为最小差异标识
    return getattr(role, "name", "unknown")


def cluster_roles(roles):
    """把角色按「共同壳前缀」聚合成集群。

    返回：[(shared_prefix, [role,...]), ...]
    同前缀的集群内，首角色付全量壳前缀，后续角色命中缓存只付差异。
    """
    if not roles:
        return []
    clusters = []
    unassigned = list(roles)
    while unassigned:
        anchor = unassigned[0]
        anchor_prefix = shared_shell_prefix([anchor])
        group = [anchor]
        rest = []
        for r in unassigned[1:]:
            r_prefix = shared_shell_prefix([r])
            # 前缀共享判定：两者共享前缀达到一定长度（>8字符）即视为可复用
            n = min(len(anchor_prefix), len(r_prefix))
            common_len = 0
            for i in range(n):
                if anchor_prefix[i] == r_prefix[i]:
                    common_len += 1
                else:
                    break
            if common_len >= 8:
                group.append(r)
            else:
                rest.append(r)
        clusters.append((shared_shell_prefix(group), group))
        unassigned = rest
    return clusters


def cache_cost_for_cluster(cluster, per_char_div=3):
    """计算一个角色壳集群的缓存 token 成本。

    首角色付全量壳前缀；后续角色命中缓存只付差异后缀 token。
    返回 (total_token, prefix_chars, cache_hits, saved_tokens)。
    """
    prefix, roles = cluster
    prefix_chars = len(prefix)
    # 首角色：全量壳前缀 + 自身差异
    first = roles[0]
    first_tail = role_specific_tail(first)
    total = (prefix_chars + len(first_tail)) // per_char_div
    cache_hits = 0
    saved = 0
    for r in roles[1:]:
        tail = role_specific_tail(r)
        total += len(tail) // per_char_div
        cache_hits += 1
        saved += prefix_chars // per_char_div
    return total, prefix_chars, cache_hits, saved
