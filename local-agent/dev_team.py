# -*- coding: utf-8 -*-
"""
dev_team · 开发小组闭环引擎（Dev Team Engine）
==============================================
参考 Goose「执行-验证-规划-监督」四维闭环，把「一个开发小组」
（小组长 + N 个开发）作为一个**确定性编排的整体**来驱动，深化结构升级。

背景（对齐用户诉求 · Issue #74）：
  - 开发是真正持续推进度的核心，辅助多则浪费 → 一套循环配 N 个开发（默认 2）；
  - 单 Agent 自己写码又自己判断「是否完成」极易陷入死循环 → 必须由确定性代码控制；
  - 「开发没干完继续接开发」可能陷入循环 → 用确定性状态机 + 进度北极星管住。

与单开发 dev-loop 的层次关系（深化结构）：
  ┌──────────────────────────────────────────────────────────────┐
  │  DevTeamEngine（小组级确定性 Orchestrator · 本模块）           │
  │  ┌────────────────────────────────────────────────────────┐  │
  │  │  小组长(team_lead)：拆解任务 / 整合产出                  │  │
  │  │  ┌──────────────────────────────────────────────────┐  │  │
  │  │  │  dev[0] 开发闭环    dev[1] 开发闭环  ... N 个开发    │  │  │
  │  │  │  execute→verify→rework(≤max_attempts)            │  │  │
  │  │  └──────────────────────────────────────────────────┘  │  │
  │  │  仅在「全部 dev 产出 APPROVED」后 → 小组长整合 → 统一交付  │  │
  │  └────────────────────────────────────────────────────────┘  │
  └──────────────────────────────────────────────────────────────┘
  硬性熔断 + 进度北极星监督贯穿每一层。

对照 Goose 四维闭环映射：
  - Planner/Leader（规划）  → 任务分解 + 全局状态：小组长拆子任务、定整合时机；
  - Coder/Executor（执行）  → N 个「架构·开发」并行实现，只做不判；
  - Reviewer/Critic（验证） → 客观验证器（测试/lint 的 APPROVED/REJECTED）；
  - Orchestrator（监督）     → 本引擎本身：确定性状态机，只有 APPROVED 才放行整合。

核心原则：
  1. **开发小组作为一个整体**：小组长只在所有 dev 产出通过客观验证后才整合交付；
  2. **执行-验证分离**：dev 不自行裁定「我完成了」，由客观验证器判定；
  3. **确定性状态机**：不让 LLM 决定「下一步/是否结束」，代码决定；
  4. **硬性熔断**：单 dev 重做超 max_attempts 上报 Leader，总迭代超上限熔断，
     空闲超时判卡死——防止单 Agent 自循环失控；
  5. **进度北极星监督**：写 goal_meters，停滞/横跳/重复错误由监控哨兵拦截；
  6. **记录优先于对话**：过程只写进度留痕 + 存档，不打断经理；
     干完调 deliver_to_manager 一次性交付。

用法：
    from dev_team import DevTeamEngine
    team = DevTeamEngine(goal_total=10.0, devs_per_team=2,
                         max_attempts=3, max_iterations=20)
    # 每轮：
    #   team.start_round(team_id, lead_id)          # 小组长发起一轮
    #   team.developer_output(dev_id, task_id, ok, evidence)  # 某开发客观验证结果
    #   team.decide()  → { verdict, stage, remaining, ... }   确定性决策
    #   完成 → team.deliver_to_manager(...)         一次性交付
"""
import os
import sys
import time
import uuid

# 确保 local-agent 目录在 sys.path
_LOCAL_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

# ---- 默认硬性熔断参数（Goose：max_attempts 后上报 Leader，不无限重试） ----
DEFAULTS = {
    "devs_per_team": 2,         # ★ Issue #74：一套循环配 N 个开发（默认 2）
    "max_attempts": 3,          # 同一子任务/同一 dev 最多重做次数，超过→上报Leader
    "max_iterations": 20,       # 一次开发小组闭环最多总迭代轮数（硬性上限）
    "max_idle_seconds": 1800,   # 单轮最长空闲秒数（30 分钟无进展视为卡死）
    "goal_eps": 0.0001,         # 完成判定：remaining 低于该值视为已完成
}

# 确定性状态机阶段（团队层面）
STAGES = ("forming", "executing", "verifying", "integrating", "done", "escalated")


class DevTeamError(Exception):
    """开发小组引擎错误。"""


class DevTeamEngine:
    """开发小组闭环引擎：确定性状态机 + 硬性熔断 + 进度北极星监督。

    一个小组成为了一个整体：N 个开发在小组长（Orchestrator）编排下各自跑
    「执行→验证→(重做|放行)」闭环，全部 APPROVED 后小组长整合并统一交付。
    """

    def __init__(self, goal_total=0.0, devs_per_team=None, max_attempts=None,
                 max_iterations=None, max_idle_seconds=None, team_id=None,
                 lead_id="架构·小组长", owner=""):
        self.team_id = team_id or f"team-{uuid.uuid4().hex[:8]}"
        self.lead_id = lead_id
        self.owner = owner
        self.goal_total = float(goal_total or 0.0)
        self.current = 0.0
        self.devs_per_team = max(1, int(devs_per_team if devs_per_team is not None
                                         else DEFAULTS["devs_per_team"]))
        self.max_attempts = int(max_attempts if max_attempts is not None
                                else DEFAULTS["max_attempts"])
        self.max_iterations = int(max_iterations if max_iterations is not None
                                  else DEFAULTS["max_iterations"])
        self.max_idle_seconds = int(max_idle_seconds if max_idle_seconds is not None
                                    else DEFAULTS["max_idle_seconds"])
        self.eps = DEFAULTS["goal_eps"]

        # 确定性状态机
        self.stage = "forming"          # forming→executing→verifying→integrating→done/escalated
        self.iterations = 0             # 总迭代轮数
        self._last_activity = time.time()

        # 每个 dev 的产出与重做计数（防无限重试）
        #   devs[dev_id] = { "task": ..., "attempts": 0, "approved": False, "evidence": "" }
        self.devs = {}
        for i in range(self.devs_per_team):
            self.devs[f"dev{i}"] = {"task": "", "attempts": 0,
                                    "approved": False, "evidence": ""}

        # 进度尺（goal_meters）留痕
        self.meter_id = f"gm-{self.team_id}"
        self.goal_eps = self.eps

    # ---------- 目标门控（Planner：goal>0 才允许进小组循环） ----------
    def can_enter_loop(self):
        """任务目标明确(goal>0) 才允许进入开发小组闭环，否则拒绝。

        Returns: (bool, reason)
        """
        if self.goal_total <= 0:
            return False, "目标未量化(goal<=0)，不可进入小组开发闭环"
        return True, "目标明确，允许进入小组开发闭环"

    # ---------- 确定性状态机驱动 ----------
    def start_round(self, task_id="", note=""):
        """小组长发起一轮小组循环（forming→executing）。

        Returns: { round, stage, devs_per_team, remaining }
        """
        self._touch()
        self.iterations += 1
        if self.iterations > self.max_iterations:
            self.stage = "escalated"
            return self.decide()
        self.stage = "executing"
        return {
            "round": self.iterations,
            "stage": self.stage,
            "devs_per_team": self.devs_per_team,
            "task": task_id or f"小组{self.team_id} 并行开发",
            "remaining": self._remaining(),
        }

    def developer_output(self, dev_id, task_id, ok, evidence="", by="客观验证器"):
        """某开发一次「执行→客观验证」的结果上报。

        ok=True  → APPROVED（该开发产出通过客观验证）
        ok=False → REJECTED（需重做，attempts+1，超 max_attempts 上报 Leader）
        """
        self._touch()
        if dev_id not in self.devs:
            raise DevTeamError(f"未知开发 {dev_id}，本小组只有 {sorted(self.devs)}")
        d = self.devs[dev_id]
        d["task"] = task_id or d["task"]
        if not ok:
            d["attempts"] += 1
            d["evidence"] = evidence
            if d["attempts"] > self.max_attempts:
                self.stage = "escalated"   # 同一子任务超限 → 上报 Leader 换方案
                return {"dev": dev_id, "approved": False,
                        "escalated": True, "attempts": d["attempts"],
                        "reason": "超 max_attempts 上报 Leader 换方案（非无限重试）"}
            return {"dev": dev_id, "approved": False,
                    "escalated": False, "attempts": d["attempts"],
                    "reason": "REJECTED，需重做"}
        d["approved"] = True
        d["evidence"] = evidence or "APPROVED"
        return {"dev": dev_id, "approved": True,
                "escalated": False, "attempts": d["attempts"]}

    def decide(self, task_id="", agent_id=""):
        """确定性状态机决策：只有「全部 dev 产出 APPROVED」才放行整合。

        Returns: { verdict, stage, remaining, reason, approved_devs, total_devs }
        """
        self._touch()
        approved = sum(1 for d in self.devs.values() if d["approved"])
        total = len(self.devs)
        if self.stage == "escalated":
            return {
                "verdict": "ESCALATED", "stage": self.stage,
                "remaining": self._remaining(),
                "reason": "开发小组超限（单dev重做超max_attempts 或 总迭代超max_iterations），"
                          "上报 Leader 换方案/重新规划，不无限重试",
                "approved_devs": approved, "total_devs": total,
            }
        if approved < total:
            self.stage = "executing"
            return {
                "verdict": "REWORK", "stage": self.stage,
                "remaining": self._remaining(),
                "reason": f"小组尚未全部产出通过客观验证（{approved}/{total} 个 dev APPROVED），"
                          "未通过者需重做",
                "approved_devs": approved, "total_devs": total,
            }
        # 全部 APPROVED → 小组长整合
        if self._remaining() <= self.eps:
            self.stage = "done"
            return {
                "verdict": "DONE", "stage": self.stage,
                "remaining": self._remaining(),
                "reason": "小组全部 dev 产出 APPROVED 且目标达成，可整合交付",
                "approved_devs": approved, "total_devs": total,
            }
        # 全部 APPROVED 但目标未满 → 继续下一阶段（如多轮迭代推进）
        self.stage = "integrating"
        return {
            "verdict": "INTEGRATE", "stage": self.stage,
            "remaining": self._remaining(),
            "reason": "小组全部 dev 产出 APPROVED，进入整合阶段（当前进度未满目标）",
            "approved_devs": approved, "total_devs": total,
        }

    # ---------- 进度与熔断 ----------
    def advance(self, delta):
        """推进小组进度（目标北极星），写 goal_meters 刻度。"""
        self._touch()
        self.current = min(self.goal_total, self.current + float(delta))
        return self._record_meter(note=f"小组推进 delta={delta}")

    def _remaining(self):
        return max(0.0, self.goal_total - self.current)

    def _record_meter(self, note=""):
        """写 goal_meters 进度尺（哨兵收敛检测）。"""
        try:
            import sentinel.engine as sentinel
            sentinel.init()
            result = sentinel.track(
                self.meter_id, task_id=self.team_id, agent_id=self.lead_id,
                target=self.goal_total, current=self.current, note=note,
            )
            return {"meter_id": self.meter_id, "current": self.current,
                    "goal_total": self.goal_total, "analysis": result.get("analysis", {})}
        except Exception as exc:  # pragma: no cover - 非关键路径
            return {"meter_id": self.meter_id, "current": self.current,
                    "goal_total": self.goal_total, "error": str(exc)}

    def check_idle_timeout(self):
        """空闲超时判定（卡死检测）。Returns: (timeout: bool, idle_seconds)"""
        idle = time.time() - self._last_activity
        return idle > self.max_idle_seconds, int(idle)

    def _touch(self):
        self._last_activity = time.time()

    # ---------- 交付 ----------
    def deliver_to_manager(self, task_id="", summary="", archive_kind="delivery"):
        """小组完成 → 一次性交付给经理（含进度回放 + 存档，经理零打扰）。"""
        self._touch()
        record = {
            "team_id": self.team_id, "lead_id": self.lead_id,
            "devs_per_team": self.devs_per_team,
            "goal_total": self.goal_total, "current": self.current,
            "remaining": self._remaining(),
            "iterations": self.iterations,
            "approved_devs": sum(1 for d in self.devs.values() if d["approved"]),
            "total_devs": len(self.devs),
            "stage": self.stage,
            "summary": summary,
        }
        try:
            from data import admin, schema
            schema.init_schema()
            admin.record_event(
                self.lead_id, "dev_team_deliver",
                {"team_id": self.team_id, "devs_per_team": self.devs_per_team,
                 "remaining": self._remaining(), "summary": summary},
                task_id or self.team_id,
            )
        except Exception:  # pragma: no cover
            pass
        # 进度刻度
        self._record_meter(note=f"交付 summary={summary[:50]}")
        return record

    # ---------- 二级信息 ----------
    def overview(self):
        """小组循环俯瞰（供小组长/经理/人类监控）。"""
        return {
            "team_id": self.team_id, "lead_id": self.lead_id,
            "stage": self.stage, "devs_per_team": self.devs_per_team,
            "iterations": self.iterations,
            "progress_pct": round(self.current / self.goal_total * 100, 1) if self.goal_total else 0.0,
            "approved": sum(1 for d in self.devs.values() if d["approved"]),
            "total_devs": len(self.devs),
            "remaining": self._remaining(),
            "devs": {k: {"attempts": v["attempts"], "approved": v["approved"]}
                     for k, v in self.devs.items()},
        }


def run_single_round(team_id, goal_total, current, dev_outputs,
                     devs_per_team=2, max_attempts=3, max_iterations=20):
    """便捷函数：构造小组引擎并执行一轮确定性决策。

    dev_outputs: list[ (dev_id, ok, evidence) ]，一轮内各开发客观验证结果。
    Returns: (engine, decision)
    """
    eng = DevTeamEngine(goal_total=goal_total, devs_per_team=devs_per_team,
                        max_attempts=max_attempts, max_iterations=max_iterations,
                        team_id=team_id)
    eng.current = float(current)
    eng.start_round(task_id=team_id)
    for dev_id, ok, evidence in dev_outputs:
        eng.developer_output(dev_id, team_id, ok, evidence=evidence)
    return eng, eng.decide()
