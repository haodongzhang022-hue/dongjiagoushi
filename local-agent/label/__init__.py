# -*- coding: utf-8 -*-
"""
标签管理能力模块（label · Issue #51）
======================================
把「标签管理 + 程序化进度查询（MCP 管线）+ 事件驱动自动打标」做成独立可复用
能力包，默认挂载到所有角色基类 BaseRole，全员可用。

对外公开接口：
  - LabelAbility    标签管理全员能力（查询/打标/提议/审批/自动触发 + 结构化标签）
  - AutoLabelEngine 事件驱动自动打标引擎（事件到达即自动打标，11 类规则）
  - cli.main()      CLI 入口（程序化 MCP 管线，供脚本/CI 调用）

解耦调用：LabelAbility 是**通用模块能力**，由 BaseRole 统一挂载，各角色不各自声明
用法，直接调用透传方法，避免迭代版本差异。

用法（任意角色实例）：
  role.query_progress("tk-xxx")            # 程序化查进度
  role.query_status("issue-12")            # 程序化查状态
  role.apply_label("issue-12","in_progress")  # 一线直接打标
  role.propose_label("issue-12","p0","阻塞上线")  # 全员提议（P0-P9 大盘）
  role.auto_trigger("progress.advance","issue-12",10,4)    # 事件自动打标
  role.set_depends("issue-12","11")        # 前置依赖
  role.set_next_step("issue-12","13")      # 完成后下一步触发
  role.set_priority("issue-12","p3")       # 优先级 P0-P9
  role.set_pipeline_node("issue-12","at_node","develop")   # 流水线节点

CLI（MCP 管线）：
  python -m label.cli progress --task tk-xxx
  python -m label.cli auto --event progress.advance --entity issue-12 --goal-total 10 --current 4
  python -m label.cli depends --entity issue-12 --issue 11
  python -m label.cli next --entity issue-12 --issue 13
  python -m label.cli priority --entity issue-12 --level p3
  python -m label.cli node --entity issue-12 --node at_node --value develop
"""
from .ability import LabelAbility
from .auto import AutoLabelEngine

__all__ = ["LabelAbility", "AutoLabelEngine"]
