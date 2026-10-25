# -*- coding: utf-8 -*-
"""
经理通路层（LaneRouter · Issue #239 二轮）
==========================================
把「派不出去就算了 / 要不要申请授权 / 只能走 @CodeBuddy 一条路」变成
**多通路穷举 + 可核验就绪 + 权责内自决**。

## 病灶（用户二轮原话）

> 「他链路不通也能通过 @CodeBuddy 这种形式实现功能，还是安排的能力之前要求过
>   安排成功的标准，没成功尝试其他路线，而不是默认就没能力做，相当于挤牙膏。」
> 「职责范围内的还在申请授权……经理角色当末端员工了。」

一句话：**通路不是一条，失败一次不等于做不到**。经理的价值就在于
第一条路断了之后，他自己知道还有第二条、第三条。

## 三条硬规则

| 规则 | 治什么 | 判定 |
|------|--------|------|
| **多通路穷举** | 一条路断了就默认没能力 | `attempt()` 按顺序真试，每条成败都留痕；全断才 `hard` |
| **可核验就绪** | "应该能派出去"这种自我安慰 | `readiness()` 用**代码**判通路是否就绪，不靠感觉 |
| **权责内自决** | 职责范围内还在申请授权 | `authorize()` 纯函数：权责内一律 `SELF`，只有不可逆/超成本/越界才 `HUMAN` |

## 通路清单（按顺序尝试，先便宜后贵）

1. `platform`   —— 平台真建任务 Issue
2. `fullpath`   —— 完整 `@org/repo(角色)` 接力卡（relay_card 模板）
3. `codebuddy`  —— `@CodeBuddy` 兜底召唤（用户点名：这条也是通路，不是没能力）
4. `direct_handle` —— 本角色 handle 直接召唤（HandleAbility 解析，不写死）
5. `lead`       —— 调配小组长（带编制承接）
6. `self`       —— 经理自己上手（最后兜底：活不掉地上）

⚠️ 通路穷举 ≠ 越权：`self` 兜底仍受职责硬表约束，只做"不越界"的承接
（拆解、组织、催办、整理），不替开发写代码、不替评审下结论。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

#: 通路顺序（先便宜后贵：平台留痕 > 完整接力 > CodeBuddy 兜底 > 直接召唤 > 组长编制 > 自己）
LANE_ORDER = ("platform", "fullpath", "codebuddy", "direct_handle", "lead", "self")

#: 每条通路的能力说明与代价（供挑选与汇报，避免"只有一条路"）
LANES = {
    "platform": {
        "desc": "平台真建任务 Issue —— 对端有可认领载体，最硬的留痕",
        "cost": "low", "needs": ("repo", "cnb"),
    },
    "fullpath": {
        "desc": "完整 @org/repo(角色) + [触发:角色] 接力卡 —— 跨库也能精准命中",
        "cost": "low", "needs": ("repo",),
    },
    "codebuddy": {
        # 四轮修正：`@CodeBuddy` 是通路，但**必须能投递**才算就绪——
        # 没有 repo 就没有可投的会话载体，判 ready 等于假装"试过了"。
        "desc": "@CodeBuddy 兜底召唤 —— 角色权限不足/未注册时的通用入口",
        "cost": "low", "needs": ("repo",),
    },
    "direct_handle": {
        # 四轮修正：过去 `handle=role` 兜底让这条**永远 ready**，实际上一个 @ 都没解析出来。
        # 现在必须真的解析到完整 `@org/repo(角色)` 才算就绪。
        "desc": "HandleAbility 解析的角色 @ 直呼 —— 不写死角色名/仓库",
        "cost": "low", "needs": ("resolved_handle",),
    },
    "lead": {
        "desc": "调配小组长（带编制承接，组内 N 开发）—— 活交给人带",
        "cost": "mid", "needs": (),
    },
    "self": {
        "desc": "经理自己承接（不越界的那部分）—— 最后兜底，活不掉地上",
        "cost": "high", "needs": (),
    },
}

#: —— 权责内自决（治"职责范围内还在申请授权"）——
#: 判为 SELF 的：经理本职内、可逆、低成本、能留痕、实测可跑。
SELF_AUTHORITY = (
    "选通路", "重试", "再唤醒", "调整安排", "调配小组长", "换角色承接",
    "拆分任务", "加派", "改派", "催办", "找替代角色", "跨岗借人",
    "自建 Issue", "发接力卡", "换召唤方式", "自己先顶上兜底",
    # 找通路的近义说法（用户原话就长这样，不能因为措辞换个字就翻成 HUMAN）
    "换方式", "换路线", "换通路", "换办法", "再试一次", "重新安排",
    "调整人员", "换人", "加人",
)

#: 超成本口径扩展（拆开写，避免误伤 —— 「扩容到 N 并发」「调高预算」这类才是 HUMAN）
HUMAN_AUTHORITY_EXTRA = {
    "扩容": "超成本：资源扩容需人类确认额度",
    "上限": "超成本：额度/上限放大需人类确认",
    "并发": "超成本：并发规模属资源预算",
    "预算": "超成本：资源预算需人类确认",
    "提升额度": "超成本：额度放大需人类确认",
    "升配": "超成本：资源升配需人类确认",
}

#: 只有这些才该找人（不可逆 / 超成本 / 敏感性 / 越出职责边界）
HUMAN_AUTHORITY = {
    "合并": "不可逆：合并需 ⏸CP3 人类确认",
    "关闭 Issue": "不可逆：关闭/废弃需人类确认",
    "删数据": "不可逆：数据销毁需人类确认",
    "花钱": "超成本：付费/额度类需人类确认",
    "扩容预算": "超成本：资源预算需人类确认",
    "改需求边界": "超职责：需求边界属产品/人类",
    "改架构方向": "超职责：架构方向属总师/人类",
    "发敏感信息": "敏感性：Token/密钥/凭证类",
}

#: 默认执行标准（用户点名"之前要求过安排成功的标准"）——
#: 安排不是"发出去了"，是**对端有接单回执 + 有开工证据**。达不到就换路线。
READY_STANDARD = {
    "receipt": "[接单] 回执",
    "work": "开工事件 / 进度尺推进（回执了不动 = 假装，不算成功）",
    "lane_proof": "通路本身可核验（Issue 号 / 接力卡文本 / 角色 handle）",
}


def authorize(action, *, reversible=True, cost="low", sensitive=False,
              in_duty=True):
    """权责边界判定（纯函数）：这个动作经理能不能自决。

    治「职责范围内的还在申请授权」：本职内 + 可逆 + 低成本 + 不敏感
    → **直接 SELF**（自己做，不申请）；只有不可逆/超成本/敏感/越界才走 HUMAN。

    Returns: {"decision": "SELF"|"HUMAN", "reason": str, "action": str}
    """
    text = str(action or "")
    for key, why in HUMAN_AUTHORITY.items():
        if key in text:
            return {"decision": "HUMAN", "action": text, "reason": why}
    # 「扩容到 500 并发 / 调高预算 / 升配」这类才走 HUMAN；泛泛的"换方式"不误伤
    for key, why in HUMAN_AUTHORITY_EXTRA.items():
        if key in text:
            return {"decision": "HUMAN", "action": text, "reason": why}
    if not in_duty:
        return {"decision": "HUMAN", "action": text,
                "reason": "超出经理职责边界：本岗只承上启下，不替别人做决定"}
    if sensitive:
        return {"decision": "HUMAN", "action": text,
                "reason": "涉及敏感信息，不自行处置"}
    if not reversible:
        return {"decision": "HUMAN", "action": text,
                "reason": "不可逆动作，须人类拍板承担"}
    if str(cost).lower() in ("high", "超成本"):
        return {"decision": "HUMAN", "action": text,
                "reason": "成本超出经理可自决范围"}
    hit = [k for k in SELF_AUTHORITY if k in text]
    return {"decision": "SELF", "action": text,
            "reason": (f"权责内（命中「{hit[0]}」）：可逆、低成本、能留痕，"
                       f"经理自决执行，不申请授权" if hit else
                       "权责内、可逆、低成本、能留痕，经理自决执行，不申请授权")}


def _resolve_handle(role, repo=""):
    """真解析一个完整 `@org/repo(角色)`：解不出来就返回空串（不拿角色名冒充）。"""
    try:
        from handle import resolver as _hr
        org, _, name = (repo or "").partition("/")
        res = _hr.best_handle(at_str=None, target_org=org or None,
                              target_repo=name or None, role=role)
        return (res or {}).get("handle") or ""
    except Exception:  # noqa: BLE001 解析能力缺失 → 未就绪，不降级冒充
        return ""


def is_full_handle(text):
    """是不是一个**完整**的 `@org/repo(角色)` 召唤格式（角色名本身不算）。"""
    t = str(text or "")
    return t.startswith("@") and "/" in t and "(" in t and t.endswith(")")


def readiness(lane, *, repo="", cnb=False, handle="", role=""):
    """通路就绪判定（代码判，不靠感觉）：这条通路现在**能不能真跑**。

    返回 {"ready": bool, "missing": [...]}。needs 全满足即 ready——
    「能不能跑」由这里判，不由"我觉得应该能"判。

    四轮修正：过去 `handle` 缺省用角色名兜底，于是 `direct_handle`
    **永远 ready**，可实际什么都没解析出来。现在只认完整 `@org/repo(角色)`。
    """
    needs = LANES.get(lane, {}).get("needs", ())
    missing = []
    for n in needs:
        if n == "repo" and not repo:
            missing.append("repo（目标仓库未探测到）")
        elif n == "cnb" and not cnb:
            missing.append("cnb（平台 CLI 不可用）")
        elif n == "resolved_handle":
            cand = handle if is_full_handle(handle) else _resolve_handle(role or handle, repo)
            if not cand:
                missing.append("handle（完整 @org/repo(角色) 未解析出）")
    return {"lane": lane, "ready": not missing, "missing": missing}


def lanes_for(role, *, repo="", cnb=False, handle="", allow_self=True):
    """列出该角色可用通路（按代价排序），并标注每条是否就绪。"""
    out = []
    for lane in LANE_ORDER:
        if lane == "self" and not allow_self:
            continue
        r = readiness(lane, repo=repo, cnb=cnb, handle=handle, role=role)
        out.append({
            "lane": lane,
            "desc": LANES[lane]["desc"],
            "cost": LANES[lane]["cost"],
            "ready": r["ready"],
            "missing": r["missing"],
        })
    return out


def attempt(role, handlers, *, repo="", cnb=False, handle="", allow_self=True,
            log=None):
    """多通路穷举：按顺序**真试**每条通路，任一条成功即停。

    handlers: {lane: callable() -> dict}，返回值须含 ok 字段。缺 handler 的通路跳过
              （跳过也留痕：`skipped_no_handler`，不假装试过）。
    log:      可选回调，签名 log(kind, payload)——经理引擎用它写 manager_actions。

    返回 {"ok": bool, "lane": 成功通路 or None, "tried": [...], "attempts": [...]}
    """
    def _log(kind, payload):
        if callable(log):
            try:
                log(kind, payload)
            except Exception:  # noqa: BLE001 留痕失败不改变判定
                pass

    tried, attempts = [], []
    for lane in LANE_ORDER:
        if lane == "self" and not allow_self:
            continue
        rd = readiness(lane, repo=repo, cnb=cnb, handle=handle, role=role)
        if not rd["ready"]:
            attempts.append({"lane": lane, "state": "skipped_unready",
                             "missing": rd["missing"]})
            _log("lane_skipped", {"lane": lane, "missing": rd["missing"]})
            continue
        fn = (handlers or {}).get(lane)
        if fn is None:
            attempts.append({"lane": lane, "state": "skipped_no_handler"})
            continue
        tried.append(lane)
        try:
            res = fn() or {}
        except Exception as e:  # noqa: BLE001 单通路失败即换下一条，绝不整体放弃
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        ok = bool(res.get("ok"))
        attempts.append({"lane": lane, "state": "ok" if ok else "failed",
                         "detail": res})
        _log("lane_attempt", {"lane": lane, "ok": ok})
        if ok:
            return {"ok": True, "lane": lane, "tried": tried,
                    "attempts": attempts, "result": res}
    _log("lane_exhausted", {"tried": tried,
                            "attempts": [a["lane"] for a in attempts]})
    return {"ok": False, "lane": None, "tried": tried, "attempts": attempts,
            "result": None}


def capability():
    """能力声明（供角色/文档/测试引用）。"""
    return {
        "name": "lane_router",
        "version": "v0.1.0",
        "module": "manager-lane",
        "lanes": LANE_ORDER,
        "lane_specs": LANES,
        "rules": {
            "多通路穷举": "一条断了换下一条，逐条留痕；全断才判 hard，绝不一次失败就说做不到",
            "可核验就绪": "通路能不能跑由 readiness() 代码判，不靠自我感觉",
            "权责内自决": "authorize() 判 SELF 就必须自己干，只有不可逆/超成本/敏感/越界才申请",
            "成功标准": READY_STANDARD,
            "self 兜底不越界": "经理自己承接仍受职责硬表约束，不替开发写码、不替评审下结论",
        },
        "entry": ["lanes_for", "attempt", "authorize", "readiness"],
    }
