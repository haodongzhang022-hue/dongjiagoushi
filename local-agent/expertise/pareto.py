# -*- coding: utf-8 -*-
"""
帕累托前沿判定（expertise.pareto）
==================================
用户点名的关键能力：**「实现对帕累托前沿的线的明确」**。

架构选型的本质不是「挑一个方案」，而是「在多个目标下划出前沿，并说清楚自己
为什么落在前沿上的这一点」。本模块提供确定性实现：

  - 多目标向量，每目标带方向（max 越大越好 / min 越小越好）；
  - 支配关系（dominates）与**非支配集**（即帕累托前沿）；
  - 前沿分层（Pareto 排名：第 1 层是最优前沿，剥掉后第 2 层 …）；
  - **为什么选这一点**的可解释输出（被谁支配 / 支配了谁 / 相对权衡）；
  - 与「七维权重」联动：把加权得分作为附加目标，避免纯多维糊在一起。

纪律：候选少于 `JUDGE_THRESHOLDS.min_alternatives` 时，前沿判定**不可信**
（只有 1 个方案就没有前沿可言），必须显式判 insufficient。
"""
from __future__ import annotations

from .spec import JUDGE_THRESHOLDS

_EPS = 1e-9


def _prepare(candidates):
    """候选规范化：[{name, objectives:{k: v}, direction:{k:'max'|'min'}}]"""
    if not candidates:
        return []
    # 统一方向：未声明的默认 max
    prepared = []
    for idx, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            raise ValueError(f"候选 #{idx} 不是对象")
        name = cand.get("name") or f"cand-{idx + 1}"
        objectives = cand.get("objectives") or {}
        if not objectives:
            raise ValueError(f"候选 {name} 没有任何目标值，无法参与前沿判定")
        direction = dict(cand.get("direction") or {})
        normalized = {}
        for key, value in objectives.items():
            try:
                num = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"候选 {name} 的目标 {key} 不是数值：{value!r}") from exc
            d = (direction.get(key) or "max").lower()
            if d not in ("max", "min"):
                raise ValueError(f"候选 {name} 的目标 {key} 方向只能是 max/min，实际 {d!r}")
            # 统一成「越大越好」的坐标，便于比较
            normalized[key] = num if d == "max" else -num
        prepared.append({"name": name, "objectives": normalized, "raw": dict(objectives),
                         "direction": {k: (direction.get(k) or "max").lower() for k in objectives}})
    return prepared


def dominates(a, b):
    """a 支配 b：**目标集合必须完全一致**，且所有目标不劣于 b、至少一个严格更优。

    目标集合不同 → 不可比 → 一律返回 False（缺维度时不得断言支配）。
    """
    oa, ob = a["objectives"], b["objectives"]
    if set(oa) != set(ob):
        return False
    if not oa:
        return False
    keys = set(oa)
    better = any(oa[k] > ob[k] + _EPS for k in keys)
    worse = any(oa[k] < ob[k] - _EPS for k in keys)
    return better and not worse


def _signature(prepared):
    """一组候选的「目标维度签名」：维度不同则不可比。"""
    return tuple(sorted({k for c in prepared for k in c["objectives"]}))


def _dominance_map(prepared):
    """只在**同目标签名**的候选之间计算支配关系。

    为什么必须按签名分组：支配判定的前提是「在同一组目标上比较」。若 A 只报了
    {效果, 成本}、D 报了 {性能, 成本, 工期}，拿 A 去支配 D 就是在缺维度的情况下
    下断言 —— 这正是「看起来对、其实错」的典型。跨签名一律互不支配（都留在前沿，
    显式交给人与更多证据判断）。
    """
    sigs = {}
    for cand in prepared:
        sigs.setdefault(_signature([cand]), []).append(cand)
    dom = {}
    for group in sigs.values():
        for target in group:
            dom[id(target)] = [
                other["name"] for other in group
                if other is not target and dominates(other, target)
            ]
    return dom


def frontier(candidates):
    """返回**第 1 层帕累托前沿**（互不支配的候选集）。"""
    prepared = _prepare(candidates)
    dom = _dominance_map(prepared)
    return [c["name"] for c in prepared if not dom.get(id(c))]


def layers(candidates):
    """帕累托分层：[[第1层...], [第2层...], ...]，用于解释「为什么在前沿之外」。"""
    remaining = _prepare(candidates)
    result = []
    while remaining:
        dom = _dominance_map(remaining)
        layer = [c for c in remaining if not dom.get(id(c))]
        if not layer:  # 防御：理论上不会发生
            break
        result.append([c["name"] for c in layer])
        layer_ids = {id(c) for c in layer}
        remaining = [c for c in remaining if id(c) not in layer_ids]
    return result


def evaluate(candidates, preferred=None):
    """完整前沿评估 + 可解释结论。

    返回：
      {trustworthy: bool, reason, frontier: [...], layers: [...],
       dominated: [{name, by: [...]}], choice: name|None, explanation: str}
    """
    min_alts = int(JUDGE_THRESHOLDS.get("min_alternatives", 2))
    prepared = _prepare(candidates)
    if len(prepared) < min_alts:
        return {
            "trustworthy": False,
            "reason": f"候选数 {len(prepared)} < 最少 {min_alts}：没有备选就没有前沿，判定不可信",
            "frontier": [],
            "layers": [],
            "dominated": [],
            "choice": None,
            "explanation": "候选不足，须补充至少一个备选方案后再做帕累托比较",
        }
    dom = _dominance_map(prepared)
    front = [c["name"] for c in prepared if not dom.get(id(c))]
    dominated = [{"name": c["name"], "by": dom[id(c)]} for c in prepared if dom.get(id(c))]

    # 选择：显式指定且在前沿上就用；否则取前沿中「标准化目标之和」最高者（可复现）
    keys = sorted({k for c in prepared for k in c["objectives"]})
    scored = []
    for c in prepared:
        if c["name"] not in front:
            continue
        total = 0.0
        for k in keys:
            if k not in c["objectives"]:
                # 跨签名的候选缺该目标：不参与该目标标准化，也不因此被当成 0（缺维≠差）。
                continue
            vals = [o["objectives"][k] for o in prepared if k in o["objectives"]]
            lo, hi = min(vals), max(vals)
            norm = 0.5 if hi - lo < _EPS else (c["objectives"][k] - lo) / (hi - lo)
            total += norm
        scored.append((round(total, 6), c["name"]))
    scored.sort(reverse=True)
    if preferred and preferred in front:
        choice = preferred
    else:
        choice = scored[0][1] if scored else None

    if choice and choice in front:
        explanation = (
            f"前沿共 {len(front)} 个互不支配候选（{', '.join(front)}）；"
            f"选定 {choice}；被支配淘汰 {len(dominated)} 个"
        )
        if preferred and preferred not in front:
            explanation += f"（指定方案 {preferred} 不在前沿上，已否决）"
    else:
        explanation = "前沿为空，无法给出可解释选择"

    return {
        "trustworthy": True,
        "reason": "候选数与目标维度充分",
        "frontier": front,
        "layers": layers(candidates),
        "dominated": dominated,
        "choice": choice,
        "scores": {name: score for score, name in scored},
        "explanation": explanation,
    }
