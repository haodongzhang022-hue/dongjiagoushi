# -*- coding: utf-8 -*-
"""
本地 Agent · 有向无环图（DAG）调度引擎
=========================================
把「直线流水线」升级为「DAG 工作流」，支持：
  - 并行波次执行：依赖满足的任务在同一波次并行推进（不再傻等上一环全完成）；
  - 提前分工：架构·总师一给出架构方案，架构·经理即可开始任务分配/分工，
    不必等下游开发完成；
  - 分形扩展：开发任务可按规模分形为多个小组并行（见 fractal.py）；
  - 分支合并：下游「小组长整合 / 测试 / 交付」等节点等待上游多路汇聚后再执行。

设计原则（对齐 AGENTS.md）：
  - AI 优先：节点/边/状态结构化、可索引、可追踪；执行进度留痕接力卡。
  - 完整不残次：不做"先跑通"的残缺骨架，一次性提供可用 DAG 调度。
  - 回转/打断协议沿用：任何节点可 [回转] 打回、[打断] 续跑。

DAG 由「节点（node）+ 依赖边（edge）」描述。节点定义：
    {
      "id": "architect",                # 唯一节点 id
      "role": "架构·总师",              # 承担角色（或 "编排引擎" 内建）
      "action": "架构设计核心",
      "depends_on": ["clarify"],        # 依赖的节点 id 列表（前置完成后才可执行）
    }

调度执行：采用「拓扑 + 波次」——
  1. 计算每个节点的入度；
  2. 每轮把所有「依赖已全部满足且未执行」的节点放入同一波次并行执行；
  3. 全部执行完成即 DAG 跑完。
"""

from collections import deque


class DagEngine:
    """DAG 工作流调度引擎。"""

    def __init__(self, name, description="", nodes=None):
        self.name = name
        self.description = description
        # 归一化节点：确保每节点有 depends_on / role / action
        self.nodes = {}
        for n in nodes or []:
            self.add_node(n)

    # ---------- 图构建 ----------
    def add_node(self, node):
        nid = node["id"]
        self.nodes[nid] = {
            "id": nid,
            "role": node.get("role", "编排引擎"),
            "action": node.get("action", ""),
            "depends_on": list(node.get("depends_on", []) or []),
            # 分形配置（可选）
            "fractal": node.get("fractal"),
        }

    def nodes_sorted(self):
        """按拓扑序返回节点 id 列表（用于静态校验/索引）。"""
        return self._topo_order()

    # ---------- 拓扑校验 ----------
    def _topo_order(self):
        """Kahn 拓扑排序，返回顺序列表；存在环则抛出异常。"""
        indeg = {nid: 0 for nid in self.nodes}
        adj = {nid: [] for nid in self.nodes}
        for nid, nd in self.nodes.items():
            for dep in nd["depends_on"]:
                if dep not in self.nodes:
                    raise ValueError(f"节点 {nid} 依赖不存在的节点 {dep}")
                adj[dep].append(nid)
                indeg[nid] += 1
        q = deque([nid for nid, d in indeg.items() if d == 0])
        order = []
        while q:
            cur = q.popleft()
            order.append(cur)
            for nxt in adj[cur]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    q.append(nxt)
        if len(order) != len(self.nodes):
            raise ValueError("DAG 存在环，无法调度")
        return order

    def validate(self):
        """校验 DAG 合法性；返回 (ok, error)。"""
        try:
            self._topo_order()
        except ValueError as e:
            return False, str(e)
        return True, ""

    # ---------- 波次调度 ----------
    def waves(self):
        """把节点按「可并行波次」分组。

        返回：list of list —— 每个内层 list 是可在同一波次并行执行的节点 id 列表。
        同一波次内的节点互不依赖，可并行。
        """
        done = set()
        remaining = set(self.nodes.keys())
        waves = []
        while remaining:
            wave = [
                nid
                for nid in remaining
                if all(d in done for d in self.nodes[nid]["depends_on"])
            ]
            if not wave:
                # 无进展且仍有剩余 → 说明存在环（理论上 validate 已拦截）
                raise ValueError("DAG 存在环或不可达节点，无法推进")
            waves.append(wave)
            done.update(wave)
            remaining.difference_update(wave)
        return waves


def build_dag_from_steps(steps):
    """把旧的 `pipeline.steps`（顺序步骤列表）转换为线性 DAG。

    用于兼容：没有显式依赖信息时，把相邻步骤串成链式依赖。
    """
    nodes = []
    prev = None
    for s in steps:
        nid = s["step"]
        nodes.append(
            {
                "id": nid,
                "role": s.get("role", "编排引擎"),
                "action": s.get("action", ""),
                "depends_on": [prev] if prev else [],
            }
        )
        prev = nid
    return DagEngine(
        name="linear", description="由顺序步骤生成的线性 DAG", nodes=nodes
    )
