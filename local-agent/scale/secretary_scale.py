# -*- coding: utf-8 -*-
"""
秘书层动态扩展机制（secretary-scale · Issue #100 决策①）
========================================================
用户拍板（Issue #100 ①）：

  "不给他写死定级，而是让他基于实际情况能够被扩展……基于信息流的位置以及任务
   是否相对独立，如果某些情况使用某场景特别多，他其实就适合被形成一种秘书机制
   去负责它……之后如果出现了适合分配的或者是需要增加的层也是有可能的。
   所以不应该被写死，而是需要一套机制能增加和减少。"

  "最后我们的秘书层可能会发展成很多个层的服务 + 层间的路由，来实现持续的扩展，
   实现功能、责任、记忆、工具的一致性。"

  "秘书主要用来交接，而不是主要完成任务，后面其实有专门的开发，我们不应该把
   秘书扩展到可以完成所有任务。它不适合承载那些，所以有一条边界，我希望这里有
   一个自动化控制和边界的机制，让它能在一个合理范围内有成长的效果。"

本模块把「秘书层动态扩展」落成 `local-agent/scale/` 的可执行扩展，分三层 + 一道护栏：

  - **识别层**：用确定性判据判定"哪段信息流 / 哪个相对独立场景值得设一个秘书"，
    避免"感觉该设就设"的拍脑袋。判据 = 复用率 + 独立边界评分 + 是否不需终端执行。
  - **注册层**：秘书以「服务」形式动态挂载/卸载，可增减（plugin 风格，进独立模块
    不入核心代码），并带生命周期（registered → active → draining → unregistered）。
  - **路由层**：层间路由——请求 → 命中对应秘书域 → 交接给下游终端角色；
    未命中则回默认终端开发线（秘书不吞活、不改形）。
  - **权限边界护栏（guard）**：确定性检查——秘书只做交接/路由/调度，不做终端任务；
    凡秘书尝试越权接终端任务即拦截（对齐 dev-standard 的确定性检查器思路）。

设计原则：
  - **不写死层数/角色**：靠机制增减，而非硬编码"秘书共 X 层"；
  - **秘书 = 交接域服务**：每个秘书是一个"可交接的边界域 + 稳定交接接口"，只交接不执行；
  - **确定性**：识别阈值、边界判定都是确定性规则，不靠 LLM 感觉；
  - **护栏不靠自觉**：越权接终端任务会被确定性拦截。

承载：
  - 识别/注册/路由/护栏逻辑本文件
  - 秘书服务定义：秘书服务 = {domain, desc, reuse(复用率信号), boundary, handoff_to}
  - 留痕：注册表 + 路由/识别动作可回溯
"""
import json
import os
import threading
import time
import uuid

# ======================================================================
# ① 识别层判据阈值（确定性 · 唯一事实源）
# ======================================================================
# 判定一个场景/信息流"是否值得设一个秘书"的三维确定性判据：
IDENTIFY_CRITERIA = {
    # 复用率：被多少场景/请求高频复用（>阈值才值得独立秘书）
    "reuse_threshold": 3,          # 至少被 3 个以上独立请求/场景复用
    # 独立边界评分：边界是否清晰可交接（>阈值才算"相对独立"）
    "boundary_threshold": 0.6,     # 0~1，基于任务独立性判据打分
    # 秘书只交接不执行：若该场景需终端执行（写业务代码/跑业务），则不应设秘书
    "requires_execution_block": True,   # 命中需终端执行 → 拦下不设秘书
}

# 独立边界评分依据（确定性打分项）：
BOUNDARY_FACTORS = {
    "clear_interface": 0.4,   # 是否有稳定清晰接口（交接点明确）
    "single_owner": 0.3,      # 是否单一归属、无跨域纠缠
    "self_contained": 0.3,    # 是否自包含（状态/记忆/工具边界清晰）
}


def identify_secretary(domain, reuse_count=0, boundary_factor_scores=None,
                       requires_execution=False):
    """识别层：判定某场景/信息流是否值得设一个秘书。

    确定性判据（不靠感觉）：
      1. 复用率 reuse_count ≥ reuse_threshold；
      2. 独立边界评分（clear_interface/single_owner/self_contained 加权和）
         ≥ boundary_threshold；
      3. 不需终端执行（requires_execution 必须 False——秘书只交接不执行）。

    返回 {warrant, score, reasons}：warrant 表示是否建议增设该秘书。
    """
    meta = IDENTIFY_CRITERIA
    thr = meta["reuse_threshold"]
    bt = meta["boundary_threshold"]

    reasons = []
    if requires_execution:
        return {"warrant": False, "score": 0.0,
                "reasons": ["requires_execution: 该场景需终端执行，秘书只交接不执行，"
                            "应走开发线而非设秘书（边界护栏①）"]}

    scores = boundary_factor_scores or {}
    score = 0.0
    for factor, weight in BOUNDARY_FACTORS.items():
        v = scores.get(factor, 0.0)
        v = max(0.0, min(1.0, float(v)))
        score += weight * v
        reasons.append(f"boundary[{factor}]={v:.2f}(w{weight})")

    if reuse_count < thr:
        reasons.append(f"reuse_count={reuse_count} < {thr}（复用不足，暂不值得独立秘书）")
    if score < bt:
        reasons.append(f"boundary_score={score:.2f} < {bt}（边界不够独立清晰）")

    warrant = (reuse_count >= thr) and (score >= bt)
    reasons.append(f"boundary_score={score:.2f} 复用={reuse_count} "
                   f"→ {'建议增设' if warrant else '暂不增设'}")
    return {"domain": domain, "warrant": warrant, "score": round(score, 4),
            "reasons": reasons}


# ======================================================================
# ② 注册层：秘书服务注册表 + 生命周期
# ======================================================================
# 一个"秘书服务"定义（秘书 = 可交接的边界域服务，只交接不执行）：
#   domain      秘书域唯一名
#   desc        该域负责什么（交接对象/场景说明）
#   reuse       复用率信号（动态累积）
#   handoff_to  命中后交接给哪个终端角色/线（秘书只交接到此，不执行）
#   status      registered / active / draining / unregistered（生命周期）
#   created_at / interfaces  稳定交接接口
_SECRETARY_REGISTRY = {}
_REGISTRY_LOCK = threading.Lock()


def register_secretary(domain, desc="", handoff_to="", reuse=0,
                       interfaces=None):
    """注册一个秘书服务（动态挂载，可增可减）。返回秘书服务 dict。

    校验：domain 唯一；handoff_to 必填（秘书必须知道自己交接给谁，不许吞活）。
    """
    if not domain:
        raise ValueError("秘书服务必须定义 domain")
    if not handoff_to:
        raise ValueError(
            f"秘书服务 {domain} 必须定义 handoff_to（秘书只交接给下游，不许吞活）"
        )
    svc = {
        "domain": domain,
        "desc": desc,
        "handoff_to": handoff_to,
        "reuse": int(reuse),
        "status": "registered",
        "interfaces": interfaces or ["handoff"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with _REGISTRY_LOCK:
        if domain in _SECRETARY_REGISTRY:
            raise ValueError(f"秘书服务域 {domain} 已注册（需先 unregister 再注册）")
        _SECRETARY_REGISTRY[domain] = svc
    return dict(svc)


def activate_secretary(domain):
    """把秘书服务置为 active（可用）。"""
    with _REGISTRY_LOCK:
        if domain not in _SECRETARY_REGISTRY:
            raise KeyError(f"秘书服务 {domain} 未注册")
        _SECRETARY_REGISTRY[domain]["status"] = "active"
        return dict(_SECRETARY_REGISTRY[domain])


def drain_secretary(domain):
    """排水（draining）：停止接收新请求，消化在途。"""
    with _REGISTRY_LOCK:
        if domain not in _SECRETARY_REGISTRY:
            raise KeyError(f"秘书服务 {domain} 未注册")
        _SECRETARY_REGISTRY[domain]["status"] = "draining"
        return dict(_SECRETARY_REGISTRY[domain])


def unregister_secretary(domain):
    """卸载一个秘书服务（可减）。返回是否成功。"""
    with _REGISTRY_LOCK:
        if domain in _SECRETARY_REGISTRY:
            del _SECRETARY_REGISTRY[domain]
            return True
        return False


def list_secretaries(status=None):
    """列出全部秘书服务（可按生命周期状态过滤）。"""
    with _REGISTRY_LOCK:
        items = [dict(s) for s in _SECRETARY_REGISTRY.values()]
    if status:
        items = [s for s in items if s["status"] == status]
    return items


def get_secretary(domain):
    """按域取秘书服务。"""
    with _REGISTRY_LOCK:
        svc = _SECRETARY_REGISTRY.get(domain)
        return dict(svc) if svc else None


def bump_reuse(domain, n=1):
    """秘书服务被命中一次就累计一次复用信号（供识别层评估成长）。"""
    with _REGISTRY_LOCK:
        if domain not in _SECRETARY_REGISTRY:
            return None
        _SECRETARY_REGISTRY[domain]["reuse"] += int(n)
        return _SECRETARY_REGISTRY[domain]["reuse"]


# ======================================================================
# ③ 路由层：层间路由（请求 → 命中秘书域 → 交接下游；未命中回终端开发线）
# ======================================================================
def route_request(request, domain_matcher=None):
    """路由层：把请求路由到匹配的秘书服务，命中则交接给其 handoff_to。

    未命中任何秘书域 → 回默认终端开发线（秘书不吞活、不改形）。
    返回 {matched, secretary, handoff, to}。
    domain_matcher: 可选匹配函数 (request, svc) -> bool；默认按 request['domain']。
    """
    svc = None
    if domain_matcher is not None:
        for s in list_secretaries():
            if s["status"] in ("active", "registered") and domain_matcher(request, s):
                svc = s
                break
    else:
        # 默认精确匹配 request['domain'] 到秘书域
        want = request.get("domain")
        for s in list_secretaries():
            if s["status"] in ("active", "registered") and s["domain"] == want:
                svc = s
                break
    if svc is None:
        return {"matched": False, "secretary": None,
                "handoff": False, "to": "终端开发线(默认)", "request": request}
    # 命中 → 秘书做的是"交接"，把请求转交其 handoff_to（只交接不执行）
    bump_reuse(svc["domain"])
    return {"matched": True, "secretary": svc["domain"],
            "handoff": True, "to": svc["handoff_to"],
            "request": {"domain": request.get("domain"), "original": request}}


# ======================================================================
# ④ 权限边界护栏（guard）：秘书只交接不执行，越权接终端任务即拦截
# ======================================================================
# 秘书被"邀请/尝试"承担的职责分两类：
#   HANDOFF_DUTY  交接/路由/调度（秘书本职，放行）
#   TERMINAL_DUTY 终端执行（写业务代码 / 跑业务 / 承担落地结果），秘书越权，拦截
HANDOFF_DUTY = {"handoff", "route", "relay", "dispatch_lite", "intake", "triage"}
TERMINAL_DUTY = {"implement", "develop", "execute", "fix_bug", "write_code",
                 "run_biz", "deliver_result", "own_task_result"}


def guard(duty, domain="", role="架构·秘书"):
    """权限边界护栏（确定性）：判定某职责是否为秘书可合法承担。

    - duty ∈ HANDOFF_DUTY → 放行（秘书本职：交接/路由）
    - duty ∈ TERMINAL_DUTY → 拦截（秘书越权接终端任务）
    - 其他 → 需有明确角色白名单，否则按"需终端结果"倾向拦截（宁拦不放，防越权）
    返回 {allowed, duty, reason}。
    """
    if duty in HANDOFF_DUTY:
        return {"allowed": True, "duty": duty, "role": role,
                "reason": "交接/路由类职责，秘书本职，放行"}
    if duty in TERMINAL_DUTY:
        return {"allowed": False, "duty": duty, "role": role,
                "reason": "终端执行类职责（会承担落地结果），秘书越权，拦截——"
                          "秘书只交接不执行，落地交专门开发线"}
    return {"allowed": False, "duty": duty, "role": role,
            "reason": "未知职责，按'需终端结果'倾向拦截（宁拦不放，防越权成长）"}


# ======================================================================
# 留痕（可回溯）
# ======================================================================
_TRACE = []
_TRACE_LOCK = threading.Lock()


def log(action, payload):
    """留痕一条秘书层动作（识别/注册/路由/护栏）。"""
    rec = {"action": action, "payload": payload,
           "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with _TRACE_LOCK:
        _TRACE.append(rec)
    return rec


def recent_logs(limit=50):
    """最近秘书层动作留痕。"""
    with _TRACE_LOCK:
        return _TRACE[-limit:]
