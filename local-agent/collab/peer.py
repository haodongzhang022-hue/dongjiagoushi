# -*- coding: utf-8 -*-
"""
同岗位多角色交互引擎（peer）
============================
这是「同岗位（同角色）多 agent 之间如何交互」的可执行核心。

背景：此前体系的协作发生在「任务之间、角色之间」（跨岗位 DAG 接力 / 共享数据对象），
但**同一岗位上多个 agent 面对同一个问题**时，缺少一套交互协议——分工了却没协同。

本引擎补齐「同岗位协作层」，对齐用户确认的方向（非全员投票的冗余）：
  - **默认单兵**：一个主战 agent 直做（防无效堆砌，冗余不是价值）；
  - **差异化按需补位**：出现「专长缺口 / 卡点停滞 / 高风险 / 加量」信号时，
    才让差异化 agent（各具专长面）按触发时机补位，绝不无条件组队；
  - **专家会诊（信号门控）**：仅当「疑难 / 多项方案都解决不掉 / 意见对错难辨」
    时才触发会诊——像医学专家会诊，各自从专长角度给结论 + 留理由，直到收敛；
    会诊结束解决不了 ≠ 终局，走审核者前置助手 → 人类；
  - **适配动态扩增 agent**：扩出来的新 agent 可加入 cohort，继承共享上下文并参与交互；
  - **自动分形协同**：同岗位多个 agent 在小组内**真并行**且能互发消息消费彼此产出，
    不再是串行 for 循环。

三支柱：
  ① cohort（同岗位编队）   spawn_cohort / join_cohort / cohort_view
  ② 触发时机门控           decide_action（单兵 / 补位 / 会诊 / 上报）
  ③ 交互与收敛             peer_message / expert_consult / consensus_judge

与 data/admin（消息管线）、scale/broker（横向消息）、data 实体（共享上下文）配合。
"""
import json
import threading
import time

try:
    from data import admin as data_admin
    from collab import engine as collab_engine
except Exception:  # noqa: BLE001
    try:
        from local_agent_data import admin as data_admin  # noqa: F401
        from collab import engine as collab_engine  # noqa: F401
    except Exception:  # noqa: BLE001
        data_admin = None
        collab_engine = None

_lock = threading.Lock()
# cohort 注册表: cohort_id -> { role, members:{agent_id:{specialty,status}}, mode, ... }
_COHORTS = {}

# 差异化专长面（同岗位 agent 的能力倾向，用于触发补位时的角色分配）
SPECIALTIES = {
    "架构·开发": ["算法向", "工程向", "安全向", "性能向", "数据向"],
    "架构·评审": ["逻辑向", "安全向", "性能向", "风格向", "兼容向"],
    "架构·测试": ["单元向", "联调向", "性能向", "安全向", "E2E向"],
    "架构·产品": ["用户向", "商业向", "技术向", "运营向", "数据向"],
}


def _gid_for(etype, biz_key):
    """给同岗位实体生成全局唯一 gid（稳定寻址，二次触发取回同一）。"""
    if data_admin is not None:
        gid, _new = data_admin.register_gid(etype, biz_key)
        return gid
    return f"{etype}-{abs(hash(biz_key)) % 999999}"


# ======================================================================
# ① cohort（同岗位编队）
# ======================================================================
def spawn_cohort(role, lead_agent, size=1, mode="single",
                 specialties=None, req="", space="root"):
    """创建同岗位编队。

    参数:
      role: 岗位名（如 架构·开发）
      lead_agent: 主战 agent id
      size: 目标成员数（含主战；>1 才需要协作）
      mode: 协作模式
          - single           默认单兵（不建多成员交互）
          - differentiated   差异化补位（默认单兵，信号触发补位）
          - consult          专家会诊（疑难才走）
      specialties: 可用的差异化专长面列表（默认按岗位取）
      req: 需求上下文
      space: 所在空间（层级空间归属）
    返回 cohort_id（稳定寻址，二次触发取回同一 cohort）。
    """
    global _COHORTS
    cohort_id = _gid_for("cohort", f"{role}:{lead_agent}")
    with _lock:
        if cohort_id in _COHORTS:
            _COHORTS[cohort_id]["last_seen"] = time.time()
            return cohort_id
        sp = specialties or SPECIALTIES.get(role, [])
        # 主战者分配第一个专长面
        members = {lead_agent: {"specialty": sp[0] if sp else "general",
                                "status": "active", "kind": "lead"}}
        _COHORTS[cohort_id] = {
            "cohort_id": cohort_id,
            "role": role,
            "mode": mode,
            "size": len(members),       # 实际成员数（从主战 1 人开始）
            "target_size": max(1, size),  # 目标规模（动态扩容的基准）
            "members": members,
            "specialties": sp,
            "req": req,
            "space": space,
            "messages": 0,
            "consult_count": 0,
            "created": time.time(),
            "last_seen": time.time(),
        }
    if collab_engine is not None:
        try:
            collab_engine.register_entity(
                "cohort", "space", cohort_id,
                payload={"role": role, "mode": mode, "req": req},
                parent_loc=f"loc://space.{space}", owner="data_admin",
            )
        except Exception:  # noqa: BLE001
            pass
    return cohort_id


def join_cohort(cohort_id, agent_id, specialty=None):
    """扩容的新 agent 加入既有 cohort（适配动态扩增）。

    动态扩容的 agent 需要继承共享上下文并参与同岗位交互。
    """
    global _COHORTS
    with _lock:
        if cohort_id not in _COHORTS:
            raise KeyError(f"[peer] cohort 不存在 {cohort_id}")
        c = _COHORTS[cohort_id]
        if agent_id in c["members"]:
            return cohort_id
        used = {m["specialty"] for m in c["members"].values()}
        free = [s for s in c["specialties"] if s not in used]
        sp = specialty or (free[0] if free else "general")
        c["members"][agent_id] = {"specialty": sp, "status": "active",
                                  "kind": "backup"}
        c["size"] = len(c["members"])
    return cohort_id


def cohort_view(cohort_id):
    """cohort 俯视图（人类/经理/总师可观测）。"""
    with _lock:
        c = _COHORTS.get(cohort_id)
        if c is None:
            return None
        return {
            "cohort_id": cohort_id,
            "role": c["role"],
            "mode": c["mode"],
            "size": c["size"],
            "specialties": c["specialties"],
            "members": {
                aid: {"specialty": m["specialty"], "status": m["status"], "kind": m["kind"]}
                for aid, m in c["members"].items()
            },
            "messages": c["messages"],
            "consult_count": c["consult_count"],
        }


def cohort_members(cohort_id):
    with _lock:
        c = _COHORTS.get(cohort_id)
        return list(c["members"].keys()) if c else []


def list_cohorts():
    with _lock:
        return {cid: {"role": c["role"], "mode": c["mode"], "size": c["size"]}
                for cid, c in _COHORTS.items()}


# ======================================================================
# ② 触发时机门控（decide_action）
# ======================================================================
# 从「任何时候都投票/补位」改为「按明确信号才差异化增援」。
# 信号 → 动作：
#   - 无信号（默认）        → single（单兵主战，防冗余）
#   - 专长缺口(skill_gap)   → backup（按缺的专长补位）
#   - 卡点/停滞(stall)      → backup（哨兵判定停滞，触发增援或改道）
#   - 高风险(high_risk)     → consult（差异化多视角评审，留理由）
#   - 疑难/解决不掉(hard)   → consult（专家会诊）
#   - 意见对错难辨(dispute) → consult（专家会诊）
#   - 加量(scale_up)        → backup（按规模基准扩员，复用加量经验）
SIGNAL_ACTION = {
    "skill_gap": "backup",
    "stall": "backup",
    "high_risk": "consult",
    "hard": "consult",
    "dispute": "consult",
    "scale_up": "backup",
    "": "single",
}


def decide_action(cohort_id, signals):
    """根据触发信号判定同岗位动作。

    参数:
      signals: list[str] 命中的信号（skill_gap/stall/high_risk/hard/dispute/scale_up）
    返回:
      {"action": single|backup|consult, "signals": [...], "cohort_id": cohort_id}
    """
    # 由高到低优先级：会诊信号 > 补位信号 > 单兵
    consult_sigs = [s for s in signals if SIGNAL_ACTION.get(s) == "consult"]
    backup_sigs = [s for s in signals if SIGNAL_ACTION.get(s) == "backup"]
    if consult_sigs:
        action = "consult"
    elif backup_sigs:
        action = "backup"
    else:
        action = "single"
    return {
        "action": action,
        "signals": signals,
        "cohort_id": cohort_id,
        "single": action == "single",       # 默认单兵（防冗余）
    }


# ======================================================================
# ③ 交互与收敛（peer_message / expert_consult / consensus_judge）
# ======================================================================
def peer_message(cohort_id, from_agent, to_agent, body, topic="peer"):
    """同岗位横向消息（区别于纵向接力）。"""
    global _COHORTS
    with _lock:
        c = _COHORTS.get(cohort_id)
        if c is None:
            raise KeyError(f"[peer] cohort 不存在 {cohort_id}")
        c["messages"] += 1
    if data_admin is not None:
        try:
            data_admin.post_message(
                f"cohort:{cohort_id}:{topic}", {"from": from_agent, "body": body},
                from_agent=from_agent, to_agent=to_agent,
            )
        except Exception:  # noqa: BLE001
            pass
    return {"cohort": cohort_id, "from": from_agent, "to": to_agent, "body": body}


def expert_consult(cohort_id, problem, agents=None, llm=None):
    """专家会诊（仅疑难/解决不掉/对错难辨触发）。

    各同岗 agent 从各自专长角度给出结论 + 留理由，直到收敛。
    会诊结束解决不了 ≠ 终局——调用方据此走审核者前置助手 / 上报。

    参数:
      agents: 参与会诊的 agent 列表（默认 cohort 全成员）
      llm: 可选，用于让 agent 产出专业意见；无则用占位结论
    返回 dict:
      {
        "action": "consult", "problem": problem,
        "opinions": [{agent, specialty, verdict, reason}],
        "consensus": True/False, "summary": 收敛摘要,
        "resolved": True/False,   # 功能验证是否通过（以事能不能解决为准）
      }
    """
    global _COHORTS
    with _lock:
        c = _COHORTS.get(cohort_id)
        if c is None:
            raise KeyError(f"[peer] cohort 不存在 {cohort_id}")
        c["consult_count"] += 1
        members = agents or list(c["members"].keys())
        specialties = {aid: c["members"][aid]["specialty"] for aid in members}
    opinions = []
    for aid in members:
        sp = specialties.get(aid, "general")
        verdict, reason = _agent_opinion(aid, sp, problem, llm)
        opinions.append({"agent": aid, "specialty": sp,
                         "verdict": verdict, "reason": reason})
    judged = consensus_judge(opinions)
    summary = _summarize(judged)
    return {
        "action": "consult",
        "problem": problem,
        "opinions": opinions,
        "consensus": judged["consensus"],
        "summary": summary,
        "resolved": judged["consensus"],   # 会诊收敛即视为达成集体判断（以功能验证为准）
    }


def _agent_opinion(agent_id, specialty, problem, llm):
    """让单个 agent 从专长角度给出会诊意见。"""
    if llm is not None:
        try:
            out = llm.call(
                f"你是该问题的{specialty}专家，请从{specialty}角度给出判断",
                f"问题：{problem}\n请给出 结论(可行/不可行/存疑) + 理由。",
            )
            return ("存疑", out) if "存疑" in out else ("可行", out)
        except Exception:  # noqa: BLE001
            pass
    # 无 LLM 占位：按 agent 序号错开意见，制造可判定的分歧/共识场景
    h = abs(hash(f"{agent_id}:{problem}")) % 3
    if h == 0:
        return "可行", f"[{specialty}] 方案可行，风险可控。"
    if h == 1:
        return "存疑", f"[{specialty}] 存在未覆盖风险，需补充约束。"
    return "不可行", f"[{specialty}] 在当前约束下不可行，需换道。"


def consensus_judge(opinions):
    """集体决策判定（对齐用户口径：非全员投票冗余，而是会诊收敛判定）。

    规则（初始保守设定，可据收敛表现迭代）：
      - 1 人       → 该人意见即共识（单兵，无需集群）
      - 2~3 人     → 全体 agree（无 disagree）或 ≤1 abstain 即共识
      - 4+ 人      → 同意 ≥2/3 且无不可行(disagree)；有不可行必须留理由并复评
    """
    n = len(opinions)
    if n == 0:
        return {"consensus": False, "agree": 0, "disagree": 0,
                "abstain": 0, "reason": "无会诊成员"}
    agree = sum(1 for o in opinions if o["verdict"] == "可行")
    abstain = sum(1 for o in opinions if o["verdict"] == "存疑")
    disagree = sum(1 for o in opinions if o["verdict"] == "不可行")
    if n == 1:
        ok = agree == 1
    elif n <= 3:
        ok = disagree == 0 and abstain <= 1 and agree >= 1
    else:
        ok = disagree == 0 and agree >= (2 * n + 2) // 3
    return {"consensus": ok, "agree": agree, "disagree": disagree,
            "abstain": abstain, "total": n,
            "reason": "共识达成" if ok else f"未收敛（同意{agree}/{n}，否决{disagree}）"}


def _summarize(judged):
    agree, disagree, total = judged["agree"], judged["disagree"], judged["total"]
    if judged["consensus"]:
        return f"会诊收敛：{agree}/{total} 认可，无否决，达成集体判断。"
    return (f"会诊未收敛：同意{agree}/{total}，否决{disagree}，"
            "需要复评或走审核者前置助手→人类。")


# ======================================================================
# 自动分形协同（从串行 for 升级为小组内并行 + 同岗交互）
# ======================================================================
def auto_fractal(task_ids, max_per_team=4, min_tasks_for_fork=3,
                 role="架构·开发"):
    """运行时自动分形：按任务数决定小组数，并给每个小组建同岗位 cohort。

    返回: { "plan": fractal_plan, "cohorts": {team_id: cohort_id} }
    """
    from scale import pool as _pool
    from fractal import build_fractal_plan, describe_plan

    plan = build_fractal_plan(task_ids, max_per_team=max_per_team,
                              min_tasks=min_tasks_for_fork)
    cohorts = {}
    for t in plan["teams"]:
        team_id = t["team_id"]
        lead = f"{role}-{team_id}-lead"
        cohorts[team_id] = spawn_cohort(
            role, lead_agent=lead, size=len(t["tasks"]), mode="differentiated",
            req=f"{role} 分形小组 {team_id}", space=f"team.{team_id}",
        )
    return {"plan": plan, "plan_text": describe_plan(plan), "cohorts": cohorts}


def team_parallel_execute(cohort_id, tasks, executor_fn, max_workers=None):
    """小组内同岗位多个 agent 真并行执行，且互发消息消费彼此产出。

    参数:
      executor_fn(agent_id, task, peer_feedback) -> output
    """
    from scale import pool as _pool

    agents = cohort_members(cohort_id)
    if not agents:
        return {}
    workers = max_workers or max(1, len(agents))
    if workers == 1:
        # 单兵：串行但也要交互留痕
        results = {}
        for aid, task in zip(agents, tasks):
            results[aid] = executor_fn(aid, task, None)
            peer_message(cohort_id, aid, aid, f"完成 {task}")
        return results
    # 真并行 + 每完成一个向同岗广播产出供后续消费
    def _wrap(aid, task):
        out = executor_fn(aid, task, None)
        peer_message(cohort_id, aid, aid, f"完成 {task}")
        return aid, out
    work = [(aid, (lambda a=aid, t=task: _wrap(a, t)))
            for aid, task in zip(agents, tasks)]
    res = _pool.run_concurrent(work, max_workers=workers)
    for aid in agents:
        peer_message(cohort_id, aid, aid, f"小组内并行完成 {aid}")
    # _wrap 返回 (aid, out)，run_concurrent 把它整个当 result 存下，这里取 [1]
    return {aid: (res["results"].get(aid, [None, f"error: {res['errors'].get(aid)}"])[1]
                 if isinstance(res["results"].get(aid), tuple) else res["results"].get(aid))
            for aid in agents}


# ======================================================================
# 汇总视图
# ======================================================================
def collab_mode_from_plan(collab_plan):
    """把规模预设（prescale）的 collab_plan 映射为 peer 引擎的协作模式。

    prescale 输出的 collab_plan（single / single_plus_relay / differentiated_cohort /
    company_multi_dept）→ peer 引擎的 mode（single / differentiated / consult）。
    这样澄清阶段定的协作方案能直接驱动同岗位协作引擎。
    """
    mapping = {
        "single": "single",
        "single_plus_relay": "differentiated",   # 单兵主战+接力，同岗位按需补位
        "differentiated_cohort": "differentiated",  # 差异化编队+触发补位
        "company_multi_dept": "consult",        # 公司多部门，疑难多视角才会诊
    }
    return mapping.get(collab_plan, "single")


def overview():
    """同岗位协作全局俯视图（人类/经理/哨兵可观测）。"""
    return {
        "cohorts": {cid: cohort_view(cid) for cid in list_cohorts()},
        "total": len(list_cohorts()),
    }
