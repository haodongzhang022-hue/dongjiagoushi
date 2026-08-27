# -*- coding: utf-8 -*-
"""
自适应 @ 定位能力（HandleAbility · 全员能力）
=============================================
把「@ 谁、@ 哪个仓库的谁」封装为**可复用的通用能力模块**，供任何 agent 挂载。

解决用户拍板的核心诉求（Issue #33）：
  - 此前跨库召唤/身份声明写死 `@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)`，
    角色名与承载仓库 hardcode，导致：
      ① 触发本仓库 CodeBuddy 的可能是**其他角色**，写死即失效；
      ② 跨仓库协作时仍用本仓库 @ 去召唤，会因**角色无目标仓库权限**而受限。
  - 本能力让每个 agent **根据当前触发它的仓库动态识别自身完整 @ 格式**，
    并在跨库协作时自动解析**目标仓库的有权限角色**，权限更高、更泛化。

能力维度：
  ╔═ 自我识别 ═════════════════════════════════════════════════════╗
  ║ self_handle()    返回本 agent 自身的完整 @ 格式（身份声明用）    ║
  ║ identity()       返回 {触发承载仓库, 当前操作仓库, 自身角色}      ║
  ╚═════════════════════════════════════════════════════════════════╝
  ╔═ 跨库定位 ══════════════════════════════════════════════════════╗
  ║ resolve(repo, role)  解析目标仓库的有权限 @ 格式（权限更高）      ║
  ║ is_cross(repo)       判定目标仓库是否跨库（防重复复用）           ║
  ║ codebuddy(repo)      目标仓库 CodeBuddy 兜底 @ 格式               ║
  ╚═════════════════════════════════════════════════════════════════╝

能力时机（何时用，见 docs/HANDLE_ABILITY.md 与 AGENTS.md）：
  - 身份声明 / 汇报落款：用 `self_handle()` 动态生成自身完整 @，不写死；
  - 跨仓库协作（要改别的仓、召唤别的仓角色）：用 `resolve(repo, role)` 解析
    目标仓库 @，保证权限够用；
  - 同仓库协作：`is_cross()==False`，直接复用本仓库 @（防冗余，不重造）。

用法（任意角色实例上直接调用，BaseRole 已挂载）：
    role = DeveloperRole()
    role.self_handle()                    # 返回自身完整 @ 格式
    role.resolve("other/repo", "CodeBuddy")   # 跨库定位目标仓库角色
"""
import os
import sys

# 确保 local-agent 目录在 sys.path（便于导入 handle.resolver）
_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class HandleAbility:
    """自适应 @ 定位能力：任何 agent 挂载即得自我识别 + 跨库定位能力。

    通过 `owner` 绑定所属 agent（角色实例/角色名），留痕归因到该 agent。
    """

    # 使用规则（供 AGENTS.md / 文档引用，集中维护一处）
    RULES = {
        "不写死": (
            "禁止把 CodeBuddy 角色名 / 承载仓库 / org hardcode。一律从会话触发串、"
            "git remote、环境变量或默认约定动态解析；写死的你kaif… 这类会失效。"
        ),
        "跨库用目标仓库": (
            "跨仓库协作时，必须用目标仓库的完整 @ `@org/repo(角色)` 召唤，"
            "否则该角色无目标仓库权限（角色权限通常只覆盖其所属仓库）。"
        ),
        "同仓复用防冗余": (
            "同仓库协作先检测：能复用本仓库 @ 就不重造；只有跨仓库才走完整解析。"
        ),
        "权限优先": (
            "要动哪个仓库，就用哪个仓库里有权限的角色（CodeBuddy 兜底或该仓库"
            "已注册的专属角色）；拿不准时给权限建议并显式暴露，不静默选择。"
        ),
    }

    def __init__(self, owner=None, at_str=None, current_org=None,
                 current_repo=None):
        """owner: 绑定所属 agent；at_str: 会话注入的触发串（用于自我识别）；
        current_org/current_repo: 当前操作仓库（缺省自动探测）。"""
        self.owner = owner
        self._owner_name = self._resolve_owner_name(owner)
        self.at_str = at_str
        self.current_org = current_org
        self.current_repo = current_repo
        self._resolver = self._import_resolver()

    @staticmethod
    def _import_resolver():
        import handle.resolver as r
        return r

    @staticmethod
    def _resolve_owner_name(owner):
        if owner is None:
            return ""
        if isinstance(owner, str):
            return owner
        name = getattr(owner, "name", "")
        return name or getattr(owner, "__class__", object).__name__

    # ------------------------------------------------------------
    # 自我识别
    # ------------------------------------------------------------
    def self_handle(self):
        """返回本 agent 自身的完整 @ 格式（身份声明 / 汇报落款用）。

        从会话触发串动态识别自身 CodeBuddy 角色承载仓库；无触发串时回退到
        当前操作仓库。绝不写死角色名。
        """
        r = self._resolver.resolve(
            at_str=self.at_str,
            current_org=self.current_org, current_repo=self.current_repo,
        )
        return r["handle"]

    def identity(self):
        """返回 { trigger承载仓库, current操作仓库, target, role, handle }。"""
        return self._resolver.resolve(
            at_str=self.at_str,
            current_org=self.current_org, current_repo=self.current_repo,
        )

    # ------------------------------------------------------------
    # 跨库定位
    # ------------------------------------------------------------
    def resolve(self, target_org=None, target_repo=None, role=None):
        """解析目标仓库的有权限 @ 格式（跨库权限更高）。

        优先级：显式 target 参数 > 触发串承载仓库 > 当前操作仓库。
        返回 dict，含 handle（最终召唤格式）、cross_repo、permission_note。
        """
        return self._resolver.resolve(
            at_str=self.at_str,
            target_org=target_org, target_repo=target_repo, role=role,
            current_org=self.current_org, current_repo=self.current_repo,
        )

    def is_cross(self, target_org=None, target_repo=None):
        """判定目标仓库是否**跨仓库**（相对当前操作仓库）。

        - 同仓库 → False（可复用本仓库 @，防冗余）；
        - 跨仓库 → True（须用目标仓库完整 @）。
        """
        return self._resolver.is_cross_repo(
            target_org, target_repo,
            current_org=self.current_org, current_repo=self.current_repo,
        )

    def codebuddy(self, target_org=None, target_repo=None):
        """目标仓库 CodeBuddy 兜底 @ 格式。"""
        return self._resolver.format_at(
            target_org or self.current_org or self._resolver.DEFAULT_ORG,
            target_repo or self.current_repo or self._resolver.DEFAULT_REPO,
            self._resolver.DEFAULT_CODEBUDDY_ROLE,
        )

    # ------------------------------------------------------------
    # 能力元信息
    # ------------------------------------------------------------
    def capability(self):
        """返回能力声明（供 AGENTS.md / 文档 / 各 agent 人设引用）。"""
        return {
            "name": "自适应 @ 定位能力 (HandleAbility)",
            "owner": self._owner_name,
            "methods": ["self_handle", "identity", "resolve", "is_cross",
                        "codebuddy"],
            "rules": self.RULES,
            "principle": (
                "不写死角色名/承载仓库/org；跨库用目标仓库完整 @ 保权限；"
                "同仓复用防冗余；要动哪个仓库就用哪个仓库的有权限角色。"
            ),
        }


def handle_ability(owner=None, at_str=None):
    """便捷工厂：返回绑定 owner 的自适应 @ 定位能力实例。"""
    return HandleAbility(owner=owner, at_str=at_str)


__all__ = ["HandleAbility", "handle_ability"]
