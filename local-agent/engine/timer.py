# -*- coding: utf-8 -*-
"""
上位机 · 定时器引擎（timer）
============================
为「机器角色」赋予**时序能力**，让上位机（调度主控）能周期性地：
  - **心跳巡检**：周期扫描所有机器角色的状态卡，发现异常（超时未续跑、
    状态卡在 in_progress 卡死等）自动触发 [打断] / 阻塞上报。
  - **超时检测**：给任务设置 deadline，超时未完成即自动转移状态并留痕。
  - **定时触发**：按 cron/间隔调度一次性或周期动作（如定时刷新看板、
    定时驱动某个机器角色上场）。

设计：
  - 复用 `state_machine.StateMachine`，超时检测直接调用合法转移
    （in_progress -> interrupted/blocked）。
  - 复用 `scale/store.py` 作为状态底座，跨后端（filesystem/memory）可用。
  - 提供同步 tick 与后台线程两种模式：默认单线程 tick 便于测试；
    规模场景可 `TimerEngine.start()` 起守护线程周期巡检。
"""
import threading
import time
from datetime import datetime, timedelta

from .state_machine import StateMachine

try:
    from ..scale import store as _store
except ImportError:  # 兼容 local-agent 作为 sys.path 根目录直接 import engine
    from scale import store as _store


class TimerEngine:
    """定时器引擎：心跳巡检 + 超时检测 + 定时任务。

    参数:
      backend       状态后端（默认 scale.store）
      tick_interval 心跳巡检间隔（秒），默认 0.1，便于测试
    """

    def __init__(self, backend=None, tick_interval=0.1):
        self._backend = backend or _store
        self._tick_interval = tick_interval
        self._jobs = {}          # job_id -> job dict
        self._timeouts = {}      # card_id -> deadline
        self._heartbeat_cbs = [] # 巡检回调（可注入规则：如触发打断/阻塞）
        self._thread = None
        self._running = False

    # ---------------- 定时任务 ----------------
    def schedule(self, job_id, interval, fn, repeat=True):
        """注册一个周期任务：每 interval 秒执行一次 fn()。

        repeat=False 时只执行一次（定时触发）。
        """
        self._jobs[job_id] = {
            "id": job_id,
            "interval": interval,
            "fn": fn,
            "repeat": repeat,
            "next_at": time.monotonic() + interval,
            "last_run": None,
            "runs": 0,
        }

    def cancel(self, job_id):
        self._jobs.pop(job_id, None)

    # ---------------- 超时检测 ----------------
    def watch(self, card_id, timeout_sec, on_timeout="interrupt", reason=""):
        """给某张机器角色状态卡设置超时（秒）。

        on_timeout:
          "interrupt" -> 自动打[打断]标记（in_progress -> interrupted）
          "block"     -> 直接置阻塞上报（in_progress -> blocked）
        返回注册的 deadline。
        """
        deadline = datetime.utcnow() + timedelta(seconds=timeout_sec)
        self._timeouts[card_id] = {
            "deadline": deadline,
            "on_timeout": on_timeout,
            "reason": reason,
        }
        return deadline

    def unwatch(self, card_id):
        self._timeouts.pop(card_id, None)

    # ---------------- 心跳巡检 ----------------
    def add_heartbeat(self, cb):
        """注册巡检回调 cb()，每次 tick 调用，可注入业务规则。"""
        self._heartbeat_cbs.append(cb)

    def tick(self):
        """同步执行一次巡检：跑到期定时任务 + 检查超时卡。返回本次处理的事件数。"""
        now = time.monotonic()
        events = 0
        # 1. 到期的定时任务
        for jid, job in list(self._jobs.items()):
            if now >= job["next_at"]:
                try:
                    job["fn"]()
                finally:
                    job["runs"] += 1
                    job["last_run"] = now
                    events += 1
                    if job["repeat"]:
                        job["next_at"] = now + job["interval"]
                    else:
                        self._jobs.pop(jid, None)
        # 2. 超时检测
        now_utc = datetime.utcnow()
        for cid, w in list(self._timeouts.items()):
            if now_utc >= w["deadline"]:
                self._timeouts.pop(cid, None)
                sm = StateMachine(cid, backend=self._backend)
                if w["on_timeout"] == "block":
                    try:
                        sm.block(actor="timer", reason=w["reason"] or "超时未完成")
                    except ValueError:
                        pass
                else:
                    try:
                        sm.interrupt(
                            actor="timer",
                            reason=w["reason"] or "超时未完成",
                            checkpoint="timer 超时自动打断，待续跑",
                        )
                    except ValueError:
                        pass
                events += 1
        # 3. 心跳回调
        for cb in self._heartbeat_cbs:
            cb()
        return events

    # ---------------- 后台线程模式 ----------------
    def start(self, daemon=True):
        """启动守护线程周期巡检（规模场景）。幂等：重复调用不重复起线程。"""
        if self._running:
            return self
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=daemon)
        self._thread.start()
        return self

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None

    def _loop(self):
        while self._running:
            self.tick()
            time.sleep(self._tick_interval)

    # ---------------- 状态 ------------
    def stats(self):
        """当前定时器状态（任务数/超时监控数/心跳回调数），供看板。"""
        return {
            "jobs": len(self._jobs),
            "timeouts": len(self._timeouts),
            "heartbeat_callbacks": len(self._heartbeat_cbs),
            "running": self._running,
        }
