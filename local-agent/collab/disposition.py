# -*- coding: utf-8 -*-
"""
collab · 统一审查处置标签引擎（disposition）
==============================================
「审查机制」的**统一处置标签**核心：把"评审/决策点到底该怎么处理"收敛为一套
**规范、稳定、强制**的标签体系，替代过去"有些加、有些不加、触发不稳定"的零散
action/信号。

对齐用户口径（Issue #31 本轮需求）：
  - 审查机制里的处置情况应**统一全加标签**：适合合并 / 适合推进 / 适合改bug /
    适合调研 / 适合移交人类判断 / 适合专家会诊 / 适合投票 等；
  - **触发要稳定**——不是"有时候加有时候不加"，而是**任何一次审查/决策点都必须
    输出一个处置标签**（强制、可被机器核验）；
  - 按标签**额外设计自动化流程**——每个标签路由到一个确定的后续动作；
  - 有说明文档 + 规则文件控制，让功能**稳定可靠、可被读取理解、相同协作**。

设计要点：
  - `DISPOSITION_LABELS` 是**唯一规范来源（single source of truth）**，引擎与
    文档、规则、测试都从这里对齐，杜绝漂移；
  - `dispose()` 是**确定性分类器**：给定"严重级 + 触发信号 + 场景"，**必然返回
    一个规范标签**（无法判定时落到 `proceed` 兜底，也保证恒有标签）；
  - `route()` 把每个标签路由到对应自动化流程（含 peer / decisions / human_gate /
    peer_guard / 评审打回），与既有 peer collab 收尾闭环无缝衔接；
  - 与「架构·评审」输出契约强制绑定：评审必须带 `disposition` 字段。

处置标签全集（label / 含义 / 引擎动作 / 下游自动化流程）：
  - merge        适合合并     → 方案成熟、评审通过        → 合并确认(CP3)/放行
  - proceed      适合推进     → 可行、继续执行            → 继续开发/回小组长整合
  - fix_bug      适合改bug    → 评审发现 🔴必修缺陷       → 打回开发修复([回转])
  - research     适合调研     → 信息不足、需调研          → 路由调研/外部探索(L2)
  - human        适合移交人类  → 需担责/必要成本决策       → 打开人类拍板闸门(human_gate)
  - consult      适合专家会诊 → 疑难/对错难辨/多项解决不掉 → 专家会诊(peer.expert_consult)
  - vote         适合投票     → 意见多重/需集体决策        → 共识表决(peer.consensus_judge)
"""
import json
import uuid

try:
    from data import admin, db
except Exception:  # noqa: BLE001
    admin = None
    db = None

# ======================================================================
# ① 唯一规范来源：处置标签全集 + 元信息
# ======================================================================
DISPOSITION_LABELS = {
    # label -> { name, action(引擎动作), route(下游自动化流程), when(触发语义) }
    "merge": {
        "name": "适合合并",
        "action": "merge",
        "route": "merge_release",
        "when": "方案成熟、评审通过、无🔴必修，可进入合并/发布放行",
    },
    "proceed": {
        "name": "适合推进",
        "action": "proceed",
        "route": "proceed_develop",
        "when": "方案可行、风险可控，继续执行/继续开发，回小组长整合",
    },
    "fix_bug": {
        "name": "适合改bug",
        "action": "fix",
        "route": "revert_to_develop",
        "when": "评审发现 🔴必修 缺陷，需打回开发修复（[回转]）",
    },
    "research": {
        "name": "适合调研",
        "action": "research",
        "route": "external_explore",
        "when": "信息不足、方案未定，需调研/外部探索（L2 开放探索型）",
    },
    "human": {
        "name": "适合移交人类判断",
        "action": "human",
        "route": "human_gate",
        "when": "需担责/必要成本决策，结果前置叫人类拍板（human_gate）",
    },
    "consult": {
        "name": "适合专家会诊",
        "action": "consult",
        "route": "expert_consult",
        "when": "疑难/对错难辨/多项方案都解决不掉，走专家会诊",
    },
    "vote": {
        "name": "适合投票",
        "action": "vote",
        "route": "consensus_vote",
        "when": "意见多重、需集体决策/共识表决（peer.consensus_judge）",
    },
    # 阶段链门控驳回专用（Issue #150 复评 N3）：**非放行**标签。
    # 语义＝「链条本该按序推进，此刻这一环被门控驳回」——不是质量结论、也不是放行，
    # 故**不得**映射到 merge/proceed（那会真转交测试、给假绿）。用途：驳回时明确表达
    # "等上游收口后按链推进"，替代此前误映射的 `proceed`（它 ∈ PASS_DISPOSITIONS）。
    "blocked": {
        "name": "链式未推进·待上游收口",
        "action": "block",
        "route": "resume_chain",
        "when": "阶段链门控驳回（上游未收口=抢跑 / 本阶段重复触发 / 回头补上游=乱序），"
                "需等上游按链条收口后再推进（非终局、非放行）",
    },
}

# 规范标签的稳定顺序（文档/看板/测试据此对齐）
DISPOSITION_ORDER = ["merge", "proceed", "fix_bug", "research",
                     "human", "consult", "vote", "blocked"]


# ======================================================================
# ② 确定性分类器：任何审查/决策点必然给出一个规范标签（稳定触发）
# ======================================================================
# 严重级：reviewer 分级（🔴必修 / 🟡建议 / 🟢优化）
_SEV = {"red": "fix_bug", "yellow": "proceed", "green": "merge"}
# 触发信号 → 处置标签（复用 peer 触发门控信号，映射到处置标签）
_SIGNAL_LABEL = {
    "skill_gap": "research",     # 专长缺口 → 需调研/补位调研
    "stall": "research",         # 卡点停滞 → 需调研/换道
    "high_risk": "consult",      # 高风险 → 专家会诊
    "hard": "consult",           # 疑难 → 专家会诊
    "dispute": "vote",           # 意见对错难辨 → 投票/会诊表决
    "scale_up": "proceed",       # 加量 → 推进（扩员继续）
    "needs_human": "human",      # 需人类担责 → 移交人类判断
    "defect": "fix_bug",         # 发现缺陷 → 改bug
    "undecided": "research",     # 方案未定/信息不足 → 调研
    "": "proceed",               # 无信号兜底 → 推进
}


def valid_labels():
    """返回全部规范标签（文档/规则/测试对齐用）。"""
    return list(DISPOSITION_ORDER)


def valid_label(label):
    """校验某标签是否为规范标签。非规范返回 False。"""
    return label in DISPOSITION_LABELS


def require_label(label):
    """强制：非规范标签直接抛错——保证标签不会被"加错/漏加"。

    用途：审查/决策点调用前先校验，确保输出契约恒为规范标签。
    """
    if not valid_label(label):
        raise ValueError(
            f"[disposition] 非规范处置标签 '{label}'。规范集合：{valid_labels()}"
        )
    return label


def resolve_label(action=None, signals=None, severity=None):
    """把"既有 action/信号/严重级"映射回规范处置标签。

    用于把旧链路（reroute/backup/escalate/adopt/consult/single）归一化到
    统一标签，实现"统一全加、不再各叫各的"。

    参数:
      action: 既有引擎动作（reroute/backup/escalate/human/adopt/consult/vote/proceed/fix/research/merge）
      signals: 触发信号列表（skill_gap/stall/high_risk/hard/dispute/scale_up/needs_human/defect/undecided）
      severity: 评审严重级（red/yellow/green/🔴/🟡/🟢）
    返回: 规范标签（恒非空）
    """
    # 1) 严重级优先（评审分级是强信号）
    if severity:
        sev = str(severity).strip()
        if sev in _SEV:
            return _SEV[sev]
        if "🔴" in sev or "red" in sev.lower():
            return "fix_bug"
        if "🟡" in sev or "yellow" in sev.lower():
            return "proceed"
        if "🟢" in sev or "green" in sev.lower():
            return "merge"
    # 2) 既有 action 映射
    if action:
        amap = {
            "merge": "merge", "release": "merge",
            "proceed": "proceed",
            "fix": "fix_bug", "fix_bug": "fix_bug", "revert": "fix_bug",
            "research": "research",
            "human": "human",
            "consult": "consult",
            "vote": "vote", "adopt": "merge",
            "escalate": "human", "reroute": "research", "backup": "proceed",
        }
        if action in amap:
            return amap[action]
    # 3) 触发信号映射（consult/vote 信号优先级高于 research/proceed）
    if signals:
        sig_list = list(signals) if isinstance(signals, list) else [signals]
        for s in sig_list:
            if s in ("hard", "high_risk"):
                return "consult"
        for s in sig_list:
            if s in ("dispute",):
                return "vote"
        for s in sig_list:
            if s in _SIGNAL_LABEL:
                return _SIGNAL_LABEL[s]
    # 4) 兜底：恒返回一个规范标签（保证"必有标签、稳定触发"）
    return "proceed"


def dispose(problem="", action=None, signals=None, severity=None,
            scenario_hint="", requires_human=False, label=None):
    """审查/决策点统一处置判定：**必然返回一个规范处置标签 + 自动化流程**。

    这是"统一全加 + 稳定触发"的强制入口——任何审查结论、任何决策点，
    都应调用本函数得到处置标签，而不是各自随便写。

    参数:
      problem: 被处置的问题/方案
      action: 既有引擎动作（可空）
      signals: 触发信号（可空）
      severity: 评审严重级（可空）
      scenario_hint: 场景提示（可命中"合并/调研/会诊/投票/交人"等语义）
      requires_human: 是否需人类担责（强制 human）
      label: 显式指定的规范标签（可选）；给出时**严格校验**，非规范即报错
    返回: { problem, disposition(规范标签), label_name, action, route, reason, flow }
    """
    # 显式标签优先且严格校验（防"加错标签"）
    if label is not None:
        require_label(label)
        meta = DISPOSITION_LABELS[label]
        return {
            "problem": problem,
            "disposition": label,
            "label_name": meta["name"],
            "action": meta["action"],
            "route": meta["route"],
            "reason": meta["when"],
            "flow": route(label, problem=problem),
        }
    # 需人类担责 → 恒 human（最高优先）
    if requires_human:
        label = "human"
    else:
        label = resolve_label(action=action, signals=signals, severity=severity)
        # 场景语义提示兜底（若上述均未命中且 hint 明确）
        if scenario_hint:
            hint_label = _hint_to_label(scenario_hint)
            if hint_label is not None:
                label = hint_label
    require_label(label)
    meta = DISPOSITION_LABELS[label]
    return {
        "problem": problem,
        "disposition": label,
        "label_name": meta["name"],
        "action": meta["action"],
        "route": meta["route"],
        "reason": meta["when"],
        "flow": route(label, problem=problem),
    }


def _hint_to_label(hint):
    """场景提示 → 处置标签（语义关键词命中）。"""
    h = str(hint).strip()
    if not h:
        return None
    if any(k in h for k in ("合并", "发布", "release", "merge")):
        return "merge"
    if any(k in h for k in ("改bug", "缺陷", "必修", "fix", "bug", "缺陷修复")):
        return "fix_bug"
    if any(k in h for k in ("调研", "信息不足", "未定", "research", "探索", "竞品")):
        return "research"
    if any(k in h for k in ("移交", "人类", "拍板", "担责", "human", "决策")):
        return "human"
    if any(k in h for k in ("会诊", "疑难", "consult", "对错难辨")):
        return "consult"
    if any(k in h for k in ("投票", "表决", "vote", "共识", "意见多重")):
        return "vote"
    return None


# ======================================================================
# ③ 按标签的自动化流程（route）—— 每个标签路由到确定下游动作
# ======================================================================
def route(label, problem="", task_id="", cohort_id="", **kwargs):
    """按处置标签返回自动化流程描述 + 需驱动的引擎动作。

    返回: {
      label, action, downstream, handoff(承接方), steps[..],
      human_gate(是否需人类拍板), consult(是否走会诊), vote(是否走表决),
      revert_to(是否打回给谁), explore(是否走外部探索), merge(是否合并放行)
    }
    """
    require_label(label)
    meta = DISPOSITION_LABELS[label]
    base = {
        "label": label,
        "label_name": meta["name"],
        "action": meta["action"],
        "downstream": meta["route"],
        "problem": problem,
    }
    flow = dict(base)
    if label == "merge":
        flow.update({
            "handoff": "经理/评审",
            "human_gate": True,          # 合并需人类确认（CP3）
            "merge": True,
            "steps": ["评审🔴清零", "验收通过", "合并确认(CP3)", "放行/发布"],
        })
    elif label == "proceed":
        flow.update({
            "handoff": "开发/小组长",
            "proceed": True,
            "steps": ["继续执行/继续开发", "回小组长整合", "推进到下一检查点"],
        })
    elif label == "fix_bug":
        flow.update({
            "handoff": "架构·开发",
            "revert_to": "开发",
            "revert": True,
            "steps": ["标🔴必修缺陷", "[回转]退回开发修复", "复评清零后放行"],
        })
    elif label == "research":
        flow.update({
            "handoff": "调研专员/架构·总师助理",
            "explore": True,             # L2 开放探索
            "steps": ["明确调研问题", "外部探索(开源/插件/skill/论文)",
                      "命中且零负面→自决采用；否则→结果前置交人"],
        })
    elif label == "human":
        flow.update({
            "handoff": "人类(用户)",
            "human_gate": True,
            "steps": ["结果前置打开人类拍板闸门(human_gate)",
                      "列清风险点/因果对齐", "人类拍板后放行/否决"],
        })
    elif label == "consult":
        flow.update({
            "handoff": "同岗编队(cohort)",
            "consult": True,
            "steps": ["触发专家会诊(peer.expert_consult)",
                      "各自从专长角度给结论+留理由",
                      "收敛→放行；未收敛→审核者前置助手→人类"],
        })
    elif label == "vote":
        flow.update({
            "handoff": "同岗编队(cohort)",
            "vote": True,
            "steps": ["触发共识表决(peer.consensus_judge)",
                      "按收敛判定(2~3人无否决/4+人≥2/3)",
                      "未共识→显式上报小组长→总师→人类"],
        })
    elif label == "blocked":
        flow.update({
            "handoff": "上游阶段（按链回退一环）",
            "blocked": True,
            "proceed": False,      # 明确：**非放行**
            "revert": False,       # 明确：不是质量结论，不打回开发返工
            "steps": ["阶段链门控驳回（抢跑/重复/乱序）",
                      "本轮零构建（dispatched=False）",
                      "等上游阶段收口 → 按链重新推进（不假绿放行、不转交测试）"],
        })
    return flow


def route_for_review(problem="", severity=None, signals=None, scenario_hint=""):
    """评审专用便捷入口：给定严重级/信号/场景 → 处置标签 + 自动化流程。

    供「架构·评审」输出契约使用，保证评审结论恒带规范处置标签。
    """
    return dispose(problem=problem, severity=severity, signals=signals,
                   scenario_hint=scenario_hint)


# ======================================================================
# ④ 留痕：处置标签落库（统一口径，供看板/审计）
# ======================================================================
def record_disposition(problem="", label="", task_id="", cohort_id="",
                       reviewer="", detail=None, source="review"):
    """把一次审查处置留痕到 archives（kind='disposition'），供审计/俯瞰。

    这是"统一全加"的可回溯保证——每次审查都留一条处置标签记录。
    """
    require_label(label)
    archive_id = f"dp-{uuid.uuid4().hex[:12]}"
    content = {
        "disposition_id": archive_id,
        "problem": problem,
        "disposition": label,
        "label_name": DISPOSITION_LABELS[label]["name"],
        "route": DISPOSITION_LABELS[label]["route"],
        "task_id": task_id,
        "cohort_id": cohort_id,
        "reviewer": reviewer,
        "detail": detail or {},
        "created_at": _now(),
    }
    if admin is not None:
        admin.archive(archive_id, "disposition",
                      f"[处置:{DISPOSITION_LABELS[label]['name']}] {problem[:40]}",
                      content, source)
    return content


def disposition_overview():
    """处置标签全局俯视图（二级信息，供人类/经理/哨兵监控）。

    统计各标签的出现次数，便于看"审查结论是否覆盖所有处置路径、有无失衡"。
    """
    labels = {lbl: 0 for lbl in DISPOSITION_ORDER}
    if admin is not None:
        try:
            archs = admin.repo.list_archives(kind="disposition", limit=1000)
            for a in archs:
                c = a.get("content") or {}
                if isinstance(c, str):
                    try:
                        c = json.loads(c)
                    except Exception:  # noqa: BLE001
                        c = {}
                lbl = c.get("disposition")
                if lbl in labels:
                    labels[lbl] += 1
        except Exception:  # noqa: BLE001
            pass
    return {
        "total": sum(labels.values()),
        "by_label": labels,
        "order": DISPOSITION_ORDER,
    }


def spec():
    """机器可读的规范（规则文件）：供文档/规则/测试一致性断言对齐。"""
    return {
        "labels": DISPOSITION_ORDER,
        "names": {lbl: DISPOSITION_LABELS[lbl]["name"] for lbl in DISPOSITION_ORDER},
        "actions": {lbl: DISPOSITION_LABELS[lbl]["action"] for lbl in DISPOSITION_ORDER},
        "routes": {lbl: DISPOSITION_LABELS[lbl]["route"] for lbl in DISPOSITION_ORDER},
    }


def _now():
    return db.now_iso() if db is not None else ""
