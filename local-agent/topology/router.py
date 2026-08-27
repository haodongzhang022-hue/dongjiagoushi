# -*- coding: utf-8 -*-
"""
融合路由接线层（Router · 把融合引擎接入真实执行链路）
=====================================================
打通「架构意图 → 真实执行」的关键断点：

  - `fusion.py` 已有完整的「规模金字塔 → 承接体系 → 拓扑选择」规则引擎；
  - `topologies.py` 已有各拓扑的节点定义（agile/dag/prefix/scatter/hybrid/event/linear）；
  - **但 `orchestrator.run_pipeline` 硬编码只走 team.yaml 的 dag**，从不 consult
    fusion.route() —— 即「小任务该走敏捷(3角色)、大任务该走完整体系」的架构意图，
    只停留在演示，实际跑起来全走 dag。

本模块是**接线层**：把「需求 → 规模评估 → 拓扑选择 → 可执行节点集」串成一条 API，
供 `run_pipeline` 在启动时按规模选择并执行对应拓扑，形成「规模→拓扑→执行」闭环。

对外唯一主入口：
    route_pipeline(req, preset=None, complexity=None, subtasks=None,
                   concurrency=None, is_scattered=None, force=None)
    → { selected, tier, system, reason, nodes, plan, slim, signals }

与老行为关系：
    - `use_fusion=False`（run.py 的 --no-fusion）时，run_pipeline 仍走 team.yaml 老 dag；
    - `force=<topo_id>`（run.py 的 --topo）时，显式指定拓扑，绕过规模评估。
"""
import os
import re
import sys

# 允许被 orchestrator 直接 import（已在 local-agent/ 包根）
_here = os.path.dirname(os.path.abspath(__file__))
_pkg = os.path.dirname(_here)          # local-agent/ 包根
if _pkg not in sys.path:
    sys.path.insert(0, _pkg)

from topology import fusion, topologies


# ---------------------------------------------------------------------------
# 从需求文本估算规模信号（当显式信号未给出时）
# ---------------------------------------------------------------------------
def estimate_complexity(req):
    """从需求文本粗略估算复杂度（0~10）。

    启发式：
      - 含架构/系统/平台/并发/兼容/安全/大型等强架构词 → 提高复杂度；
      - 含"改一下/修个 bug/优化/补个/简单/小"等弱词 → 降低复杂度；
      - 文本越长、涉及环节越多 → 越复杂。
    返回 0~10 整数。
    """
    if not req:
        return 1
    strong = ["架构", "系统", "平台", "并发", "兼容", "安全", "大型", "完整",
              "企业", "多部门", "扩展", "性能", "重构", "集成", "分布式"]
    weak = ["改一下", "修", "bug", "优化", "补", "简单", "小修", "调整",
            "单点", "字段", "文案", "样式"]
    s = sum(1 for w in strong if w in req)
    w = sum(1 for w in weak if w in req)
    base = min(10, 2 + s * 2 - w)
    base = max(1, min(10, base + len(req) // 120))
    return base


def estimate_subtasks(req):
    """从需求文本粗略估算子任务数（对齐 orchestrator._estimate_tasks 的口径）。"""
    if not req:
        return 1
    # ① 显式编号条目
    numbered = re.findall(r'(?:^|[\s，,、。.;；)])(\d{1,2})\s*[\.、)）]?\s*(?=[^\d])', req)
    if numbered:
        nums = sorted({int(x) for x in numbered})
        if nums and max(nums) >= 2:
            return min(max(max(nums), len(nums)), 50)
    # ② 顿号/逗号/分号分隔条目
    parts = [p for p in re.split(r'[、，,；;\n]', req) if p.strip()]
    if len(parts) >= 3:
        return min(len(parts), 50)
    # ③ 兜底按长度
    return min(max(1, len(req) // 40), 50)


def estimate_concurrency(req):
    """从需求文本粗略估算预期并发（默认 1，含"2500/大量/并发"等词提高）。"""
    if not req:
        return 1
    if re.search(r'2500|并发|高并发|大量|并行', req):
        return 15
    return 1


# ---------------------------------------------------------------------------
# 主接线入口：需求 → 规模评估 → 拓扑选择 → 可执行节点集
# ---------------------------------------------------------------------------
def route_pipeline(req, preset=None, complexity=None, subtasks=None,
                   concurrency=None, is_scattered=None, force=None,
                   available=None):
    """把需求路由到可执行的拓扑节点集（融合路由接线层主入口）。

    参数：
      - req:            用户需求文本（用于估算规模信号，显式信号优先）
      - preset:         规模预设结果（prescale 产物，可含 complexity_hint/subtasks 等）
      - complexity:     显式复杂度分（0~10，None 则从 req 估算）
      - subtasks:       显式子任务数（None 则从 req 估算）
      - concurrency:    显式并发量（None 则从 req 估算）
      - is_scattered:   是否零散（None 则由 fusion 按并发/子任务数判定）
      - force:          显式指定拓扑 id（绕过规模评估，直接用它）
      - available:      可用的拓扑 id 子集

    返回：
      { selected, tier, system, reason, nodes, plan, slim, signals, estimated }
      - selected:  最终选定的拓扑 id
      - nodes:     该拓扑的可执行节点列表（来自 topologies.TOPOLOGIES）
      - plan:      fusion.build_plan 的四套配套方案
      - slim:      精简体系角色子集（slim.slim_route）
      - estimated: 本次评估所用的规模信号（便于留痕/调试）
    """
    if preset:
        complexity = complexity if complexity is not None else preset.get("complexity_hint")
        subtasks = subtasks if subtasks is not None else preset.get("subtasks")

    # 规模信号：显式 > preset > 文本估算
    c = complexity if complexity is not None else estimate_complexity(req or "")
    s = subtasks if subtasks is not None else estimate_subtasks(req or "")
    k = concurrency if concurrency is not None else estimate_concurrency(req or "")
    # 规模信号归一到 fusion 口径
    if isinstance(c, str):
        c = {"simple": 1, "medium": 4, "complex": 8}.get(c, 1)

    # 显式指定拓扑（绕过规模评估）
    if force:
        try:
            topo = topologies.get_topology(force)
        except ValueError:
            raise ValueError(
                f"未知拓扑：{force}，可选：{list(topologies.TOPOLOGIES.keys())}"
            )
        nodes = [dict(n) for n in topo["nodes"]]
        scale = fusion.evaluate_scale(complexity=c, subtasks=s, concurrency=k,
                                      is_scattered=is_scattered)
        return {
            "selected": force,
            "tier": scale["tier"],
            "system": scale["system"],
            "reason": f"显式指定拓扑 {force}（绕过规模评估）",
            "nodes": nodes,
            "plan": fusion.build_plan(force, scale),
            "slim": fusion.slim_route(scale["tier"]),
            "signals": scale["signals"],
            "estimated": {"complexity": c, "subtasks": s, "concurrency": k,
                          "is_scattered": is_scattered},
        }

    # 常规：融合路由选拓扑
    routed = fusion.route(complexity=c, subtasks=s, concurrency=k,
                          is_scattered=is_scattered, available=available)
    selected = routed["selected"]
    try:
        topo = topologies.get_topology(selected)
    except ValueError:
        # 兜底：选中的拓扑不存在（如 scramble 未注册）→ 回退 dag
        selected = "dag"
        topo = topologies.get_topology("dag")

    nodes = [dict(n) for n in topo["nodes"]]
    result = {
        "selected": selected,
        "tier": routed["tier"],
        "system": routed["system"],
        "reason": routed["reason"],
        "nodes": nodes,
        "plan": routed["plan"],
        "slim": routed["slim"],
        "signals": routed["signals"],
        "estimated": {"complexity": c, "subtasks": s, "concurrency": k,
                      "is_scattered": is_scattered},
    }
    return result


def route_for_tier(tier, available=None):
    """按档位直接路由（不依赖文本估算，供测试/单测用）。

    tier: micro/small/medium/large/huge
    """
    c = {"micro": 0, "small": 2, "medium": 4, "large": 7, "huge": 9}[tier]
    s = {"micro": 1, "small": 3, "medium": 10, "large": 25, "huge": 60}[tier]
    k = 15 if tier in ("large", "huge") else 3
    return route_pipeline(None, complexity=c, subtasks=s, concurrency=k,
                          available=available)


def overview(samples=None):
    """二级信息：各档位路由到的拓扑 + 节点数（供人类俯瞰/测试断言）。"""
    rows = []
    for tier in ["micro", "small", "medium", "large", "huge"]:
        r = route_for_tier(tier)
        rows.append({
            "tier": tier,
            "selected": r["selected"],
            "nodes": len(r["nodes"]),
            "system": r["system"],
            "roles": r["slim"]["roles"],
        })
    return {
        "rule": "融合路由接线层：规模→拓扑→可执行节点集（run_pipeline 按此动态执行）",
        "rows": rows,
    }


# CLI 入口
if __name__ == "__main__":
    import json as _json
    args = sys.argv[1:]
    if "--overview" in args:
        print(_json.dumps(overview(), ensure_ascii=False, indent=2))
    elif "--route" in args:
        def _arg(name, default=None):
            for i, a in enumerate(args):
                if a == name and i + 1 < len(args):
                    return args[i + 1]
            return default
        req = _arg("--req", "")
        force = _arg("--force")
        c = _arg("--complexity")
        s = _arg("--subtasks")
        k = _arg("--concurrency")
        r = route_pipeline(
            req,
            complexity=int(c) if c else None,
            subtasks=int(s) if s else None,
            concurrency=int(k) if k else None,
            force=force,
        )
        print(_json.dumps({
            "selected": r["selected"], "tier": r["tier"], "system": r["system"],
            "reason": r["reason"], "node_count": len(r["nodes"]),
            "estimated": r["estimated"],
        }, ensure_ascii=False, indent=2))
    else:
        print("用法: python3 topology/router.py --overview")
        print("      python3 topology/router.py --route --req '大型系统' [--force prefix]")
