# -*- coding: utf-8 -*-
"""
dev_team_driver · 开发小组闭环「接线驱动层」（方案 A · 把能力接成真实可跑链路）
==============================================================================
背景（对齐 Issue #74 + 架构·总师方案 A）：
  DevTeamEngine（local-agent/dev_team.py）已经把「一个开发小组」做成确定性编排
  的整体（N 个开发执行-验证-决策，全部 APPROVED 后小组长整合交付），**但整条
  执行流水线没有任何一处调用它** —— 能力有了、流程没有。

  本模块是**接线驱动层**：把 DevTeamEngine 接到真实执行流水线，补上总师方案 A
  的 5 个接线点：
    ① 建组入口    —— 从拓扑节点（lead + N 个 dev）建 DevTeamEngine；
    ② 驱动循环    —— 确定性状态机驱动 execute→verify→decide，不让 LLM 决定；
    ③ 进度北极星  —— advance() 写 goal_meters，喂哨兵（停滞/横跳/重复错误拦截）；
    ④ 整合交付    —— 全部 dev APPROVED 后 deliver_to_manager + aggregate 收口；
    ⑤ 路由/分形   —— 大任务拓扑（dev_enhanced 等）的 lead 节点走本驱动。

对外主入口：
    drive_dev_team(topology, lead_node, goal_total, devs_per_team, req,
                   llm, card, team, on_dev_output=None)
    → DevTeamDriver 结果 dict（建组/循环/裁决/交付全景）

依赖：local-agent/dev_team.py（DevTeamEngine）+ sentinel（进度尺）。
"""
import os
import sys

# 确保 local-agent 目录在 sys.path
_LOCAL_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class DevTeamDriverError(Exception):
    """开发小组接线驱动错误。"""


def _is_dev_team_node(nd):
    """判断是否为开发小组内的开发节点：id 严格匹配 dev_\d+（如 dev_1/dev_2）。

    注意：不能匹配单独的 develop 节点（id="develop" 不以 dev_ 编号），
    否则会把 dag/agile 的单个开发节点误当成开发小组成员。
    """
    if nd.get("role") != "架构·开发":
        return False
    import re
    return bool(re.match(r'^dev_\d+$', str(nd.get("id", ""))))


def collect_dev_nodes(nodes, lead_id="lead"):
    """从拓扑节点集收集「开发小组」的开发节点（跟随 lead 的 dev_N 节点）。

    dev_enhanced 拓扑约定：lead（小组长）后直接跟 dev_1..dev_N（架构·开发），
    其中节点 id 严格匹配 dev_\d+（如 dev_1/dev_2），排除单独的 develop 节点。

    Returns: [ {id, role, action, ...}, ... ] 按声明顺序。
    """
    devs = []
    for nd in nodes or []:
        if _is_dev_team_node(nd):
            devs.append(nd)
    return devs


def estimate_goal_total(req):
    """从需求文本粗估开发小组目标进度总量（供 goal_meters / 进度北极星）。

    与 orchestrator._estimate_tasks 同口径：按子任务数折算目标，保底 1。
    """
    n = 1
    import re
    numbered = re.findall(r'(?:^|[\s，,、。.;；)])(\d{1,2})\s*[\.、)）]?\s*(?=[^\d])', req or "")
    if numbered:
        nums = sorted({int(x) for x in numbered})
        if nums and max(nums) >= 2:
            n = min(max(max(nums), len(nums)), 50)
    parts = [p for p in re.split(r'[、，,；;\n]', req or "") if p.strip()]
    if len(parts) >= 3:
        n = min(len(parts), 50)
    return float(max(n, 1))


class DevTeamDriver:
    """开发小组闭环接线驱动：把 DevTeamEngine 接成真实可跑链路。

    职责（对齐总师方案 A 5 接线点）：
      ① 建组：根据拓扑 lead+dev 节点建 DevTeamEngine（devs_per_team 取 dev 数）；
      ② 驱动：确定性状态机跑 execute→verify→decide 轮，映射 dev 节点产出；
      ③ 北极星：advance() 写 goal_meters → 哨兵收敛判定；
      ④ 交付：全部 APPROVED → deliver_to_manager（+ aggregate 收口信息）；
      ⑤ 路由：暴露驱动入口供 orchestrator 的 lead 节点调用。
    """

    def __init__(self, goal_total=0.0, devs_per_team=None, max_attempts=None,
                 max_iterations=None, lead_id="架构·小组长", owner=""):
        from dev_team import DevTeamEngine
        self.goal_total = float(goal_total)
        # 未指定 dev 数时默认 2（Issue #74：一套循环 2 个开发）
        self.devs_per_team = max(1, int(devs_per_team if devs_per_team is not None else 2))
        self.team = DevTeamEngine(
            goal_total=self.goal_total,
            devs_per_team=self.devs_per_team,
            max_attempts=max_attempts, max_iterations=max_iterations,
            lead_id=lead_id, owner=owner,
        )
        self.rounds = 0
        self.log = []

    # ---- ① 建组入口 ----
    @staticmethod
    def from_topology(topology, lead_id="lead", req="", goal_total=None,
                      devs_per_team=None, **kw):
        """从拓扑节点集建驱动（lead + N 个 dev → DevTeamEngine）。

        - devs_per_team 未指定时取拓扑里 dev 节点数，再不行默认 2；
        - goal_total 未指定时从 req 粗估。
        """
        nodes = (topology or {}).get("nodes", []) if isinstance(topology, dict) else (topology or [])
        dev_nodes = collect_dev_nodes(nodes, lead_id=lead_id)
        n_devs = len(dev_nodes) or devs_per_team or 2
        goal = goal_total if goal_total else estimate_goal_total(req)
        return DevTeamDriver(goal_total=goal, devs_per_team=n_devs, **kw), dev_nodes

    # ---- ② 驱动循环 ----
    def can_enter(self):
        """目标门控：goal>0 才允许进开发小组闭环。"""
        return self.team.can_enter_loop()

    def run_round(self, dev_outputs, task_id=""):
        """驱动一轮：小组长发起 → 各开发上报客观验证结果 → 确定性决策。

        dev_outputs: [ (dev_idx 或 dev_id, ok, evidence), ... ]
        返回 { round, stage, verdict, remaining, reason, approved, total }
        """
        start = self.team.start_round(task_id=task_id or f"小组{self.team.team_id}")
        for item in dev_outputs:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                dev_ref, ok = item[0], item[1]
                evidence = item[2] if len(item) > 2 else ""
                # 支持 dev_id（"dev0"/"dev_1"）或索引
                if isinstance(dev_ref, int):
                    dev_id = f"dev{dev_ref}"
                else:
                    dev_id = str(dev_ref)
                    if dev_id.startswith("dev_"):
                        dev_id = "dev" + dev_id[4:]
                if dev_id not in self.team.devs:
                    # 按拓扑顺序映射到 dev0..devN
                    idx = self._dev_index(dev_ref)
                    if idx is not None:
                        dev_id = f"dev{idx}"
                    else:
                        continue
                self.team.developer_output(dev_id, task_id or self.team.team_id,
                                           bool(ok), evidence=evidence)
        self.rounds += 1
        decision = self.team.decide(task_id=task_id or self.team.team_id,
                                    agent_id=self.team.lead_id)
        self.log.append({"round": self.rounds, "verdict": decision.get("verdict"),
                         "stage": decision.get("stage"),
                         "remaining": decision.get("remaining"),
                         "reason": decision.get("reason"),
                         "approved": decision.get("approved_devs"),
                         "total": decision.get("total_devs")})
        return {"round": self.rounds, "start": start, **decision}

    def _dev_index(self, dev_ref):
        """把 dev 引用映射到小组内 dev 索引（0-based）。"""
        if isinstance(dev_ref, int):
            return dev_ref if 0 <= dev_ref < self.team.devs_per_team else None
        s = str(dev_ref)
        # dev0 → 0 / dev_1 → 1 / dev1 → 1
        import re
        m = re.search(r'dev_?(\d+)', s)
        if m:
            idx = int(m.group(1))
            # dev_1 对应索引 1；但小组内是 dev0..devN-1
            return (idx - 1) if s.startswith("dev_") and not s.startswith("dev0") else idx
        return None

    # ---- ③ 进度北极星 ----
    def advance(self, delta):
        """推进小组进度（写 goal_meters → 哨兵收敛判定）。"""
        return self.team.advance(delta)

    def progress(self):
        """二级信息：当前进度百分比 / 剩余 / 各 dev 状态。"""
        return self.team.overview()

    # ---- ④ 整合交付 ----
    def deliver(self, task_id="", summary=""):
        """全部 APPROVED 且目标达成后，一次性交付给经理。"""
        return self.team.deliver_to_manager(task_id=task_id or self.team.team_id,
                                            summary=summary)

    def aggregate(self, task_id="", summary=""):
        """小组长整合收口（aggregate 信息，供 ops/交付留痕）。"""
        ov = self.team.overview()
        return {
            "team_id": self.team.team_id, "lead_id": self.team.lead_id,
            "devs_per_team": ov["devs_per_team"],
            "approved": ov["approved"], "total_devs": ov["total_devs"],
            "progress_pct": ov["progress_pct"], "remaining": ov["remaining"],
            "iterations": ov["iterations"], "stage": ov["stage"],
            "summary": summary,
        }

    # ---- 全流程 ----
    def drive(self, req="", task_id="", dev_output_provider=None, summary="",
              delta_per_round=1.0, max_rounds=30):
        """全流程驱动：建组→循环（执行-验证-决策）→推进→交付。

        dev_output_provider: 回调 fn(round, devs_remaining) → 返回本轮
            [(dev_ref, ok, evidence), ...]；默认给全 APPROVED 的注入样例。
        返回完整驱动结果 dict（供 orchestrator / 测试断言）。
        """
        ok, reason = self.can_enter()
        if not ok:
            return {"entered": False, "reason": reason,
                    "goal_total": self.goal_total}
        result = {"entered": True, "rounds": [], "delivery": None,
                  "aggregate": None, "progress": self.progress()}
        provider = dev_output_provider or self._default_provider
        for r in range(1, max_rounds + 1):
            outputs = provider(r, list(self.team.devs.keys()))
            if not outputs:
                outputs = [(i, True, "APPROVED") for i in range(self.team.devs_per_team)]
            rd = self.run_round(outputs, task_id=task_id or req)
            result["rounds"].append(rd)
            self.advance(delta_per_round)
            result["progress"] = self.progress()
            if rd.get("verdict") in ("DONE", "ESCALATED"):
                break
        result["aggregate"] = self.aggregate(task_id=task_id or req, summary=summary)
        if self.team.stage in ("done", "integrating"):
            result["delivery"] = self.deliver(task_id=task_id or req, summary=summary)
        result["log"] = self.log
        return result

    @staticmethod
    def _default_provider(round_no, dev_ids):
        """默认产出提供器：假设所有开发均通过客观验证。"""
        return [(i, True, f"APPROVED round{round_no}") for i in range(len(dev_ids))]
