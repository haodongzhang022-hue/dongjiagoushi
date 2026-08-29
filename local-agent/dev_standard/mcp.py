# -*- coding: utf-8 -*-
"""
开发规范 · MCP 工具暴露层（dev-standard · mcp.py · Issue #83）
================================================================
把 StandardAbility 能力暴露为 MCP 风格工具调用，供外部宿主（cnb.cool /
deepseek harness / CLI / 任意 agent 运行时）统一接入。本层是**薄封装**，
所有逻辑收口到 StandardAbility，不重复实现。

暴露工具：
  - standard.list         列出规范条目
  - standard.get          取单条规范
  - standard.enforced     取某阶段强制规范清单
  - standard.check        程序化合规检查（确定性）
  - standard.report       合规报告
  - standard.summary      规范概览

MCP 工具名统一前缀 `standard.`，与现有 label/cli MCP 管线风格一致。
"""
import json
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

from dev_standard import StandardAbility

# 对外暴露的工具清单（供宿主注册）
MCP_TOOLS = [
    {"name": "standard.list", "description": "列出开发规范条目",
     "params": {"level": "可选，L1/L2/L3", "category": "可选，structure/code/docs/process/quality"}},
    {"name": "standard.get", "description": "取单条规范详情",
     "params": {"spec_id": "必填，如 S01"}},
    {"name": "standard.enforced", "description": "取某开发阶段强制规范清单",
     "params": {"stage": "必填，pre_pr/review/commit/deliver/all"}},
    {"name": "standard.check", "description": "程序化合规检查（确定性）",
     "params": {"target": "必填，dict（pr_info/code_file/issue_info 等）"}},
    {"name": "standard.report", "description": "合规报告",
     "params": {"results": "必填，check 返回结果", "format": "json/markdown"}},
    {"name": "standard.summary", "description": "规范注册表概览", "params": {}},
]


def _ability(operator="系统"):
    return StandardAbility(owner=operator)


def call_mcp(tool_name, params=None, operator="系统"):
    """MCP 工具调用入口。给定工具名 + 参数，返回标准化响应。"""
    params = params or {}
    ab = _ability(operator)
    try:
        if tool_name == "standard.list":
            return {"ok": True, "data": ab.list_standards(
                level=params.get("level"), category=params.get("category"))}
        if tool_name == "standard.get":
            return {"ok": True, "data": ab.get_standard(params.get("spec_id"))}
        if tool_name == "standard.enforced":
            return {"ok": True, "data": [s["id"] for s in
                    ab.get_enforced_specs(params.get("stage"))]}
        if tool_name == "standard.check":
            target = params.get("target")
            if isinstance(target, str):
                target = json.loads(target)
            return {"ok": True, "data": ab.check_standard(target or {})}
        if tool_name == "standard.report":
            results = params.get("results") or {}
            fmt = params.get("format", "json")
            return {"ok": True, "data": ab.report_compliance(
                params.get("entity", "mcp"), results, format=fmt)}
        if tool_name == "standard.summary":
            return {"ok": True, "data": ab.standards_summary()}
        return {"ok": False, "error": f"未知工具 {tool_name}",
                "available": [t["name"] for t in MCP_TOOLS]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
