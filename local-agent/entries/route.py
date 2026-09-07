# -*- coding: utf-8 -*-
"""
入口归一化路由（entries.route · Issue #105 三入口归一化）
==========================================================
把三个执行入口（网页对话 / cnb.cool 云端 NPC / 本地 harness-AI）的一句话
统一收敛到**唯一主入口「架构·秘书」**，再由秘书路由到对应角色/流水线。

设计要点：
  1. 主入口锁死秘书：`guard_entry` 强制护栏（default/company 等模板必须经秘书，
     harness 内嵌允许跳过）——入口之争消亡，三入口只是「把话送到秘书面前」的通道。
  2. 配置管差异：入口→(适配器 / 执行地 / profile) 由 `ENTRY_LOCI` 配置承载，
     不做 if 分支。
  3. 三入口差异收敛到适配层，核心编排仅一份。
"""
import os
import sys

# 允许本地直接 import local-agent 下兄弟模块
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from scale import profile
from . import adapter as _adapter


def resolve_entry(raw):
    """把用户触达的「入口」收敛为规范入口标识（web / cnb / local）。

    用户可能用别名/场景词描述入口，这里做归一化映射（配置驱动，非 if 堆砌）：
      - 网页/网页对话/公司页/web       → web
      - cnb.cool/云端NPC/Issue/评论/@  → cnb
      - 本地/本地AI/harness/CLI/run.py → local
    未知入口默认 local（保守本地直驱）。
    """
    if not raw:
        return "local"
    r = str(raw).strip().lower()
    web_kw = ("web", "网页", "对话")
    cnb_kw = ("cnb", "云端", "issue", "评论", "npc")
    local_kw = ("local", "本地", "harness", "cli", "run.py", "脚本")
    for kw in cnb_kw:
        if kw in r:
            return "cnb"
    for kw in web_kw:
        if kw in r:
            return "web"
    for kw in local_kw:
        if kw in r:
            return "local"
    return "local"


def entry_guard(entry, direct_role=None, spec_profile=None):
    """入口护栏：确认「秘书为唯一主入口」的强制规则。

    - 非 harness 模板强制从「架构·秘书」进入（复用 scale.profile.guard_entry）；
    - 返回结构化护栏结果，供调用方判断是否合规。
    """
    p = spec_profile or _adapter.ENTRY_LOCI.get(entry, ("", "", "default"))[2]
    g = profile.guard_entry(p, direct_role=direct_role)
    return {
        "entry": entry,
        "main_entry": profile.SECRETARY_ROLE,
        "mandatory": g["mandatory"],
        "ok": g["ok"],
        "profile": p,
        "message": g["message"],
        "direct_role": direct_role,
    }


def route(entry, task, role=None, direct_role=None):
    """入口归一化路由：把「入口 + 任务」收敛到秘书主入口并落位适配器。

    返回接力/触发上下文：
      - 若违反强制入口（直接 @ 角色跳过秘书）→ ok=False，提示先补秘书路由留痕；
      - 否则 → 定位到对应适配器，交由适配器 trigger（秘书主入口→目标角色）。
    """
    entry = resolve_entry(entry)
    # 1) 确认秘书主入口护栏
    guard = entry_guard(entry, direct_role=direct_role)
    adapter = _adapter.get_adapter(entry)
    if not guard["ok"]:
        return {
            "ok": False,
            "entry": entry,
            "main_entry": guard["main_entry"],
            "guard": guard,
            "action": "需先经架构·秘书接收/翻译/路由留痕",
            "adapter": adapter.describe(),
        }
    # 2) 秘书主入口接收 → 路由到目标角色
    #    - 显式给定 role / 本入口放行的 direct_role → 路由到该角色；
    #    - 否则默认秘书澄清（主入口唯一，其余只是触达通道）。
    if role:
        target_role = role
    elif direct_role and guard["ok"]:
        target_role = direct_role   # 入口放行的直接 @ 角色
    else:
        target_role = guard["main_entry"]
    trig = adapter.trigger(target_role, task)
    return {
        "ok": True,
        "entry": entry,
        "main_entry": guard["main_entry"],
        "guard": guard,
        "routed_to": target_role,
        "ack": f"已接管自秘书路由的 {target_role}",
        "action": "adapter.trigger",
        "trigger": trig,
        "adapter": adapter.describe(),
    }


def run_scaled(req, entry, spec_obj=None, backend=None):
    """走单份核心编排跑规模化流水线（差异只在本层，核心不感知入口）。

    入口(web/cnb/local)只决定适配器 + 执行地/profile 配置（非 if 分支），
    真正的规模化编排委托 scale.engine.run_scaled 单份执行。
    """
    entry = resolve_entry(entry)
    adapter = _adapter.get_adapter(entry)
    from scale import engine
    spec_obj = dict(spec_obj or {})
    # 执行地/ profile 由入口配置决定，落到核心 spec，非硬编码
    spec_obj.setdefault("profile", adapter.profile)
    # 入口护栏：default 系（web/cnb）必须经秘书；harness 系（local）放行
    g = entry_guard(entry)
    if not g["ok"]:
        return {"ok": False, "entry": entry, "guard": g,
                "action": "需先经秘书主入口"}
    rep = engine.run_scaled(req, spec_obj=spec_obj, verbose=False)
    rep["ok"] = True
    rep["entry"] = entry
    rep["adapter"] = adapter.describe()
    rep["locus"] = adapter.locus
    return rep


def overview():
    """二级信息俯瞰：三入口归一化全貌。"""
    rows = _adapter.overview()
    # 秘书主入口护栏核对：default（web/cnb 入口的 profile）必须强制秘书
    g = profile.guard_entry("default")
    rows["main_entry_guard"] = {
        "main_entry": profile.SECRETARY_ROLE,
        "mandatory": g["mandatory"],
        "ok": g["ok"],
    }
    return rows
