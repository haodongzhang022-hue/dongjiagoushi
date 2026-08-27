# -*- coding: utf-8 -*-
"""
事件驱动自动打标引擎（AutoLabelEngine · Issue #51）
=====================================================
把「加标签」从**能力层（等人调）**升级为**自动化触发层（事件到达即自动打标）**。
这是用户强调的『自动化程度较高的流水线』核心：不需要任何 agent 记得去调，
事件到达命中规则即自动打标/刷值。

内置事件→标签规则（EVENT_RULES）：
  issue.open         → open
  issue.update       → 刷进度标签 progress_pct（若给 goal/current）
  requirement        → open
  progress.advance   → in_progress + 进度百分比标签 progress_pct
  task.done          → done
  pr.merged          → merged + done
  review.need_fix    → need_fix + blocked
  review.pass        → merge_ready（评审通过→打合并放行标签，替代推送"评审通过"）
  review.merge       → merged（评审合并→打合并标签）
  sentinel.alert     → stale（停滞）
  deps.met           → ready（前置依赖满足，放行下一步）★新增
  next.trigger       → at_node + trigger_next（流水线自动触发下一步）★新增
  priority.set       → p0..p9（P0-P9 大盘，value 存优先级）★新增

进度百分比（人可读层）：
  读 goal/current 折算 round(current/goal*100)；无量化时按状态估算
  （todo→5 / in_progress→40 / review→90 / done→100）。
  机器收敛判定仍用哨兵内部 distance（不丢"还剩多少"），百分比是给人俯瞰，两者互补。

接入方式：
  - 任意角色实例：role.auto_trigger(event, entity, goal_total, current)
  - CLI 管线：python -m label.cli auto --event ... --entity ... --goal-total ...
  - CI 事件钩子：.cnb.yml 在 issue.open/issue.update 事件自动调 scripts/auto-label.sh
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class AutoLabelEngine:
    """事件驱动自动打标引擎。触发规则集中维护 EVENT_RULES，命中即自动打标。"""

    # 事件 → (主标签, 额外标签列表, 是否刷新进度百分比)
    EVENT_RULES = {
        "issue.open":        ("open",        [], False),
        "issue.update":      (None,          [], True),   # 仅刷进度
        "requirement":       ("open",        [], False),
        "progress.advance":  ("in_progress", [], True),   # 进度推进→in_progress+百分比
        "task.done":         ("done",        [], False),
        "pr.merged":         ("merged",      ["done"], False),
        "review.need_fix":   ("need_fix",    ["blocked"], False),
        "review.pass":       ("merge_ready", [], False),   # 评审通过→合并放行标签（打标签替代推送）
        "review.merge":      ("merged",      [], False),   # 评审合并→合并标签
        "sentinel.alert":    ("stale",       [], False),
        # 前置依赖满足 → ready（放行下一步）
        "deps.met":          ("ready",       ["in_progress"], False),
        # 流水线自动触发下一步 → at_node + trigger_next
        "next.trigger":      ("at_node",     ["trigger_next"], False),
        # 优先级设定（P0-P9 大盘，value 存 p0..p9）
        "priority.set":      (None,          [], False),
    }

    # 无量化时按状态估算进度（人可读兜底）
    ESTIMATE_PCT = {"todo": 5, "in_progress": 40, "review": 90, "done": 100}

    def __init__(self, owner=None):
        self.owner = owner
        self._owner_name = self._resolve_owner_name(owner)

    @staticmethod
    def _resolve_owner_name(owner):
        if owner is None:
            return ""
        if isinstance(owner, str):
            return owner
        return getattr(owner, "_owner_name", "") or getattr(owner, "name", "") or "system"

    def _repo(self):
        from data import repository as repo
        return repo

    def _operator(self):
        return self._owner_name or "系统"

    # ---- 进度百分比折算（人可读层）----
    @staticmethod
    def pct_from(goal_total, current):
        """有量化：round(current/goal*100)；goal 无效→None。"""
        if goal_total:
            try:
                return max(0, min(100, int(round(current / goal_total * 100))))
            except (TypeError, ZeroDivisionError):
                return None
        return None

    @staticmethod
    def pct_estimate(status):
        """无量化：按状态估算百分比（兜底，供人俯瞰）。"""
        return AutoLabelEngine.ESTIMATE_PCT.get(status)

    # ---- 事件触发主入口 ----
    def trigger(self, event, entity, goal_total=None, current=None, status=None,
                note="", value=""):
        """事件到达即自动打标。返回本次自动打出的标签列表。

        value: 携带事件值（如 priority.set → "p3"、next.trigger → 下一步 issue 编号）。
        """
        if event not in self.EVENT_RULES:
            return {"ok": True, "event": event, "entity": entity,
                    "applied": [], "reason": "无匹配规则，跳过"}
        main, extra, refresh_pct = self.EVENT_RULES[event]
        applied = []

        # 优先级设定（P0-P9 大盘）：value 存 p0..p9 标签，主/附加不适用
        if event == "priority.set":
            priority = value or (note.split()[-1] if note else "")
            if priority:
                self._repo().apply_label(entity, priority, operator=self._operator(),
                                         value=priority, action="apply",
                                         source="auto", note=f"事件 {event} 自动设优先级 {priority}")
                applied.append(f"priority:{priority}")
            return {"ok": True, "event": event, "entity": entity, "applied": applied}

        # 主标签 + 额外标签
        for key in ([main] if main else []) + list(extra):
            self._repo().apply_label(entity, key, operator=self._operator(),
                                     value="", action="apply", source="auto",
                                     note=note or f"事件 {event} 自动打标")
            applied.append(key)

        # 刷新进度百分比（人可读层）
        if refresh_pct or event in ("progress.advance", "issue.update"):
            pct = self.pct_from(goal_total, current)
            if pct is None and status:
                pct = self.pct_estimate(status)
            if pct is not None:
                self._repo().apply_label(entity, "progress_pct",
                                         operator=self._operator(),
                                         value=str(pct), action="apply",
                                         source="auto",
                                         note=f"进度 {pct}% 自动刷新")
                applied.append(f"progress_pct:{pct}%")

        return {"ok": True, "event": event, "entity": entity, "applied": applied}

    def rules(self):
        """返回触发规则清单（供文档/监控引用）。"""
        return {k: {"label": v[0], "extra": v[1], "refresh_pct": v[2]}
                for k, v in self.EVENT_RULES.items()}
