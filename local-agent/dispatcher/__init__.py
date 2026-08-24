# -*- coding: utf-8 -*-
"""
调度中枢（dispatcher）· 事件驱动自动化调度层
=============================================
本模块是「事件驱动自触发团队」的核心：把协作从**对话/人工触发**升级为
**机制自动触发**——持续扫描事件源（Issue/PR/评论/驳回/哨兵告警/外部适配器），
识别触发条件，经 Action 队列 + 防无效护栏，按 **gid 精准路由**到对应 agent，
并在 Web 面板上实时俯瞰。

对齐 ISSUE #26；对应 docs/DISPATCHER.md。目标 Y：
  「让团队事件（岗位需求 / Issue 待审核 / 驳回待处理 / 遗漏未处理）自动识别 →
   自动路由到对应 agent，靠机制而非等人下命令，同时有足够机制防止无效触发。」

子模块：
  | 模块          | 职责                                                        |
  |---------------|-------------------------------------------------------------|
  | source.py     | 事件源监听器：规范化事件（本仓库 + 外部适配器插槽）           |
  | rules.py      | 触发规则引擎：事件 ↔ 条件 → 路由目标（自动优先/规则优先）     |
  | guard.py      | 防无效护栏：去重 / 去抖 / 幂等 / 频限 / sentinel 进度上限     |
  | queue.py      | Action 队列：自动放行 + 规则拦截 + 人工审核闸门，不卡进程      |
  | router.py     | 路由派发器：按 gid 精准定位负责 agent，投 pool / 接力卡 / broker |
  | reject.py     | 驳回迭代表：驳回非终点，按 gid 回派改进重提，迭代闭环          |
  | webui.py      | Web 可视化面板：事件流 / 待路由 / 已派发 / 守卫拦截 / 驳回     |
  | engine.py     | 统一调度入口：dispatcher 单次扫描 / --watch 持续守护           |
  | cli.py        | 命令行入口                                                    |

用法：
  # 单次扫描（扫描事件源 → 规则识别 → 入队 → 守卫 → 派发）
  python -m local-agent.dispatcher.cli scan

  # 持续守护（--watch，复用 timer 心跳巡检）
  python -m local-agent.dispatcher.cli watch --interval 5

  # 起 Web 面板（实时俯瞰事件流/路由/拦截/驳回）
  python -m local-agent.dispatcher.cli web --port 8080
"""
from . import source, rules, guard, queue, router, reject, engine, webui
from .source import ExternalAdapter, RepoPollAdapter, normalize_event
from .rules import RuleEngine, default_rules
from .guard import Guard

__all__ = [
    "source", "rules", "guard", "queue", "router", "reject", "engine", "webui",
    "ExternalAdapter", "RepoPollAdapter", "normalize_event",
    "RuleEngine", "default_rules", "Guard",
]
