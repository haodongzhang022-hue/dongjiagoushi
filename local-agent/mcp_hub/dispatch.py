# -*- coding: utf-8 -*-
"""
MCP 汇聚注册表 · 工具转发层
===========================
按 `specs.ENDPOINTS` 的 `call_via` 真实转发，本层**自己不实现任何业务逻辑**：

  - `relay.check` / `relay.gen` → `relay_card`
  - `standard.*`               → `dev_standard.mcp.call_mcp`
  - `label.*`                  → `label.LabelAbility`（写操作需白名单 operator，否则拒）

转发在本进程内直接 import 调用（子进程隔离留给长耗时/第三方宿主，避免为每个工具
付一次进程启动成本）。**未接的工具如实返回 `not_wired`，不假装成功**——这是本模块
和「看起来 ok 的假集成」的分界线。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

from . import specs

# 标签写操作：必须带合法 operator，否则拒（白名单在 label 模块内校验）
_LABEL_WRITE = {"label.apply", "label.remove", "label.propose", "label.review",
                "label.auto", "label.depends", "label.next", "label.priority",
                "label.node"}


def _err(reason, **extra):
    return {"ok": False, "reason": reason, **extra}


def call(tool, params=None, operator=None):
    """按工具名转发。返回 `{ok: bool, ...}`，未接线/未登记一律 `ok=false`。"""
    params = params or {}
    tool_name = (tool or "").strip()
    if not tool_name:
        return _err("empty_tool")
    if specs.endpoint_for_tool(tool_name) is None:
        return _err("unknown_tool", tool=tool_name,
                    hint="先 python -m mcp_hub.cli tools 查登记；新增端点改 specs.ENDPOINTS")

    try:
        if tool_name == "relay.check":
            from relay_card import check
            ok, reasons = check(params.get("text", ""))
            return {"ok": bool(ok), "data": {"valid": bool(ok), "reasons": reasons}}
        if tool_name == "relay.gen":
            from relay_card import gen
            return {"ok": True, "data": {"card": gen(
                params.get("to", ""), repo=params.get("repo") or None)}}
        if tool_name.startswith("standard."):
            from dev_standard import mcp as std_mcp
            return std_mcp.call_mcp(tool_name, params, operator=operator or "系统")
        if tool_name.startswith("label."):
            if tool_name in _LABEL_WRITE and not operator:
                return _err("operator_required", tool=tool_name,
                            hint="写操作必须带 operator（白名单校验在 label 模块），裸调不回假绿")
            from label import LabelAbility
            return _call_label(tool_name, params, operator or "系统")
        if tool_name.startswith("roster."):
            return _err("http_only", tool=tool_name,
                        hint="roster 走 POST /webhook/<source>/roster（真实鉴权），不经本 hub")
        if tool_name.startswith("dsh."):
            return _err("external_host", tool=tool_name,
                        hint="dsh 工具由 dsh 插件装载时经子进程桥调用")
        return _err("not_wired", tool=tool_name)
    except Exception as e:  # noqa: BLE001 —— 转发层不吞异常，但要如实回报
        return _err("call_failed", tool=tool_name, error=f"{type(e).__name__}: {e}")


def _call_label(tool_name, params, operator):
    from label import LabelAbility
    ab = LabelAbility(owner=operator)
    sub = tool_name.split(".", 1)[1]
    if sub == "progress":
        return {"ok": True, "data": ab.query_progress(params.get("task", ""))}
    if sub == "status":
        return {"ok": True, "data": ab.query_status(params.get("entity", ""))}
    if sub == "labels":
        return {"ok": True, "data": ab.query_labels(params.get("entity", ""))}
    if sub == "apply":
        return {"ok": True, "data": ab.apply_label(
            params.get("entity", ""), params.get("label", ""),
            value=params.get("value", ""), note=params.get("note", ""))}
    if sub == "remove":
        return {"ok": True, "data": ab.remove_label(
            params.get("entity", ""), params.get("label", ""))}
    if sub == "propose":
        return {"ok": True, "data": ab.propose_label(
            params.get("entity", ""), params.get("label", ""),
            reason=params.get("reason", ""))}
    if sub == "review":
        return {"ok": True, "data": ab.review_request(
            params.get("request", ""), decision=params.get("decision", "approved"),
            note=params.get("note", ""))}
    if sub == "auto":
        return {"ok": True, "data": ab.auto_trigger(
            params.get("event", ""), params.get("entity", ""),
            goal_total=int(params.get("goal_total", 0) or 0),
            current=int(params.get("current", 0) or 0), note=params.get("note", ""))}
    if sub == "depends":
        return {"ok": True, "data": ab.set_depends(
            params.get("entity", ""), int(params.get("issue", 0) or 0))}
    if sub == "next":
        return {"ok": True, "data": ab.set_next_step(
            params.get("entity", ""), int(params.get("issue", 0) or 0))}
    if sub == "priority":
        return {"ok": True, "data": ab.set_priority(
            params.get("entity", ""), params.get("level", ""))}
    if sub == "node":
        return {"ok": True, "data": ab.set_pipeline_node(
            params.get("entity", ""), params.get("node", ""),
            value=params.get("value", ""))}
    return _err("not_wired", tool=tool_name)
