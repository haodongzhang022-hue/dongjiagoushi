# -*- coding: utf-8 -*-
"""
调度中枢 · 统一调度引擎（engine）
=================================
把「事件源 → 规则识别 → 入队 → 防无效护栏 → 路由派发 → 驳回迭代」串成一条
可运行的自动化闭环。提供：

  - `scan_once()`：单次扫描所有事件源，处理一轮（供 CLI `scan` 与定时调用）；
  - `watch(interval)`：持续守护循环（复用 timer 心跳巡检），周期扫描；
  - `drain()`：处理已入队的自动意图（auto_release → guard → dispatch）；
  - `process_event(event)`：处理单个事件（供外部/webhook 直接投递）。

设计目标（用户拍板全 5 点）：
  - 触发源：本仓库 + 外部适配器（source.ExternalAdapter 插槽）——#1；
  - 队列不卡进程：Action 队列，auto 自动放行 / hold 人工闸门——#2；
  - 驳回迭代闭环：rejections 表 + 按 gid 回派改进重提——#3；
  - 防无效：guard 去重/频限/进度上限 + sentinel 量化监控——#4；
  - Web 面板：webui 实时俯瞰——#5。
"""
import time
from datetime import datetime

from data import db
from . import rules as rules_mod
from . import source as source_mod
from . import guard as guard_mod
from . import queue as queue_mod
from . import router as router_mod
from . import reject as reject_mod


class Dispatcher:
    """事件驱动调度中枢。"""

    def __init__(self, sources=None, rule_engine=None, guard=None):
        self._sources = sources or [source_mod.RepoPollAdapter()]
        self._rules = rule_engine or rules_mod.RuleEngine()
        self._guard = guard or guard_mod.Guard()
        self._stats = {"scanned": 0, "matched": 0, "dispatched": 0, "blocked": 0, "skipped": 0}

    # ---- 单事件处理 ----
    def process_event(self, raw_event):
        """处理单个事件：规范化 → 规则匹配 → 入队 → (自动)护栏 → 派发。

        返回处理结果 dict，供面板/webhook 回显。
        """
        event = source_mod.normalize_event(raw_event)
        self._stats["scanned"] += 1
        rule = self._rules.match(event)
        if not rule:
            self._stats["skipped"] += 1
            return {"event_id": event["event_id"], "status": "skipped",
                    "note": "无规则命中", "event": event}

        intent = self._rules.build_intent(rule, event)
        self._stats["matched"] += 1

        # 驳回事件：登记到 rejections 表（数据库）→ 构造回派意图
        if event["event_type"] == "rejection":
            detail = event.get("detail", {})
            rej = reject_mod.register(
                task_id=detail.get("task_id", event.get("gid", "")),
                gid=event.get("gid", ""),
                agent_id=detail.get("agent_id", event.get("gid", "")),
                reason=detail.get("reason", event.get("detail", {}).get("reason", "")),
                level=detail.get("level", "must"),
            )
            intent = reject_mod.route_intent(rej)
            intent["event_id"] = event["event_id"]

        # 入队（Action 队列，不卡进程；hold 进人工闸门）
        enq = queue_mod.enqueue(intent)
        if enq["status"] == "hold":
            return {"event_id": event["event_id"], "status": "hold",
                    "note": "需人工判断，进入审核闸门", "rule": rule.get("name"), "event": event}

        # 自动意图：guard 判定 → 派发
        ok, reason = self._guard.evaluate(intent)
        if not ok:
            queue_mod.mark_rejected(event["event_id"], reason)
            self._stats["blocked"] += 1
            return {"event_id": event["event_id"], "status": "rejected",
                    "note": reason, "rule": rule.get("name"), "event": event}

        self._guard.mark_dedup(intent)
        result = router_mod.dispatch(intent, event["event_id"])
        queue_mod.mark_dispatched(event["event_id"],
                                  target_agent=result["target_agent"],
                                  note=f"派发给 {result['target_agent']}")
        self._stats["dispatched"] += 1
        return {"event_id": event["event_id"], "status": "dispatched",
                "rule": rule.get("name"), "target_agent": result["target_agent"],
                "event": event}

    # ---- 扫描所有事件源 ----
    def scan_once(self):
        """扫描所有事件源并逐条处理，返回本轮的扫描摘要。"""
        events = []
        for src in self._sources:
            try:
                events.extend(src.poll())
            except Exception as e:  # 单个事件源失败不阻断整体
                events.append({"event_type": "source.error", "entity": src.name,
                               "detail": {"error": str(e)}, "source": src.name})
        results = [self.process_event(ev) for ev in events]
        return {
            "scanned": len(events),
            "results": results,
            "stats": dict(self._stats),
        }

    # ---- 处理待处理的自动意图（drain 队列） ----
    def drain(self):
        """把已入队的 auto 意图批量放行并派发（不卡进程）。"""
        released = queue_mod.auto_release()
        done = []
        for r in released:
            intent = {
                "event_id": r["event_id"], "event_type": r["event_type"],
                "source": r["source"], "entity": r["entity"], "gid": r["gid"],
                "rule": r["matched_rule"], "target_role": r["target_role"],
                "target_agent": r["target_agent"], "gate": "auto",
                "dedup_key": r["dedup_key"],
            }
            ok, reason = self._guard.evaluate(intent)
            if not ok:
                queue_mod.mark_rejected(r["event_id"], reason)
                done.append({"event_id": r["event_id"], "status": "rejected", "note": reason})
                continue
            self._guard.mark_dedup(intent)
            result = router_mod.dispatch(intent, r["event_id"])
            queue_mod.mark_dispatched(r["event_id"], target_agent=result["target_agent"])
            done.append({"event_id": r["event_id"], "status": "dispatched",
                         "target_agent": result["target_agent"]})
        return {"released": len(released), "done": done}

    # ---- 驳回迭代闭环扫描 ----
    def scan_rejections(self):
        """扫描待处理的驳回记录，按 gid 回派原负责 agent（改进重提）。

        驳回非终点：迭代闭环持续推动改进，直到通过或被哨兵判 2 级 blocked。
        """
        out = []
        for rej in reject_mod.pending():
            # 已回派且未超时迭代则跳过（由 guard/去重护栏防重复）
            ok, reason = self._guard.evaluate({
                "gid": rej["gid"], "event_type": "rejection",
                "dedup_key": f"{rej['gid']}:rejection", "target_agent": rej["agent_id"],
            })
            if not ok:
                out.append({"rejection_id": rej["rejection_id"], "status": "blocked_by_guard", "reason": reason})
                continue
            self._guard.mark_dedup({"dedup_key": f"{rej['gid']}:rejection"})
            result = router_mod.reroute_rejection(rej)
            reject_mod.mark_reassigned(rej["rejection_id"], result["target_agent"])
            out.append({"rejection_id": rej["rejection_id"], "status": "reassigned",
                        "target_agent": result["target_agent"]})
        return out

    # ---- 持续守护 ----
    def watch(self, interval=5, iterations=None, on_scan=None):
        """持续守护循环：周期扫描事件源 + drain 队列 + 驳回回派。

        复用 timer 心跳巡检语义（interval 秒一轮）。on_scan 回调每轮结果。
        """
        n = 0
        while iterations is None or n < iterations:
            n += 1
            scan = self.scan_once()
            drained = self.drain()
            rejects = self.scan_rejections()
            round_info = {
                "round": n,
                "scanned": scan["scanned"],
                "dispatched": drained["done"],
                "rejections": rejects,
                "stats": dict(self._stats),
            }
            if on_scan:
                on_scan(round_info)
            if iterations is not None:
                break
            time.sleep(interval)
        return round_info


def build_default():
    return Dispatcher()
