# -*- coding: utf-8 -*-
"""
评审段调度器（review-cycle · Issue #150）
==========================================
解决用户痛点（Issue #150）：
  「现在……每次触发评审之后跑开发，然后评审，这样效率很慢，
   又触发大量的 CPU 构建和 CPU 开发的损耗。」

根因：现在的「评审 ⇄ 开发」是**同步乒乓**——每轮评审一条评论就唤醒一次开发 +
拉起一次构建，冷启动开销被轮次 N 倍放大。

本模块把评审循环改成**异步攒批调度**：
  ① **DAG 增量收集**：评审项 → 开发增量 → 测试信号 → 回评审，不是"发一次就唤醒一次"；
  ② **攒批触发**：把开发请求 / 测试请求投进 `hybrid.BusRunner` 队列（**入列 0 成本**），
     到点（或显式 flush）**一次发车整批跑完**——一次冷启动摊全批；
  ③ **内容指纹复用**：同一变更指纹已被评审过/已跑过 → **不重复触发开发/构建**，
     只做引用；指纹一变才失效；
  ④ **增量评审上下文**：评审每轮只吃 `review_context` 的 (冻结骨架摘要 + 本轮变化)，
     不再复述整个大项目；
  ⑤ **以测试为准**：整批测试信号决定是否放行，不靠"看法"。

对外接口：
  - Scheduler(dry_run=...)            调度器
  - s.run(task_key, stable, volatile) 跑一轮评审段（增量收集 + 攒批 + 复用）
  - s.stats()                         省下的成本报表
  - s.overview()                      全局俯瞰（轮次表 + 报表）

CLI：
  python -m review_cycle run --demo
  python -m review_cycle run --task-key T --stable '{...}' --volatile '{...}'
"""
from .cycle import Scheduler, default_scheduler
from . import spec

__all__ = ["Scheduler", "default_scheduler", "spec"]
