# -*- coding: utf-8 -*-
"""
架构·进度推手（ProgressPusherRole · Issue #51）
=================================================
「进度标签 + 优先级 + 自动化喂料」专项角色，挂载 LabelAbility（查询/打标/自动触发），
并可基于进度/优先级触发额外自动化（喂给哨兵触发协议）。

定位：把内部量化距离（goal_meters 的 current/distance）翻译成人可读的**百分比标签**，
并在进度停滞/高优先级阻塞时**自动触发**对应处置（1 级打断重规划 / 升级上报），
形成"事件驱动 + 进度可观测 + 自动化推进"的闭环。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, os.path.dirname(_LOCAL_AGENT_DIR))  # 供 roles.base 导入

from roles.base import BaseRole


class ProgressPusherRole(BaseRole):
    """架构·进度推手：进度标签 + 优先级 + 自动化喂料专项角色。"""

    name = "架构·进度推手"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        # 确保拥有标签能力
        try:
            from label import LabelAbility
            if self.label_ability is None:
                self.label_ability = LabelAbility(owner=self)
        except Exception:
            pass

    def push_progress(self, entity, task_id="", goal_total=None, current=None):
        """推进进度：刷新百分比标签 + 状态标签（事件驱动自动打标）。"""
        event = "progress.advance"
        applied = self.auto_trigger(event, entity, goal_total=goal_total,
                                    current=current, note="进度推手推进")
        if task_id:
            self.query_progress(task_id)
        return applied

    def push_priority(self, entity, priority, reason=""):
        """设定/调整优先级（P0-P9 大盘：p0 最紧急→p9 最不紧急，正交维度）。"""
        return self.set_priority(entity, priority, note=reason or "进度推手设优先级")

    def push_depends(self, entity, issue_no):
        """打前置依赖标签（depends_on → value 存前置 Issue 编号）。"""
        return self.set_depends(entity, issue_no, note="进度推手标前置依赖")

    def push_next_step(self, entity, issue_no):
        """打完成后下一步触发标签（next_step → value 存下一步 Issue 编号）。"""
        return self.set_next_step(entity, issue_no, note="进度推手标下一步触发")

    def push_pipeline_node(self, entity, node, value=""):
        """打流水线自动化关键节点标签（at_node/trigger_next/gate）。"""
        return self.set_pipeline_node(entity, node, value=value,
                                      note="进度推手标流水线节点")

    def check_auto(self, entity, task_id="", stall_rounds=3, priority=""):
        """自动化触发检查：进度停滞→1级打断重规划；高优先级阻塞→升级上报。

        返回触发建议（喂给哨兵触发协议 / 供监控哨兵消费）。
        """
        prog = self.query_progress(task_id) if task_id else None
        labels = self.query_labels(entity)
        pct_label = next((l for l in labels if l["label_key"] == "progress_pct"), None)
        pct = int(pct_label["value"]) if pct_label and pct_label["value"].isdigit() else None
        actions = []
        # 停滞：进度百分比连续不变（有量化且 <= 已到值，且停滞轮数达阈值）
        if prog and prog.get("goal_total") and prog.get("distance", 0) > 0:
            # 此处简化判定：由哨兵 distance 为准，进度推手只做喂料提醒
            actions.append({"kind": "feeder_note",
                            "entity": entity, "task_id": task_id,
                            "percent": pct, "distance": prog.get("distance"),
                            "note": "进度推手已刷新进度标签，停滞判定交给监控哨兵 distance"})
        # 高优先级阻塞（P0-P9 大盘：P0/P1 为高优，需关注阻塞）
        from label import LabelAbility
        high_prio = [f"p{i}" for i in (0, 1)]
        has_high = any(l["label_key"] in high_prio for l in labels)
        if has_high:
            prio_key = next((l["label_key"] for l in labels if l["label_key"] in high_prio), "p0")
            actions.append({"kind": "escalate",
                            "entity": entity, "reason": f"{prio_key.upper()} 高优先级任务需关注阻塞",
                            "action": "升级上报"})
        return {"entity": entity, "percent": pct, "actions": actions}

    def output_contract(self):
        return {
            "role": self.name,
            "contract": (
                "进度标签(progress_pct) / 优先级(P0-P9 大盘) / 前置依赖(depends_on) / "
                "下一步触发(next_step) / 流水线节点(at_node/trigger_next/gate) / "
                "事件驱动自动打标 / 基于进度触发自动化(停滞喂哨兵打断 / 高优先级阻塞升级上报)"
            ),
        }
