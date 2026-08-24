# -*- coding: utf-8 -*-
"""
调度中枢 · 触发规则引擎（rules）
==================================
把「事件」映射到「路由目标 + 动作」。**自动优先、规则优先**（用户拍板 #2）：
规则命中即产生派发意图，只有命中 `needs_human=True` 的规则才进人工审核闸门，
其余默认自动放行。

规则结构：
  {
    "name": "rejection_reroute",        # 规则名（唯一）
    "match": {"event_type": "rejection"},  # 匹配条件（事件字段等于某值）
    "target_role": "架构·开发",          # 路由目标角色
    "action": "reject_reroute",          # 动作（派发/回派/安排审核…）
    "gate": "auto",                      # auto=自动放行 / hold=人工审核闸门
    "dedup_key": "{gid}:rejection",      # 去重键模板（{gid} 占位，同键只派一次）
    "priority": 10,                      # 优先级（大者先匹配）
  }

内置规则表覆盖用户点名的四大场景：
  ① 新岗位/需求出现 → 派发 架构·产品（需求转化）
  ② Issue 遗漏未审核 → 安排 架构·评审
  ③ 驳回（[回转]/🔴必修/🔴阻塞）→ 按 gid 回派原负责 agent（reject_reroute）
  ④ 哨兵告警（无效努力）→ 打断重规划 → 路由对应 agent

规则表由「总师/产品」共同维护，引擎只负责匹配，不硬编码业务内容。
"""
from . import source as _src


class RuleEngine:
    def __init__(self, rules=None):
        # 内置默认规则表（可被构造参数覆盖/追加）
        self._rules = []
        for r in (rules if rules is not None else default_rules()):
            self.add_rule(r)

    def add_rule(self, rule):
        if not rule.get("name"):
            raise ValueError("规则必须带 name")
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.get("priority", 0), reverse=True)

    def match(self, event):
        """对一个标准事件返回命中的规则（按优先级取最高一条；未命中返回 None）。"""
        for rule in self._rules:
            if self._matches(rule, event):
                return rule
        return None

    def _matches(self, rule, event):
        cond = rule.get("match", {})
        for key, expected in cond.items():
            val = event.get(key)
            if isinstance(expected, (list, tuple, set)):
                if val not in expected:
                    return False
            elif val != expected:
                return False
        return True

    def rules(self):
        return list(self._rules)

    def build_intent(self, rule, event):
        """由命中的规则 + 事件，构造「派发意图」dict。"""
        dedup_key = rule.get("dedup_key", "")
        if dedup_key:
            dedup_key = dedup_key.format(
                gid=event.get("gid", ""),
                entity=event.get("entity", ""),
                type=event.get("event_type", ""),
            )
        return {
            "rule": rule.get("name"),
            "event_type": event.get("event_type"),
            "entity": event.get("entity"),
            "gid": event.get("gid", ""),
            "target_role": rule.get("target_role", ""),
            "action": rule.get("action", "dispatch"),
            "gate": rule.get("gate", "auto"),
            "dedup_key": dedup_key,
            "detail": event.get("detail", {}),
            "source": event.get("source", "repo"),
            "event_id": event.get("event_id", ""),
        }


def default_rules():
    """内置默认规则表（覆盖用户点名四大场景；规则表可被总师/产品维护扩展）。"""
    return [
        {
            "name": "rejection_reroute",
            "match": {"event_type": "rejection"},
            "target_role": "",            # 实际目标 = 原负责 agent（按 gid 回派）
            "action": "reject_reroute",
            "gate": "auto",               # 驳回回派自动优先（用户拍板 #3）
            "dedup_key": "{gid}:rejection",
            "priority": 100,
        },
        {
            "name": "requirement_dispatch",
            "match": {"event_type": "requirement"},
            "target_role": "架构·产品",
            "action": "dispatch",
            "gate": "auto",
            "dedup_key": "{entity}:requirement",
            "priority": 90,
        },
        {
            "name": "issue_review_needed",
            "match": {"event_type": "issue.open"},
            "target_role": "架构·评审",
            "action": "arrange_review",
            "gate": "auto",               # 常规不人工，规则优先（用户拍板 #2）
            "dedup_key": "{entity}:review",
            "priority": 80,
        },
        {
            "name": "missed_scan",
            "match": {"event_type": "missed.scan"},
            "target_role": "架构·评审",
            "action": "arrange_review",
            "gate": "hold",               # 遗漏安排需人工确认（避免误派）
            "dedup_key": "{entity}:missed",
            "priority": 60,
        },
        {
            "name": "sentinel_alert_reroute",
            "match": {"event_type": "sentinel.alert"},
            "target_role": "",            # 目标 = 被打断的 agent（按 gid）
            "action": "interrupt_reroute",
            "gate": "auto",
            "dedup_key": "{gid}:sentinel",
            "priority": 70,
        },
    ]
