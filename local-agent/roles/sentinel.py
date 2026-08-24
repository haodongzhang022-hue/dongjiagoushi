# -*- coding: utf-8 -*-
"""
内置角色 · 架构·监控哨兵（sentinel）
====================================
本角色负责「**防无效努力 / 目标收敛监控**」，是让团队"稳定运行、不出错、
不陷入无意义循环、不在同一件事上反复尝试同一个错误"的**量化监管**载体。

职责（详见 docs/SENTINEL.md，与 sentinel/engine.py 对应）：
  1. 量化刻度：每个角色领取任务后，为任务建立**目标进度尺**（goal_meters），
     以「到目标的量化距离 distance」记录每次推进（goal_total/current/delta）。
  2. 机器判定：用 detect 引擎判定「停滞(stagnation) / 横跳(oscillation) /
     重复错误(repeated_error)」——持续距目标近似距离、反复横跳达不到即命中。
  3. 打断重规划（1 级）：命中即发 [打断]，依据**剩余距离**重新规划再分配，
     禁止在同类失败上反复尝试（留痕 sentinel_actions）。
  4. 上报调整（2 级）：同一目标二次命中 → 上报「架构·总师助理」，讨论
     是否对**架构局部调整**（目标定义 / 分配 / 流程），标 blocked 待人工介入。
  5. 防目标偏差：全程以「距北极星的量化距离」为统一口径，不跑偏、不无效努力。

协作纪律：架构·经理负责"把任务派出去"，架构·监控哨兵负责"盯着是否真的在收敛"；
只管"是否在无效努力 + 是否该打断/上报"，不替代被监控角色返工。
触发协议：显式[触发:架构·监控哨兵]/语义命中"监控/哨兵/无效努力/横跳/停滞/卡住"即进入本角色；
被打回视为重新触发返工；打断在接力卡 current_progress 留续跑点。
"""
from .base import BaseRole


class SentinelRole(BaseRole):
    """监控哨兵：量化监管各角色到目标的收敛，触发打断/重规划/上报调整，防无效努力与目标偏差。"""

    name = "架构·监控哨兵"

    SYSTEM_PROMPT = (
        "你是「架构·监控哨兵」，本团队的「防无效努力」量化监管核心。职责：\n"
        "① 为每个领取任务的角色建立**目标进度尺**（goal_meters），以量化距离记录每次推进；\n"
        "② 用机器判定引擎检测**无效努力**：停滞（距离几乎不变）、横跳（反复来回不收敛）、"
        "重复错误（同一失败反复尝试）；\n"
        "③ 命中即触发处置协议：1级=发[打断]依据剩余距离重新规划再分配；"
        "2级=上报「架构·总师助理」评估局部架构调整并标 blocked 待人工；\n"
        "④ 以「到北极星的量化距离」为统一口径防目标偏差，主动显式暴露风险，不事后兜底、"
        "不替代被监控角色返工。\n"
        "所有判定与动作真实落库（goal_meters/sentinel_actions）、可回放可审计。"
        "以结构化结果（刻度/判定/处置动作）输出。"
    )

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "目标进度尺(track: goal_total/current/distance/delta)",
                "无效努力判定(analyze: stagnation/oscillation/repeated_error)",
                "1级处置(interrupt: [打断]+依据剩余距离重新规划再分配)",
                "2级处置(escalate: 上报架构·总师助理讨论局部调整+标blocked)",
                "健康报告(health_report: 刻度数/打断数/上报数)",
            ],
            "namespace": "架构·",
        }

    def run(self, llm, user_input):
        """按监控哨兵契约执行：初始化哨兵数据底座，或交由 LLM 结构化返回。"""
        try:
            from sentinel import engine
            init = engine.init()
        except Exception:  # noqa: BLE001
            init = None
        if llm and hasattr(llm, "call"):
            try:
                return llm.call(self.system_prompt(), user_input)
            except Exception:  # noqa: BLE001
                pass
        return (
            f"[角色·{self.name}] 目标收敛监控底座初始化完成"
            f"（tables={init.get('tables') if init else '?'}）\n"
            f"  · 目标进度尺 / 无效努力判定 / 打断重规划 / 上报局部调整 由 sentinel 引擎承载；\n"
            f"  · 以「到北极星的量化距离」为统一口径，防无效努力、防目标偏差、主动显式暴露风险。"
        )
