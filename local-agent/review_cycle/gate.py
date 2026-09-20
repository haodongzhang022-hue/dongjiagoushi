# -*- coding: utf-8 -*-
"""评审段「阶段链门控」确定性引擎（gate · Issue #150 打断补齐）。

把「开发→测试→评审」从"一次触发就多点并发"改回**链式有序推进**：

- **active 阶段**：同一任务任一时刻只承认**一个活跃阶段**（由阶段活动登记表裁定）；
- **放行**：上游阶段已收口 + 本阶段未在跑 → `allow`，链式往后推进；
- **驳回（三种，缺一即乱）**：
  - `blocked_active`：本阶段已在跑 = 重复触发 → 复用进行中的任务（不新起、不冲进度）；
  - `blocked_upstream`：上游未收口 = 抢跑（"开发还没完就跑去测试/评审"）；
  - `blocked_switched`：先跑了下游再回头补上游 = 乱序（会把一条链拆成两条并行）。

全部为**确定性判定**（代码给定输入必得同一判决），不让 LLM 决定"现在该谁跑"。
状态落本地 JSON（与 cycle 的 state 同目录习惯），可跨调用方共享。
"""
import json
import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from review_cycle import stage_spec as spec  # noqa: E402

_STATE_LOCK = threading.Lock()
# 允许环境变量覆盖（`REVIEW_STAGE_FILE`）：测试隔离用，避免污染工作区共享链状态。
_STATE_FILE = os.environ.get(
    "REVIEW_STAGE_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "state",
                 "review_stages.json"))


def _quiet_seconds():
    try:
        return int(os.environ.get("REVIEW_STAGE_QUIET_SECONDS",
                                  spec.DEFAULT_QUIET_SECONDS))
    except Exception:  # noqa: BLE001
        return spec.DEFAULT_QUIET_SECONDS


def _load_state():
    try:
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_state(data):
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


class StageGate(object):
    """阶段链门控器：登记阶段活动 + 判定触发放行/驳回（确定性）。"""

    def __init__(self, state_file=None, quiet_seconds=None):
        self.state_file = state_file or _STATE_FILE
        self.quiet_seconds = (quiet_seconds if quiet_seconds is not None
                              else _quiet_seconds())

    # ---------- 状态存取（允许注入隔离文件：测试不污染工作区共享状态） ----------
    def _load(self):
        if self.state_file == _STATE_FILE:
            return _load_state()
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    if isinstance(d, dict):
                        return d
        except Exception:  # noqa: BLE001
            pass
        return {}

    def _save(self, data):
        if self.state_file == _STATE_FILE:
            _save_state(data)
            return
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 登记阶段活动（某阶段"正在跑"） ----------
    def mark_active(self, task_key, stage, note="", now=None):
        """登记某任务的某阶段为活跃（如「架构·开发 开工」/「架构·测试 接单」）。

        静默接管：同一阶段重复登记只**刷新心跳**，不产生第二个活跃阶段
        （重复触发 = 同一条链，不该涨进度）。
        """
        self._validate_stage(stage)
        now = now if now is not None else time.time()
        d = self._load()
        rec = d.get(task_key) or {"task_key": task_key, "active": None,
                                 "visited": [], "updated_at": now}
        repeated = (rec.get("active") or {}).get("stage") == stage
        rec["active"] = {"stage": stage, "actor": spec.STAGE_ACTOR[stage],
                         "note": note, "since": now,
                         "heartbeat": now, "repeats": (
                             (rec.get("active") or {}).get("repeats", 0) + 1
                             if repeated else 1)}
        if stage not in rec.get("visited", []):
            rec.setdefault("visited", []).append(stage)
        rec["updated_at"] = now
        d[task_key] = rec
        self._save(d)
        return {"ok": True, "task_key": task_key, "stage": stage,
                "actor": spec.STAGE_ACTOR[stage],
                "repeated": repeated, "repeats": rec["active"]["repeats"]}

    # ---------- 阶段收口（某阶段做完，"交回"给链条） ----------
    def mark_done(self, task_key, stage, now=None):
        """登记某阶段收口：仅当其正是当前活跃阶段才解除（防误清）。

        同时把该阶段记入 `visited`（供乱序判定"回头补上游"）。
        """
        self._validate_stage(stage)
        now = now if now is not None else time.time()
        d = self._load()
        rec = d.get(task_key) or {"task_key": task_key, "active": None,
                                 "visited": [], "updated_at": now}
        active = rec.get("active") or {}
        if active.get("stage") == stage:
            rec["active"] = None
            rec["updated_at"] = now
        if stage not in rec.get("visited", []):
            rec.setdefault("visited", []).append(stage)
        rec["last_done"] = {"stage": stage, "at": now}
        d[task_key] = rec
        self._save(d)
        return {"ok": True, "task_key": task_key, "stage": stage,
                "cleared": active.get("stage") == stage}

    # ---------- 当前活跃阶段（含静默超时接管） ----------
    def active_stage(self, task_key, now=None):
        """读当前活跃阶段；超过静默阈值视为已收口（防活动登记残留卡死整条链）。"""
        now = now if now is not None else time.time()
        rec = self._load().get(task_key) or {}
        active = rec.get("active") or {}
        stage = active.get("stage")
        if not stage:
            return None
        if now - float(active.get("heartbeat", active.get("since", now))) > \
                self.quiet_seconds:
            return None   # 静默接管：视为已收口
        return stage

    def chain_view(self, task_key, now=None):
        """单任务链视角（二级信息，供人/哨兵俯瞰）。"""
        rec = self._load().get(task_key) or {}
        active = rec.get("active") or {}
        return {
            "task_key": task_key,
            "active_stage": self.active_stage(task_key, now=now),
            "active_actor": active.get("actor", ""),
            "since": active.get("since"),
            "repeats": active.get("repeats", 0),
            "visited": list(rec.get("visited", [])),
            "updated_at": rec.get("updated_at"),
        }

    # ---------- 核心：触发前门控判定（确定性） ----------
    def should_trigger(self, task_key, stage, force=False, now=None):
        """判定某阶段此刻发起触发是否放行。

        返回 {allow, decision, reason, active_stage, upstream, upstream_done}
        - `force=True` 是**逃生门**：显式说明"我知道在抢跑/复用"，仍记录驳回原因但不拦。
        """
        self._validate_stage(stage)
        now = now if now is not None else time.time()
        rec = self._load().get(task_key) or {}
        visited = list(rec.get("visited", []))
        active = self.active_stage(task_key, now=now)
        upstream = spec.UPSTREAM.get(stage)
        up_idx = spec.STAGE_ORDER.index(stage) - 1
        # 上游是否已收口：**上游（或更上游）确已完成后**才为 True；
        # 仅"正在活跃推进"不算收口（活跃在上游 = 上游还在跑，本阶段发起即抢跑）。
        up_done = (upstream is not None and
                   upstream in visited and
                   active != upstream)

        def _verdict(decision):
            return {
                "allow": decision == "allow" or bool(force),
                "decision": decision,
                "reason": spec.DECISION_REASON[decision],
                "forced": bool(force) and decision != "allow",
                "task_key": task_key,
                "stage": stage,
                "active_stage": active,
                "upstream": upstream,
                "upstream_done": up_done,
                "actor": spec.STAGE_ACTOR[stage],
            }

        s_idx = spec.STAGE_ORDER.index(stage)
        a_idx = (spec.STAGE_ORDER.index(active)
                 if active in spec.STAGE_ORDER else -1)

        # ① 本阶段已在跑 → 重复触发（复用，不新起任务、不冲进度）
        if active == stage:
            return _verdict("blocked_active")

        # ② 乱序（链被并行拆成两条）：**本阶段是下游、但更下游的环节已在跑**
        #    —— 说明有人从下游那一头起头了（乱序），此时本阶段回头插进去就是并行链。
        if a_idx > s_idx:
            return _verdict("blocked_switched")

        # ③ 抢跑：上游未收口就发起本阶段（"开发还没完就跑去测试/评审"）。
        #    上游收口判据 = 该阶段已完成（visited）或此刻正活跃且**已是更上游**（仍在推进）。
        if upstream is not None and not up_done:
            if active is not None and a_idx < s_idx:
                # 更上游阶段正在推进中 → 明确抢跑
                return _verdict("blocked_upstream")
            if active is None:
                # 无任何活跃阶段、上游也没做完 → 抢跑（链条还没推进到本阶段）
                return _verdict("blocked_upstream")

        # ④ 顺序推进但重复触发同一阶段的**后续**环节：本阶段未在跑、上游已完成 → 放行
        return _verdict("allow")

    # ---------- 便捷：门控 + 登记（一次调用，供调度器/角色接线） ----------
    def admit(self, task_key, stage, note="", force=False, now=None):
        """触发前统一入口：判定；放行则登记活跃，驳回则**不改状态**。

        返回 should_trigger 的判决 + `admitted`（是否真登记）+ `reused`（复用进行中任务）。
        """
        v = self.should_trigger(task_key, stage, force=force, now=now)
        v["admitted"] = False
        v["reused"] = False
        if v["allow"] and not v.get("forced"):
            self.mark_active(task_key, stage, note=note, now=now)
            v["admitted"] = True
        elif v["decision"] == "blocked_active":
            v["reused"] = True     # 复用进行中的同一阶段任务，不新起
        return v

    # ---------- 俯瞰 ----------
    def overview(self):
        d = self._load()
        items = []
        counts = {k: 0 for k in spec.GATE_DECISIONS}
        for tk in d:
            cv = self.chain_view(tk)
            items.append(cv)
            if cv["active_stage"]:
                counts["allow"] += 0   # 活跃即曾放行（计数在 stats 里更准）
        return {"module": spec.MODULE, "module_version": spec.MODULE_VERSION,
                "quiet_seconds": self.quiet_seconds,
                "chains": items, "gates": counts}

    def reset(self):
        """清空状态（仅供测试隔离）。"""
        with _STATE_LOCK:
            self._save({})

    # ---------- 内部 ----------
    @staticmethod
    def _validate_stage(stage):
        if stage not in spec.STAGE_ORDER:
            raise ValueError("非法阶段 %r（唯一事实源 spec.STAGE_ORDER=%s）"
                             % (stage, list(spec.STAGE_ORDER)))


def record_gate(verdict, source="stage_gate"):
    """把一次门控判决留痕到 `archives(kind='stage_gate')`（可回溯，不静默）。

    与 `collab.disposition.record_disposition` 同构：每条判决一条存档，
    `gate_stats()` 从这些存档统计放行/驳回次数（唯一口径，不各自取名）。
    """
    import uuid
    archive_id = "sg-%s" % uuid.uuid4().hex[:12]
    content = {
        "gate_id": archive_id,
        "task_key": verdict.get("task_key", ""),
        "stage": verdict.get("stage", ""),
        "actor": verdict.get("actor", ""),
        "decision": verdict.get("decision", ""),
        "reason": verdict.get("reason", ""),
        "active_stage": verdict.get("active_stage"),
        "upstream": verdict.get("upstream"),
        "upstream_done": verdict.get("upstream_done"),
        "forced": verdict.get("forced", False),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        from data import admin
        admin.archive(archive_id, "stage_gate",
                      "[阶段门:%s] %s" % (content["decision"], content["stage"]),
                      content, source)
    except Exception:  # noqa: BLE001
        pass
    return content


def gate_stats():
    """全量门控统计（放行/三类驳回各多少次）——进度不失衡的可核验口径。

    统计来源是 `archives(kind='stage_gate')` 留痕（每次门控判定都留痕）。
    """
    counts = {k: 0 for k in spec.GATE_DECISIONS}
    try:
        from data import admin
        rows = admin.repo.list_archives(kind="stage_gate", limit=1000) or []
    except Exception:  # noqa: BLE001
        rows = []
    for r in rows:
        c = (r or {}).get("content") or {}
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except Exception:  # noqa: BLE001
                c = {}
        d = c.get("decision")
        if d in counts:
            counts[d] += 1
    return {
        "module": spec.MODULE, "module_version": spec.MODULE_VERSION,
        "gates": counts,
        "allowed": counts["allow"],
        "skipped_retriggers": (counts["blocked_active"]
                              + counts["blocked_upstream"]
                              + counts["blocked_switched"]),
        "note": "驳回即「本该串行却并行触发」被拦下；拦截数=避免的乱序/重复触发次数",
    }


__all__ = ["StageGate", "record_gate", "gate_stats"]
