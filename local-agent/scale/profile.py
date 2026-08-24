# -*- coding: utf-8 -*-
"""
前置流程区分层 · 入口模板（profile）
====================================
用户诉求："不同位置的流程稍微不同，需要做前置的区分。"

当前体系只有**一条**默认入口（架构·秘书 → 产品 → 总师 → ...）。但实际场景
（个人开发 / 企业项目 / 对外获客 / 客服售后 / deepseek harness 内嵌模式 /
在线公司模式）的**前置流程不同**——有的要先销售建联，有的要先客服接单，
有的直接进产品/架构。

本模块提供 **入口模板（Entry Profile）**：

  - 每个 profile 定义：入口角色、前置步骤序列、需要的角色子集、DAG 子集、路由规则；
  - 系统先做「前置区分」（路由到正确 profile），再走该 profile 的流程；
  - 可在 team.yaml 里注册新 profile，实现「不同位置不同流程」的扩展。

内建 profile：
  - default       个人/内部需求：秘书 → 产品 → 总师 → 经理 → ...（现状）
  - company       在线公司模式：秘书 → 销售/客服(建联) → 产品 → 架构 → 部门协同
  - harness       deepseek harness 内嵌模式：直接产品 → 架构 → 开发（无市场层）
  - acquisition   对外获客：销售 → 线索 → 方案 → 成交 → 交付
  - support       客服售后：客服 → 分级 → 升级/售后闭环
"""
import os

DEFAULT_PROFILES = {
    "default": {
        "entry": "架构·秘书",
        "pre": ["secretary", "clarify"],
        "roles": ["架构·秘书", "架构·产品", "架构·总师", "架构·经理",
                   "架构·小组长", "架构·开发", "架构·评审", "架构·对齐",
                   "架构·找工具", "架构·测试"],
        "route": "个人/内部需求",
    },
    "company": {
        "entry": "架构·秘书",
        "pre": ["secretary", "sales_followup"],
        "roles": ["架构·秘书", "市场·销售", "市场·客服", "市场·数据",
                   "市场·渠道", "市场·工具", "架构·产品", "架构·总师",
                   "架构·经理", "架构·开发", "架构·评审", "架构·测试"],
        "route": "在线公司模式（多部门协同）",
    },
    "harness": {
        "entry": "架构·产品",
        "pre": ["clarify", "architect", "plan"],
        "roles": ["架构·产品", "架构·总师", "架构·经理", "架构·开发",
                   "架构·评审", "架构·测试"],
        "route": "deepseek harness 内嵌（无市场层，直入研发）",
    },
    "acquisition": {
        "entry": "市场·销售",
        "pre": ["sales_lead", "proposal"],
        "roles": ["市场·销售", "市场·数据", "市场·渠道", "市场·工具",
                   "架构·产品", "架构·总师", "架构·开发"],
        "route": "对外获客（销售建联 → 方案 → 交付）",
    },
    "support": {
        "entry": "市场·客服",
        "pre": ["support_triage"],
        "roles": ["市场·客服", "市场·工具", "市场·数据"],
        "route": "客服售后（接单 → 分级 → 闭环）",
    },
}


def list_profiles():
    """列出所有可用入口模板。"""
    return list(DEFAULT_PROFILES.keys())


def get_profile(name):
    """获取一个入口模板；不存在返回 None。"""
    return DEFAULT_PROFILES.get(name)


def describe(name):
    """渲染某 profile 的可读描述（人类/AI 俯瞰用）。"""
    p = get_profile(name)
    if not p:
        return f"[未知 profile] {name}"
    return (
        f"入口: {p['entry']}  |  前置: {' → '.join(p['pre'])}  |  "
        f"路由: {p['route']}"
    )


def route(spec_profile="default"):
    """前置路由：根据请求的 profile 返回实际应走的流程模板。"""
    p = get_profile(spec_profile)
    if p is None:
        # 未知 profile → 回退 default 并标记
        p = get_profile("default")
        return {
            "profile": "default",
            "description": describe("default"),
            "entry": p["entry"],
            "pre": p["pre"],
            "route": p["route"],
            "fallback": True,
            "requested": spec_profile,
        }
    return {
        "profile": spec_profile,
        "description": describe(spec_profile),
        "entry": p["entry"],
        "pre": p["pre"],
        "route": p["route"],
        "fallback": False,
        "requested": spec_profile,
    }
