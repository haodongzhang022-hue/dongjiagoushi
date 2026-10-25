# -*- coding: utf-8 -*-
"""
承接方标准工作接口（WorkFace · Issue #239 四轮）
================================================
经理「督促」的判据是**客观证据**。可"证据从哪来"这件事，过去没人管：
引擎里有个 `simulate` 参数，能让对端"看起来接了单"——测试里用它跑通了整条链，
于是**绿的信号灯证明的是模拟器，不是经理**。

这一层补两件事：

| 事 | 为什么 |
|----|--------|
| `RoleWorkFace` 实现同一套 `accept/start/progress/deliver` | 任何角色都能"真的上工"，产出**真实**证据（progress 事件 + goal_meters + 回执消息），不靠 simulate |
| `credential_of()` 把证据分级 | 派发方只认 `real` / `role`；`simulated` 只准出现在测试里，主链路里出现即视为「假装分工」 |

## 证据分级（一句话）

```
simulated  —— 演练/测试注入，不算干活
role       —— 角色真回执 + 真写进度尺（本地/云端任一载体）
external   —— 平台侧可核验（Issue 评论回执 / PR / CI），最硬
```

`READY_LEVELS = {"role", "external"}`——这就是"安排成功的标准"的代码版。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

#: 算"真干活"的证据等级（simulated 明确排除在外）
READY_LEVELS = ("role", "external")

#: 进度尺前缀候选（跨模块复用，避免各写一份）
METER_PREFIXES = ("g-", "gm-", "role-")

#: 回执 message topic 前缀（角色工作面投递的回执消息）
RECEIPT_TOPIC = "work.receipt."


def record_work(task_key, kind, agent="", role="", task_id="", note="",
                evidence="", delta=0.0, goal_total=0.0, current=None):
    """落一条**工作证据**：progress 事件 + 归档（可回溯、可被派发方核验）。

    kind: accepted / started / progressed / delivered
    返回 {"task_id", "kind", "level"}；level 由是否有外部凭据决定。
    """
    from gid import gid_for
    from data import admin
    task_id = task_id or gid_for("task", task_key) or task_key
    level = "external" if evidence else "role"
    admin.record_event(
        agent or role or "role",
        {"accepted": "accepted", "started": "work_started",
         "progressed": "progressed", "delivered": "delivered"}[kind],
        {"task_key": task_key, "task_id": task_id, "role": role or agent,
         "kind": kind, "note": note, "evidence": evidence},
        task_id,
    )
    try:
        admin.archive(f"work_{kind}_{task_id}", "work",
                      f"{role or agent} · {kind}", {
                          "task_key": task_key, "kind": kind, "note": note,
                          "evidence": evidence, "delta": delta,
                      }, source=agent or role or "role")
    except Exception:  # noqa: BLE001 归档失败不改变判定
        pass
    if kind in ("progressed", "delivered") and (delta or current is not None):
        _meter(agent or role, task_id, task_key, goal_total, current, delta, note)
    return {"task_id": task_id, "kind": kind, "level": level}


def _meter(agent_id, task_id, task_key, goal_total, current, delta, note):
    """写进度尺（goal_meters）——哨兵收敛判定与经理监督的唯一量化来源。"""
    try:
        from sentinel import engine as sentinel
        meter_id = f"g-{task_id}"
        if current is None:
            series = sentinel.store.meter_series(meter_id) or []
            base = series[-1]["current"] if series else 0.0
            current = base + (delta or 0.0)
        sentinel.track(meter_id, task_id=task_id, agent_id=agent_id or "",
                       target=task_key, goal_total=goal_total or current,
                       current=current, note=note or "")
    except Exception:  # noqa: BLE001 尺写不了不谎报进度，交由上层判 awaiting
        pass


class RoleWorkFace:
    """承接方标准工作面：让**任何角色**都能真上工，产出可核验证据。

    引擎侧（`RoleWorker` / `manager.ShadowWorker`）只要实现了这四个方法，
    `ManagerEngine` 就能真正驱动它干活——而不再只是投一张卡等回执。
    """

    def __init__(self, role="", agent_id="", delegate=True):
        self.role = role
        self.agent_id = agent_id
        self.delegate = delegate

    # ---------------- 四步标准动作 ----------------
    def accept(self, task_key, task_id="", note=""):
        """回执 [接单]：真落事件 + 真投回执消息（经理据此判 L3）。"""
        from data import admin
        rec = record_work(task_key, "accepted", agent=self.agent_id,
                          role=self.role, task_id=task_id,
                          note=note or "[接单] 已接手")
        admin.post_message(
            topic=f"{RECEIPT_TOPIC}{self.role}",
            payload={"task_key": task_key, "task_id": rec["task_id"],
                     "agent_id": self.agent_id, "role": self.role,
                     "action": "accept", "note": note or "[接单] 已接手"},
            from_agent=self.agent_id or self.role, to_agent="架构·经理",
        )
        return {"accepted": True, "level": rec["level"], "task_id": rec["task_id"]}

    def start(self, task_key, task_id="", note=""):
        """开工：落 `work_started` 事件（L4 的唯一凭据）。"""
        return record_work(task_key, "started", agent=self.agent_id,
                           role=self.role, task_id=task_id,
                           note=note or "已开工")

    def progress(self, task_key, task_id="", target="", goal_total=0.0,
                 current=None, delta=0.0, note=""):
        """推进：写进度尺（哨兵与被监督方共用同一把尺）。"""
        return record_work(task_key, "progressed", agent=self.agent_id,
                           role=self.role, task_id=task_id, note=note,
                           goal_total=goal_total, current=current, delta=delta)

    def deliver(self, task_key, output="", task_id="", evidence=""):
        """交付：落 `delivered` 事件 + 归档产出；有外部凭据（Issue/PR/CI）升级为 external。"""
        return record_work(task_key, "delivered", agent=self.agent_id,
                           role=self.role, task_id=task_id,
                           note=str(output)[:500], evidence=evidence)


class WorkerRegistry:
    """承接方注册表：经理按**角色名**取到会干活的承接方。

    用法（本地引擎/云端 harness 都适用）：

        reg = WorkerRegistry()
        reg.register("架构·开发", RoleWorkFace("架构·开发"))
        engine = ManagerEngine(repo=..., workers=reg)
    """

    def __init__(self, workers=None):
        self._workers = dict(workers or {})

    def register(self, role, worker):
        self._workers[role] = worker
        return self

    def get(self, role):
        return self._workers.get(role)

    def has(self, role):
        """该角色是否**真能干活**（实现了 accept+start 两个最小动作）。"""
        w = self._workers.get(role)
        return bool(w) and all(callable(getattr(w, n, None))
                               for n in ("accept", "start"))

    def roles(self):
        return sorted(self._workers)


class ShadowWorker(RoleWorkFace):
    """演练承接方（测试/演练用）：行为可配，证据带 `simulated` 标记。

    真实经理**不接受**它的回执（`credential_of` 判 simulated → 不算干活）。
    它存在的唯一理由是让"无人接单 → 调人 → 上工"的链路能离线验证。
    """

    def __init__(self, role="", agent_id="", mode="deliver",
                 goal_total=1.0, rounds=2):
        super().__init__(role=role, agent_id=agent_id or f"sim-{role}")
        self.mode = mode            # accept / deliver / work（只有 accept 就停）
        self.goal_total = goal_total
        self.rounds = max(1, int(rounds))
        self._cur = 0.0

    def accept(self, task_key, task_id="", note=""):
        res = super().accept(task_key, task_id=task_id, note=note)
        return {**res, "level": "simulated"}

    def run_round(self, task_key, task_id="", round_no=1):
        """跑一轮活：按 mode 决定干到哪一步（accept 模式只回执，不干活）。"""
        if self.mode == "accept":
            return {"did": [], "note": "演练：只回执，不开工"}
        did = [self.start(task_key, task_id=task_id,
                          note="演练开工")["kind"]]
        step = (self.goal_total or 1.0) / self.rounds
        self._cur = min(self.goal_total or 1.0, self._cur + step)
        did.append(self.progress(task_key, task_id=task_id,
                                 goal_total=self.goal_total or 1.0,
                                 current=self._cur, delta=step)["kind"])
        if self.mode == "deliver" and self._cur >= (self.goal_total or 1.0):
            did.append(self.deliver(task_key, output="演练交付",
                                    task_id=task_id)["kind"])
        return {"did": did, "current": self._cur}


def credential_of(task_id, role=""):
    """把某任务上的证据分级：simulated 不算干活，role/external 才算。

    返回 {"level", "events", "meters", "why"}——派发方**只认 READY_LEVELS**。
    """
    from data import db
    events, simulated, external = [], False, False
    real_kinds = ("accepted", "work_started", "progressed", "delivered")
    real_events, sim_kinds = [], set()
    try:
        rows = db.query("SELECT event, detail, agent_id FROM progress WHERE task_id=? ORDER BY id",
                        (task_id,))
        for row in rows:
            ev = row["event"] if not isinstance(row, tuple) else row[0]
            detail = row["detail"] if not isinstance(row, tuple) else row[1]
            agent = row["agent_id"] if not isinstance(row, tuple) else row[2]
            events.append(ev)
            text = str(detail or "")
            # 演练标记按**每条事件**判：一次演练回执不能把后续真实开工也打成"假"。
            mock = ("演练" in text or "simulated" in text
                    or str(agent or "").startswith("sim-"))
            if mock:
                simulated = True
                sim_kinds.add(ev)
            elif ev in real_kinds:
                real_events.append(ev)
            if any(k in text for k in ("issue#", "pull#", "PR#", "ci:", "平台回执")):
                external = True
    except Exception:  # noqa: BLE001 读不到事件 = 无证据，不臆断
        pass
    meters = []
    try:
        from sentinel import store
        meters = list(store.meters_for_task(task_id) or [])
    except Exception:  # noqa: BLE001
        meters = []
    if external:
        level = "external"
    elif real_events:
        level = "role"
    elif sim_kinds:
        level = "simulated"
    else:
        level = "none"
    return {"level": level, "events": events, "meters": len(meters),
            "simulated": simulated, "real_events": real_events,
            "why": {"external": "外部可核验凭据（Issue/PR/CI）",
                    "role": "承接方真回执 + 真推进",
                    "simulated": "演练注入，不算干活",
                    "none": "无任何证据"}[level]}


def is_ready(cred):
    """这条凭据算不算"安排成功"（simulated/none → False）。"""
    return str((cred or {}).get("level")) in READY_LEVELS
