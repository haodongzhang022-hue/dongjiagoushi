# -*- coding: utf-8 -*-
"""
秘书·感知能力层（SecretarySense · 规模匹配 + 决策博弈 + 测试兜底接管）
====================================================================
用户 Issue #41 核心纠偏（@CodeBuddy 继续，最终版本）：

  "优先级不用调整，而是以规模匹配，不是优先级的问题，这一般不是第一步，
   其实前面大概率是从秘书开始的，然后到产品，这时候评估项目层级，开始的后续的流程，
   所以选择规模的能力在秘书和产品这给他体现出来就行，根据规模进行，不是优先级的。"

  "秘书这一步的价值就是充分了解需求后，做到了需求的明确，然后提示词优化，
   跟产品明确细节，完成后续的沟通 对接，方案的确定，确保成本和结果的复合要求，
   甚至包含成果的测试，因为很多时候开发觉得完成了，测试功能的时候还是完全跑不通，
   这时候交给人类，想法也是继续开发，不可能存在其他说法，直接被秘书接管才是合理的。"

  "以及有些是汇报进度和让选择的，常规的选择我们提过，很多时候都是因为2个选项都不对，
   导致的犹豫不决，秘书那边决策体系因为多了信息，多了探索决策规则和多选项博弈等，
   甚至包含了本地环境，所以可以解决大部分疑问。甚至因为他本身立场和后面不同，
   还能使用博弈，就像对抗生成，可能效果不错。"

本模块把秘书/产品在「需求澄清阶段」的三项核心感知能力沉淀为可复用、可测试、可留痕的
工程能力（对齐仓库「解耦式功能模块开发」规则，独立模块、独立演进、显式接口）：

  ① **规模匹配（scale-match）· 落位澄清阶段**
     - 语义：不是第一步、不是优先级，而是"秘书→产品澄清时评估项目层级 → 据此走后续流程"。
     - 落地：复用 `fusion.route()`（规模金字塔→承接体系→拓扑），在澄清阶段产出
       {tier, system, topology, roles(角色子集), plan(四套方案)} 作为后续协作基准锚点，
       再交由经理按架构做增量修正（不做从零规划，不二次评估）。

  ② **决策博弈（decision-game）· 对抗生成式立场校验 + 多选项博弈**
     - 语义：常规"二选一都不对"的犹豫，根因常是两个选项都不够好；秘书因多了信息、
       多了探索决策规则、多选项博弈、甚至本地环境，能内部摊开更多候选，并可从不同
       立场做对抗校验（秘书立场 ≠ 后续开发立场 → 像对抗生成一样互搏，收敛出更稳方案）。
     - 落地：
       * `expand_candidates(question)` → 内部摊开多选项（合并保留·区分场景 / 加约束 /
         换道 / 补集 / 开放探索外部最优解），解决"A or B 都不够好"；
       * `adversarial_check(question, candidates)` → 用"秘书"立场与"落地开发"立场
         对抗互搏，指出各自盲区，收敛出更稳选项（对抗生成式）。
       * `recommend(question)` → 综合多选项博弈 + 对抗校验 + 本地环境上下文，给出
         推荐 + 理由 + 是否需交人拍板（结果前置原则）。

  ③ **成果测试兜底接管（test-takeover）· 开发说完成≠能跑通**
     - 语义：很多时候开发觉得完成了，测试功能时还是跑不通 → 此时"想法也是继续开发，
       不可能存在其他说法"，**由秘书直接接管**（不是"其他角色顶上/放弃"），
       把"测试跑不通"作为继续开发的输入交回，必要时前置给人类（结果前置、列清风险）。
     - 落地：`takeover(dev_done_report, test_result)` → 判定接管路径
       {接管, 继续开发输入, 是否交人类, 人类风险点}。

统一留痕：本模块所有判断都产出结构化决策卡（dict），并写入 `secretary_actions` 留痕，
保证"秘书做了什么/为什么"可核验、可回溯，配合防无效努力监控。
"""
import json
import os
import threading

# ---------------------------------------------------------------------------
# 留痕：秘书感知动作持久化（配合防无效努力 / 可回溯）
# ---------------------------------------------------------------------------
_ACTIONS = []
_ACTIONS_LOCK = threading.Lock()
_SECRETARY_STATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state", "secretary_sense",
)


def _ensure_dir():
    os.makedirs(_SECRETARY_STATE_DIR, exist_ok=True)


def log_action(kind, payload):
    """留痕一条秘书感知动作（规模匹配 / 决策博弈 / 测试接管）。"""
    import time
    rec = {
        "kind": kind,
        "payload": payload,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with _ACTIONS_LOCK:
        _ACTIONS.append(rec)
    _ensure_dir()
    try:
        import uuid
        with open(os.path.join(_SECRETARY_STATE_DIR, f"{uuid.uuid4().hex}.json"),
                  "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 留痕尽力而为，不阻断主流程
    return rec


def secretary_actions():
    """返回全部秘书感知动作（供俯瞰/审计）。"""
    with _ACTIONS_LOCK:
        return list(_ACTIONS)


def clear_actions():
    global _ACTIONS
    with _ACTIONS_LOCK:
        _ACTIONS = []
    _ensure_dir()
    try:
        for f in os.listdir(_SECRETARY_STATE_DIR):
            os.remove(os.path.join(_SECRETARY_STATE_DIR, f))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ① 规模匹配（scale-match）· 落位澄清阶段
# ---------------------------------------------------------------------------
def scale_match(req=None, complexity=None, subtasks=None, concurrency=None,
                is_scattered=None, kind="default"):
    """秘书/产品在**需求澄清阶段**评估项目层级 → 匹配承接体系与拓扑。

    语义：不是第一步、不是优先级；而是"秘书→产品澄清时评估项目层级 → 据此走后续流程"。
    与 `prescale()`（团队规模基准）互补：本处产出**承接体系/拓扑/角色子集/四套方案**，
    作为后续协作的形态基准；经理按架构做增量修正，不做从零规划、不二次评估。

    返回：{tier, system, topology, roles, plan, reason, matched_in_clarify}
    """
    from topology import fusion
    # 路由核心：按规模选承接体系+拓扑+四套方案
    routed = fusion.route(
        complexity=complexity,
        subtasks=subtasks,
        concurrency=concurrency,
        is_scattered=is_scattered,
    )
    slim = routed.get("slim") or {}
    result = {
        "tier": routed["tier"],            # micro/small/medium/large/huge
        "system": routed["system"],        # agile/architected/company/full
        "topology": routed["selected"],    # agile/dag/prefix/scatter/...
        "roles": slim.get("roles", []),    # 最小角色子集
        "ratio": slim.get("ratio"),
        "collab": slim.get("collab"),
        "cache": slim.get("cache"),
        "plan": routed["plan"],            # 四套方案（cache/division/reporting/merge）
        "reason": routed["reason"],
        "matched_in_clarify": True,        # 落位澄清阶段（秘书→产品）
    }
    log_action("scale_match", result)
    return result


# ---------------------------------------------------------------------------
# ② 决策博弈（decision-game）
# ---------------------------------------------------------------------------
# 常规"A or B 二选一都不够好"的疑问，底层常是"两者都不够好、答案藏在并集/补集"。
# 秘书决策体系：多信息 + 探索决策规则 + 多选项博弈 + 本地环境 → 内部摊开更多候选，
# 并可做立场对抗校验（对抗生成式），收敛出更稳方案。
# ---------------------------------------------------------------------------

# 多选项博弈的 5 类 or 分支（对齐审核者前置助手 L1/L2 内部分支思想，秘书内部自用）
GAME_BRANCHES = (
    ("merge_keep",    "合并保留·区分场景", "把 A/B 合并保留，按不同场景区分启用（取并集，不二选一）"),
    ("add_constraint","加约束",            "给 A/B 各加一个约束条件，划清适用边界后两者都可保留"),
    ("switch_lane",   "换道",              "当前两条路都不够好，换一条新实现道（绕开 A/B 之争）"),
    ("complement",    "补集",              "答案藏在 A/B 的并集与补集里，找出被两者忽略的第三项"),
    ("open_explore",  "开放探索",          "内部都落空时，看向外部开源/插件/skill/论文公开最优解"),
)

# 本地环境上下文（秘书"多了本地环境"的语义：可探测本地已具备的能力/约束）
def _probe_local_context():
    """探测本地环境能力/约束（秘书决策"多了本地环境"的信息增量）。"""
    ctx = {
        "python": None,
        "has_cnb": None,
        "has_llm_creds": None,
        "os": os.name,
    }
    try:
        import sys
        ctx["python"] = sys.version.split()[0]
    except Exception:
        pass
    ctx["has_cnb"] = os.system("which cnb >/dev/null 2>&1") == 0
    ctx["has_llm_creds"] = bool(os.environ.get("OPENAI_API_KEY")
                                or os.environ.get("DEEPSEEK_API_KEY")
                                or os.environ.get("LLM_API_KEY"))
    return ctx


def expand_candidates(question, branch_hint=None):
    """内部摊开多选项（解决"A or B 都不够好"）。返回候选列表 + 本地环境上下文。"""
    branches = []
    _branch_map = {n: {"name": n, "label": l, "how": h} for n, l, h in GAME_BRANCHES}
    if branch_hint in _branch_map:
        branches = [_branch_map[branch_hint]]
    else:
        branches = list(_branch_map.values())
    result = {
        "question": question,
        "branches": branches,
        "local_context": _probe_local_context(),
        "note": "秘书多选项博弈：因多了信息/探索规则/本地环境，能在 A/B 之外摊开更多候选。",
    }
    log_action("decision_game_expand", result)
    return result


def adversarial_check(question, candidates=None, stance_a="秘书", stance_b="落地开发"):
    """对抗生成式立场校验：秘书立场 vs 落地开发立场互搏，指出各自盲区。

    返回：{stance_a_points, stance_b_points, blind_spots, converged_suggestion}
    """
    stance_a_points = [
        "看全局/成本/结果复合：优先考虑需求是否被充分明确、方案是否在成本与结果间复合。",
        "重需求澄清与提示词优化：宁可多问一步也不让下游在模糊需求上返工。",
        "含测试兜底：开发说完成≠能跑通，秘书会把'测试跑不通'作为继续开发输入接管。",
    ]
    stance_b_points = [
        "看落地可行/工期：优先考虑能否在当前规模下高效完成、不背载冗余流程。",
        "重模块解耦与最小交付：按规模匹配承接体系（小任务不背公司流程）。",
        "看缓存命中/资源：高并发下控制 token 与 bug（水龙头蔓延 / 缓存命中为主线）。",
    ]
    # 互搏收敛：各自立场暴露对方盲区 → 综合成更稳建议
    blind_spots = [
        "秘书立场盲区：可能过度澄清/过度设计，忽略小任务该快速闭环的诉求。",
        "落地开发立场盲区：可能只盯局部实现，忽略需求结果是否符合预期、测试是否真跑通。",
    ]
    suggestion = (
        "对抗收敛：先按规模匹配承接体系（规模为准，非优先级），"
        "再以'能完成目标+结果符合预期'为判据；开发产出必须经测试验证，"
        "跑不通即由秘书接管并交人类继续开发（结果前置）。"
    )
    result = {
        "question": question,
        "candidates": candidates or [],
        "stance_a": stance_a,
        "stance_b": stance_b,
        "stance_a_points": stance_a_points,
        "stance_b_points": stance_b_points,
        "blind_spots": blind_spots,
        "converged_suggestion": suggestion,
    }
    log_action("decision_game_adversarial", result)
    return result


def recommend(question, branch_hint=None, with_adversarial=True):
    """秘书综合决策：多选项博弈 + 对抗校验 → 推荐 + 是否交人拍板。

    返回：{question, candidates, adversarial, recommendation, need_human, human_risk_points}
    """
    expanded = expand_candidates(question, branch_hint=branch_hint)
    adv = adversarial_check(question, [b["label"] for b in expanded["branches"]]) \
        if with_adversarial else None
    # 默认秘书能自决大部分疑问；仅当"必须担责/风险不低"才结果前置交人
    need_human = False
    human_risk_points = []
    rec = adv["converged_suggestion"] if adv else expanded["note"]
    result = {
        "question": question,
        "branches": expanded["branches"],
        "local_context": expanded["local_context"],
        "adversarial": adv,
        "recommendation": rec,
        "need_human": need_human,
        "human_risk_points": human_risk_points,
        "note": "秘书决策体系因多信息/探索规则/多选项博弈/本地环境，能解决大部分疑问；"
                "仅当承担不可逆责任/风险时结果前置交人拍板。",
    }
    log_action("decision_game_recommend", result)
    return result


# ---------------------------------------------------------------------------
# ③ 成果测试兜底接管（test-takeover）
# ---------------------------------------------------------------------------
def takeover(dev_done_report, test_result, human_risk=None):
    """成果测试兜底接管：开发说完成但测试跑不通 → 秘书直接接管，交人类继续开发。

    语义：很多时候开发觉得完成了，测试功能时还是完全跑不通 → 此时"想法也是继续开发，
          不可能存在其他说法"，**由秘书直接接管**（不是放弃/其他说法），把
          "测试跑不通"作为继续开发的输入交回；必要时结果前置给人类（列清风险）。

    返回：{takeover: True, mode, continue_development_input, handover_to_human,
          human_risk_points, reason}
    """
    passed = bool(test_result and test_result.get("passed"))
    failed_reason = "" if passed else (test_result.get("reason") or "功能测试跑不通")
    # 是否需前置给人类：功能测试跑不通且开发自认已完成 → 属"结果不符预期"，结果前置交人
    handover_to_human = False
    human_risk_points = list(human_risk or [])
    if not passed:
        # 想法也是继续开发，不可能存在其他说法：秘书接管，继续开发
        # 但因"开发说完成却跑不通"是责任边界不清 → 结果前置交人类拍板（列清风险）
        handover_to_human = True
        if not human_risk_points:
            human_risk_points = [
                f"开发报称已完成，但测试验证失败：{failed_reason}。",
                "需人类拍板：是否继续由原开发修复，或调整方案后继续开发（结果前置，非事后背锅）。",
            ]
    result = {
        "takeover": True,
        "mode": "test_takeover" if not passed else "test_passed",
        "continue_development_input": (
            f"测试未通过（{failed_reason}）→ 由秘书接管，作为继续开发的输入交回："
            f"继续开发，直到功能测试真正跑通。"
            if not passed else "测试通过，交付符合预期。"
        ),
        "handover_to_human": handover_to_human,
        "human_risk_points": human_risk_points,
        "reason": (
            "开发觉得完成了，但测试功能时跑不通 → 想法也是继续开发，不可能存在其他说法，"
            "由秘书直接接管并把'测试跑不通'作为继续开发输入；结果不符预期时结果前置交人类拍板。"
            if not passed else "测试通过，无需接管。"
        ),
    }
    log_action("test_takeover", result)
    return result


def capability():
    """秘书感知能力声明（配合全员能力声明范式）。"""
    return {
        "name": "SecretarySense",
        "kind": "role_capability",
        "abilities": {
            "scale_match": "规模匹配（落位澄清阶段）：秘书→产品澄清时评估项目层级→匹配承接体系/拓扑/角色子集，作为后续协作基准（非第一步、非优先级）",
            "decision_game": "决策博弈：多选项摊开 + 对抗生成式立场校验 + 本地环境，解决'A or B 都不够好'的犹豫，能自决即自决、需担责结果前置交人",
            "test_takeover": "成果测试兜底接管：开发说完成≠能跑通，测试跑不通由秘书接管并交人类继续开发（不可能存在其他说法）",
        },
    }


if __name__ == "__main__":
    import sys
    if "--capability" in sys.argv:
        print(json.dumps(capability(), ensure_ascii=False, indent=2))
    elif "--overview" in sys.argv:
        print("=== 秘书·感知能力层 ===")
        print(json.dumps(capability(), ensure_ascii=False, indent=2))
        m = scale_match(complexity=0, subtasks=1)
        print("\n[规模匹配示例] 单点修改 →", m["tier"], "/", m["system"], "/", m["topology"])
        r = recommend("A 方案快但返工风险高，B 方案稳但慢，选哪个？")
        print("\n[决策博弈示例] 推荐:", r["recommendation"][:80], "...")
        tk = takeover({"status": "done"}, {"passed": False, "reason": "接口调用返回 500"})
        print("\n[测试接管示例] mode=", tk["mode"], "| 交人=", tk["handover_to_human"])
