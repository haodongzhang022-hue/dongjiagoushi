# -*- coding: utf-8 -*-
"""
本地 Agent · 角色库
====================
每个角色是一个可加载模块，与云端 .cnb/settings.yml / SKILL.md 人设同源。
角色统一「架构·」前缀命名空间（市场层「市场·」为获客领域扩展，属同体系）。
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
from .data_admin import DataAdminRole
from .secretary import SecretaryRole
from .market import (
    SalesRole,
    SupportRole,
    DataRole,
    ChannelRole,
    ToolingRole,
)

ROLE_REGISTRY = {
    # ---- 入口层 ----
    "架构·秘书": SecretaryRole,
    # ---- 需求转化/设计 ----
    "架构·产品": ProductRole,
    "架构·总师": ArchitectRole,
    # ---- 调度/协同 ----
    "架构·经理": ManagerRole,
    "架构·小组长": TeamLeadRole,
    # ---- 实现/质量 ----
    "架构·开发": DeveloperRole,
    "架构·评审": ReviewerRole,
    "架构·对齐": VersionKeeperRole,
    "架构·找工具": ToolFinderRole,
    "架构·测试": TesterRole,
    "架构·数据管理员": DataAdminRole,
    # ---- 市场获客分层（通用基建）----
    "市场·销售": SalesRole,
    "市场·客服": SupportRole,
    "市场·数据": DataRole,
    "市场·渠道": ChannelRole,
    "市场·工具": ToolingRole,
}


def get_role(name):
    """按角色名取角色实例；找不到返回 None。"""
    cls = ROLE_REGISTRY.get(name)
    return cls() if cls else None


def list_roles():
    return list(ROLE_REGISTRY.keys())
