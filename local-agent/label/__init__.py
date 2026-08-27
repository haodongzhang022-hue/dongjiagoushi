# -*- coding: utf-8 -*-
"""
标签管理能力模块（label · Issue #51）
======================================
把「标签管理 + 程序化进度查询（MCP 管线）+ 事件驱动自动打标」做成独立可复用
能力包，默认挂载到所有角色基类 BaseRole，全员可用。

对外公开接口：
  - LabelAbility    标签管理全员能力（查询/打标/提议/审批/自动触发）
  - AutoLabelEngine 事件驱动自动打标引擎（事件到达即自动打标）
  - cli.main()      CLI 入口（程序化 MCP 管线，供脚本/CI 调用）

用法（任意角色实例）：
  role.query_progress("tk-xxx")            # 程序化查进度
  role.query_status("issue-12")            # 程序化查状态
  role.apply_label("issue-12","in_progress")  # 一线直接打标
  role.propose_label("issue-12","p0_critical","阻塞上线")  # 全员提议
  role.auto_trigger("progress.advance","issue-12",10,4)    # 事件自动打标

CLI（MCP 管线）：
  python -m label.cli progress --task tk-xxx
  python -m label.cli auto --event progress.advance --entity issue-12 --goal-total 10 --current 4
"""
from .ability import LabelAbility
from .auto import AutoLabelEngine

__all__ = ["LabelAbility", "AutoLabelEngine"]
