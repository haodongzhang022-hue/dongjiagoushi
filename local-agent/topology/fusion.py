# -*- coding: utf-8 -*-
"""
融合拓扑规则引擎（Fusion Topology Router · 按任务规模选择 · 融合机制）
======================================================================
用户 Issue #41 核心诉求（含本次纠偏升级）：
  ① "装一个规则机制，根据任务规模选择，而且不是选一个了……是融合机制。"
  ② **关键纠偏**："不行，小任务其实占比最高，这个才最适合体系承接，但需要简化的体系，
     类似于只剩下产品和开发、审查了，复杂度低的基本就是敏捷开发。中等开始有架构师，
     复杂度高的公司结构拉满，再高的就是完整体系了，公司规模最大，动态扩容，加下面的
     水龙头蔓延，带蔓延关系的回传合并。核心是缓存命中为主线。……越小的部分反而占比越高，
     越需要好好优化。"

本模块把「选哪个拓扑」升级为**按任务规模分层选择承接体系 + 拓扑**的可执行规则引擎。
核心设计（规模金字塔 → 承接体系，缓存命中为主线）：

  - **规模金字塔（从小到大的 5 档承接体系）**：
      * micro（单任务修改/单开发即可）→ **简化体系·敏捷**（产品→开发→审查）
        ★ 占比最高，最该精雕细琢；
      * small（低复杂度）→ **敏捷开发**（同上，仍轻量）；
      * medium（中等）→ **加架构师**（产品→架构→开发→评审→测试）；
      * large（高复杂度）→ **公司结构拉满**（DAG 全角色 + 分形 + 找工具/对齐）；
      * huge（极高复杂度/大型）→ **完整体系** + 公司规模最大 + 动态扩容
        + 水龙头蔓延 + 带蔓延关系的回传合并（融合拓扑）。
  - **缓存命中为主线（cache-first）**：所有档位都共享上下文复用，只是聚合程度递增：
      micro/small → 最简共享需求前缀（一次构造，后续增量蔓延）；
      medium/large→ 按 role 聚合共享前缀；huge → 水龙头蔓延聚合为集群。
  - **融合（fusion）不是选一个**：中小规模默认框架能承载的交给默认框架；只有
    「极高复杂度/大型（huge）」或「任务性质=散沙高并发」才触发融合/散沙。
  - **四套方案配套**：① 缓存命中（主线） ② 分工 ③ 信息回传 ④ 合并。

触发门控（对齐用户"只有…才触发"）：
  - `scale_exceeded`：极高复杂度/大型（huge）→ 完整体系 + 水龙头蔓延；
  - `scattered_high_concurrency`：任务性质天然适合散沙式高并发 → 直接用新框架一窝蜂；
  - 否则 → 按规模档位走对应承接体系（agile/architected/company），不轻易上融合。

设计原则（对齐用户纠偏）：
  - **小任务最该优化**：micro/small 走简化体系（敏捷），不做重分工、不背载完整公司流程，
    因为占比最高，累计优化收益最大；
  - **承接体系随规模递增**：敏捷 → 加架构师 → 公司拉满 → 完整体系+蔓延，
    分工协作架构以「能完成目标」为准，高复杂/大型才兼顾快速（提速）。
"""
import json
import os

# ---------------------------------------------------------------------------
# 规模分层阈值（可调，作为规则引擎的判定边界）
# ---------------------------------------------------------------------------
# 复杂度分（0~10）：≤MICRO = 单任务/单开发即可完成；≤LOW = 低复杂度（敏捷）；
#                    ≤MID = 中等（加架构师）；>MID = 复杂/大型（公司拉满/完整体系）
COMPLEXITY_MICRO = 1
COMPLEXITY_LOW = 3
COMPLEXITY_MID = 6

# 子任务数分层：≤MICRO_TASKS = 单任务修改；≤SMALL_TASKS = 轻量敏捷；
#               ≤MED_TASKS = 公司式分工
MICRO_TASKS = 1
SMALL_TASKS = 5
MED_TASKS = 20

# 并发预期：>HIGH_CONCURRENCY = 触发散沙式高并发
HIGH_CONCURRENCY = 10

# 超大子任务数：>HUGE_TASKS = 升级「huge」档（完整体系 + 规模超默认承载 → 融合蔓延）
HUGE_TASKS = 50
# 超高复杂度：>HUGE_COMPLEXITY = 升级「huge」档
HUGE_COMPLEXITY = 9

# 默认框架（公司式分工 dag）可承载的最大规模档位；超过即判定「规模超默认承载」
DEFAULT_FRAMEWORK_TIER = "large"   # dag 承载到 large；超 large 才融合蔓延

# 融合拓扑注册
FUSION_TOPOLOGIES = ("hybrid", "prefix", "scramble")
# 散沙式拓扑注册
SCATTER_TOPOLOGIES = ("scatter", "scramble")

# ---------------------------------------------------------------------------
# 承接体系（体系复杂度）映射 —— 用户 Issue #41 纠偏核心
# ---------------------------------------------------------------------------
# 用户："小任务其实占比最高……需要简化的体系，类似于只剩下产品和开发、审查，
#       复杂度低的基本就是敏捷开发；中等开始有架构师；复杂度高的公司结构拉满；
#       再高的就是完整体系了……越小的部分反而占比越高，越需要好好优化。"
#
# 规模金字塔 → 承接体系（从小到大的「协作复杂度」）：
#   micro  (单任务修改)       → agile      简化体系（敏捷：产品+开发+审查）
#   small  (低复杂度)         → agile      敏捷开发（同上，仍轻量）
#   medium (中等)             → architected 加架构师（产品→架构→开发→评审→测试）
#   large  (高复杂度)         → company    公司结构拉满（DAG 全角色 + 分形 + 找工具/对齐）
#   huge   (极高复杂度/大型)  → full       完整体系 + 公司规模最大 + 动态扩容
#                                       + 水龙头蔓延 + 带蔓延关系的回传合并
#
# 缓存命中为主线（cache-first）：所有档位都共享上下文复用，只是聚合程度递增：
#   micro/small → 最简共享前缀（需求上下文一次构造，后续增量蔓延）；
#   medium/large→ 按 role 聚合共享前缀；
#   huge        → 水龙头蔓延聚合为集群（前缀只构造一次，后续节点增量蔓延）。
TIER_SYSTEM = {
    "micro":  "agile",        # 简化体系（敏捷：产品+开发+审查）★ 最高频最该优化
    "small":  "agile",        # 敏捷开发（低复杂度，仍轻量）
    "medium": "architected",  # 加架构师
    "large":  "company",      # 公司结构拉满（DAG 全角色）
    "huge":   "full",         # 完整体系 + 蔓延（动态扩容/水龙头/回传合并）
}

# 各档位应选用的拓扑（承接体系 → 拓扑）
AGILE_TOPOLOGY = "agile"      # micro/small 简化体系拓扑（产品→开发→审查）
ARCHITECTED_TOPOLOGY = "dag"  # medium 加架构师
COMPANY_TOPOLOGY = "dag"      # large 公司结构拉满（DAG 生产拓扑）
FULL_TOPOLOGY = "prefix"      # huge 完整体系 + 水龙头蔓延（融合）
SCATTER_TOPOLOGY = "scatter"  # 散沙一窝蜂（零散无架构任务仍可用）


# ---------------------------------------------------------------------------
# 规模评估（把任务规模信号归一化成分层档位）
# ---------------------------------------------------------------------------
def evaluate_scale(complexity=None, subtasks=None, concurrency=None, is_scattered=None):
    """评估任务规模，返回分层档位 + 关键信号。

    输入（均可省略，省略项按保守默认处理）：
      - complexity:   复杂度分（0~10）
      - subtasks:     子任务数
      - concurrency:  预期并发量
      - is_scattered: 是否零散（无复杂架构 / 常规补全 / 小修小补）

    返回：{tier, system, signals, decisions}
      tier:   micro / small / medium / large / huge（规模档位，从小到大的金字塔）
      system: 承接体系（agile / architected / company / full），见 TIER_SYSTEM
      signals: 各关键信号布尔（micro_task/small_task/scattered/mid_complex/high_concurrency/scale_exceeded）
    """
    complexity = complexity if complexity is not None else 1
    subtasks = subtasks if subtasks is not None else 1
    concurrency = concurrency if concurrency is not None else 1
    is_scattered = bool(is_scattered)

    # 规模档位判定（复杂度 + 子任务数双维，取高）
    if complexity > HUGE_COMPLEXITY or subtasks > HUGE_TASKS:
        tier = "huge"            # 极高复杂度/大型 → 完整体系 + 蔓延（规模超默认承载）
    elif complexity <= COMPLEXITY_MICRO and subtasks <= MICRO_TASKS:
        tier = "micro"          # ★ 单任务修改 / 单开发即可完成 → 简化体系（敏捷），占比最高
    elif complexity <= COMPLEXITY_LOW and subtasks <= SMALL_TASKS:
        tier = "small"          # 低复杂度 → 敏捷开发（简化体系）
    elif complexity <= COMPLEXITY_MID and subtasks <= MED_TASKS:
        tier = "medium"         # 中等 → 加架构师
    elif complexity > COMPLEXITY_MID or subtasks > MED_TASKS:
        tier = "large"          # 高复杂度 → 公司结构拉满
    else:
        tier = "medium"

    # 承接体系（体系复杂度）映射
    system = TIER_SYSTEM.get(tier, "agile")

    # 散沙型高并发：零散 或 并发预期超阈值 → 升级融合/散沙
    scattered = is_scattered or (subtasks > SMALL_TASKS and concurrency > HIGH_CONCURRENCY)

    # 规模是否超默认框架承载：档位 > DEFAULT_FRAMEWORK_TIER
    tier_order = ["micro", "small", "medium", "large", "huge"]
    scale_exceeded = tier_order.index(tier) > tier_order.index(DEFAULT_FRAMEWORK_TIER)

    signals = {
        "micro_task": tier == "micro",
        "small_task": tier in ("micro", "small"),
        "scattered": scattered,
        "mid_complex": COMPLEXITY_LOW < complexity <= COMPLEXITY_MID,
        "high_concurrency": concurrency > HIGH_CONCURRENCY,
        "scale_exceeded": scale_exceeded,
        "tier": tier,
        "system": system,
    }
    decisions = {
        "complexity": complexity,
        "subtasks": subtasks,
        "concurrency": concurrency,
        "is_scattered": is_scattered,
    }
    return {"tier": tier, "system": system, "signals": signals, "decisions": decisions}


# ---------------------------------------------------------------------------
# 规则引擎：按规模分层选择拓扑（融合触发门控）
# ---------------------------------------------------------------------------
def select_topology(scale, available=None):
    """核心规则引擎：根据规模评估选择最优拓扑（融合触发门控）。

    scale: evaluate_scale() 的返回值（tier/signals/decisions）。

    选择逻辑（对齐用户 Issue #41 纠偏：规模金字塔 → 承接体系，缓存命中为主线）：
      1. 极高复杂度/大型（huge，规模超默认承载）→ 完整体系 + 水龙头蔓延（prefix/hybrid）
         动态扩容 + 带蔓延关系的回传合并；
      2. 散沙型高并发（scattered）→ 直接用新框架（scatter 一窝蜂），不设中央深度设计；
      3. micro（单任务修改）→ 简化体系（agile：产品→开发→审查），占比最高最该优化，
         cache-first 共享需求前缀复用；
      4. small（低复杂度）→ 敏捷开发（agile），仍轻量、cache-first；
      5. medium（中等）→ 加架构师（dag）；
      6. large（高复杂度）→ 公司结构拉满（dag 全角色）；
      7. 兜底 → dag（默认生产拓扑）。

    返回：{selected, system, reason, alternatives, plan}
      selected:   最终选定拓扑 id
      system:     承接体系（agile/architected/company/full）
      reason:     选择依据（一句话）
      alternatives: 备选拓扑（降级/融合路径）
      plan:       四套配套方案（cache/division/reporting/merge）——cache 为主线横贯所有档位
    """
    available = available or list_topology_ids()
    system = scale.get("system", TIER_SYSTEM.get(scale["tier"], "agile"))

    # 1) 极高复杂度/大型（huge）→ 完整体系 + 水龙头蔓延（融合拓扑）
    if scale["signals"]["scale_exceeded"]:
        chosen = "prefix" if "prefix" in available else ("hybrid" if "hybrid" in available else "dag")
        plan = build_plan(chosen, scale)
        return {
            "selected": chosen,
            "system": system,
            "reason": "极高复杂度/大型 → 完整体系 + 公司规模最大 + 动态扩容 + 水龙头蔓延 + 带蔓延关系的回传合并",
            "alternatives": ["hybrid", "prefix", "scramble"],
            "plan": plan,
        }

    # 2) 散沙型高并发 → 直接用新框架（scatter 一窝蜂），不设中央深度设计
    if scale["signals"]["scattered"]:
        chosen = "scatter" if "scatter" in available else ("scramble" if "scramble" in available else "dag")
        plan = build_plan(chosen, scale)
        return {
            "selected": chosen,
            "system": "scattered",
            "reason": "任务性质=散沙型高并发（零散/无架构依赖/并发大）→ 直接用新框架一窝蜂并行解决",
            "alternatives": ["scatter", "scramble", "prefix"],
            "plan": plan,
        }

    # 3) micro（单任务修改）→ 简化体系（agile：产品→开发→审查）★ 最高频最该优化
    if scale["signals"]["micro_task"]:
        chosen = AGILE_TOPOLOGY if AGILE_TOPOLOGY in available else ("scatter" if "scatter" in available else "dag")
        plan = build_plan(chosen, scale)
        return {
            "selected": chosen,
            "system": system,
            "reason": "单任务修改（占比最高）→ 简化体系·敏捷开发（产品→开发→审查），不做重分工，cache-first 共享需求前缀",
            "alternatives": [AGILE_TOPOLOGY, "scatter", "linear"],
            "plan": plan,
        }

    # 4) small（低复杂度）→ 敏捷开发（简化体系，仍轻量）
    if scale["signals"]["small_task"]:
        chosen = AGILE_TOPOLOGY if AGILE_TOPOLOGY in available else ("scatter" if "scatter" in available else "dag")
        plan = build_plan(chosen, scale)
        return {
            "selected": chosen,
            "system": system,
            "reason": "低复杂度 → 敏捷开发（简化体系·产品→开发→审查），轻量承接，cache-first",
            "alternatives": [AGILE_TOPOLOGY, "scatter", "linear"],
            "plan": plan,
        }

    # 5) medium → 加架构师（dag）
    if scale["tier"] == "medium":
        plan = build_plan("dag", scale)
        return {
            "selected": "dag" if "dag" in available else (list(available)[0] if available else "linear"),
            "system": system,
            "reason": "中等复杂度 → 加架构师（产品→架构→开发→评审→测试），架构把关",
            "alternatives": ["dag", "event"],
            "plan": plan,
        }

    # 6) large → 公司结构拉满（dag 全角色 + 分形 + 找工具/对齐）
    plan = build_plan("dag", scale)
    return {
        "selected": "dag" if "dag" in available else (list(available)[0] if available else "linear"),
        "system": system,
        "reason": "高复杂度 → 公司结构拉满（DAG 全角色 + 分形多小组 + 找工具/对齐），承载大型任务",
        "alternatives": ["dag", "event", "hybrid"],
        "plan": plan,
    }


def list_topology_ids():
    """返回当前注册的全部拓扑 id（去重保序）。"""
    try:
        from topology.topologies import TOPOLOGIES
        return list(TOPOLOGIES.keys())
    except Exception:
        return ["linear", "dag", "event", "hybrid", "scatter", "agile", "prefix"]


# ---------------------------------------------------------------------------
# 四套配套方案：缓存命中 / 分工 / 信息回传 / 合并
# ---------------------------------------------------------------------------
def build_plan(topology, scale):
    """针对选定的拓扑，生成四套配套方案（cache/division/reporting/merge）。

    返回 {cache, division, reporting, merge} 各为一句话落地要点。
    这些方案是「大规模/融合场景」的配套，让"越大越快 + 缓存命中 + 信息回传合并"可落地。
    """
    tier = scale["tier"]
    subtasks = scale["decisions"]["subtasks"]
    concurrency = scale["decisions"]["concurrency"]
    system = TIER_SYSTEM.get(tier, "agile")

    # ① 缓存命中方案：**主线（cache-first）横贯所有档位**，只是聚合程度递增：
    #    micro/small → 最简共享需求前缀（一次构造，后续增量蔓延）；
    #    medium/large→ 按 role 聚合共享前缀；
    #    huge        → 水龙头蔓延聚合为集群（前缀只构造一次，后续节点增量蔓延）。
    if topology in ("prefix", "hybrid"):
        cache_plan = (
            f"【主线·缓存命中】共享前缀聚合为集群（缓存命中为索引）：同一 role 节点共享前缀"
            f"只构造一次，后续节点命中缓存只付增量差异 token；不同集群天然并行。规模 {tier}，"
            f"{subtasks} 子任务 → 水龙头蔓延（动态扩容 + 带蔓延关系的回传合并）。"
        )
    elif topology == "agile":
        cache_plan = (
            f"【主线·缓存命中】简化体系（敏捷）：产品→开发→审查 共享需求前缀，前缀只构造一次，"
            f"后续节点命中缓存只付增量 token —— 单任务虽小，也要复用共享上下文（cache-first），"
            f"降 token 降 bug。规模 {tier}（占比最高），{subtasks} 修改点。"
        )
    elif topology in ("scatter", "scramble"):
        cache_plan = (
            f"【主线·缓存命中】一窝蜂高并发下：为同 role 共享上下文做前缀聚合，命中缓存增量推进，"
            f"避免每节点独立重构造完整上下文（降 token 降 bug）。并发 {concurrency}。"
        )
    else:  # dag 等常规拓扑（medium/large）
        cache_plan = (
            f"【主线·缓存命中】承接体系 {system}（{topology}）：按 role 聚共享前缀，命中缓存增量蔓延，"
            f"常规规模 token 复用充分即可，不强制水龙头。"
        )

    # ② 分工方案：规模分层映射子任务分配策略
    if tier in ("large", "huge"):
        division_plan = (
            f"超大规模：中央调控先吃核心/高价值部分（内部消化），余量子任务一窝蜂瓜分补全；"
            f"或分形拆小组并行，各小组组长整合后统一向上交付（公司规模最大 + 动态扩容）。"
        )
    elif tier in ("micro", "small"):
        division_plan = f"简化体系（敏捷）：不做重分工，{subtasks} 个修改点由单个开发完成即可（占比最高最该优化）。"
    else:
        division_plan = f"中等（加架构师）/公司：按功能域拆分 {subtasks} 个子任务，并行推进。"

    # ③ 信息回传方案：子任务结果回传收口
    if topology == "agile":
        reporting_plan = f"简化体系：产品→开发→审查 单线回传，轻量留痕于 Issue/PR（小任务快速闭环）。"
    elif topology in ("scatter", "scramble", "hybrid", "prefix"):
        reporting_plan = (
            f"抢单/水龙头节点各自完成后回传结果，统一收口到评审/测试节点；"
            f"gid 稳定寻址回传对象，回传留痕于 task_prs/commit。"
        )
    else:
        reporting_plan = f"公司式分工：各小组按接力卡回传，小组长整合后向上交付，留痕于 Issue/PR。"

    # ④ 合并方案：按最小模块统一向上整合交付
    if tier in ("large", "huge") or topology in ("scatter", "scramble", "hybrid", "prefix"):
        merge_plan = (
            f"分形/抢单结果按最小模块粒度统一向上整合交付（commits 以小组为单位），"
            f"避免多 agent 改同一对象冲突、Issue 合并不失效。"
        )
    else:
        merge_plan = f"简化体系/常规：按最小模块整合，统一提交交付（单任务直接闭环）。"

    return {
        "cache": cache_plan,
        "division": division_plan,
        "reporting": reporting_plan,
        "merge": merge_plan,
    }


# ---------------------------------------------------------------------------
# 便捷入口：一条 API 完成「规模评估 → 规则选择 → 方案」
# ---------------------------------------------------------------------------
def route(complexity=None, subtasks=None, concurrency=None, is_scattered=None,
          available=None, verbose=False):
    """一条 API 完成融合拓扑路由（规模评估 + 规则选择 + 四套方案）。

    返回：
      {selected, tier, reason, signals, alternatives, plan}
      若 verbose=True 额外附带完整 scale 评估细节。
    """
    scale = evaluate_scale(
        complexity=complexity, subtasks=subtasks,
        concurrency=concurrency, is_scattered=is_scattered,
    )
    result = select_topology(scale, available=available)
    result["tier"] = scale["tier"]
    result["system"] = scale["system"]
    result["signals"] = scale["signals"]
    if verbose:
        result["scale"] = scale
    return result


# ---------------------------------------------------------------------------
# 二级信息汇总（供人类俯瞰决策）
# ---------------------------------------------------------------------------
def overview(scales=None):
    """输出融合规则引擎的二级信息快照（供人类俯瞰）。

    scales: 可传入多个规模评估样本，输出每样本的选中拓扑 + 依据。
    """
    rows = []
    if scales:
        for s in scales:
            r = select_topology(s)
            rows.append({
                "tier": s["tier"],
                "scattered": s["signals"]["scattered"],
                "scale_exceeded": s["signals"]["scale_exceeded"],
                "selected": r["selected"],
                "reason": r["reason"],
            })
    return {
        "rule": "按任务规模分层选择承接体系 + 拓扑（规模金字塔 → 简化→完整，缓存命中为主线）",
        "tiers": {
            "micro": "简化体系·敏捷（产品→开发→审查）★占比最高最该优化",
            "small": "简化体系·敏捷（同上，仍轻量）",
            "medium": "加架构师（产品→架构→开发→评审→测试）",
            "large": "公司结构拉满（DAG 全角色 + 分形 + 找工具/对齐）",
            "huge": "完整体系 + 蔓延（动态扩容/水龙头/带蔓延关系回传合并）",
        },
        "cache_first": "缓存命中为主线，横贯所有档位（micro/small 最简共享前缀 → huge 水龙头蔓延聚合）",
        "trigger": {
            "scale_exceeded": "极高复杂度/大型（huge）→ 完整体系 + 蔓延",
            "scattered_high_concurrency": "散沙型高并发 → 新框架一窝蜂",
        },
        "rows": rows,
    }


# CLI 入口
if __name__ == "__main__":
    import sys
    # 用法：python3 topology/fusion.py --route --complexity 8 --subtasks 30
    args = sys.argv[1:]
    if "--route" in args:
        def _arg(name, default=None):
            for i, a in enumerate(args):
                if a == name and i + 1 < len(args):
                    return int(args[i + 1])
            return default
        c = _arg("--complexity", 3)
        s = _arg("--subtasks", 10)
        k = _arg("--concurrency", 5)
        res = route(complexity=c, subtasks=s, concurrency=k, verbose=True)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif "--overview" in args:
        samples = [
            evaluate_scale(complexity=0, subtasks=1, concurrency=1, is_scattered=False),  # micro
            evaluate_scale(complexity=2, subtasks=3, concurrency=1, is_scattered=False),  # small
            evaluate_scale(complexity=4, subtasks=10, concurrency=3),                     # medium
            evaluate_scale(complexity=7, subtasks=25, concurrency=15),                    # large
            evaluate_scale(complexity=9, subtasks=60, concurrency=15),                    # huge
        ]
        print(json.dumps(overview(samples), ensure_ascii=False, indent=2))
    else:
        print("用法: python3 topology/fusion.py --route --complexity N --subtasks N --concurrency N")
        print("      python3 topology/fusion.py --overview")
