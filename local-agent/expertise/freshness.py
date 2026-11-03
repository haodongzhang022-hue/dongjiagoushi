# -*- coding: utf-8 -*-
"""
信息时效性闸门（expertise.freshness）
=====================================
用户点名的核心约束：**「信息也是陈旧的不一定可信，注意时效性」**。

本模块把「时效性」变成**确定性闸门**，而不是靠 agent 自觉：

  1. 按信息**类型**（AI 模型 / 框架 API / 行业做法 / 法规 / 价格 / 榜单 …）给出
     可接受的最大陈旧天数（规范在 `spec.FRESHNESS_SPECS`，唯一事实源）；
  2. 判定四档：fresh / ageing / stale / undated(→stale) / unknown；
  3. **无日期 = 不可信**（无法证明时效），**读不到来源 = unknown**（绝不当通过）；
  4. 与 `source` 一起做**可核验性**判断：没有来源链接/标识的「事实」不得作为
     架构决策依据进入七维评估。

用法：
    from expertise.freshness import assess
    assess({"kind": "ai_framework", "source": "...", "dated_at": "2026-10-01"})
    # -> {"tier": "fresh", "usable": True, "age_days": 33, ...}
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .spec import DEFAULT_MAX_AGE_DAYS, FRESHNESS_SPECS, FRESHNESS_TIERS

# 达到硬上限多少倍仍可「aging」（用来自省分档），当前策略：超过 max_age 即 stale。
# 单独的 ageing 档用 max_age*0.7 作为建议复核线，超线即提醒复核。
AGEING_RATIO = 0.7


def _today(now=None):
    if now is None:
        return datetime.now(timezone.utc).date()
    if isinstance(now, datetime):
        return now.astimezone(timezone.utc).date() if now.tzinfo else now.date()
    if isinstance(now, date):
        return now
    text = str(now).strip().replace("Z", "+00:00")
    for parser in (datetime.fromisoformat,):
        try:
            dt = parser(text)
            return dt.astimezone(timezone.utc).date() if dt.tzinfo else dt.date()
        except Exception:  # noqa: BLE001
            continue
    try:
        return date.fromisoformat(text)
    except Exception:  # noqa: BLE001
        return None


def policy_for(kind):
    """取某类信息的时效策略；未知类型走保守默认（180 天）。"""
    if kind and kind in FRESHNESS_SPECS:
        max_age, note = FRESHNESS_SPECS[kind]
        return {"kind": kind, "max_age_days": max_age, "note": note, "known_kind": True}
    return {
        "kind": kind or "unknown",
        "max_age_days": DEFAULT_MAX_AGE_DAYS,
        "note": "未登记的信息类型，按保守默认 180 天处置；建议在 FRESHNESS_SPECS 登记以便精细控制",
        "known_kind": False,
    }


def assess(item, now=None):
    """判定一条信息的时效性。

    item: {kind, source, dated_at, [title]}
    返回：
      {tier, usable, age_days, max_age_days, policy, reason, source_ok}
    """
    today = _today(now)
    kind = (item or {}).get("kind") if isinstance(item, dict) else None
    policy = policy_for(kind)
    dated_raw = (item or {}).get("dated_at") if isinstance(item, dict) else None
    source = ((item or {}).get("source") or "").strip() if isinstance(item, dict) else ""
    source_ok = bool(source)
    max_age = policy["max_age_days"]

    base = {
        "kind": kind,
        "policy": policy,
        "source_ok": source_ok,
        "max_age_days": max_age,
        "age_days": None,
        "usable": False,
    }

    if today is None:
        base.update({"tier": "unknown", "reason": "当前时间读不到，无法判定时效（不得当通过）"})
        return base

    if max_age is None:
        # 内部决策类：不按天数失效，按 ADR 版本状态判定（由调用方给 superseded 标志）
        superseded = bool(((item or {}).get("superseded")) if isinstance(item, dict) else False)
        base.update({
            "tier": "stale" if superseded else "fresh",
            "usable": not superseded,
            "reason": "内部决策以 ADR 版本为准；已被 Superseded 即不可用",
        })
        return base

    if not dated_raw:
        base.update({
            "tier": "undated",
            "reason": "无日期：无法证明时效，按不可信处置（须补 dated_at 后重评）",
        })
        return base

    dated = _today(dated_raw)
    if dated is None:
        base.update({"tier": "unknown", "reason": f"日期格式无法解析：{dated_raw!r}"})
        return base

    age = (today - dated).days
    base["age_days"] = age
    if age < -1:
        base.update({"tier": "unknown", "reason": "日期在未来，时间戳不可信"})
        return base
    if age > max_age:
        base.update({
            "tier": "stale",
            "usable": False,
            "reason": f"已陈旧 {age} 天 > 上限 {max_age} 天：{policy['note']}",
        })
        return base
    if age > max_age * AGEING_RATIO:
        base.update({
            "tier": "ageing",
            "usable": source_ok,
            "reason": f"接近有效期（{age}/{max_age} 天），可用但须标注并尽快复核",
        })
        return base
    base.update({
        "tier": "fresh",
        "usable": source_ok,
        "reason": "在有效期内" if source_ok else "在有效期内但**缺少来源**，不得作为决策依据",
    })
    return base


def gate(items, now=None):
    """一批信息的时效性闸门：任一 stale/undated/unknown 即不过（不可用于决策）。"""
    items = items or []
    results = [assess(i, now=now) for i in items]
    bad = [r for r in results if r["tier"] in ("stale", "undated", "unknown")]
    no_source = [r for r in results if not r["source_ok"]]
    usable = sum(1 for r in results if r["usable"])
    total = len(results)
    passed = bool(total) and not bad and not no_source
    return {
        "passed": passed,
        "total": total,
        "usable": usable,
        "problems": [f"{r['kind']}: {r['reason']}" for r in bad]
                   + [f"{r['kind']}: 缺少来源标识" for r in no_source],
        "tiers": [r["tier"] for r in results],
        "evidence": round(usable / total, 3) if total else 0.0,
    }


assert set(FRESHNESS_TIERS) >= {"fresh", "ageing", "stale", "undated", "unknown"}
