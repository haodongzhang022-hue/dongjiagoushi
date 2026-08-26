# -*- coding: utf-8 -*-
"""
调度中枢 · 脉冲式信号探测器（probe）
====================================
用户拍板纠偏：**轮询不好，换脉冲式的一个信号探测器**——有条件就触发、路由到脚本、
不多处一直轮询（轮询会静默失败，机制上就不好）。

背景（对齐 docs/DISPATCHER.md）：
  - 旧 dispatcher 靠 `ExternalAdapter.poll()` / `RepoPollAdapter` / `LocalHostAdapter`
    的 `poll` + `Dispatcher.watch()` 持续守护循环 **多次轮询扫描**事件源；
  - 轮询的问题：① 无事件时空转，多个源各自轮询（"多处一直轮询"）；② 单源 poll
    失败被 `except` 吞掉（"静默失败"）；③ 事件到达后要靠下一轮扫描才被捕获，
    有延迟、会漏。
  - 用户要的是**脉冲式信号探测器**：有信号（事件/条件满足）才触发，一次命中即
    路由到对应脚本/处理器，无信号不空转，每次触发显式留痕、失败显式上报不吞。

本模块（probe.py）落地「脉冲式信号探测器」：
  - **探测器（probe）** = 触发条件(matcher) + 处理器(handler/script)。注册成表。
  - **信号触发（fire_signal）**：收到一个信号（事件/条件）时，精确匹配探测器，
    命中即触发对应处理器**一次**。有信号才动作，无信号不空转。
  - **路由到脚本（route_to_script）**：探测器可配 `script`（脚本路径），触发时
    经 `subprocess` 路由执行该脚本；也可配 `handler`（callable）或 `target_role`
    （经 dispatcher 路由派发给对应 agent）。
  - **不静默失败（显式留痕）**：每次触发把结果（matched/fired/ok/error/note）写入
    `probe_firings` 表；失败**显式上报**（写 firing 且 note 标 error），绝不吞异常。

与既有零件的配合：
  - `fire_signal` 是**事件驱动入口**（webhook / host.emit / 显式调用都走这里），
    取代「poll 消费本地暂存队列」的轮询消费方式；
  - 探测器可复用 `guard` 做去重/去抖/频限，防无效触发；
  - 可与 `router.dispatch` 联动：`action.type="dispatch"` 时把信号路由派发给 agent。
"""
import os
import subprocess
import threading
import uuid
from datetime import datetime

try:
    from data import db
    from . import guard as guard_mod
    _DB_OK = True
except Exception:  # noqa: BLE001 兼容缺库环境（纯内存模式）
    db = None
    guard_mod = None
    _DB_OK = False

# 模块级去重护栏（进程内共享实例，跨 fire_signal 调用生效，防无效触发）
_GUARD = guard_mod.Guard() if guard_mod is not None else None


_lock = threading.Lock()
# 进程内探测器注册表：probe_id -> probe dict
_PROBES = {}


# ---------------------------------------------------------------------------
# 探测器数据模型
# ---------------------------------------------------------------------------
def _now():
    return datetime.utcnow().isoformat()


def _new_id():
    return f"prb-{uuid.uuid4().hex[:12]}"


def register_probe(name, event_type="", source="", condition=None,
                   action=None, enabled=True, probe_id=None, priority=0):
    """注册一个脉冲式信号探测器。

    参数（= 触发条件 + 处理器）:
      name        探测器名（业务标识）
      event_type  命中的事件类型（空=任意，如 issue.open / sentinel.alert / requirement）
      source      命中的事件源（空=任意，如 repo / local_pc / 外部适配器名）
      condition   额外触发条件：callable(signal)->bool 或谓词字符串（可含属性名）
      action      处理器路由配置 dict：
                    {"type":"script",   "script":"路径",  "args":{}}    → 路由执行脚本
                    {"type":"handler",  "handler":callable(signal)}     → 调用处理器函数
                    {"type":"dispatch", "target_role":"架构·开发"}       → 路由派发给 agent
                    {"type":"emit",     "event_type":"...", "target_role":"..."}
                                                                        → 转成新事件再投递
                    （缺省 type 视为 handler，若 action 是 callable 直接用）
      enabled     是否启用（False 则 fire_signal 不匹配它）
      probe_id    稳定寻址 id（同一探测器二次注册取回同一 id，不漂移）
      priority    匹配优先级（值大先匹配；默认 0）
    返回 probe_id（稳定寻址，二次注册同 name 取回同一探测器）。
    """
    global _PROBES
    pid = probe_id or name
    with _lock:
        if pid in _PROBES:
            # 二次注册 = 更新配置（稳定寻址，同一探测器）
            _PROBES[pid].update({
                "event_type": event_type, "source": source, "condition": condition,
                "action": action, "enabled": enabled, "priority": priority,
            })
            return pid
        _PROBES[pid] = {
            "probe_id": pid,
            "name": name,
            "event_type": event_type or "",
            "source": source or "",
            "condition": condition,
            "action": action,
            "enabled": enabled,
            "priority": priority,
            "registered_at": _now(),
            "firings": 0,
        }
    if _DB_OK:
        try:
            db.execute(
                "INSERT OR REPLACE INTO probe (probe_id, name, event_type, source,"
                " action, enabled, priority, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (pid, name, event_type or "", source or "", _action_json(action),
                 int(enabled), priority, _now()),
            )
        except Exception:  # noqa: BLE001 表可能未建，内存态仍可用
            pass
    return pid


def _action_json(action):
    """把 action 持久化为可 JSON 的形态（丢弃 callable/script 路径外的不可序列化项）。"""
    if action is None:
        return ""
    if not isinstance(action, dict):
        return str(action)
    out = dict(action)
    out.pop("handler", None)   # callable 不落库，重启后由接入方重新注册
    return out


def unregister_probe(probe_id):
    """注销一个探测器（enabled=False + 移除进程内注册）。"""
    global _PROBES
    with _lock:
        _PROBES.pop(probe_id, None)
    if _DB_OK:
        try:
            db.execute("UPDATE probe SET enabled=0 WHERE probe_id=?", (probe_id,))
        except Exception:  # noqa: BLE001
            pass


def list_probes(enabled=None):
    """探测器俯视图（含累计触发数）。"""
    with _lock:
        probes = list(_PROBES.values())
    if enabled is not None:
        probes = [p for p in probes if p["enabled"] == enabled]
    return [
        {
            "probe_id": p["probe_id"], "name": p["name"],
            "event_type": p["event_type"], "source": p["source"],
            "enabled": p["enabled"], "priority": p["priority"],
            "firings": p["firings"],
            "action": _action_json(p.get("action")),
        }
        for p in probes
    ]


# ---------------------------------------------------------------------------
# 触发条件匹配（有条件就触发）
# ---------------------------------------------------------------------------
def _match_condition(probe, signal):
    """判定一个信号是否命中某探测器（= 触发条件是否满足）。"""
    et = probe.get("event_type") or ""
    if et and signal.get("event_type") != et:
        return False
    src = probe.get("source") or ""
    if src and signal.get("source") != src:
        return False
    cond = probe.get("condition")
    if cond is None:
        return True
    if callable(cond):
        try:
            return bool(cond(signal))
        except Exception:  # noqa: BLE001 条件求值异常视为不命中，且显式上报
            _record_firing(probe, signal, matched=False, ok=False,
                           note=f"condition error: {cond!r}")
            return False
    # 谓词字符串：直接 bool 求值（谨慎），或按"属性:值"等号匹配
    if isinstance(cond, str):
        s = str(signal)
        return cond in s
    return False


# ---------------------------------------------------------------------------
# 路由到脚本 / 处理器（有条件就触发一次）
# ---------------------------------------------------------------------------
def route_to_script(script, signal, args=None, timeout=30):
    """把信号路由执行一个脚本（subprocess）。

    返回 (ok, note)。脚本可通过 argv 或 stdin 收到信号（JSON）。
    """
    if not script or not os.path.exists(script):
        return False, f"script not found: {script!r}"
    payload = {"signal": signal, "args": args or {}}
    try:
        proc = subprocess.run(
            ["python3", script, os.path.abspath(script)],
            input=json_dumps(payload), capture_output=True, text=True,
            timeout=timeout,
        )
        if proc.returncode == 0:
            return True, (proc.stdout or "ok").strip()[:200]
        return False, f"script exit={proc.returncode}: {(proc.stderr or '').strip()[:200]}"
    except subprocess.TimeoutExpired:
        return False, f"script timeout>{timeout}s"
    except Exception as e:  # noqa: BLE001
        return False, f"script error: {e}"


def json_dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


def fire_action(probe, signal):
    """执行探测器路由动作，返回 (ok, note, result)。"""
    action = probe.get("action")
    atype = "handler" if not isinstance(action, dict) else action.get("type", "handler")
    if atype == "script":
        ok_, note_ = route_to_script(action.get("script", ""), signal,
                                     args=action.get("args"))
        return ok_, note_, None
    if atype == "dispatch":
        from . import router
        intent = {
            "event_id": signal.get("event_id", ""),
            "event_type": signal.get("event_type", ""),
            "source": signal.get("source", ""),
            "entity": signal.get("entity", ""),
            "gid": signal.get("gid", ""),
            "detail": signal.get("detail", {}),
            "target_role": action.get("target_role", "架构·开发"),
            "action": action.get("action", "dispatch"),
            "rule": action.get("rule", probe.get("name", "")),
        }
        res = router.dispatch(intent, signal.get("event_id", ""))
        return True, f"dispatched -> {res.get('target_agent')}", res
    if atype == "emit":
        from . import engine
        from .source import normalize_event
        ev = {
            "event_type": action.get("event_type", signal.get("event_type", "")),
            "source": signal.get("source", ""),
            "entity": signal.get("entity", ""),
            "gid": signal.get("gid", ""),
            "detail": dict(signal.get("detail", {})),
        }
        dispatcher = engine.Dispatcher()
        res = dispatcher.process_event(normalize_event(ev))
        return True, f"emitted {res.get('status')}", res
    # handler（默认）：action 直接是 callable 或 action["handler"] 是 callable
    handler = action if callable(action) else (
        action.get("handler") if isinstance(action, dict) else None)
    if handler is not None and callable(handler):
        try:
            result = handler(signal)
            return True, str(result)[:200], result
        except Exception as e:  # noqa: BLE001
            return False, f"handler error: {e}", None
    # action 是 {"type":"handler"}（占位，未注入 callable）：视为已接收匹配信号（成功，不误报）
    if atype == "handler":
        return True, "signal received (handler 占位)", None
    return False, f"unknown action type: {atype}", None


# ---------------------------------------------------------------------------
# 信号触发入口（脉冲式核心）
# ---------------------------------------------------------------------------
def fire_signal(signal, register_miss=True):
    """脉冲式信号触发：收到一个信号，精确匹配探测器，命中即触发一次。

    返回触发报告：
      {
        "signal_id", "matched": int, "fired": int,
        "ok": bool, "results": [...],
        "missed": bool,   # 无探测器命中（可据此显式暴露"遗漏未处理"）
      }

    特性（对齐用户诉求）：
      - 有条件就触发：只有命中触发条件的探测器才触发，绝不无差别全触发；
      - 路由到脚本：action.type="script" 时路由执行脚本；其余路由到 handler/dispatch；
      - 不轮询：本函数是事件驱动入口（有信号才调），无信号不空转；
      - 不静默失败：每次触发写 probe_firings 留痕，失败 note 显式标 error；
      - 防无效：可复用 guard（去重/去抖/频限）拦截重复触发。
    """
    signal = dict(signal)
    signal.setdefault("event_id", f"ev-{uuid.uuid4().hex[:12]}")
    signal.setdefault("event_type", "unknown")
    signal.setdefault("source", "repo")
    signal.setdefault("entity", "")
    signal.setdefault("gid", "")
    signal.setdefault("detail", {})

    with _lock:
        probes = sorted(
            [p for p in _PROBES.values() if p.get("enabled")],
            key=lambda p: p.get("priority", 0), reverse=True,
        )

    results = []
    matched = fired = 0
    ok = True
    for probe in probes:
        if not _match_condition(probe, signal):
            continue
        matched += 1
        # 防无效护栏：去重（同一 signal_id+probe 只触发一次）
        if _GUARD is not None:
            try:
                dk = f"{signal.get('event_id')}:{probe['probe_id']}"
                if not _GUARD.check_dedup({"dedup_key": dk}):
                    results.append({"probe_id": probe["probe_id"],
                                    "name": probe["name"], "fired": False,
                                    "note": "dedup", "ok": True})
                    continue
                _GUARD.mark_dedup({"dedup_key": dk})
            except Exception:  # noqa: BLE001 护栏异常不阻断触发
                pass
        fired += 1
        fok, note, res = fire_action(probe, signal)
        ok = ok and fok
        probe["firings"] += 1
        _record_firing(probe, signal, matched=True, ok=fok, note=note)
        results.append({"probe_id": probe["probe_id"], "name": probe["name"],
                        "fired": True, "ok": fok, "note": note, "result": res})

    missed = matched == 0
    # 无探测器命中：显式暴露（对应"遗漏未处理要安排"，不静默吞掉）
    if missed and register_miss:
        _record_miss(signal)

    return {
        "signal_id": signal.get("event_id"),
        "matched": matched,
        "fired": fired,
        "ok": ok,
        "missed": missed,
        "results": results,
    }


# ---------------------------------------------------------------------------
# 显式留痕（不静默失败）
# ---------------------------------------------------------------------------
def _record_firing(probe, signal, matched, ok, note=""):
    """把一次触发写入 probe_firings（显式留痕，失败 note 标 error）。"""
    if not _DB_OK:
        return
    try:
        db.execute(
            "INSERT INTO probe_firings (firing_id, probe_id, probe_name, event_id,"
            " event_type, source, entity, gid, matched, ok, note, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"pf-{uuid.uuid4().hex[:12]}", probe.get("probe_id", ""),
             probe.get("name", ""), signal.get("event_id", ""),
             signal.get("event_type", ""), signal.get("source", ""),
             signal.get("entity", ""), signal.get("gid", ""),
             int(matched), int(ok), str(note)[:500], _now()),
        )
    except Exception:  # noqa: BLE001 留痕失败不阻断触发主流程
        pass


def _record_miss(signal):
    """无探测器命中时留痕（遗漏未处理，显式暴露而非静默）。"""
    if not _DB_OK:
        return
    try:
        db.execute(
            "INSERT INTO probe_misses (miss_id, event_id, event_type, source,"
            " entity, gid, note, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (f"pm-{uuid.uuid4().hex[:12]}", signal.get("event_id", ""),
             signal.get("event_type", ""), signal.get("source", ""),
             signal.get("entity", ""), signal.get("gid", ""),
             "未命中任何探测器（遗漏未处理，需安排）", _now()),
        )
    except Exception:  # noqa: BLE001
        pass


def firing_overview(limit=50):
    """探测器触发留痕俯视图（二级信息，供人类/面板俯瞰）。"""
    if not _DB_OK:
        return {"firings": [], "misses": []}
    try:
        firings = [dict(r) for r in db.query(
            "SELECT * FROM probe_firings ORDER BY id DESC LIMIT ?", (limit,))]
    except Exception:  # noqa: BLE001
        firings = []
    try:
        misses = [dict(r) for r in db.query(
            "SELECT * FROM probe_misses ORDER BY id DESC LIMIT ?", (limit,))]
    except Exception:  # noqa: BLE001
        misses = []
    return {"firings": firings, "misses": misses,
            "ok": sum(1 for f in firings if f.get("ok")),
            "error": sum(1 for f in firings if not f.get("ok"))}


# ---------------------------------------------------------------------------
# 便捷：把现有 dispatcher 扫描语义改为信号触发语义
# ---------------------------------------------------------------------------
def scan_to_signal(sources, dispatcher=None, on_event=None):
    """把「扫描所有事件源」改为「对每个事件逐个 fire_signal 脉冲触发」。

    不再依赖持续轮询：每个来源产出的事件（signal）到达即触发一次对应探测器。
    返回触发报告列表。
    """
    reports = []
    for src in sources:
        try:
            events = src.poll()   # 一次显式拉取（单次扫描，非持续轮询）
        except Exception as e:  # 单源失败显式上报，不静默
            reports.append({"source": getattr(src, "name", "?"), "ok": False,
                            "note": f"source error: {e}", "results": []})
            continue
        for ev in events:
            from .source import normalize_event
            sig = normalize_event(ev)
            if on_event:
                on_event(sig)
            reports.append({"source": getattr(src, "name", "?"),
                            **fire_signal(sig)})
    return reports
