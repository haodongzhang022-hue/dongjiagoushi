# -*- coding: utf-8 -*-
"""
dev_loop · 开发闭环引擎（Dev Loop Engine）
==========================================
参考 Goose 的「执行-验证-规划-监督」四维闭环，把开发自循环从
「单 Agent 自己写码 + 自己判断是否继续/结束」升级为 **确定性代码控制流程**：

  ┌──────────────────────────────────────────────────────────────┐
  │  Orchestrator（本引擎，确定性代码）· 不让 LLM 决定下一步/是否结束  │
  │                                                                │
  │  PLANNER(目标明确) → CODER(执行产出) → VERIFIER(客观验证)       │
  │      ▲                               │                        │
  │      └── REJECTED(重做,≤max_attempts) │ APPROVED → 完成/下一阶段 │
  │                                        │ FAIL超限 → 上报Leader  │
  └──────────────────────────────────────────────────────────────┘

对照 Goose 四维闭环的映射：
  - **Planner/Leader（规划）** → 任务分解 + 全局状态追踪：接入 dispatch_engine（目标明确
    goal>0 才允许进循环），Leader 不参与编码，仅根据验证反馈调整策略。
  - **Coder/Executor（执行）** → 代码生成/修改：只负责「做」，不负责「判」——本引擎的
    coder 阶段产出 diff/commit，绝不自行裁定是否合格。
  - **Reviewer/Critic（验证）** → 独立于 Coder 的客观验证：verifier 用 **objective_verdict**
    （真实测试/lint/静态检查结果 APPROVED/REJECTED），不用主观判断。
  - **Orchestrator/Router（监督/确定性控制）** → **本引擎本身**：非 LLM 的确定性状态机，
    只有 verifier 返回 APPROVED 才放行进下一阶段，否则强制回退给 coder 重做，
    最多 N 次后上报 Leader；并接入 sentinel 进度北极星做停滞/横跳/重复错误拦截。

核心原则（对标 Goose）：
  1. 至少分离「执行」与「验证」两个角色——这是最小有效多智能体单元；
  2. 用确定性代码控制流程——不让 LLM 决定「下一步做什么」或「是否结束」；
  3. 验证必须用客观结果（测试/lint），纯文本审核效果有限；
  4. 设置硬性熔断——最大重试次数 + 最大迭代 + 时间上限，防止资源耗尽；
  5. Leader 定策略，执行/验证快跑，兼顾质量与成本。

使用方式：
    from dev_loop import DevLoopEngine
    engine = DevLoopEngine(goal_total=10.0, max_attempts=3, max_iterations=20)
    # 每轮：
    #   coder 产出 → engine.start_iteration(task_id, agent_id)
    #   客观验证 → engine.verify(approved=True/False, evidence="...")
    #   engine.decide()  → 返回 { verdict, stage, remaining, reason } 确定性决策
    #   完成 → engine.deliver_to_manager(...) 一次性交付
"""
import os
import sys
import time
import uuid

# 确保 local-agent 目录在 sys.path
_LOCAL_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

# ---- 默认硬性熔断参数（Goose：max_attempts 之后上报 Leader，不无限重试） ----
DEFAULTS = {
    "max_attempts": 3,          # 同一子任务最多重做次数，超过→上报Leader（非无限重试）
    "max_iterations": 20,       # 一次开发闭环最多总迭代轮数（硬性上限，防资源耗尽）
    "max_idle_seconds": 1800,   # 单轮最长空闲秒数（30 分钟无进展视为卡死）
    "goal_eps": 0.0001,         # 完成判定：remaining 低于该值视为已完成
}


class DevLoopError(Exception):
    """开发闭环异常（如熔断触发、参数非法）。"""


class DevLoopEngine:
    """Goose 风格开发闭环引擎：确定性状态机 + 执行验证分离 + 硬性熔断。

    角色定位：本引擎即 **Orchestrator**（非 LLM 的确定性代码），控制
    「规划→执行→验证→(重做/完成)」流转，不让 LLM 自行决定下一步或是否结束。
    """

    def __init__(self, goal_total=0.0, max_attempts=None, max_iterations=None,
                 max_idle_seconds=None, goal_eps=None, params=None):
        if goal_total <= 0:
            raise DevLoopError(
                f"目标总量必须 >0（goal_total={goal_total}）。"
                f"目标不明确(gid={getattr(self, 'loop_id', '')})拒绝进入循环——"
                f"Goose 原则：Planner 先明确目标，Coder 才允许开工。"
            )
        self.goal_total = float(goal_total)
        params = params or {}
        self.max_attempts = int(params.get("max_attempts", max_attempts or DEFAULTS["max_attempts"]))
        self.max_iterations = int(params.get("max_iterations", max_iterations or DEFAULTS["max_iterations"]))
        self.max_idle_seconds = int(params.get("max_idle_seconds", max_idle_seconds or DEFAULTS["max_idle_seconds"]))
        self.goal_eps = float(params.get("goal_eps", goal_eps or DEFAULTS["goal_eps"]))
        # 闭环状态（确定性状态机）
        self.loop_id = f"loop-{uuid.uuid4().hex[:8]}"
        self.phase = "idle"          # idle→plan→execute→verify→(rework|done)
        self.attempts = 0            # 同一子任务已重做次数
        self.iterations = 0          # 已迭代总轮数
        self.current = 0.0           # 进度北极星 current
        self.last_timestamp = 0.0    # 最近一次推进时间戳（空闲超时判定）
        self.verdict = None          # 最近验证结论 {approved, evidence, by}
        self.leader_escalated = False  # 是否已上报 Leader

    # ------------------------------------------------------------
    # Orchestrator：确定性状态机控制流转（不让 LLM 决定下一步/是否结束）
    # ------------------------------------------------------------
    def can_enter_loop(self):
        """Planner 门控：任务明确（goal>0 且未完成且未熔断）才允许进循环。"""
        if self.goal_total <= 0:
            return False, "goal_total<=0，任务不明确，拒绝进入循环"
        if self.current >= self.goal_total - self.goal_eps:
            return False, f"已完成(current={self.current}>=goal={self.goal_total})，无需循环"
        if self.iterations >= self.max_iterations:
            return False, f"已达最大迭代上限({self.max_iterations})，熔断"
        if self.leader_escalated:
            return False, "已上报 Leader，等待决策，禁止自行继续"
        return True, "任务明确且未完成且未熔断，可进入开发闭环"

    def start_iteration(self, task_id, agent_id, target="", note=""):
        """Coder 开工：确定性记录进入 execute 阶段，并登记进度北极星刻度。

        返回 { loop_id, iteration, phase, remaining, can_continue }。
        """
        ok, why = self.can_enter_loop()
        if not ok:
            raise DevLoopError(f"[start_iteration] 拒绝开工：{why}")
        self.phase = "execute"
        self.iterations += 1
        self.last_timestamp = time.time()
        # 记录进度刻度（供哨兵收敛判定，Goose: 每次推进留痕）
        meter = self._record_meter(task_id, agent_id, target, note)
        return {
            "loop_id": self.loop_id,
            "iteration": self.iterations,
            "phase": self.phase,
            "remaining": self._remaining(),
            "can_continue": True,
            "meter": meter,
        }

    def verify(self, approved, evidence="", by="客观验证器", task_id="", agent_id=""):
        """Reviewer 阶段：用**客观结果**（测试/lint/静态检查）给出 APPROVED/REJECTED。

        这是「执行与验证分离」的关键——Coder 不自己裁定合格，由独立验证器判定。
        approved: bool，必须由客观证据支撑（evidence 记录测试/工具输出）。
        """
        if self.phase not in ("execute", "rework"):
            raise DevLoopError(f"[verify] 当前阶段={self.phase}，不在可验证状态")
        self.verdict = {"approved": bool(approved), "evidence": evidence, "by": by,
                        "iteration": self.iterations}
        self.phase = "verify"
        # 验证即推进（记录刻度，供哨兵判定是否停滞/横跳/重复错误）
        self._record_meter(task_id, agent_id, "", f"verify:{'PASS' if approved else 'FAIL'}")
        return self.verdict

    def decide(self, task_id="", agent_id=""):
        """Orchestrator 确定性决策：根据验证结论强制流转（不让 LLM 决定）。

        返回 { verdict, stage, remaining, reason }：
          - verdict='approved'   → 验证通过，进入下一阶段/完成；
          - verdict='rework'     → 验证失败，强制回退 Coder 重做（attempts+1）；
          - verdict='escalate'   → 重做超过 max_attempts，上报 Leader（熔断，非无限重试）；
          - verdict='complete'   → 已达成目标（remaining<=eps），闭环完成。
        """
        if self.verdict is None:
            raise DevLoopError("[decide] 必须先 verify() 给出客观结论才能决策")
        approved = self.verdict["approved"]
        if approved:
            # APPROVED：进入下一阶段（Goose：只有 Reviewer 返回 APPROVED 才放行）
            if self._remaining() <= self.goal_eps:
                self.phase = "done"
                return {"verdict": "complete", "stage": "done",
                        "remaining": self._remaining(),
                        "reason": "验证通过且已达成目标，闭环完成"}
            self.phase = "plan"   # 进入下一子任务（重新规划）
            return {"verdict": "approved", "stage": "next_phase",
                    "remaining": self._remaining(),
                    "reason": "验证通过，进入下一阶段"}
        # REJECTED：强制回退 Coder 重做
        self.attempts += 1
        if self.attempts > self.max_attempts:
            # 硬性熔断：超过最大重做次数 → 上报 Leader（Goose：最多 N 次后上报）
            self.leader_escalated = True
            self.phase = "escalated"
            return {"verdict": "escalate", "stage": "escalated",
                    "remaining": self._remaining(),
                    "reason": (f"重做超过最大次数({self.max_attempts})仍未通过客观验证，"
                               f"上报 Leader 重新评估方案（如换算法），不再无限重试")}
        self.phase = "rework"
        return {"verdict": "rework", "stage": "rework",
                "remaining": self._remaining(),
                "reason": f"客观验证失败(第{self.attempts}次)，强制回退 Coder 重做"}

    # ------------------------------------------------------------
    # 进度北极星监督（接入 sentinel）
    # ------------------------------------------------------------
    def _remaining(self):
        return max(0.0, self.goal_total - self.current)

    def _record_meter(self, task_id, agent_id, target, note):
        from sentinel import engine
        try:
            engine.track(f"loop-{self.loop_id}", task_id=task_id, agent_id=agent_id,
                         target=target, goal_total=self.goal_total,
                         current=self.current, note=note or "")
        except Exception:  # noqa: BLE001 记录失败不阻断主流程
            pass
        return {"remaining": self._remaining(), "current": self.current}

    def advance(self, delta):
        """推进进度北极星（Coder 每完成一段有效产出，向目标靠近 delta）。"""
        if delta < 0:
            raise DevLoopError("进度不可回退（delta>=0），横跳由哨兵判定")
        self.current = min(self.goal_total, self.current + delta)
        self.last_timestamp = time.time()

    def check_idle_timeout(self):
        """空闲超时判定：超过 max_idle_seconds 无推进 → 判定卡死，返回 True。"""
        if not self.last_timestamp:
            return False
        return (time.time() - self.last_timestamp) > self.max_idle_seconds

    # ------------------------------------------------------------
    # 完成 / 交付
    # ------------------------------------------------------------
    def deliver_to_manager(self, task_id, agent_id, summary=""):
        """干完统一交付给经理：一次性通知 + 完整进度回放（非每轮对话打扰）。

        仅允许在阶段 done/complete 或验证通过后调用（Goose：只有 APPROVED 才交付）。
        """
        if self.phase != "done" and self.verdict != {"approved": True}:
            # 若未完成，至少要求已通过一次验证
            if not (self.verdict and self.verdict.get("approved")):
                raise DevLoopError(
                    "[deliver_to_manager] 尚未通过客观验证(APPROVED)，不可交付。"
                    f"当前阶段={self.phase}。")
        from data import admin
        try:
            admin.record_event(
                agent_id, "dev_loop_deliver",
                {"loop_id": self.loop_id, "task_id": task_id,
                 "goal_total": self.goal_total, "current": self.current,
                 "attempts": self.attempts, "iterations": self.iterations,
                 "summary": summary},
                task_id)
        except Exception:  # noqa: BLE001
            pass
        return {
            "loop_id": self.loop_id,
            "task_id": task_id,
            "phase": self.phase,
            "remaining": self._remaining(),
            "attempts": self.attempts,
            "iterations": self.iterations,
            "delivered": True,
        }

    def overview(self):
        """闭环运行俯瞰（二级信息）：阶段/重做/迭代/剩余距离/熔断状态。"""
        return {
            "loop_id": self.loop_id,
            "phase": self.phase,
            "goal_total": self.goal_total,
            "current": self.current,
            "remaining": self._remaining(),
            "attempts": self.attempts,
            "iterations": self.iterations,
            "max_attempts": self.max_attempts,
            "max_iterations": self.max_iterations,
            "leader_escalated": self.leader_escalated,
            "last_verdict": self.verdict,
            "can_continue": self.can_enter_loop()[0],
        }


# ------------------------------------------------------------
# 便捷工厂：确定性编排一次「执行→验证→决策」单轮
# ------------------------------------------------------------
def run_single_round(task_id, agent_id, goal_total, current,
                     approved, evidence="", max_attempts=3, target=""):
    """编排一次确定性单轮：start → (可选 advance) → verify → decide。

    返回完整决策结果。用于脚本/CI/确定性调用（Orchestrator 控制，不让 LLM 自决）。
    """
    eng = DevLoopEngine(goal_total=goal_total, max_attempts=max_attempts)
    eng.current = min(goal_total, current)
    start = eng.start_iteration(task_id, agent_id, target=target, note="round-start")
    eng.verify(approved=approved, evidence=evidence, by="objective_verifier",
               task_id=task_id, agent_id=agent_id)
    decision = eng.decide(task_id=task_id, agent_id=agent_id)
    decision.update({"iteration": start["iteration"], "remaining": start["remaining"]})
    return decision


if __name__ == "__main__":
    # 冒烟：确定性单轮 P0 判定
    d = run_single_round("t1", "架构·开发", 10.0, 2.0, approved=True, evidence="test 8/8 pass")
    assert d["verdict"] == "approved", d
    print("dev_loop smoke OK:", d)
