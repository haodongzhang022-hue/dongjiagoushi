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
                 cost=None, state="idle", select_error=""):
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
        # 选测失败显式留痕（不静默吞：空串=无错，非空=真实故障信息）
        self.select_error = select_error

    def to_dict(self):
        return {
            "task_key": self.task_key, "round": self.index,
            "diff_fp": self.diff_fp, "pack_fp": self.pack_fp,
            "dispatched": self.dispatched, "reused": self.reused,
            "tests": self.tests, "disposition": self.disposition,
            "cost": self.cost, "state": self.state,
            "select_error": self.select_error,
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
        # _HERE = <repo>/local-agent → 仓库根 = dirname(_HERE)（修复：原先多 dirname 一次解析到 "/"）
        self.root_dir = root_dir or os.path.dirname(_HERE)
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
    def _select_tests(self, diff_fp, changed_files=None):
        """按变更文件做增量选测；无增量信息 → 返回空（由评测段跳过构建）。

        changed_files: 显式传入变更文件清单（供测试/调用方注入，替代 git diff）。

        选测失败**不静默吞**（对齐 dev-standard C01「错误处理不吞异常」）：
        异常上抛，由调用方显式降级并留痕，避免"看起来没变更"掩盖真实故障。
        """
        changed = (list(changed_files) if changed_files is not None
                   else self._changed_files())
        if not changed:
            return []
        from hybrid.selector import IncrementalSelector
        # 注意：`default_selector` 是**实例**不是工厂函数，不可当函数调用；
        # 这里显式实例化，避免 TypeError 被吞后恒返回 []（评审段永不发车）。
        sel = IncrementalSelector(root_dir=self.root_dir)
        return list(sel.select(changed) or [])

    def _changed_files(self):
        """变更文件清单（确定性回退链，兼容本地开发与 CI/PR 两种场景）。

        - 本地开发：工作区未提交变更（`git diff` + `--cached`）；
        - CI/PR：工作区干净，回退到与**基线分支**的 diff（origin/main → main → HEAD~1）。
        无任何可用基线/变更 → 返回空（调用方可显式传 `changed_files` 注入）。
        """
        import subprocess
        candidates = (
            ["git", "diff", "--name-only"],
            ["git", "diff", "--cached", "--name-only"],
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            ["git", "diff", "--name-only", "main...HEAD"],
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
        )
        for cmd in candidates:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      cwd=self.root_dir, timeout=30)
            except Exception:  # noqa: BLE001
                continue
            if proc.returncode != 0:
                continue
            files = [x for x in proc.stdout.splitlines() if x.strip()]
            if files:
                return files
        return []

    # ---------- 主入口：跑一轮（或增量多轮）评审段 ----------
    def run(self, task_key, stable=None, volatile=None, prev_pack=None,
            max_rounds=1, round_volatiles=None, force=False, changed_files=None):
        """跑一轮（或多轮）评审段。

        参数：
          task_key:        任务标识（同一任务二次触发不漂移）
          stable:          稳定骨架（构建一次 → 冻结）
          volatile:        本轮变化片段
          prev_pack:       上一轮 review_context pack（用于复用冻结骨架）
          max_rounds:      连续跑几轮（模拟"评审→开发增量→再评审"的可控迭代）
          round_volatiles: 每轮的 volatile 列表（覆盖 volatile）
          force:           强制发车（忽略复用判定，供首次/验证用）
          changed_files:   显式变更文件清单（替代 git diff；供测试/调用方注入）

        返回 {task_key, rounds[], stats, context, bus, state}
        """
        cycles = _load_state()
        rec = cycles.get(task_key) or {"task_key": task_key, "rounds": [],
                                       "processed_fps": []}
        processed = set(rec.get("processed_fps", []))
        rounds = []
        pack = prev_pack
        volatiles = round_volatiles or [volatile or {}]
        bus_state = None   # 最后一班车的站台状态（供返回/俯瞰；无发车则 None）

        for i in range(min(max_rounds, len(volatiles))):
            vol = dict(volatiles[i] or {})
            # ① 增量上下文：只吃 (冻结骨架摘要 + 本轮变化)
            pack = ctx_engine.build(stable or {}, vol, prev=pack, task_key=task_key)
            # ② 触发门控：diff 指纹已处理过且非强制 → 不重复触发开发/构建
            diff_fp = ctx_engine.fingerprint(vol.get("diff_summary", ""))
            already = (diff_fp in processed) and not force
            select_error = ""
            if already:
                tests = []
            else:
                # 选测失败**不静默吞**（C01）：显式捕获并留痕到本轮，降级为"不拉构建"
                try:
                    tests = self._select_tests(diff_fp, changed_files=changed_files)
                except Exception as e:  # noqa: BLE001
                    tests = []
                    select_error = "%s: %s" % (type(e).__name__, e)

            # ③④ 攒批入列（0 成本）→ 本轮调度点整批发车（一次构建跑完一批）
            plan = None
            dispatched = False
            if tests and not already:
                bus = self._bus_runner()
                bus.enqueue(tests, source="review_cycle",
                            note="评审段 %s 第 %d 轮" % (task_key, i + 1))
                plan = bus.dispatch(note="review_cycle %s r%d" % (task_key, i + 1))
                dispatched = True
                bus_state = bus.status()

            # ⑤ 以测试为准：整批信号决定处置（无测试/复用时引用上轮信号）
            test_signals = self._test_signals(plan, vol, already)
            disp = self._dispose(test_signals, vol, reused=already)

            # ⑥ 回评审（增量上下文）：评审只吃 pack["context"]
            rnd = Round(task_key, i + 1, diff_fp, pack["stable_fp"],
                        dispatched=dispatched, reused=already, tests=tests,
                        disposition_label=disp, cost=self._cost(plan, pack),
                        state="reviewed", select_error=select_error)
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
