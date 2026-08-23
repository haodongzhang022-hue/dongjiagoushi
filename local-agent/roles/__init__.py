# -*- coding: utf-8 -*-
"""
本地 Agent · 角色库
====================
每个角色是一个可加载模块，与云端 .cnb/settings.yml / SKILL.md 人设同源。
角色统一「架构·」前缀命名空间。
"""
from .product import ProductRole
from .architect import ArchitectRole
from .manager import ManagerRole
from .team_lead import TeamLeadRole
from .developer import DeveloperRole
from .reviewer import ReviewerRole
from .version_keeper import VersionKeeperRole
from .tool_finder import ToolFinderRole
from .tester import TesterRole

ROLE_REGISTRY = {
    "架构·产品": ProductRole,
    "架构·总师": ArchitectRole,
    "架构·经理": ManagerRole,
    "架构·小组长": TeamLeadRole,
    "架构·开发": DeveloperRole,
    "架构·评审": ReviewerRole,
    "架构·对齐": VersionKeeperRole,
    "架构·找工具": ToolFinderRole,
    "架构·测试": TesterRole,
}


def get_role(name):
    """按角色名取角色实例；找不到返回 None。"""
    cls = ROLE_REGISTRY.get(name)
    return cls() if cls else None


def list_roles():
    return list(ROLE_REGISTRY.keys())
