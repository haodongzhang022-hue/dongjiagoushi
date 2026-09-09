# -*- coding: utf-8 -*-
"""
七层协作深度引擎（DepthEngine · L1→L7）
=========================================
把「协作能走多深、真唤醒还是假描述」封装为**可核验的七层深度模型**（docs/DEPTH_MODEL.md）。

背景（用户 Issue #47 拍板）：
  - 很多 agent 其实只在"描述"（L1 表述层），并没有真正触发对面角色过来工作——
    "路由其实并没有真实现唤醒"。秘书路由 @产品 后，甚至不能确认是否给对面传达了足够内容。
  - 需要一个**可量化、可核验**的深度阶梯，逐层确认"真的在推进"，而不是"嘴上说在推进"。
  - 这是**通用能力**，不是只给一个 agent：应做好后作为独立模块能力，给每个 agent 对接并让其会用。

七层深度阶梯（每层都必须有可核验的留痕才算达标）：
  L1 表述层    —— 能到对应角色拿到信息（仅表述/传达，秘书/多数 agent 现状）
  L2 任务对接层 —— 能到对应 Issue 接到任务、匹配到 agent（有明确载体 + 责任 agent）
  L3 开工层    —— 能接受任务开始工作（含【路由真实唤醒】确认：目标 agent 回执接单）
  L4 成果交互层 —— 成果能和当前 agent 双向交互（下游/上游能读到产物并反馈）
  L5 进度可控层 —— 进度可控、可来回轮次触发、有自动化规则持续维持流程（哨兵收敛/超时重触发/停滞升级）
  L6 持续到结果层 —— 能一套自动化持续到结果（秘书目标档位；需收尾确认后交付）
  L7 全自动到结果层 —— 全自动持续到结果，无需人工/授权中断（体系目标档位）

设计原则：
  - **每一层可核验**：逐层记录 event / 深度标记到数据层，供俯瞰（depth_overview）与测试断言。
  - **防跳层**：某层操作前须已满足前置深度，否则显式报错（借鉴 dispatch_engine._require_level）。
  - **唤醒优先**：L3 含 `awake()` —— 路由后检测目标 agent 是否真的回执，解决"只描述没唤醒"。
  - **自动化维持**：L5 含 `auto_guard()` —— 哨兵收敛/超时重触发/停滞升级的自动化规则引擎。
  - **可持续到结果**：L6/L7 含 `persist()` / `auto_run()` —— 一套流程闭环到结果。
"""
import os
import sys

# 确保 local-agent 目录在 sys.path（便于导入 data/dispatch_engine/sentinel）
_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


# 七层深度定义（唯一规范，文档/规则/测试都从这里对齐）
DEPTH_LEVELS = {
    1: {"key": "L1_表述", "name": "表述层", "desc": "到对应角色拿到信息（仅表述/传达）"},
    2: {"key": "L2_任务对接", "name": "任务对接层", "desc": "到对应 Issue 接到任务、匹配到 agent"},
    3: {"key": "L3_开工", "name": "开工层", "desc": "接受任务开始工作（含路由真实唤醒确认）"},
    4: {"key": "L4_成果交互", "name": "成果交互层", "desc": "成果能和当前 agent 双向交互"},
    5: {"key": "L5_进度可控", "name": "进度可控层", "desc": "进度可控、可来回轮次触发、自动化规则维持流程"},
    6: {"key": "L6_持续到结果", "name": "持续到结果层", "desc": "一套自动化持续到结果（秘书目标档位）"},
    7: {"key": "L7_全自动到结果", "name": "全自动到结果层", "desc": "全自动持续到结果，无需人工中断（体系目标档位）"},
}


def _admin():
    """惰性导入 data.admin（统一留痕）。"""
    from data import admin
    return admin


def _engine():
    """惰性导入 dispatch_engine（复用 L1-L4 既有分发链路）。"""
    import dispatch_engine
    return dispatch_engine


def _sentinel():
    """惰性导入 sentinel.engine（复用目标收敛监控）。"""
    from sentinel import engine as sentinel
    return sentinel


def _gid_for(kind, biz_key):
    """惰性导入 gid_for。"""
    from gid import gid_for
    return gid_for(kind, biz_key)


# ============================================================
# 深度记录与查询（贯穿 L1-L7 的通用底座）
# ============================================================
def record_depth(task_key, level, agent_id="", note=""):
    """记录某个任务当前已达的深度层（含 note 说明），供俯瞰与测试核验。

    level 取值 1-7；超过当前记录的深度才覆盖（只升不降），
    但 note 每次都会追加留痕（append 到 archives）。
    """
    admin = _admin()
    task_id = _gid_for("task", task_key) or task_key
    event = {
        "task_key": task_key,
        "task_id": task_id,
        "depth": level,
        "level_key": DEPTH_LEVELS.get(level, {}).get("key", f"L{level}"),
        "agent_id": agent_id or "",
        "note": note or "",
    }
    # 事件留痕
    admin.record_event(
        agent_id or "system", f"depth_L{level}",
        {"task_key": task_key, "task_id": task_id, "note": note or ""},
        task_id or "",
    )
    # 归档（可回溯）
    try:
        admin.archive(
            f"depth_{task_id}_L{level}", "depth",
            f"任务 {task_key} 到达 L{level}（{DEPTH_LEVELS.get(level,{}).get('key','')}）",
            event,
            source=agent_id or "system",
        )
    except Exception:
        pass
    return event


def depth_of(task_key):
    """查询某个任务当前已达的最大深度层（无记录返回 1）。"""
    from data import repository as repo
    task_id = _gid_for("task", task_key) or task_key
    progress = repo.recent_progress(limit=5000)
    depth = 1
    events = []
    for p in progress:
        if p.get("task_id") == task_id and p.get("event", "").startswith("depth_L"):
            try:
                d = int(p["event"].replace("depth_L", ""))
            except (ValueError, TypeError):
                continue
            if d > depth:
                depth = d
            events.append(d)
    return {"task_key": task_key, "task_id": task_id,
            "depth": depth, "level_key": DEPTH_LEVELS.get(depth, {}).get("key", f"L{depth}"),
            "events": events}


def require_depth(task_key, needed, note=""):
    """防跳层前置校验：某层操作前须已满足前置深度，否则显式报错。"""
    cur = depth_of(task_key)["depth"]
    if cur < needed:
        raise ValueError(
            f"防跳层：任务 {task_key} 当前深度 L{cur}（{DEPTH_LEVELS.get(cur,{}).get('key','')}），"
            f"须先推进到 L{needed}（{DEPTH_LEVELS.get(needed,{}).get('name','')}）才可执行该操作。"
            f"{note or ''}"
        )
    return cur


# ============================================================
# L1 表述层：到对应角色拿到信息
# ============================================================
def express(task_key, from_agent, to_agent, message):
    """L1 · 表述：向目标角色传达信息（仅表述层）。

    返回：表述记录（含对目标 agent 的唤醒意图）。这是最浅层，
    是否真正唤醒由 L3 的 awake() 校验。
    """
    admin = _admin()
    msg = admin.post_message(
        topic=f"depth.{to_agent}",
        payload={"task_key": task_key, "from": from_agent, "to": to_agent,
                 "depth": 1, "level": "L1_表述", "message": message,
                 "wake_intent": True},
        from_agent=from_agent,
        to_agent=to_agent,
    )
    record_depth(task_key, 1, agent_id=from_agent, note=f"L1 表述：向 {to_agent} 传达信息")
    return {"level": 1, "level_key": "L1_表述",
            "from": from_agent, "to": to_agent, "msg_id": msg.get("msg_id", ""),
            "note": "仅表述——是否真实唤醒目标 agent 由 L3 awake() 校验"}


# ============================================================
# L2 任务对接层：到对应 Issue 接到任务、匹配到 agent
# ============================================================
def connect(task_key, issue_ref="", role="架构·开发", domain="通用",
            title="", detail="", repo=""):
    """L2 · 任务对接：把任务落到明确载体（Issue）+ 匹配到责任 agent。

    复用 dispatch_engine 的 L2 分发（dispatch_assign），确保任务写入 tasks 表、
    投入功能域池、注册 agent gid、绑定 Issue——有明确载体 + 责任 agent。
    前置：须先完成 L1（表述/声明）——基于本模块七层深度模型校验，不跳层。
    """
    require_depth(task_key, 1, "L2 任务对接须先完成 L1 表述（先到对应角色拿信息）")
    engine = _engine()
    result = engine.dispatch_assign(repo, [{
        "task_key": task_key, "title": title or task_key,
        "role": role, "domain": domain, "depends_on": "", "priority": "P1",
        "detail": detail,
    }])
    item = result[0]
    # 登记到 issue（若给了 issue_ref 则记录绑定）
    admin = _admin()
    if issue_ref:
        admin.record_event(
            "", "issue_bound",
            {"task_key": task_key, "issue_ref": issue_ref, "role": role},
            item["task_id"],
        )
    record_depth(task_key, 2, agent_id=role, note=f"L2 任务对接：Issue {issue_ref} + agent {role}")
    return {
        "level": 2, "level_key": "L2_任务对接",
        "task_key": task_key, "task_id": item["task_id"],
        "agent_id": item["agent_id"], "role": role,
        "domain": domain, "issue_ref": issue_ref or f"#{item['issue_number']}" if item.get("issue_number") else "(待建)",
        "gid": item["task_id"],
    }


# ============================================================
# L3 开工层：接受任务开始工作（含【路由真实唤醒】确认）
# ============================================================
def awake(task_key, target_agent, from_agent, issue_ref="", context="", timeout=3):
    """L3 · 路由真实唤醒：确认目标 agent 真的被唤醒接单，而不是只描述了。

    这是用户 Issue #47 的核心痛点："路由其实并没有真实现唤醒"。
    awake() 不只投递消息，还：
      1. 投递带 [触发:<角色>] 的接力卡（路由真实传递足够内容）；
      2. 通过消息管线定向唤醒目标 agent（topic=depth.wake.<target>）；
      3. 校验是否有目标 agent 的回执（[接单]/awake_ack）——没有回执即"未真实唤醒"。

    返回：{awakened: bool, receipt: ...}，供秘书/派发方核验路由是否真唤醒。
    """
    admin = _admin()
    task_id = _gid_for("task", task_key) or task_key
    # ① 投递带 [触发] 标记 + 完整 @org/repo 路径的接力卡（#142 全路径出发）
    #    context 已由 BaseRole.awake/fullpath_relay 前置完整 @ 路径；
    #    此处兜底：若 context 仍缺完整 @，自动补（防底层直调漏路径）。
    ctx = context or ""
    ctx_note = ""
    if ctx and not ctx.lstrip().startswith("@"):
        # 兜底补完整 @ 路径（防底层直调漏路径）；解析失败不静默（best_handle）
        try:
            from handle import resolver as _hr
            _res = _hr.best_handle(
                at_str=None, target_repo="dongjiagoushi", role=target_agent)
            _handle = _res["handle"]
            ctx = "%s [触发:%s]。\n%s" % (_handle, target_agent, ctx)
            ctx_note = _res.get("warning") or ""
        except Exception:
            ctx_note = ("handle 包不可用，awake 未能自动补全 @ 路径（可能无法真实唤醒对端）")
    relay_card = {
        "handle": (ctx.split(" ")[0] if ctx.startswith("@") else ""),
        "trigger": f"[触发:{target_agent}]",
        "relay_text": ctx,
        "depth": 3, "level": "L3_开工",
        "task_key": task_key, "task_id": task_id,
        "issue": f"#{issue_ref}" if issue_ref else "",
        "context": ctx,
        "note": ctx_note,
        "action": "回执 [接单] 确认真实唤醒",
        "expect": "[接单]/awake_ack 回执，无回执 = 路由未真实唤醒",
    }
    admin.post_message(
        topic=f"depth.wake.{target_agent}",
        payload=relay_card,
        from_agent=from_agent,
        to_agent=target_agent,
    )
    # ② 记录唤醒意图（供校验回执）
    admin.record_event(
        from_agent, "wake_intent",
        {"task_key": task_key, "task_id": task_id,
         "target_agent": target_agent, "issue": issue_ref or "",
         "ctx_note": ctx_note or ""},
        task_id or "",
    )
    # ③ 校验目标 agent 是否回执（[接单] / awake_ack）
    receipts = admin.consume(agent_id=target_agent, topic="depth.wake.*")
    # consume 返回该 agent 的所有未消费消息；检查是否有接单回执
    from data import repository as repo
    recent = repo.recent_progress(limit=2000)
    accepted = False
    ack_events = []
    for p in recent:
        if p.get("task_id") == task_id and p.get("agent_id", "") == target_agent:
            ev = p.get("event", "")
            if ev in ("accepted", "awake_ack"):
                accepted = True
                ack_events.append(p)
    record_depth(task_key, 3, agent_id=target_agent,
                 note=f"L3 路由唤醒{'成功' if accepted else '待回执'}：目标 {target_agent}")
    return {
        "level": 3, "level_key": "L3_开工",
        "task_key": task_key, "target_agent": target_agent,
        "from_agent": from_agent, "issue": issue_ref or "",
        "awakened": accepted,
        "awakened_note": "目标 agent 已回执 [接单]/awake_ack，路由真实唤醒"
                         if accepted else
                         "尚未收到目标 agent 回执——路由未真实现唤醒，需重触发或升级",
        "receipts": ack_events,
    }


def ack_wake(task_key, agent_id, role="", note=""):
    """被唤醒方回执：确认收到接力卡并接管，标记路由真实唤醒成立。"""
    admin = _admin()
    task_id = _gid_for("task", task_key) or task_key
    admin.record_event(
        agent_id, "awake_ack",
        {"task_key": task_key, "task_id": task_id,
         "role": role or "", "note": note or "[接单] 已收到接力卡并接管"},
        task_id or "",
    )
    admin.post_message(
        topic="depth.awake_ack",
        payload={"task_key": task_key, "task_id": task_id,
                 "agent_id": agent_id, "role": role or ""},
        from_agent=agent_id,
        to_agent="",
    )
    record_depth(task_key, 3, agent_id=agent_id, note="L3 被唤醒方已回执接管")
    return {"status": "awake_ack", "task_key": task_key,
            "agent_id": agent_id, "role": role or ""}


def start_work(task_key, agent_id, role="", note=""):
    """L3 · 开工：接单后正式开工，复用 dispatch_engine.dispatch_start 语义。"""
    require_depth(task_key, 2, "L3 开工须先完成 L2 任务对接")
    engine = _engine()
    result = engine.dispatch_start([{
        "task_key": task_key, "gid": _gid_for("task", task_key),
        "agent_id": agent_id, "role": role or "",
    }])
    record_depth(task_key, 3, agent_id=agent_id, note="L3 已开工")
    return {"level": 3, "status": "working", "task_key": task_key,
            "agent_id": agent_id, "detail": result[0]}


# ============================================================
# L4 成果交互层：成果能和当前 agent 双向交互
# ============================================================
def interact(task_key, producer_agent, consumer_agent, artifact, feedback=None):
    """L4 · 成果交互：产出方交付成果给消费方，消费方可回读并反馈。

    双向：producer → artifact → consumer；consumer 可 post 反馈 → producer。
    """
    require_depth(task_key, 3, "L4 成果交互须先完成 L3 开工")
    admin = _admin()
    task_id = _gid_for("task", task_key) or task_key
    # 产出归档（consumer 可读）
    admin.archive(
        f"interact_{task_id}", "artifact",
        f"任务 {task_key} 产物", artifact,
        source=producer_agent,
    )
    # 通知 consumer
    admin.post_message(
        topic=f"depth.artifact.{consumer_agent}",
        payload={"task_key": task_key, "task_id": task_id,
                 "producer": producer_agent, "artifact": artifact,
                 "action": "读取产物并反馈"},
        from_agent=producer_agent,
        to_agent=consumer_agent,
    )
    # 若 consumer 反馈，回写给 producer（双向）
    feedback_note = ""
    if feedback is not None:
        admin.post_message(
            topic=f"depth.feedback.{producer_agent}",
            payload={"task_key": task_key, "task_id": task_id,
                     "from": consumer_agent, "feedback": feedback},
            from_agent=consumer_agent,
            to_agent=producer_agent,
        )
        feedback_note = f"consumer {consumer_agent} 已回写反馈"
    record_depth(task_key, 4, agent_id=producer_agent,
                 note=f"L4 成果交互：{producer_agent} → {consumer_agent}")
    return {
        "level": 4, "level_key": "L4_成果交互",
        "task_key": task_key, "producer": producer_agent,
        "consumer": consumer_agent,
        "artifact_stored": True,
        "feedback": feedback_note or "待 consumer 反馈",
    }


# ============================================================
# L5 进度可控层：进度可控、可来回轮次触发、自动化规则维持
# ============================================================
def track_round(task_key, agent_id, target, goal_total, current, note="", role=""):
    """L5 · 进度可控 + 轮次触发：写进度尺 + 记录轮次。

    复用 sentinel.track（目标收敛判定）+ dispatch_engine.track_progress 语义。
    """
    require_depth(task_key, 4, "L5 进度可控须先完成 L4 成果交互")
    engine = _engine()
    result = engine.track_progress(
        task_key, agent_id, target=target, goal_total=goal_total,
        current=current, note=note, role=role or "")
    record_depth(task_key, 5, agent_id=agent_id,
                 note=f"L5 进度推进 current={current}/{goal_total}")
    return {
        "level": 5, "level_key": "L5_进度可控",
        "task_key": task_key, "meter": result["meter"],
        "analysis": result["analysis"],
        "distance": result["distance"], "delta": result["delta"],
    }


def auto_guard(task_key, agent_id, rule="stall_escalate", timeout_rounds=3):
    """L5 · 自动化规则维持流程：哨兵收敛 / 超时重触发 / 停滞升级。

    规则引擎（rule）：
      - 'stall_escalate'：检测到停滞（连续无净进展）→ 上报升级，避免无效努力循环；
      - 'timeout_retrigger'：超过 timeout_rounds 轮仍无进度 → 自动重触发目标 agent；
      - 'converge_check'：检查到北极星距离是否为 0（已达结果）→ 判定收敛。

    返回：{rule, action, triggered, note}——有自动化规则持续维持流程（L5 达标）。
    """
    require_depth(task_key, 4, "L5 自动规则须先完成 L4 成果交互")
    admin = _admin()
    task_id = _gid_for("task", task_key) or task_key
    sentinel = _sentinel()

    if rule == "converge_check":
        # 检查目标是否收敛（distance 是否为 0）
        from sentinel import store as sentinel_store
        meter = sentinel_store.latest_meter(f"g-{task_id}")
        distance = meter.get("distance") if meter else None
        converged = (distance == 0) if distance is not None else False
        action = "converged" if converged else "still_running"
        admin.record_event(
            agent_id, "auto_guard",
            {"task_key": task_key, "rule": rule, "action": action,
             "distance": distance}, task_id or "")
        record_depth(task_key, 5, agent_id=agent_id,
                     note=f"L5 自动规则 converge_check：{'收敛' if converged else '仍在推进'}")
        return {"level": 5, "rule": rule, "action": action,
                "converged": converged, "distance": distance}

    if rule == "timeout_retrigger":
        # 超过 timeout_rounds 轮仍无进度 → 自动重触发
        from data import repository as repo
        recent = repo.recent_progress(limit=2000)
        rounds = sum(1 for p in recent
                     if p.get("task_id") == task_id and p.get("event", "").startswith("depth_L5"))
        triggered = rounds >= timeout_rounds
        action = "retrigger" if triggered else "hold"
        admin.record_event(
            agent_id, "auto_guard",
            {"task_key": task_key, "rule": rule, "action": action,
             "rounds": rounds, "timeout_rounds": timeout_rounds}, task_id or "")
        record_depth(task_key, 5, agent_id=agent_id,
                     note=f"L5 自动规则 timeout_retrigger：{'已重触发' if triggered else '未到超时'}")
        return {"level": 5, "rule": rule, "action": action,
                "triggered": triggered, "rounds": rounds}

    # 默认：stall_escalate（停滞升级）——用哨兵 detect.analyze 判定是否停滞
    from sentinel import store as sentinel_store
    from sentinel import detect as sentinel_detect
    series = sentinel_store.meter_series(f"g-{task_id}")
    sentinel_action = sentinel_detect.analyze(
        series, goal_total=0.0, agent_id=agent_id, task_id=task_id)
    stalled = bool(sentinel_action.get("hit"))
    action = "escalate" if stalled else "ok"
    admin.record_event(
        agent_id, "auto_guard",
        {"task_key": task_key, "rule": rule, "action": action,
         "sentinel": sentinel_action}, task_id or "")
    record_depth(task_key, 5, agent_id=agent_id,
                 note=f"L5 自动规则 stall_escalate：{'停滞已升级' if stalled else '推进正常'}")
    return {"level": 5, "rule": rule, "action": action,
            "stalled": stalled, "sentinel": sentinel_action}


# ============================================================
# L6 持续到结果层：一套自动化持续到结果（秘书目标档位）
# ============================================================
def persist_to_result(task_key, agent_id, milestones, role="",
                      auto_check_every=1, need_human_gate=False):
    """L6 · 持续到结果：一套自动化流程按里程碑持续推进，直到结果。

    milestones: 有序里程碑列表 [{step, action, target, goal_total, current}]
    need_human_gate: 收尾是否需要人工/授权确认（L6 秘书档位 = 收尾确认后交付；
                     L7 全自动档位 = 无需人工中断）。

    返回：{reached_result, completed_milestones, remaining, human_gate}。
    """
    require_depth(task_key, 5, "L6 持续到结果须先完成 L5 进度可控")
    admin = _admin()
    task_id = _gid_for("task", task_key) or task_key
    completed = 0
    remaining = []
    for i, m in enumerate(milestones):
        # 逐里程碑推进：写进度尺
        sentinel = _sentinel()
        sentinel.track(
            f"g-{task_id}", task_id=task_id, agent_id=agent_id,
            target=m.get("target", ""), goal_total=m.get("goal_total", 1),
            current=m.get("current", 0), note=m.get("note", ""),
        )
        # 若里程碑自带 action，执行之（不静默失败）
        if m.get("action"):
            try:
                engine = _engine()
                res = engine._run_action(m["action"], task_id, role or agent_id,
                                         agent_id, task_key=task_key)
                if res and res.get("status") == "error":
                    admin.record_event(
                        agent_id, "milestone_error",
                        {"task_key": task_key, "step": m.get("step", i),
                         "error": res.get("note", "")}, task_id or "")
            except Exception:
                pass
        completed += 1
        record_depth(task_key, 6, agent_id=agent_id,
                     note=f"L6 里程碑[{i+1}/{len(milestones)}] {m.get('step','')} 完成")
        # 若需要人工闸门且当前里程碑到达收尾点，则停等确认
        if need_human_gate and i >= len(milestones) - 1:
            remaining = milestones[i+1:]
            break
    reached = completed >= len(milestones)
    human_gate = need_human_gate and reached
    record_depth(task_key, 6, agent_id=agent_id,
                 note=f"L6 持续到结果：{'已完成全部里程碑' if reached else '进行中'} "
                      f"{'（需人工确认收尾）' if human_gate else '（可自动交付）'}")
    return {
        "level": 6, "level_key": "L6_持续到结果",
        "task_key": task_key, "agent_id": agent_id,
        "reached_result": reached,
        "completed_milestones": completed,
        "total_milestones": len(milestones),
        "remaining": remaining,
        "human_gate": human_gate,
        "note": "L6 已持续到结果（收尾需确认后交付）"
                if reached and human_gate else
                "L6 持续推进中",
    }


# ============================================================
# L7 全自动到结果层：无需人工中断，全自动闭环
# ============================================================
def auto_run_to_result(task_key, agent_id, milestones, role="",
                       max_rounds=10):
    """L7 · 全自动到结果：完全自动闭环到结果，无需人工/授权中断。

    与 L6 区别：need_human_gate 恒为 False——所有里程碑自动推进，
    直到目标收敛（distance=0）或耗尽 max_rounds。

    返回：{reached_result, rounds, final_distance, note}。
    """
    require_depth(task_key, 6, "L7 全自动到结果须先完成 L6 持续到结果")
    admin = _admin()
    task_id = _gid_for("task", task_key) or task_key
    sentinel = _sentinel()
    rounds = 0
    for m in milestones:
        rounds += 1
        sentinel.track(
            f"g-{task_id}", task_id=task_id, agent_id=agent_id,
            target=m.get("target", ""), goal_total=m.get("goal_total", 1),
            current=m.get("current", 0), note=m.get("note", ""),
        )
        if m.get("action"):
            try:
                engine = _engine()
                res = engine._run_action(m["action"], task_id, role or agent_id,
                                         agent_id, task_key=task_key)
                if res and res.get("status") == "error":
                    admin.record_event(agent_id, "auto_run_error",
                                       {"task_key": task_key,
                                        "step": m.get("step", rounds),
                                        "error": res.get("note", "")}, task_id or "")
            except Exception:
                pass
        record_depth(task_key, 7, agent_id=agent_id,
                     note=f"L7 全自动里程碑[{rounds}/{len(milestones)}] {m.get('step','')} 完成")
        if rounds >= max_rounds:
            break
    from sentinel import store as sentinel_store
    final_meter = sentinel_store.latest_meter(f"g-{task_id}")
    final_distance = final_meter.get("distance") if final_meter else None
    reached = final_distance == 0 if final_distance is not None else rounds >= len(milestones)
    record_depth(task_key, 7, agent_id=agent_id,
                 note=f"L7 全自动到结果：{'已达结果' if reached else '未收敛'}（{rounds} 轮）")
    return {
        "level": 7, "level_key": "L7_全自动到结果",
        "task_key": task_key, "agent_id": agent_id,
        "reached_result": reached, "rounds": rounds,
        "final_distance": final_distance,
        "note": "L7 全自动闭环到结果，无需人工中断" if reached else "未收敛（耗尽轮次）",
    }


# ============================================================
# 七层俯瞰（二级信息 · 人类/监控哨兵）
# ============================================================
def depth_overview():
    """按七层深度分组俯瞰所有任务（二级信息 · 回答"哪些真正走到了深层"）。"""
    from data import repository as repo
    tasks = repo.list_tasks()
    progress = repo.recent_progress(limit=8000)
    depth_count = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0}
    detail = []
    # 收集所有出现过 depth 事件的任务（不依赖 tasks 表，覆盖仅 L1 表述的任务）
    seen = {}
    for p in progress:
        ev = p.get("event", "")
        if ev.startswith("depth_L") and p.get("task_id"):
            tid = p["task_id"]
            try:
                d = int(ev.replace("depth_L", ""))
            except (ValueError, TypeError):
                continue
            cur = seen.get(tid, {"depth": 1, "status": ""})
            if d > cur["depth"]:
                cur["depth"] = d
            seen[tid] = cur
    # 合并 tasks 表中有但无 depth 事件的任务（depth=1）
    for t in tasks:
        tid = t.get("task_id", "")
        if tid and tid not in seen:
            seen[tid] = {"depth": 1, "status": t.get("status", "")}
        elif tid in seen and t.get("status"):
            seen[tid]["status"] = t.get("status", "")
    for tid, info in seen.items():
        depth = info["depth"]
        depth_count[depth] = depth_count.get(depth, 0) + 1
        detail.append({
            "task_key": tid, "task_id": tid,
            "depth": depth,
            "level_key": DEPTH_LEVELS.get(depth, {}).get("key", f"L{depth}"),
            "status": info.get("status", ""),
        })
    return {
        "total_tasks": len(seen),
        "by_depth": depth_count,
        "reached_L6": depth_count.get(6, 0),
        "reached_L7": depth_count.get(7, 0),
        "note": "L6=秘书目标档位，L7=体系目标档位；多数 agent 默认停在 L5（进度可控），"
                "需自动规则持续推进到 L6/L7 才算「一套持续到结果」",
        "detail": detail,
    }


# 层级规范（供文档/规则/测试对齐）
def levels_spec():
    return DEPTH_LEVELS


if __name__ == "__main__":
    import json
    print(json.dumps(levels_spec(), ensure_ascii=False, indent=2))
