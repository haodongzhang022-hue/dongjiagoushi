# -*- coding: utf-8 -*-
"""
七维专家评估器（expertise.evaluator）
=====================================
把「专家级架构判断」做成**确定性、可复现、可留痕**的一次调用：

    评估输入（assessment）
      ├─ dimensions:  七维各自的证据（strength + 说明 + 事实来源）
      ├─ alternatives: 备选方案（多目标）→ 帕累托前沿
      ├─ claims:      外部验证证据（**必须真实执行**，见 external_validation）
      └─ facts:       引用的事实/信息（带日期与来源）→ 时效性闸门

    判定输出（verdict）
      ├─ admissible:  七维准入门（缺必过维度即不可放行）
      ├─ score:       加权得分（权重来自 spec.DIMENSION_SPECS，唯一事实源）
      ├─ tier:        expert / competent / insufficient / inadmissible
      └─ highlights:  人类可读的「为什么是/不是专家级」

设计纪律：
  - **外部验证不接受自述**：`claim.verified` 字段一律忽略，只认真实执行证据
    （exit_code + output_digest + executed_at + 功能性命令判定）；
  - 事实缺失日期/来源 → 时效性闸门判不过，该维度不得给高分；
  - 判不出来 → `unknown`，**绝不静默转成通过**。
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import external_validation, freshness, pareto
from .spec import (
    DIMENSION_BY_KEY,
    DIMENSION_KEYS,
    JUDGE_THRESHOLDS,
    QUALITY_TIERS,
    REQUIRED_DIMENSIONS,
    validate_specs,
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _score_dimension(key, evidence):
    """单维证据强度归一化：0~1；缺失/读不到 → 0 且标记 unknown。"""
    spec = DIMENSION_BY_KEY.get(key, {})
    if evidence is None:
        return {"key": key, "name": spec.get("name", key), "strength": 0.0,
                "status": "missing", "note": "未提供该维度证据", "evidence": []}
    if isinstance(evidence, (int, float)):
        strength = float(evidence)
        note = "调用方直接给出强度"
        items = []
    elif isinstance(evidence, dict):
        try:
            strength = float(evidence.get("strength", 0.0))
        except (TypeError, ValueError):
            strength = 0.0
        note = evidence.get("note") or ""
        items = evidence.get("evidence") or []
    else:
        return {"key": key, "name": spec.get("name", key), "strength": 0.0,
                "status": "unknown", "note": f"证据形态不可识别：{type(evidence).__name__}",
                "evidence": []}
    strength = max(0.0, min(1.0, strength))
    floor = JUDGE_THRESHOLDS["min_evidence_strength"]
    status = "ok" if strength >= floor else "weak"
    return {
        "key": key,
        "name": spec.get("name", key),
        "strength": round(strength, 3),
        "status": status,
        "note": note,
        "evidence": items if isinstance(items, list) else [items],
    }


def assess(assessment, now=None):
    """执行一次七维专家级评估。assessment 见模块文档；返回完整 verdict。"""
    assessment = assessment or {}
    ok_spec, spec_errors = validate_specs()
    if not ok_spec:
        return {
            "tier": "inadmissible",
            "admissible": False,
            "score": 0.0,
            "error": "评估规范自身不一致，拒绝评估（先修 spec.py）",
            "spec_errors": spec_errors,
            "evaluated_at": _now_iso(),
        }

    dims_in = assessment.get("dimensions") or {}
    results = [_score_dimension(k, dims_in.get(k)) for k in DIMENSION_KEYS]
    by_key = {r["key"]: r for r in results}

    # ---- 1) 时效性闸门（事实必须先新鲜可信，才能支撑任何维度）----
    fresh_gate = freshness.gate(assessment.get("facts") or [], now=now)

    # ---- 2) 外部验证闸门（只认真实执行证据）----
    claims = assessment.get("claims") or []
    ext_gate = external_validation.gate(claims, now=now)
    # 用闸门结果**约束**自述强度，避免「我自己说验证过了」：
    #   闸门通过 → 承认调用方给的强度（可到 1.0，真实证据托底）；
    #   闸门未过 → 无论自述多少，一律压到 <=0.3 并标 weak。
    if "external_validation" in by_key:
        dim = by_key["external_validation"]
        if ext_gate["passed"]:
            dim.update({"strength": max(dim["strength"], 0.8), "status": "ok",
                        "note": f"真实执行验证 {ext_gate['verified_count']}/{ext_gate['total']} 通过"
                                f"（功能性 {ext_gate['functional_count']}）"})
        else:
            dim.update({
                "strength": round(min(dim["strength"], 0.3), 3),
                "status": "weak",
                "note": "外部验证闸门未通过：" + "；".join(ext_gate["problems"][:3]),
            })

    # ---- 3) 帕累托前沿（帕累托维度必须有可比较的备选）----
    pareto_result = pareto.evaluate(assessment.get("alternatives") or [],
                                    preferred=assessment.get("preferred"))
    if "pareto" in by_key:
        dim = by_key["pareto"]
        if pareto_result["trustworthy"] and pareto_result["frontier"]:
            faithful = assessment.get("preferred") in (None, "") \
                or assessment.get("preferred") in pareto_result["frontier"]
            if not faithful:
                dim.update({"status": "weak", "strength": round(min(dim["strength"], 0.4), 3),
                            "note": "指定方案不在前沿上，取舍未自洽"})
            else:
                dim.update({"strength": max(dim["strength"], 0.8), "status": "ok",
                            "note": pareto_result["explanation"]})
        else:
            dim.update({"status": "weak", "strength": round(min(dim["strength"], 0.3), 3),
                        "note": "前沿不可信：" + pareto_result["reason"]})

    # ---- 4) 准入判定（缺必过维度即 inadmissible）----
    missing = [k for k in REQUIRED_DIMENSIONS
               if by_key.get(k, {}).get("status") in ("missing", "unknown")]
    weak = [k for k in REQUIRED_DIMENSIONS
            if by_key.get(k, {}).get("status") == "weak"]
    # 两条**准入门**同时成立才准入：
    #   ① 必过维度不得缺失（missing 计入，weak 不阻断但会拉低分档）；
    #   ② 时效性闸门必须过 —— 事实不新鲜则证据不可信，准入不成立。
    admissible = (
        len(missing) <= JUDGE_THRESHOLDS["max_missing_required"]
        and bool(fresh_gate["passed"])
    )

    # ---- 5) 加权得分 ----
    score = 0.0
    for key in DIMENSION_KEYS:
        score += DIMENSION_BY_KEY[key]["weight"] * by_key[key]["strength"]
    score = round(score, 4)

    # ---- 6) 分档 ----
    if not admissible:
        tier = "inadmissible"
    elif score >= JUDGE_THRESHOLDS["score_expert"] and not weak:
        tier = "expert"
    elif score >= JUDGE_THRESHOLDS["score_competent"]:
        tier = "competent"
    else:
        tier = "insufficient"
    assert tier in QUALITY_TIERS

    highlights = []
    if missing:
        highlights.append("缺失必过维度：" + "、".join(DIMENSION_BY_KEY[k]["name"] for k in missing))
    if weak:
        highlights.append("证据偏弱的维度：" + "、".join(DIMENSION_BY_KEY[k]["name"] for k in weak))
    if not fresh_gate["passed"]:
        highlights.append(f"时效性闸门未过（{len(fresh_gate['problems'])} 项）")
    if not ext_gate["passed"]:
        highlights.append(f"外部验证未过（{len(ext_gate['problems'])} 项）")
    if tier == "expert":
        highlights.append("七维齐备、外部验证真实执行、事实新鲜：达到专家级")
    elif tier == "competent":
        highlights.append("七维齐备但证据强度不足以称专家级")

    return {
        "tier": tier,
        "admissible": admissible,
        "score": score,
        "dimensions": results,
        "missing_required": missing,
        "weak_dimensions": weak,
        "freshness": fresh_gate,
        "external_validation": ext_gate,
        "pareto": pareto_result,
        "highlights": highlights,
        "thresholds": dict(JUDGE_THRESHOLDS),
        "evaluated_at": _now_iso(),
    }


def explain(verdict):
    """把 verdict 渲染成人可读报告（供贡献者/人类俯瞰，不替代 verdict）。"""
    if not isinstance(verdict, dict):
        return "（无评估结果）"
    lines = [
        f"专家级判定：{verdict.get('tier')} ｜ 准入：{'通过' if verdict.get('admissible') else '未通过'}"
        f" ｜ 加权得分：{verdict.get('score')}",
    ]
    for dim in verdict.get("dimensions") or []:
        lines.append(f"  - {dim['name']}({dim['key']}) {dim['strength']} [{dim['status']}]"
                     f" {dim.get('note') or ''}".rstrip())
    if verdict.get("pareto", {}).get("frontier"):
        lines.append("  帕累托前沿：" + ", ".join(verdict["pareto"]["frontier"]))
    for item in verdict.get("highlights") or []:
        lines.append(f"  ! {item}")
    return "\n".join(lines)
