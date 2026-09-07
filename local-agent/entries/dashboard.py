# -*- coding: utf-8 -*-
"""
跨端聚合控制页（entries.dashboard · Issue #105 最常用链路深化 · module platform-adapter v0.4.0）
================================================================================================
用户诉求（#105 评论）："做一个方便控制的聚合，类似于 fastapi 聚合页包括状态显示，
然后每个端我都尝试建立一个，这样跨端交互的就会更加顺畅。"

本模块把「跨端交互（本地 deepseek harness ⇄ 网页/gemini 工具桥 ⇄ cnb.cool 云端
异步开发）」的**全部状态聚合到一个控制面上**，供人类 / 本地 harness / 网页桥
**俯瞰 + 便捷控制**——像 FastAPI /docs 聚合页那样：一个地址看到各端状态 + 可触发的
控制动作，不用逐个入口翻状态、不用记每条 CLI。

设计要点：
  1. **宿主无关聚合（single core）**：聚合不感知真实宿主，统一收集
     三端适配器（web/cnb/local）+ 本地⇄云端桥接句柄 + 接力卡 + 成本模型，
     拼成一张「控制台快照」。任何端只从本模块读同一份聚合，杜绝散点状态。
  2. **每端一个面板（per-end panel）**：同一聚合器按端过滤出「本端视角」面板——
     web/cnb/local 各一个面板，看自己的句柄/适配器/动作；跨端则看 total 大盘。
     与「一套核心 + 每端适配层」同构，不另起炉灶。
  3. **FastAPI 风格可读输出**：聚合快照呈 REST 形状（/overview /health /entry/{e}
     /handles /control/{action} 的路由式键），并提供**人可读 HTML 聚合页**
     （状态灯 + 表 + 一键动作），供人类俯瞰 / 网页桥嵌入。
  4. **控制动作回写真实状态机**：一键动作（collect / align / localtest / refresh）
     复用 bridge/route 真实状态流转，非假状态——控制台不只是看板，能真操作。
  5. 全程确定性可本地单测：默认本地模拟传输，真实 cnb/web 桥经 transport 接入。

能力暴露：
  - `panel(entry)`          取某端面板（web/cnb/local 每端一个）+ 聚合大盘
  - `snapshot()`            全端聚合控制台快照（FastAPI 风格路由键）
  - `html_page(entry=None)` 人可读 HTML 聚合页（含状态灯 + 一键控制表单）
  - `control(action,...)`   控制动作：refresh/collect/align/localtest/handles
"""
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from entries import adapter as _adapter
    from entries import route as _route
    from entries import bridge as _bridge
    _HAVE_ENTRIES = True
except Exception:  # noqa: BLE001
    _HAVE_ENTRIES = False

# FastAPI 风格的聚合页「路由表」——控制台支持的路由 + 动作（配置驱动，非 if 堆砌）
# 每个端面板都从这张总路由表过滤出「本端可用动作」。
ENDPOINTS = {
    "GET /health":      {"desc": "控制台健康检查（状态灯）", "action": "health"},
    "GET /overview":    {"desc": "全端聚合大盘（矩阵 + 句柄 + 接力卡 + 成本）", "action": "overview"},
    "GET /entry/{e}":   {"desc": "某端（web/cnb/local）面板视角", "action": "panel"},
    "GET /handles":     {"desc": "全部桥接句柄 + 按状态归集", "action": "handles"},
    "GET /relay":       {"desc": "接力卡当前进度（跨端共享）", "action": "relay"},
    "POST /control/collect":   {"desc": "按句柄收集云端产出（merged/done/need_fix）", "action": "collect"},
    "POST /control/align":     {"desc": "按句柄做本地数据对齐", "action": "align"},
    "POST /control/localtest": {"desc": "云端CPU密集测试下放本地（降建环境成本）", "action": "localtest"},
    "POST /control/request":   {"desc": "发起云端异步开发请求（新句柄）", "action": "request"},
}


# ---------------------------------------------------------------------------
# 一、聚合数据采集（宿主无关，统一从既有真实模块读，不造假）
# ---------------------------------------------------------------------------
def _adapters_view():
    """三端适配器矩阵（沿用 entries.adapter.list_adapters + 秘书主入口护栏）。"""
    try:
        return _route.overview()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _handles_view(status=None):
    """桥接句柄视图：总数 + 按状态归集 + 明细列表。"""
    try:
        handles = _bridge.list_handles(status)
        by_status = {}
        for h in handles.values():
            s = h.get("status", "?")
            by_status.setdefault(s, []).append({
                "handle_id": h.get("handle_id"),
                "req": h.get("req"),
                "entry": h.get("entry"),
                "state": (h.get("cloud_result") or {}).get("state", ""),
                "pr_ids": (h.get("cloud_result") or {}).get("pr_ids", []),
                "updated_at": h.get("updated_at"),
            })
        return {
            "ok": True,
            "total": len(handles),
            "by_status": by_status,
            "handles": list(handles.values()),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _relay_view():
    """接力卡当前进度（跨端共享唯一接力卡协议）。"""
    try:
        sys.path.insert(0, _HERE)
        import relay
        card = relay.load() or {}
        return {"ok": True, "card": card}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _cost_view():
    """成本模型：云端建环境贵 → CPU 密集测试下放本地的分工边界（CLOUD_LOCAL_COOP）。"""
    return {
        "locus": {
            "cloud": "cnb.cool 云端（LLM 强相关 / 异步开发 / 评审）",
            "local": "本地（CPU 密集测试 / harness 管理）——云端建环境贵",
            "hybrid": "按工作类型分流（web 入口默认）",
        },
        "default_rule": "CPU密集测试下放本地执行，云端只保留LLM强相关（用户点名主要成本点）",
    }


# ---------------------------------------------------------------------------
# 二、FastAPI 风格控制台快照（路由键 + 状态灯 + 每端面板）
# ---------------------------------------------------------------------------
def _status_light(ok):
    return "🟢" if ok else "🔴"


def snapshot():
    """全端聚合控制台快照（FastAPI 风格路由键，供人类/harness/网页桥读）。"""
    adapters = _adapters_view()
    handles = _handles_view()
    relay = _relay_view()
    cost = _cost_view()
    now = datetime.utcnow().isoformat()
    # 聚合健康度：适配层 + 句柄层 + 接力卡是否都可用
    healthy = (
        adapters.get("ok", True) is not False
        and handles.get("ok", True) is not False
        and relay.get("ok", True) is not False
    )
    return {
        "module": "platform-adapter",
        "issue": "Issue #105",
        "capability": "entries.dashboard (跨端聚合控制页 · v0.4.0)",
        "generated_at": now,
        "health": {
            "status": "ok" if healthy else "degraded",
            "light": _status_light(healthy),
            "adapters": adapters.get("ok", True) is not False,
            "handles": handles.get("ok", True) is not False,
            "relay": relay.get("ok", True) is not False,
        },
        "main_entry": "架构·秘书",   # 三入口都只是触达通道，主入口唯一
        "entries": adapters.get("entries", []),
        "handles": handles,
        "relay": relay,
        "cost": cost,
        "endpoints": ENDPOINTS,
    }


# ---------------------------------------------------------------------------
# 三、每端一个面板（web/cnb/local）——同一聚合器按端过滤，跨端看大盘
# ---------------------------------------------------------------------------
def panel(entry="local"):
    """取某端控制面板（web/cnb/local 每端一个）。

    面板 = 「本端视角」：本端适配器 + 本端发起的桥接句柄 + 本端可用控制动作 +
    全局大盘参照。任何端看自己都从同一份 snapshot 过滤——不另起数据。
    """
    from . import route as _r
    entry = _r.resolve_entry(entry)
    snap = snapshot()
    this_adapter = None
    for e in snap.get("entries", []):
        if e.get("entry") == entry:
            this_adapter = e
            break
    # 本端发起的句柄（按 entry 过滤）
    handles = snap.get("handles", {})
    my_handles = [
        h for h in handles.get("handles", [])
        if (h.get("entry") or "local") == entry
    ]
    # 本端可用控制动作：总路由表中与本端能力相关的动作
    per_entry_actions = {
        "web":   ["health", "overview", "handles", "request", "collect", "align"],
        "cnb":   ["health", "overview", "handles", "request", "collect"],
        "local": ["health", "overview", "handles", "relay", "request", "collect",
                  "align", "localtest"],   # 本地承载 CPU 密集测试 → localtest 在本端
    }
    my_actions = [
        {"action": a["action"], "desc": a["desc"]}
        for a in ENDPOINTS.values()
        if a["action"] in per_entry_actions.get(entry, [])
    ]
    return {
        "ok": True,
        "entry": entry,
        "panel": {
            "title": f"{entry} 端 · 跨端交互控制面板",
            "health_light": snap["health"]["light"],
            "status": snap["health"]["status"],
            "this_adapter": this_adapter,
            "my_handles_total": len(my_handles),
            "my_handles": my_handles,
            "all_entries_total": len(snap.get("entries", [])),
            "all_handles_total": snap["handles"].get("total", 0),
            "actions": my_actions,
        },
        "global": {
            "entries": [e["entry"] for e in snap.get("entries", [])],
            "handles_by_status": snap["handles"].get("by_status", {}),
            "main_entry": snap["main_entry"],
        },
        "cost": snap["cost"],
    }


def all_panels():
    """三端面板并列（跨端顺畅交互的总览——每个端都建了一个）。"""
    return {
        "web": panel("web"),
        "cnb": panel("cnb"),
        "local": panel("local"),
        "generated_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# 四、控制动作（一键操作，复用真实状态机，非假状态）
# ---------------------------------------------------------------------------
def control(action, handle_id=None, collect_state=None, pr_ids=None, req=None,
            entry="local"):
    """控制动作路由：refresh / health / overview / panel / handles / relay /
    request / collect / align / localtest。

    返回 FastAPI 风格结果（action + ok + data），供人类/网页桥一键触发。
    """
    action = (action or "overview").lower()
    if action in ("health", "overview"):
        return {"action": action, "ok": True, "data": snapshot()}
    if action == "panel":
        return {"action": action, "ok": True, "data": panel(entry)}
    if action == "handles":
        return {"action": action, "ok": True, "data": _handles_view()}
    if action == "relay":
        return {"action": action, "ok": True, "data": _relay_view()}
    if action == "request":
        if not req:
            return {"action": action, "ok": False, "error": "request 需 req 参数"}
        return {"action": action, "ok": True,
                "data": _bridge.request_cloud_dev(req, entry=entry)}
    if action in ("collect", "align", "localtest"):
        if not handle_id:
            return {"action": action, "ok": False,
                    "error": f"{action} 需 handle_id 参数"}
        if action == "collect":
            prs = [x.strip() for x in (pr_ids or "").split(",") if x.strip()]
            return {"action": action, "ok": True,
                    "data": _bridge.collect_cloud_result(
                        handle_id, cloud_state=collect_state, pr_ids=prs)}
        if action == "align":
            return {"action": action, "ok": True,
                    "data": _bridge.align_local(handle_id)}
        if action == "localtest":
            return {"action": action, "ok": True,
                    "data": _bridge.local_test_first(handle_id)}
    return {"action": action, "ok": False,
            "error": f"未知控制动作: {action}", "available": list(ENDPOINTS.keys())}


# ---------------------------------------------------------------------------
# 五、人可读 HTML 聚合页（FastAPI /docs 式：状态灯 + 表 + 一键控制表单）
# ---------------------------------------------------------------------------
def html_page(entry=None):
    """生成人可读聚合控制页 HTML（含状态显示 + 一键控制动作）。

    entry=None → 全端大盘；entry=web/cnb/local → 某端面板页。
    供人类在浏览器俯瞰 / 网页桥嵌入 iframe。
    """
    if entry:
        s = panel(entry)
        title = f"{entry} 端 · 跨端交互控制面板"
    else:
        s = snapshot()
        title = "跨端交互聚合控制台"
    health = s.get("health", {}) if entry is None else {"status": s["panel"]["status"],
                                                         "light": s["panel"]["health_light"]}
    rows = []
    if entry is None:
        # 大盘：三端适配器矩阵
        for e in s.get("entries", []):
            rows.append(f"<tr><td>{e['entry']}</td><td>{e['name']}</td>"
                        f"<td>{e['locus']}</td><td>{e['profile']}</td>"
                        f"<td>{','.join(e['interfaces'])}</td></tr>")
        table_title = "三端适配器矩阵"
    else:
        p = s["panel"]
        this = p.get("this_adapter") or {}
        rows.append(f"<tr><td>{p['title']}</td><td>本端状态 {p['health_light']} {p['status']}</td>"
                    f"<td>适配器 {this.get('name')} / locus={this.get('locus')}</td>"
                    f"<td>本端句柄 {p['my_handles_total']} / 全局 {p['all_handles_total']}</td>"
                    f"<td>主入口 {s.get('global',{}).get('main_entry')}</td></tr>")
        table_title = "面板概览"
    handles = s.get("handles", {}) if entry is None else {
        "by_status": s.get("global", {}).get("handles_by_status", {})}
    by_status = handles.get("by_status", {})
    def _cell_ids(v):
        ids = [x if isinstance(x, str) else x.get('handle_id', '') for x in v][:8]
        return ', '.join(ids) or '—'
    status_rows = "".join(
        "<tr><td>%s</td><td>%d</td><td>%s</td></tr>" % (k, len(v), _cell_ids(v))
        for k, v in by_status.items())
    # 一键控制动作
    actions = list(ENDPOINTS.items())
    if entry:
        p = s["panel"]
        acts = {a["action"] for a in p["actions"]}
        actions = [(k, v) for k, v in ENDPOINTS.items() if v["action"] in acts]
    action_rows = "".join(
        f"<tr><td>{k}</td><td>{v['desc']}</td>"
        f"<td><form method='post' style='display:inline'>"
        f"<input name='action' value='{v['action']}' hidden>"
        f"<button>{v['action']}</button></form></td></tr>"
        for k, v in actions)
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:sans-serif;max-width:960px;margin:24px auto;padding:0 16px;background:#f7f7f9}}
h1{{font-size:22px}} .light{{font-size:18px}} table{{border-collapse:collapse;width:100%;margin:12px 0}}
td,th{{border:1px solid #ccc;padding:6px 10px;text-align:left;font-size:13px}}
th{{background:#e8e8ef}} code{{background:#eee;padding:1px 5px;border-radius:3px}}
button{{cursor:pointer;padding:3px 10px;border-radius:4px;border:1px solid #999}}
.note{{color:#666;font-size:12px}}
</style></head><body>
<h1>🔧 {title}</h1>
<p class="light">控制台健康度：<span>{health.get('light','🟢')}</span> <b>{health.get('status','ok')}</b>
 · 主入口 <code>{s.get('main_entry','架构·秘书')}</code> · module platform-adapter v0.4.0 · Issue #105</p>
<h2>{table_title}</h2>
<table><tr><th>入口</th><th>名称</th><th>执行地 locus</th><th>profile</th><th>宿主接口</th></tr>{''.join(rows)}</table>
<h2>桥接句柄状态（按状态归集）</h2>
<table><tr><th>状态</th><th>数量</th><th>句柄</th></tr>{status_rows or '<tr><td colspan=3>暂无句柄</td></tr>'}</table>
<h2>一键控制动作</h2>
<table><tr><th>路由</th><th>说明</th><th>动作</th></tr>{action_rows}</table>
<p class="note">跨端交互顺畅：三端都从同一份聚合快照读状态；控制动作回写真实桥接/接力状态机，非假状态。</p>
</body></html>"""


# ---------------------------------------------------------------------------
# 六、CLI 便捷：聚合控制台 一步触发（供 run.py --dashboard / --panel 调用）
# ---------------------------------------------------------------------------
def cli_dashboard(entry=None, action="overview", handle_id=None, collect_state=None,
                  pr_ids=None, req=None, html=False):
    """run.py --dashboard 的语义入口。

    action: health / overview / panel / handles / relay / request / collect /
            align / localtest / html
    """
    if html:
        return {"ok": True, "html": html_page(entry), "entry": entry or "all"}
    if action == "html":
        return {"ok": True, "html": html_page(entry), "entry": entry or "all"}
    if action == "panel":
        return {"ok": True, "data": panel(entry or "local")}
    return control(action, handle_id=handle_id, collect_state=collect_state,
                   pr_ids=pr_ids, req=req, entry=entry or "local")


# ---- 便利引用 ----
overview = snapshot
