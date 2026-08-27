# -*- coding: utf-8 -*-
"""
自适应 @ 定位能力包（handle · 全员能力）
=========================================
把「@ 谁、@ 哪个仓库的谁」从写死的字符串，升级为**每个 agent 都可复用的通用能力**。

背景（用户拍板 · Issue #33）：
  此前身份声明 / 跨库召唤写死 `@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)`，
  角色名与承载仓库 hardcode，导致：
    ① 触发本仓库 CodeBuddy 的可能不是 `youkaifaxilieagent`——写死即失效；
    ② 跨仓库协作时用本仓库 @ 去召唤目标仓库，因角色无目标仓库权限而受限。

本包提供「自适应 @ 定位」能力，让任意 agent 挂载后即可：
  - 根据**当前触发它的仓库**动态识别自身完整 @ 格式（身份声明不写死）；
  - 跨仓库协作时自动解析**目标仓库的有权限角色** @ 格式（权限更高）；
  - 同仓库先检测可复用（防冗余），跨仓库才走完整解析。

模块组成：
  - `resolver.py`   核心解析器：触发串/探测/跨同仓判定/权限建议
  - `ability.py`    HandleAbility 能力类（self_handle/resolve/is_cross…）

用法（任意角色实例上，BaseRole 已挂载）：
    role = DeveloperRole()
    role.self_handle()                    # 自身完整 @ 格式
    role.resolve("other/repo", "CodeBuddy")  # 跨库定位目标仓库角色

详见 docs/HANDLE_ABILITY.md 与 AGENTS.md。
"""
from .ability import HandleAbility, handle_ability

__all__ = ["HandleAbility", "handle_ability"]
