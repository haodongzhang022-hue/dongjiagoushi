# -*- coding: utf-8 -*-
"""
collab · 审核者前置助手引擎（precursor）
========================================
「审核者前置助手 · 决策补全机制」的可执行核心，对应 docs/REVIEWER_PRECURSOR.md。

背景（用户确立的认知根因）：当产生「A or B 二选一 / 两者都不够好」的疑问时，
底层常不是二选一，而是 A 与 B 都不完整，正确答案藏在 A、B 之外的**并集/补集**。
本引擎在每次这样的决策瞬间，**强制把「被忽略的那条路」摊上桌面**。

触发硬约束（缺前置直接触发 = 错误）：
  - 本链路**只在功能实现不了时才接入**；前置（单兵 → 补位 → 专家会诊）
    一个都不能丢，它只是完整链路的一小段，不是独立完整链路。

三层时点 + 五类 or 分支：
  L1 决策瞬间   ① 合并保留·区分场景  ② 加约束  ③ 换道  ④ 补集（向内摊开内部方案）
  L2 全部落空   ⑤ 开放探索型——看向外部搜公开最优解（开源/插件/skill/论文），
                命中且「负面足够小 + 零成本 + 零安全风险」→ **直接自决使用**；
                带成本/风险 → 结果前置交人类拍板；未命中 → 带探索素材包交人判断。
  L3 交人判断   带问题 + 探索素材包 + 折中选项给人类拍板（人类自己选、自己接受）。
"""
import json
import uuid

try:
    from data import admin, db
except Exception:  # noqa: BLE001
    admin = None
    db = None

# ---------- L1 内部分支：摊开被忽略的内部 or 方案 ----------

def _branch_merge(a, b, scenarios):
    """① 合并保留·区分场景：不砍 A 也不砍 B，按场景切分适用域。"""
    return {
        "branch": "merge",
        "label": "合并保留·区分场景",
        "proposal": f"同时保留 A 与 B，按场景切分：{scenarios or '需进一步细化场景边界'}",
    }


def _branch_constraint(a, b, defects_a, defects_b):
    """② 加约束：把各自"不对处"显式列出作为新增约束过滤。"""
    return {
        "branch": "constraint",
        "label": "加约束",
        "proposal": f"A 的缺陷：{defects_a or '无'}; B 的缺陷：{defects_b or '无'}。"
                    f"把两者缺陷作为新增约束，过滤出满足全部约束的方案。",
    }


def _branch_switch(a, b, alt=""):
    """③ 换道：放弃 A、B，搜索第三方案。"""
    return {
        "branch": "switch",
        "label": "换道",
        "proposal": f"放弃 A、B，改用第三条路：{alt or '待外部探索/设计第三方案'}",
    }


def _branch_complement(a, b, blank=""):
    """④ 补集：检查 A、B 都没覆盖的空白域，那里往往藏着答案。"""
    return {
        "branch": "complement",
        "label": "补集",
        "proposal": f"检查 A、B 均未覆盖的空白域：{blank or '需系统盘点未被任一方案覆盖的需求'}",
    }


def l1_explore(problem, option_a, option_b, scenarios="", defects_a="",
               defects_b="", alt="", blank=""):
    """L1 决策瞬间：把 ①合并 ②加约束 ③换道 ④补集 四种内部 or 分支全部摊开。

    返回 { layer: "L1", problem, branches: [...], exhausted: False }
    """
    branches = [
        _branch_merge(option_a, option_b, scenarios),
        _branch_constraint(option_a, option_b, defects_a, defects_b),
        _branch_switch(option_a, option_b, alt),
        _branch_complement(option_a, option_b, blank),
    ]
    return {
        "layer": "L1",
        "problem": problem,
        "option_a": option_a,
        "option_b": option_b,
        "branches": branches,
        "exhausted": False,
    }


# ---------- L2 开放探索型：看向外部找公开最优解 ----------

# 可注入的外部搜索实现（默认占位，生产可接 web 搜索 / RAG / 插件市场）
_EXTERNAL_SEARCH = None


def set_external_search(fn):
    """注入外部搜索函数 fn(keyword) -> list[ {source, title, snippet, url} ]。"""
    global _EXTERNAL_SEARCH
    _EXTERNAL_SEARCH = fn


def _external_search(keyword):
    """调用外部搜索；未注入则返回占位（提示需接入真实检索）。"""
    if _EXTERNAL_SEARCH is not None:
        try:
            return _EXTERNAL_SEARCH(keyword) or []
        except Exception:  # noqa: BLE001
            return []
    # 占位：用内存里登记的已知现成方案（测试/演示用）
    return _KNOWN_PATTERNS.get(keyword.strip().lower(), [])


# 已知现成方案登记表（L2 命中判定用；演示/测试可注入）
_KNOWN_PATTERNS = {}


def register_known_pattern(keyword, source, title, snippet="", url=""):
    """登记一个已知公开方案（模拟外部检索命中，供测试/演示）。"""
    _KNOWN_PATTERNS.setdefault(keyword.strip().lower(), []).append({
        "source": source, "title": title, "snippet": snippet, "url": url,
    })


def l2_explore(problem, keyword="", known_patterns=None, use_external=False):
    """L2 全部落空后：开放探索型——看向外部搜公开最优解。

    命中判定：
      - 命中方案且「负面足够小 + 零成本 + 零安全风险」→ self_decide=True（直接自决使用）；
      - 命中但带成本/安全风险 → self_decide=False（结果前置交人）；
      - 未命中 → 带探索素材包交人判断。
    """
    hits = known_patterns if known_patterns is not None else _external_search(keyword or problem)
    return {
        "layer": "L2",
        "problem": problem,
        "keyword": keyword or problem,
        "hits": hits,
        "found": bool(hits),
        # self_decide 的判定由调用方按负面/成本/安全风险给定；这里给出候选
        "self_decidable": _is_self_decidable(hits),
        "exhausted": not bool(hits),
    }


def _is_self_decidable(hits):
    """默认判定：命中且无任何负面/成本/安全标记 → 可自决。

    生产上可由 hit 携带 meta（negative/cost/risk）参与判定；默认未标注即视为零负面。
    """
    if not hits:
        return False
    return all(not h.get("negative") and not h.get("cost") and not h.get("risk")
               for h in hits)


# ---------- L3 交人判断 ----------

def l3_human(problem, exploration_pack, options=None):
    """L3 交人判断：带问题 + 探索素材包 + 折中选项给人类拍板。

    原则（结果前置·非事后背锅）：
      - 有负面责任需要决策的那一刻就把人类叫出来拍板，因果对齐；
      - 信息必须足够明确，尤其把风险点显式列清；
      - 人类自己选的自己接受，agent 不背锅不代替。
    返回: { layer:"L3", problem, pack, options, needs_human: True }
    """
    return {
        "layer": "L3",
        "problem": problem,
        "pack": exploration_pack,
        "options": options or [],
        "needs_human": True,
        "principle": "结果前置：决策点交人类拍板，风险点列清，人类自己选自己接受",
    }


# ---------- 编排：单次决策补全走 L1 → L2 → L3 ----------

def run(problem, option_a="", option_b="", scenario_hint="", keyword="",
        known_patterns=None, defects_a="", defects_b="", alt="", blank=""):
    """审核者前置助手一次完整决策补全：L1 摊开内部分支 → L2 外部探索 → L3 交人。

    返回 { problem, layers: [L1, L2, L3], outcome, decision }
      - outcome: 是否在某一层收敛出可落地决策
      - decision: 若 L2 命中且可自决 → { self_decide: True, adopt: <首个命中> }
                   否则 → { needs_human: True, pack: {...} }
    """
    l1 = l1_explore(problem, option_a, option_b, scenarios=scenario_hint,
                    defects_a=defects_a, defects_b=defects_b, alt=alt, blank=blank)
    # 若调用方显式给出某内部 or 分支已选定 → 视为 L1 收敛
    selected_branch = None
    for b in l1["branches"]:
        if b.get("selected"):
            selected_branch = b
            break
    if selected_branch is not None:
        return {
            "problem": problem,
            "layers": [l1],
            "outcome": "l1_resolved",
            "decision": {"self_decide": True, "branch": selected_branch["branch"],
                         "proposal": selected_branch["proposal"]},
        }

    # L2 外部探索
    l2 = l2_explore(problem, keyword=keyword, known_patterns=known_patterns)
    if l2["found"] and l2["self_decidable"]:
        adopt = l2["hits"][0]
        return {
            "problem": problem,
            "layers": [l1, l2],
            "outcome": "l2_adopt",
            "decision": {"self_decide": True, "adopt": adopt,
                         "source": adopt.get("source", "")},
        }

    # L3 交人判断（含"命中但需担责 → 结果前置交人"与"未命中 → 带素材包交人"）
    l3 = l3_human(problem, {"l1": l1, "l2": l2}, options=[])
    return {
        "problem": problem,
        "layers": [l1, l2, l3],
        "outcome": "human",
        "decision": {"needs_human": True, "pack": l3,
                     "reason": "L2 命中但需担责，或未命中外部方案"},
    }
