# -*- coding: utf-8 -*-
"""
执行体槽位池（slot.pool）· 近因优先 + 可配队列 + 领取后自愈
============================================================
三条规则的**确定性实现**（不依赖 LLM 判断，给定输入必然同样结果）：

① 近因优先取件（LIFO）
   旧行为 FIFO：`pick` 取 `enqueued_at` 最早的一条。于是一个卡住的老任务会
   长期占住并发额度，后面的永远排不上——「他不止一次这样了」的病根。
   新行为：取 **最新入队** 的一条。`picked` 的活卡住 → 被 `reserve` 占用 →
   下一次 `do_get` 直接**跨过它**取更新的，卡住的只卡一次，不堵后面。

② 队列加长（`queue_capacity`）
   FIFO 时代有效并发额度 ≈ 1，队列短一点就立刻见底。加长队列后，即使有 `stuck`
   任务被跨过、被重新接回，也还有位置放下新的，池子不会一堵就空。

③ 领取后自愈（`reserve()` 内部触发 `repair_rest`）
   领走一件活后，把**同一批里同样卡住的其它活重新接上**（repair 次数 +1、重置
   计时、重新入队），不需要人一个个去捞。次数上限 `max_repairs` 兜底，超限标
   `dead` 并显式暴露（升级/上报），**不静默吞**。

状态机（每个 Task）：
    queued ──pick──▶ picked ──reserve──▶ running
                                            │
                        ┌───────────────────┼────────────────────┐
                        ▼                   ▼                    ▼
                     done(成功)      stuck(超时/卡死)        dead(自愈超限)
                                          │
                                     repair_rest 重新入队 → queued（可再被取）

三个数字必须分开看（不混成一个「都挺好」）：
   `queued`（等着）/ `running`（在跑）/ `stuck`+`dead`（要处置）
"""
import threading
import time
import uuid
from datetime import datetime


DEFAULTS = {
    # 队列容量：小队列 + 一个卡死任务 = 立刻见底；加长后卡住不影响后面
    "queue_capacity": 512,
    # 同时可占用的执行体槽位（云端 NPC 并发额度 ≈ 这里）
    "slots": 4,
    # 占用超过该秒数没释放 → 判 stuck（卡住）
    "stuck_after_seconds": 300,
    # 同一任务最多自愈接回几次（超限 → dead 显式暴露，不静默）
    "max_repairs": 3,
    # summary 里最多列多少个 stuck 明细（避免刷屏）
    "max_report": 10,
}


class Task(object):
    """池子里的一个待执行/执行中的活。"""

    __slots__ = ("task_id", "kind", "entity", "enqueued_at", "updated_at",
                 "state", "repairs", "slot", "note")

    def __init__(self, task_id, kind="", entity="", now=None):
        self.task_id = task_id
        self.kind = kind
        self.entity = entity
        now = now if now is not None else time.time()
        self.enqueued_at = now
        self.updated_at = now
        self.state = "queued"
        self.repairs = 0
        self.slot = None
        self.note = ""

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "kind": self.kind,
            "entity": self.entity,
            "state": self.state,
            "repairs": self.repairs,
            "slot": self.slot,
            "note": self.note,
            "waiting_seconds": round(self.updated_at - self.enqueued_at, 3),
        }

    def __repr__(self):
        return f"<Task {self.task_id} {self.state} repairs={self.repairs}>"


class SlotPool(object):
    """执行体槽位池：近因优先取件 + 加长队列 + 领取后自愈。

    纯内存 + 线程安全；进程外可持久化到 dispatcher 的 dispatch 表（本层不绑定 DB，
    避免把调度语义耦合进存储）。
    """

    def __init__(self, capacity=None, slots=None, stuck_after_seconds=None,
                 max_repairs=None, order="recency", clock=None, **kw):
        cfg = dict(DEFAULTS)
        cfg.update({k: v for k, v in kw.items() if k in DEFAULTS})
        if capacity is not None:
            cfg["queue_capacity"] = int(capacity)
        if slots is not None:
            cfg["slots"] = max(1, int(slots))
        if stuck_after_seconds is not None:
            cfg["stuck_after_seconds"] = float(stuck_after_seconds)
        if max_repairs is not None:
            cfg["max_repairs"] = int(max_repairs)
        cfg["order"] = order if order in ("recency", "fifo") else "recency"
        self.cfg = cfg
        self._clock = clock or (lambda: time.time())
        self._lock = threading.RLock()
        self._tasks = {}          # task_id -> Task（保持插入序不重要，取件按时间戳）
        self._order = []          # 入队顺序（task_id），仅供俯瞰
        self._rejected = 0        # 队列满拒绝计数（显式暴露，不静默丢）

    # ------------------------------------------------------------------
    # 入队
    # ------------------------------------------------------------------
    def enqueue(self, task_id=None, kind="", entity="", note=""):
        """把一件活放进池子。队列满 → 拒绝并计数（返回 None），不静默丢。"""
        tid = task_id or f"tk-{uuid.uuid4().hex[:10]}"
        with self._lock:
            exist = self._tasks.get(tid)
            if exist is not None:
                # 同一 task_id 重复入队：幂等（不漂移、不重复占位）
                if exist.state in ("done", "dead"):
                    exist.state = "queued"
                    exist.updated_at = self._clock()
                return exist
            if self._queued_count() >= self.cfg["queue_capacity"]:
                self._rejected += 1
                return None
            t = Task(tid, kind=kind, entity=entity, now=self._clock())
            t.note = note
            self._tasks[tid] = t
            self._order.append(tid)
            return t

    # ------------------------------------------------------------------
    # 取件（近因优先）
    # ------------------------------------------------------------------
    def pick(self):
        """取一条 queued 的活（默认近因优先：最新入队优先）；无则 None。

        默认 `max(enqueued_at)`；`order="fifo"` 时为旧行为 `min(enqueued_at)`（仅用于对比/
        回归）。卡住的老任务在近因优先下**不会**长期压住池头。
        """
        with self._lock:
            cands = [t for t in self._tasks.values() if t.state == "queued"]
            if not cands:
                return None
            order = {tid: i for i, tid in enumerate(self._order)}
            if self.cfg.get("order") == "fifo":
                chosen = min(cands, key=lambda t: (t.enqueued_at, order.get(t.task_id, 0)))
            else:
                chosen = max(cands, key=lambda t: (t.enqueued_at, order.get(t.task_id, 0)))
            chosen.state = "picked"
            chosen.updated_at = self._clock()
            return chosen

    def reserve(self, task_id=None, auto_repair=True):
        """占一个槽位并领走一件活（默认近因优先）。

        **领走之后立刻尝试把其它卡住的接上**（用户要的「领取一个后，把其他接上，
        这样自动修了」）——这是本方法内建的，不依赖调用方记得调 `repair_rest`。

        返回 {task, slot, repairs, blocked}：
          task     领到的 Task（None = 无可领）
          slot     占用的槽位号（None = 槽位满）
          repairs  本次顺带接回的任务列表（task_id）
          blocked  槽位满时为 True，显式暴露不假装领到
        """
        with self._lock:
            repairs = []
            slot = self._free_slot()
            if slot is None:
                # 槽位满：仍尝试自愈（卡住的活占着槽位，能接回就有机会释放）
                if auto_repair:
                    repairs = self._repair_locked()
                return {"task": None, "slot": None, "repairs": repairs, "blocked": True}

            if task_id:
                task = self._tasks.get(task_id)
                if task is None or task.state not in ("queued", "stuck"):
                    task = None
            else:
                task = self.pick()

            if task is None:
                return {"task": None, "slot": None, "repairs": repairs, "blocked": False}

            task.state = "running"
            task.slot = slot
            task.updated_at = self._clock()
            if auto_repair:
                repairs = self._repair_locked(exclude=task.task_id)
            return {"task": task, "slot": slot, "repairs": repairs, "blocked": False}

    def release(self, task_id, ok=True, note=""):
        """释放槽位。ok=True → done；ok=False → stuck（等下一次自愈接回）。"""
        with self._lock:
            t = self._tasks.get(task_id)
            if t is None:
                return None
            t.state = "done" if ok else "stuck"
            t.slot = None
            t.updated_at = self._clock()
            t.note = note or t.note
            return t

    def mark_stuck(self, task_id, note="超时未释放"):
        return self.release(task_id, ok=False, note=note)

    # ------------------------------------------------------------------
    # 自愈接回
    # ------------------------------------------------------------------
    def repair_rest(self, exclude=None):
        """把池子里**卡住（stuck）**的其它活重新接回（对外入口）。"""
        with self._lock:
            return self._repair_locked(exclude=exclude)

    def _repair_locked(self, exclude=None):
        """（持锁）stuck → queued，repairs+1；超 max_repairs → dead 显式暴露。"""
        repaired = []
        now = self._clock()
        for t in list(self._tasks.values()):
            if t.task_id == exclude:
                continue
            if t.state != "stuck":
                continue
            if t.repairs >= self.cfg["max_repairs"]:
                t.state = "dead"
                t.note = f"自愈接回超限({t.repairs})，需上报/换方案"
                t.updated_at = now
                continue
            t.repairs += 1
            t.state = "queued"
            t.slot = None
            t.updated_at = now
            # 重置计时：重新入队视为一次新的等待窗口（近因优先下会比老任务更早被取）
            t.enqueued_at = now
            repaired.append(t.task_id)
        return repaired

    def sweep_stuck(self):
        """把超过 stuck_after_seconds 仍在 running 的活判 stuck（不静默挂着）。"""
        now = self._clock()
        out = []
        with self._lock:
            for t in self._tasks.values():
                if t.state == "running" and (now - t.updated_at) >= self.cfg["stuck_after_seconds"]:
                    t.state = "stuck"
                    t.slot = None
                    t.updated_at = now
                    t.note = t.note or "占用超时判 stuck"
                    out.append(t.task_id)
        return out

    # ------------------------------------------------------------------
    # 俯瞰
    # ------------------------------------------------------------------
    def _queued_count(self):
        return sum(1 for t in self._tasks.values() if t.state in ("queued", "picked"))

    def _busy_slots(self):
        return sum(1 for t in self._tasks.values() if t.state == "running")

    def _free_slot(self):
        used = {t.slot for t in self._tasks.values() if t.state == "running" and t.slot is not None}
        for i in range(self.cfg["slots"]):
            if i not in used:
                return i
        return None

    def stats(self):
        c = {}
        for t in self._tasks.values():
            c[t.state] = c.get(t.state, 0) + 1
        return {
            "queued": c.get("queued", 0) + c.get("picked", 0),
            "running": c.get("running", 0),
            "stuck": c.get("stuck", 0),
            "dead": c.get("dead", 0),
            "done": c.get("done", 0),
            "rejected_full": self._rejected,
        }

    def overview(self):
        """二级信息：三类状态分开 + stuck 明细 + 配置（人可读俯瞰）。"""
        st = self.stats()
        stuck = [t.to_dict() for t in self._tasks.values() if t.state in ("stuck", "dead")]
        stuck.sort(key=lambda d: d["repairs"], reverse=True)
        return {
            "config": dict(self.cfg),
            "stats": st,
            "capacity_left": self.cfg["queue_capacity"] - st["queued"],
            "slots_free": self.cfg["slots"] - st["running"],
            "needs_action": st["stuck"] + st["dead"],
            "stuck_detail": stuck[: self.cfg["max_report"]],
            "order_policy": "recency-first（最新入队优先，卡住的只卡一次）",
        }


# ----------------------------------------------------------------------
# 配置：从 .cnb.yml 的 npc_task.slot_pool 读（单一事实源，不在代码里另写一套）
# ----------------------------------------------------------------------
def load_npc_pool_config(repo_root=None):
    """读取 `.cnb.yml` 里 `npc_task.slot_pool` 配置块（不依赖 pyyaml）。

    CI（`.cnb.yml`）与本地引擎（本模块）读**同一份**配置，避免两边各写一套漂移。
    缺配置或读不到 → 返回 DEFAULTS（不报错，退化为默认），并在返回值里标 `source`。
    """
    import os
    root = repo_root or os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    path = os.path.join(root, ".cnb.yml")
    cfg = dict(DEFAULTS)
    cfg["source"] = "defaults"
    if not os.path.isfile(path):
        return cfg
    keys = ("queue_capacity", "slots", "stuck_after_seconds", "max_repairs")
    in_block = False
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("slot_pool:"):
                in_block = True
                continue
            if in_block:
                if ":" not in stripped:
                    break
                k, _, v = stripped.partition(":")
                k = k.strip()
                v = v.split("#")[0].strip()
                # 退出块：出现顶格新键且不是本块键
                if raw[:1] not in (" ", "\t") or k not in keys:
                    in_block = False
                    continue
                try:
                    cfg[k] = int(v) if k != "stuck_after_seconds" else float(v)
                    cfg["source"] = ".cnb.yml:npc_task.slot_pool"
                except ValueError:
                    pass
    return cfg


def pool_from_config(repo_root=None, **override):
    """按 `.cnb.yml` 的 slot_pool 配置构造 SlotPool（CI 与本地同源）。"""
    cfg = load_npc_pool_config(repo_root)
    kw = {k: v for k, v in cfg.items() if k in DEFAULTS}
    kw.update(override)
    pool = SlotPool(**kw)
    pool.cfg["source"] = cfg.get("source", "defaults")
    return pool
