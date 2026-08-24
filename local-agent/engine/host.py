# -*- coding: utf-8 -*-
"""
上位机 · 运行内核（host）
=========================
「上位机」在本文档中 = 调度主控台：统一管理其下每一台「机器角色」的
**时序（定时器）** 与 **状态（状态机）**，让整条 agent 接力链路具备
工程可观测、可超时、可续跑、可放行的能力。

host 把三样东西装配在一起：
  1. 一组机器角色（role 名清单，来自 team.yaml / 编排）；
  2. 每个机器角色当前任务对应的 StateMachine（状态卡）；
  3. 全局 TimerEngine（心跳巡检 + 超时 + 定时任务）。

对外提供：
  - `HostEngine.start_role(...)`：让某个机器角色上场（建状态机 -> 启动）
  - `HostEngine.tick()`：由上位机统一巡检，把所有角色的状态/超时管起来
  - `HostEngine.overview()`：一张表俯瞰所有机器角色状态（人工俯瞰二级信息）
  - `HostEngine.timeout_watch(...)`：给某个机器角色任务设超时

用法：
  host = HostEngine()
  host.start_role("架构·开发", card_id="dev_1")
  host.timeout_watch("dev_1", timeout_sec=5)   # 5 秒没完成自动打断
  host.run(ticks=50)                            # 上位机跑 50 次巡检
  print(host.overview())
"""
import time

from .timer import TimerEngine
from .state_machine import StateMachine

try:
    from ..scale import store as _store
except ImportError:  # 兼容 local-agent 作为 sys.path 根目录直接 import engine
    from scale import store as _store


class HostEngine:
    """上位机运行内核：统一管理各机器角色的状态与时序。"""

    def __init__(self, backend=None, tick_interval=0.01):
        self._backend = backend or _store
        self._timer = TimerEngine(backend=self._backend, tick_interval=tick_interval)
        self._machines = {}   # card_id -> StateMachine
        self._roles = {}      # card_id -> role 名

    # ---- 机器角色入场 / 出场 ----
    def start_role(self, role, card_id, initial="pending"):
        """让一台机器角色带着任务状态卡上场。"""
        sm = StateMachine(card_id, backend=self._backend, initial=initial)
        self._machines[card_id] = sm
        self._roles[card_id] = role
        return sm

    def stop_role(self, card_id):
        self._timer.unwatch(card_id)
        self._machines.pop(card_id, None)
        self._roles.pop(card_id, None)

    # ---- 状态操作（代理到 StateMachine）----
    def machine(self, card_id):
        """返回某机器角色的状态机（实时从后端同步最新状态）。"""
        sm = self._machines[card_id]
        card = self._backend.get(card_id)
        if card and card.get("status"):
            sm._status = card["status"]  # 与后端同步（定时器可能已改状态）
        return sm

    # ---- 时序操作（代理到 TimerEngine）----
    def timeout_watch(self, card_id, timeout_sec, on_timeout="interrupt", reason=""):
        return self._timer.watch(card_id, timeout_sec, on_timeout, reason)

    def unwatch(self, card_id):
        self._timer.unwatch(card_id)

    def schedule(self, job_id, interval, fn, repeat=True):
        self._timer.schedule(job_id, interval, fn, repeat)

    # ---- 上位机统一巡检 ----
    def tick(self):
        """上位机跑一次巡检：把定时器（到期任务+超时）作用到所有机器角色上。"""
        return self._timer.tick()

    def run(self, ticks=100, sleep=0.001):
        """同步跑 ticks 次巡检（测试/单机用）。"""
        for _ in range(ticks):
            self.tick()
            if sleep:
                time.sleep(sleep)

    # ---- 俯瞰（二级信息）----
    def overview(self):
        """生成一张「机器角色状态总表」，供人类/上位机俯瞰决策。"""
        rows = []
        for cid in list(self._machines.keys()):
            sm = self.machine(cid)  # 实时同步
            rows.append({
                "role": self._roles.get(cid, "?"),
                "card_id": cid,
                "status": sm.status,
                "card": sm.peek(),
            })
        return rows

    def summary(self):
        """状态统计摘要（各状态计数），供看板/断言。"""
        from collections import Counter
        return Counter(r["status"] for r in self.overview())
