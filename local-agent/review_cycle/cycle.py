# -*- coding: utf-8 -*-
"""评审段调度器 · 确定性引擎（cycle）—— 见 __init__ 文档。"""
import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from review_cycle import spec
from review_context import engine as ctx_engine

# 可选依赖（缺失即降级，不崩）：评审角色 / 回写桥 / 哨兵
try:
    from collab import disposition
except Exception:  # noqa: BLE001
    disposition = None


# ---------------------------------------------------------------------------
# 一、评审段状态持久化（本地 JSON；跨项目可抽取，不依赖数据层）
# ---------------------------------------------------------------------------
_STATE_LOCK = threading.Lock()
_STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "state", "review_cycles.json")


def _load_state():
    import json
    try:
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_state(data):
    import json
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 二、轮次（round）—— 同一评审段的多轮迭代，靠指纹判定"是否真需要跑"
# ---------------------------------------------------------------------------
class Round(object):
    """一轮评审轮次（幂等：同 task_key + 同内容指纹永不重复触发开发/构建）。"""

    def __init__(self, task_key, index, diff_fp, pack_fp,
                 dispatched=False, reused=False, tests=None, disposition_label="",
                 cost=None, state="idle"):
        self.task_key = task_key
        self.index = index
        self.diff_fp = diff_fp
        self.pack_fp = pack_fp
        self.dispatched = dispatched      # 本轮是否真的发了构建（False=复用，省 CPU）
        self.reused = reused              # 是否命中复用（免重复开发/构建）
        self.tests = list(tests or [])
        self.disposition = disposition_label
        self.cost = cost or {}
        self.state = state

    def to_dict(self):
        return {
            "task_key": self.task_key, "round": self.index,
            "diff_fp": self.diff_fp, "pack_fp": self.pack_fp,
            "dispatched": self.dispatched, "reused": self.reused,
            "tests": self.tests, "disposition": self.disposition,
            "cost": self.cost, "state": self.state,
        }


# ---------------------------------------------------------------------------
# 三、调度器
# ---------------------------------------------------------------------------
class Scheduler(object):
    """评审段调度器：增量收集 → 攒批触发 → 增量上下文回评审。

    dry_run=True（默认）：不真跑 CPU 密集测试，只产出等效计划与成本账
                          （供本地/CI 确定性单测；真实执行由宿主显式打开）。
    """

    def __init__(self, dry_run=True, root_dir=None, interval=None, bus=None):
        self.dry_run = dry_run
        self.root_dir = root_dir or os.path.dirname(os.path.dirname(_HERE))
        self.interval = interval or spec.DEFAULT_INTERVAL_SECONDS
        self._bus = bus

    # ---------- 攒批通道：入列 0 成本，到点/显式 flush 才发车 ----------
    def _bus_runner(self):
        if self._bus is not None:
            return self._bus
        from hybrid.bus import BusRunner
        self._bus = BusRunner(dry_run=self.dry_run, timeout=300)
        return self._bus

    # ---------- 变更感知选测（同 diff 指纹不重复选、不重复跑） ----------
    def _select_tests(self, diff_fp):
        """按变更文件做增量选测；无增量信息 → 返回空（由评测段跳过构建）。"""
        changed = self._changed_files()
        if not changed:
            return []
        try:
            from hybrid.selector import IncrementalSelector, default_selector
            sel = default_selector(root_dir=self.root_dir) \
                if hasattr(default_selector, "root_dir") \
                else IncrementalSelector(root_dir=self.root_dir)
            return list(sel.select(changed) or [])
        except Exception:  # noqa: BLE001
            return []

    def _changed_files(self):
        import subprocess
        try:
            proc = subprocess.run(["git", "diff", "--name-only"],
                                  capture_output=True, text=True,
                                  cwd=self.root_dir, timeout=30)
            if proc.returncode == 0:
                return [x for x in proc.stdout.splitlines() if x.strip()]
        except Exception:  # noqa: BLE001
            pass
        return []

    # ---------- 主入口：跑一轮（或增量多轮）评审段 ----------
    def run(self, task_key, stable=None, volatile=None, prev_pack=None,
            max_rounds=1, round_volatiles=None, force=False):
        """跑一轮（或多轮）评审段。

        参数：
          task_key:        任务标识（同一任务二次触发不漂移）
          stable:          稳定骨架（构建一次 → 冻结）
          volatile:        本轮变化片段
          prev_pack:       上一轮 review_context pack（用于复用冻结骨架）
          max_rounds:      连续跑几轮（模拟"评审→开发增量→再评审"的可控迭代）
          round_volatiles: 每轮的 volatile 列表（覆盖 volatile）
          force:           强制发车（忽略复用判定，供首次/验证用）

        返回 {task_key, rounds[], stats, context, bus, state}
        """
        cycles = _load_state()
        rec = cycles.get(task_key) or {"task_key": task_key, "rounds": [],
                                       "processed_fps": []}
        processed = set(rec.get("processed_fps", []))
        rounds = []
        pack = prev_pack
        volatiles = round_volatiles or [volatile or {}]

        for i in range(min(max_rounds, len(volatiles))):
            vol = dict(volatiles[i] or {})
            # ① 增量上下文：只吃 (冻结骨架摘要 + 本轮变化)
            pack = ctx_engine.build(stable or {}, vol, prev=pack, task_key=task_key)
            # ② 触发门控：diff 指纹已处理过且非强制 → 不重复触发开发/构建
            diff_fp = ctx_engine.fingerprint(vol.get("diff_summary", ""))
            already = (diff_fp in processed) and not force
            tests = [] if already else self._select_tests(diff_fp)

            # ③ 攒批：把本轮要跑的测试**入列**（0 成本），不发车
            bus_state = None
            if tests and not already:
                bus = self._bus_runner()
                bus.enqueue(tests, source="review_cycle",
                            note="评审段 %s 第 %d 轮" % (task_key, i + 1))

            # ④ 发车判定：入列后即在本轮调度点整批发车（一次构建跑完一批）
            plan = None
            dispatched = False
            if tests and not already:
                bus = self._bus_runner()
                plan = bus.dispatch(note="review_cycle %s r%d" % (task_key, i + 1))
                dispatched = True

            # ⑤ 以测试为准：整批信号决定处置（无测试/复用时引用上轮信号）
            test_signals = self._test_signals(plan, vol, already)
            disp = self._dispose(test_signals, vol, reused=already)

            # ⑥ 回评审（增量上下文）：评审只吃 pack["context"]
            rnd = Round(task_key, i + 1, diff_fp, pack["stable_fp"],
                        dispatched=dispatched, reused=already, tests=tests,
                        disposition_label=disp, cost=self._cost(plan, pack),
                        state="reviewed")
            rounds.append(rnd)
            processed.add(diff_fp)
            rec["rounds"].append(rnd.to_dict())

        rec["processed_fps"] = sorted(processed)
        rec["state"] = "done" if rounds else "idle"
        rec["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with _STATE_LOCK:
            cycles[task_key] = rec
            full = _load_state()
            full[task_key] = rec
            _save_state(full)

        return {
            "task_key": task_key,
            "rounds": [r.to_dict() for r in rounds],
            "context": pack.get("context") if pack else "",
            "bus": bus_state,
            "state": rec["state"],
            "stats": self.stats(),
        }

    # ---------- 内部：测试信号（以测试为准，不靠看法） ----------
    def _test_signals(self, plan, vol, reused):
        if reused:
            return {"light": "♻️", "note": "同变更指纹已处理 → 复用上轮测试信号，本轮零构建"}
        if plan is None:
            return {"light": "🟡", "note": "无受影响测试（变更未命中/无增量）→ 不拉构建"}
        s = plan.get("summary", {})
        fail = s.get("fail", 0)
        return {"light": "🟢" if not fail else "🔴",
                "total": s.get("total"), "fail": fail,
                "pass": s.get("pass"),
                "note": "整批一次构建跑完：%s 项，fail=%s" % (s.get("total"), fail)}

    # ---------- 内部：处置（复用统一审查处置标签，不各自取名） ----------
    def _dispose(self, signals, vol, reused):
        if disposition is None:
            return "proceed"
        if signals.get("light") == "🔴":
            return disposition.dispose(problem="", signals=["defect"],
                                       severity="🔴").get("disposition", "fix_bug")
        return disposition.dispose(problem="", severity="🟢").get("disposition",
                                                                 "merge")

    # ---------- 内部：成本（省下的 CPU + 省下的复述 token） ----------
    def _cost(self, plan, pack):
        cost = {
            "dispatched": plan is not None,
            "batches": 1 if plan is not None else 0,
            "tests": len(plan.get("summary", {}).get("total", [])) if plan
            and isinstance(plan.get("summary", {}).get("total"), list)
            else plan.get("summary", {}).get("total") if plan else 0,
            "context_saved_chars": pack.get("saved_chars", 0),
            "context_saved_tokens": ctx_engine.estimate_saved_tokens(pack),
        }
        if plan is not None:
            fin = plan.get("finish", {}) or {}
            cost["net_save"] = (fin.get("cost") or {}).get("net_save", 0)
        return cost

    # ---------- 俯瞰：省下的成本报表 ----------
    def stats(self):
        """全局统计：几轮真发了构建 / 几轮复用 / 省下多少（供人类俯瞰）。"""
        cycles = _load_state()
        total_rounds = dispatched = reused = 0
        saved_tokens = 0
        batches = 0
        for rec in cycles.values():
            for r in rec.get("rounds", []):
                total_rounds += 1
                if r.get("dispatched"):
                    dispatched += 1
                    batches += r.get("cost", {}).get("batches", 0)
                if r.get("reused"):
                    reused += 1
                saved_tokens += r.get("cost", {}).get("context_saved_tokens", 0)
        avoided = reused  # 被复用拦下的构建次数 = 省下的构建
        return {
            "module": spec.MODULE,
            "module_version": spec.MODULE_VERSION,
            "tasks": len(cycles),
            "rounds": total_rounds,
            "dispatched_builds": dispatched,
            "batched_runs": batches,
            "reused_rounds": reused,
            "avoided_builds": avoided,
            "context_saved_tokens": saved_tokens,
            "note": "攒批把 N 次构建收敛为每轮 1 批；复用把同指纹轮次构建收敛为 0",
        }

    def overview(self):
        """全局俯瞰：每个任务的评审段轮次表 + 成本报表。"""
        cycles = _load_state()
        return {
            "module": spec.MODULE,
            "stats": self.stats(),
            "cycles": {
                k: {"state": v.get("state"),
                    "rounds": len(v.get("rounds", [])),
                    "dispatched": sum(1 for r in v.get("rounds", [])
                                      if r.get("dispatched")),
                    "reused": sum(1 for r in v.get("rounds", [])
                                  if r.get("reused")),
                    "updated_at": v.get("updated_at")}
                for k, v in cycles.items()
            },
        }

    def reset(self):
        """清空调度状态（仅供测试隔离）。"""
        with _STATE_LOCK:
            _save_state({})


default_scheduler = Scheduler()
