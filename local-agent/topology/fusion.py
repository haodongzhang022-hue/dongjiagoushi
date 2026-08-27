# -*- coding: utf-8 -*-
"""
融合拓扑规则引擎（Fusion Topology Router · 按任务规模选择 · 融合机制）
======================================================================
用户 Issue #41 核心诉求：
  "装一个规则机制，根据任务规模选择，而且不是选一个了，现在构建了融合机制，
   是可以用新框架的处理规模不很大的情况的，只有规则变大到默认的框架不够
   或者下面就是适合这种散沙类型高并发的，就触发这个。
   之前的在类似于公司的那种协作方式下……就已经可以承载98%以上的任务了吧，
   只有规模再大的时候走完上面再到这一步。"

本模块把「选哪个拓扑」从**手工/散点声明**升级为**可执行、按任务规模分层选择、
可降级、可融合**的规则引擎。核心设计（融合分层 + 触发门控）：

  - **分层选择（tier routing）**：按任务规模（复杂度 + 子任务数 + 并发预期）分层：
      * 小规模/零散   → **轻量新框架**（scatter 一窝蜂 / 直接跑），不做过度分工；
      * 中/大规模     → **公司式分工**（dag/company 协作），承载 ~98% 任务；
      * 超大规模/散沙型高并发 → **触发融合**（hybrid+prefix 水龙头蔓延 / scramble），
        只有前两层默认框架不够或任务天然适合高并发散沙才触发。
  - **融合（fusion）不是选一个**：默认框架能承载的交给默认框架；只有
    「规模超默认承载」或「任务性质=散沙高并发」才叠加/切换到融合拓扑。
  - **四套方案配套**（针对融合/大规模场景）：
      * ① 缓存命中方案（cache）——共享前缀聚合为集群，命中索引，增量蔓延；
      * ② 分工方案（division）——规模分层映射子任务分配策略（内部消化核心 vs 余量瓜分）；
      * ③ 信息回传方案（reporting）——子任务结果回传收口、汇总合并；
      * ④ 合并方案（merge）——分形小组/抢单结果按最小模块统一向上整合交付。

触发门控（对齐用户"只有…才触发"）：
  - `scale_exceeded`：任务规模预估超出默认框架（dag/company）可承载阈值 → 触发融合；
  - `scattered_high_concurrency`：任务性质天然适合散沙式高并发（零散补全/无架构依赖）
    → 直接用新框架（scatter 一窝蜂）；
  - 否则 → 默认走公司式分工（dag），不轻易上融合（防止对小任务过度设计）。

设计原则（对齐用户纠偏）：
  - **默认承载 98%**：中小/大规模默认公司式分工（dag），融合是少数大任务/散沙高并发才触发；
  - **融合不是必选**：规模小就走轻量，规模正常就走 dag，只有超载/散沙高并发才走融合；
  - **完成度优先**：对毫秒级分工时差无体感，重要的是任务完成情况 —— 融合/分形无论速度
    都是优势，越大越明显，只是需要针对这些情况配套缓存命中、分工、回传、合并方案。
"""
import json
import os

# ---------------------------------------------------------------------------
# 规模分层阈值（可调，作为规则引擎的判定边界）
# ---------------------------------------------------------------------------
# 复杂度分（0~10）：≤LOW = 零散/小修；≤MID = 中等；>MID = 复杂/大型
COMPLEXITY_LOW = 3
COMPLEXITY_MID = 6

# 子任务数分层：≤SMALL_TASKS = 轻量可一窝蜂；≤MED_TASKS = 公司式分工
SMALL_TASKS = 5
MED_TASKS = 20

# 并发预期：>HIGH_CONCURRENCY = 触发散沙式高并发
HIGH_CONCURRENCY = 10

# 超大子任务数：>HUGE_TASKS = 升级「huge」档（规模超默认框架承载 → 触发融合）
HUGE_TASKS = 50
# 超高复杂度：>HUGE_COMPLEXITY = 升级「huge」档
HUGE_COMPLEXITY = 9

# 默认框架（公司式分工）可承载的最大规模档位；超过即判定「规模超默认承载」
DEFAULT_FRAMEWORK_TIER = "large"   # dag 承载到 large；超 large 才融合

# 融合拓扑注册
FUSION_TOPOLOGIES = ("hybrid", "prefix", "scramble")
# 散沙式拓扑注册
SCATTER_TOPOLOGIES = ("scatter", "scramble")


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

    返回：{tier, signals, decisions}
      tier:   small / medium / large / huge（规模档位）
      signals: 各关键信号布尔（small_task/scattered/mid_complex/high_concurrency/scale_exceeded）
    """
    complexity = complexity if complexity is not None else 1
    subtasks = subtasks if subtasks is not None else 1
    concurrency = concurrency if concurrency is not None else 1
    is_scattered = bool(is_scattered)

    # 规模档位判定（复杂度 + 子任务数双维，取高）
    if complexity > HUGE_COMPLEXITY or subtasks > HUGE_TASKS:
        tier = "huge"            # 超大规模：规模超默认框架承载 → 融合
    elif complexity <= COMPLEXITY_LOW and subtasks <= SMALL_TASKS:
        tier = "small"
    elif complexity <= COMPLEXITY_MID and subtasks <= MED_TASKS:
        tier = "medium"
    elif complexity > COMPLEXITY_MID or subtasks > MED_TASKS:
        tier = "large"
    else:
        tier = "medium"

    # 散沙型高并发：零散 或 并发预期超阈值 → 升级融合/散沙
    scattered = is_scattered or (subtasks > SMALL_TASKS and concurrency > HIGH_CONCURRENCY)

    # 规模是否超默认框架承载：档位 > DEFAULT_FRAMEWORK_TIER
    tier_order = ["small", "medium", "large", "huge"]
    scale_exceeded = tier_order.index(tier) > tier_order.index(DEFAULT_FRAMEWORK_TIER)

    signals = {
        "small_task": tier == "small",
        "scattered": scattered,
        "mid_complex": COMPLEXITY_LOW < complexity <= COMPLEXITY_MID,
        "high_concurrency": concurrency > HIGH_CONCURRENCY,
        "scale_exceeded": scale_exceeded,
        "tier": tier,
    }
    decisions = {
        "complexity": complexity,
        "subtasks": subtasks,
        "concurrency": concurrency,
        "is_scattered": is_scattered,
    }
    return {"tier": tier, "signals": signals, "decisions": decisions}


# ---------------------------------------------------------------------------
# 规则引擎：按规模分层选择拓扑（融合触发门控）
# ---------------------------------------------------------------------------
def select_topology(scale, available=None):
    """核心规则引擎：根据规模评估选择最优拓扑（融合触发门控）。

    scale: evaluate_scale() 的返回值（tier/signals/decisions）。

    选择逻辑（对齐用户"只有…才触发融合"）：
      1. 规模超默认承载（scale_exceeded）→ 触发融合拓扑（hybrid+prefix 水龙头蔓延）；
      2. 散沙型高并发（scattered）→ 直接用新框架（scatter 一窝蜂），不设中央深度设计；
      3. 小规模（small）→ 轻量新框架（scatter 一窝蜂 或 直跑），不做过重分工；
      4. 中/大规模（medium/large）→ 默认公司式分工（dag），承载 98% 任务；
      5. 兜底 → dag（默认生产拓扑）。

    返回：{selected, reason, alternatives, plan}
      selected:   最终选定拓扑 id
      reason:     选择依据（一句话）
      alternatives: 备选拓扑（降级/融合路径）
      plan:       四套配套方案（cache/division/reporting/merge）针对本次选择的落地要点
    """
    available = available or list_topology_ids()

    # 1) 规模超默认承载 → 融合拓扑（hybrid 或 prefix，prefix 是 hybrid 的缓存优化版）
    if scale["signals"]["scale_exceeded"]:
        chosen = "prefix" if "prefix" in available else ("hybrid" if "hybrid" in available else "dag")
        plan = build_plan(chosen, scale)
        return {
            "selected": chosen,
            "reason": "规模超默认框架（公司式分工）承载上限 → 触发融合拓扑（前缀缓存·水龙头蔓延 + 中央调控）",
            "alternatives": ["hybrid", "prefix", "scramble"],
            "plan": plan,
        }

    # 2) 散沙型高并发 → 直接用新框架（scatter 一窝蜂），不设中央深度设计
    if scale["signals"]["scattered"]:
        chosen = "scatter" if "scatter" in available else ("scramble" if "scramble" in available else "dag")
        plan = build_plan(chosen, scale)
        return {
            "selected": chosen,
            "reason": "任务性质=散沙型高并发（零散/无架构依赖/并发大）→ 直接用新框架一窝蜂并行解决",
            "alternatives": ["scatter", "scramble", "prefix"],
            "plan": plan,
        }

    # 3) 小规模 → 轻量新框架，不做过重分工
    if scale["signals"]["small_task"]:
        chosen = "scatter" if "scatter" in available else "dag"
        plan = build_plan(chosen, scale)
        return {
            "selected": chosen,
            "reason": "小规模零散任务 → 轻量一窝蜂解决，不做重分工（防过度设计）",
            "alternatives": ["scatter", "dag", "linear"],
            "plan": plan,
        }

    # 4) 中/大规模 → 默认公司式分工（dag），承载 98% 任务
    plan = build_plan("dag", scale)
    return {
        "selected": "dag" if "dag" in available else (list(available)[0] if available else "linear"),
        "reason": f"中/大规模（{scale['tier']}）→ 默认公司式分工（DAG 并行），承载 ~98% 常规任务，不上融合",
        "alternatives": ["dag", "event", "hybrid"],
        "plan": plan,
    }


def list_topology_ids():
    """返回当前注册的全部拓扑 id（去重保序）。"""
    try:
        from topology.topologies import TOPOLOGIES
        return list(TOPOLOGIES.keys())
    except Exception:
        return ["linear", "dag", "event", "hybrid", "scatter", "prefix"]


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

    # ① 缓存命中方案：按共享前缀聚合集群，命中索引增量蔓延
    if topology in ("prefix", "hybrid"):
        cache_plan = (
            f"共享前缀聚合为集群（缓存命中为索引）：同一 role 节点共享前缀只构造一次，"
            f"后续节点命中缓存只付增量差异 token；不同集群天然并行。规模 {tier}，{subtasks} 子任务 → 水龙头蔓延。"
        )
    elif topology in ("scatter", "scramble"):
        cache_plan = (
            f"一窝蜂高并发下：为同 role 共享上下文做前缀聚合，命中缓存增量推进，"
            f"避免每节点独立重构造完整上下文（降 token 降 bug）。并发 {concurrency}。"
        )
    else:  # dag 等常规拓扑
        cache_plan = (
            f"公司式分工（{topology}）：按 role 聚共享前缀，命中缓存增量蔓延，"
            f"常规规模 token 复用充分即可，不强制水龙头。"
        )

    # ② 分工方案：规模分层映射子任务分配策略
    if tier in ("large", "huge"):
        division_plan = (
            f"超大规模：中央调控先吃核心/高价值部分（内部消化），余量子任务一窝蜂瓜分补全；"
            f"或分形拆小组并行，各小组组长整合后统一向上交付。"
        )
    elif tier == "small":
        division_plan = f"小规模：不做重分工，{subtasks} 个子任务一窝蜂并行解决即可。"
    else:
        division_plan = f"中/大规模：公司式分工，按功能域拆分 {subtasks} 个子任务，并行推进。"

    # ③ 信息回传方案：子任务结果回传收口
    if topology in ("scatter", "scramble", "hybrid", "prefix"):
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
        merge_plan = f"常规规模：小组内按最小模块整合，统一提交交付。"

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
        "rule": "按任务规模分层选择拓扑（融合触发门控）",
        "tiers": {"small": "轻量一窝蜂", "medium": "公司式分工dag", "large": "公司式分工dag", "huge": "融合(hybrid/prefix)"},
        "trigger": {
            "scale_exceeded": "规模超默认框架承载 → 融合",
            "scattered_high_concurrency": "散沙型高并发 → 新框架一窝蜂",
        },
        "default_covers": "~98% 任务（中/大规模走 dag 公司式分工）",
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
            evaluate_scale(complexity=1, subtasks=2, concurrency=1, is_scattered=True),
            evaluate_scale(complexity=4, subtasks=10, concurrency=3),
            evaluate_scale(complexity=7, subtasks=25, concurrency=15),
        ]
        print(json.dumps(overview(samples), ensure_ascii=False, indent=2))
    else:
        print("用法: python3 topology/fusion.py --route --complexity N --subtasks N --concurrency N")
        print("      python3 topology/fusion.py --overview")
