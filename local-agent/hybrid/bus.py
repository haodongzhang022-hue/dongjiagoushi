# -*- coding: utf-8 -*-
"""
BusRunner · 公交车式批量测试计划执行器（Issue #90 · 攒批防核时浪费）
=====================================================================
Issue #150 追加：同一变更指纹的**重复入列**不得造成重复构建——用 diff 指纹做
"攒批去重门"（同指纹测试已进过队列/已发过车 → 只引用，不再重复处）；
并允许 `--diff-fp` 显式带上调用方（评审段调度器）算好的指纹。

对应 Issue #90 收尾诉求："这些测试非常消耗核时……打包一批跑，应该不会那么慢。
和公交车一样，无论多少，有需要就每隔15分钟发车，没有就不跑。然后这一批以
计划形式跑完，不是拉起了跑1个关闭再唤醒构建很久再跑。"

问题根因
--------
云端 CI / 评审迭代每跑 1 个测试，都要【冷启动一次构建环境】（docker +
pip install + 环境初始化 = 固定 CPU 开销）。37 个测试若各自单独拉起、各唤醒
一次构建（甚至跨 Issue/PR 多次唤醒），固定开销 ×N 次 → 核时暴涨（37 个测试
约 696 核·分钟）。且"跑 1 个关闭再唤醒构建很久再跑"的串行乒乓，既慢又贵。

方案（公交车 · Bus 模型）
------------------------
把"测试运行请求"当乘客：本地/云端先把待跑测试投进一个队列（enqueue，0 成本）；
按固定**发车间隔**（默认 15 分钟 = 900s）定时"发车"：
  - 队列非空  → 发一班车：把队列里【全部】待跑测试作为【一个批次计划】，
                在【同一进程/同一构建环境】内整批跑完（一次冷启动摊到全批），
                跑完统一 sync 留痕 + cost 报表 + quota 记账，然后清空队列。
  - 队列为空  → 不发车（没有空闲空转的构建浪费）。

由此：无论多少个测试，只要攒到一起，一次构建全跑完；间隔内没需求就不起任何
构建。固定开销从 N 次收敛到 1 次/班，核时大幅下降、也避免反复唤醒构建。

本模块为纯逻辑 + 子进程执行，不依赖数据层；状态落到本地 JSON（与
quota/batch/station 同目录习惯）。

用法（CLI）：
  python3 -m hybrid.cli bus enqueue local-agent/tests/test_scale.sh ...
  python3 -m hybrid.cli bus status                 # 看队列/下一班车时间
  python3 -m hybrid.cli bus dispatch --real        # 立即整批发车（跑全部队列）
  python3 -m hybrid.cli bus tick --real            # 定时哨兵：到点且非空才发车
"""
import json
import os
import time

# 攒批队列文件（与 quota/batch/station 同目录）
QUEUE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bus_queue.json")

# 默认发车间隔：15 分钟（900s）——"有需要就每隔15分钟发车"
DEFAULT_INTERVAL_SECONDS = 900
# 单测试超时（秒）
DEFAULT_TIMEOUT = 600
# 默认并行度（整批并行跑，加速"这一批以计划形式跑完"）
DEFAULT_PARALLEL = 4
# 变更指纹历史保留上限（攒批去重门用，防无限增长）
DEFAULT_FP_HISTORY = 200


def _now_ts():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _now_epoch():
    return time.time()


class BusRunner(object):
    """公交车式批量测试计划执行器。"""

    def __init__(self, queue_file=QUEUE_FILE,
                 interval=DEFAULT_INTERVAL_SECONDS, timeout=DEFAULT_TIMEOUT,
                 parallel=DEFAULT_PARALLEL, dry_run=False):
        self.queue_file = queue_file
        self.interval = interval
        self.timeout = timeout
        self.parallel = parallel
        self.dry_run = dry_run

    # ---------- 队列存取 ----------
    def _load(self):
        try:
            if os.path.exists(self.queue_file):
                with open(self.queue_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    if isinstance(d, dict) and "tests" in d:
                        return d
        except Exception:  # noqa
            pass
        return {"tests": [], "last_dispatch": 0.0,
                "history": [], "interval": self.interval,
                "processed_fps": []}

    def _save(self, d):
        with open(self.queue_file, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

    # ---------- 入列（乘客上车 · 0 成本） ----------
    def enqueue(self, tests, source="manual", note="", diff_fp=None):
        """把一个或多个测试投进待跑队列（0 成本，绝不立即拉起构建）。

        tests:   单个脚本路径 or 脚本路径 list。
        diff_fp: 变更指纹（Issue #150 攒批去重门）——同一指纹**已发过车**的测试
                 再入列时不再重复处（避免同 diff 反复触发构建）；
                 仍在队列中的同指纹测试也不重复加。

        返回 {queued, batch_size, due_in, next_due, skipped_fp}。
        """
        if isinstance(tests, str):
            tests = [tests]
        d = self._load()
        processed = set(d.get("processed_fps", []) or [])
        # ---- 指纹去重门：同一变更指纹的测试已经跑过 → 不再重复入列（省一次构建）----
        if diff_fp and diff_fp in processed:
            return {"queued": 0, "batch_size": 0, "skipped_fp": diff_fp,
                    "reason": "该变更指纹已发过车（攒批去重门）→ 不重复构建",
                    "next_due_in": 0}

        tests = [t for t in tests if t and t not in self._queued_set()]
        if not tests:
            st = self.status()
            st["skipped_fp"] = None
            return st
        for t in tests:
            d["tests"].append({
                "test": t,
                "source": source,
                "note": note,
                "diff_fp": diff_fp,
                "ts": _now_ts(),
            })
        d["interval"] = self.interval
        d["pending_fp"] = diff_fp or d.get("pending_fp")
        self._save(d)
        st = self.status()
        st["skipped_fp"] = None
        return st

    def _queued_set(self):
        return {t["test"] for t in self._load().get("tests", [])}

    # ---------- 判定（该不该发车） ----------
    def should_dispatch(self, now=None):
        """公交车逻辑：队列非空 且 距上次发车间隔已到 → 发车；否则等下一班。"""
        d = self._load()
        now = now if now is not None else _now_epoch()
        queued = len(d.get("tests", []))
        if queued == 0:
            return {"dispatch": False, "reason": "empty_queue",
                    "queued": 0}
        last = float(d.get("last_dispatch", 0.0))
        elapsed = now - last
        due = elapsed >= self.interval
        if not due:
            return {"dispatch": False, "reason": "not_due",
                    "queued": queued,
                    "next_due_in": int(self.interval - elapsed),
                    "next_due_at": _now_ts()}
        return {"dispatch": True, "reason": "due_with_passengers",
                "queued": queued, "elapsed": int(elapsed)}

    # ---------- 状态（站台信息） ----------
    def status(self):
        d = self._load()
        tests = d.get("tests", [])
        now = _now_epoch()
        last = float(d.get("last_dispatch", 0.0))
        elapsed = now - last if last else now
        due_in = max(0, int(self.interval - elapsed)) if tests else 0
        queued_names = [t["test"] for t in tests]
        return {
            "queued": len(tests),
            "tests": queued_names,
            "interval_seconds": self.interval,
            "due_in_seconds": due_in,
            "due": (len(tests) > 0 and due_in == 0),
            "last_dispatch": _now_ts() if last else "",
            "last_dispatch_ts": last,
            "dispatch_count": len(d.get("history", [])),
            # Issue #150 攒批去重门：已处理的变更指纹数（同指纹不再触发构建）
            "processed_fps": len(d.get("processed_fps", []) or []),
            "pending_fp": d.get("pending_fp"),
        }

    # ---------- 发车（整批跑完 · 一次构建） ----------
    def dispatch(self, now=None, extra_tests=None, note="bus batch"):
        """发一班车：把队列里全部待跑测试作为一批计划，整批跑完。

        复用 ParallelExecutor（单进程内批量跑全部），一次环境/一次构建摊全批；
        跑完统一 sync 留痕 + cost 报表 + quota 记账，然后清空队列。
        返回批运行汇总（含 per-test 结果 + 计划耗时）。

        now: 传入便于测试注入时间。
        extra_tests: 可选，发车前临时追加（不落队列）。
        """
        d = self._load()
        tests = [t["test"] for t in d.get("tests", [])]
        if extra_tests:
            tests.extend(extra_tests if isinstance(extra_tests, list) else [extra_tests])
        # 去重保序
        seen = set(); tests = [t for t in tests if not (t in seen or seen.add(t))]

        if not tests:
            return {"dispatched": 0, "reason": "empty", "tests": []}

        # ---- 整批作为一批计划，在单个执行器里跑完（一次构建摊全批） ----
        plan = self._run_plan(tests)

        # ---- 统一收尾：sync 留痕 + cost 报表 + quota 记账 ----
        finish = self._finish(plan)

        # ---- 清空队列（本班乘客已送达），记录发车历史 ----
        now = now if now is not None else _now_epoch()
        history = d.setdefault("history", [])
        history.append({
            "ts": _now_ts(), "epoch": now,
            "tests": len(tests),
            "pass": plan["summary"]["pass"],
            "fail": plan["summary"]["fail"],
            "wall_seconds": plan["summary"].get("wall_seconds", plan["summary"].get("total_duration", 0)),
            "note": note,
        })
        d["tests"] = []
        d["last_dispatch"] = now
        d["interval"] = self.interval
        # ---- 攒批去重门（Issue #150）：记录本班车跑过的变更指纹，同指纹不再触发构建 ----
        fp = d.get("pending_fp")
        if fp:
            fps = list(d.get("processed_fps", []) or [])
            if fp not in fps:
                fps.append(fp)
            d["processed_fps"] = fps[-DEFAULT_FP_HISTORY:]
            d["pending_fp"] = None
        self._save(d)

        plan["dispatched"] = len(tests)
        plan["finish"] = finish
        plan["queued_cleared"] = True
        plan["history_count"] = len(history)
        return plan

    # ---------- 整批执行（一批计划） ----------
    def _run_plan(self, tests):
        from hybrid.parallel import ParallelExecutor
        ex = ParallelExecutor(timeout=self.timeout, dry_run=self.dry_run,
                              parallel=self.parallel)
        if self.dry_run:
            # 演练：不真跑，产出等效汇总（每项记 [dry-run]）
            results = [{"script": t, "exit_code": 0, "duration": 0.0,
                        "output": "[dry-run] bus would run: %s (in one batch)" % t}
                       for t in tests]
            summary = {"total": len(results), "pass": len(results),
                       "fail": 0, "total_duration": 0.0, "wall_seconds": 0.0,
                       "parallel": self.parallel,
                       # Issue #150：冷启动摊薄的确定性测算——N 个测试若各自单发
                       # 要 N 次冷启动；整批只需 1 次（省 N-1 次固定开销）
                       "cold_starts_naive": len(results),
                       "cold_starts_batched": 1 if results else 0,
                       "cold_start_saved": max(0, len(results) - 1)}
            return {"results": results, "summary": summary}
        return ex.run_parallel(tests, parallel=self.parallel)

    # ---------- 统一收尾（sync + cost + quota） ----------
    def _finish(self, plan):
        out = {"synced": False, "cost": None, "quota": None}
        # 1. 结果留痕（可回溯；失败不影响留痕）
        try:
            from hybrid.sync import ResultSync
            sync = ResultSync()
            s = sync.sync(plan, batch_name="bus")
            out["synced"] = bool(s.get("synced"))
        except Exception:  # noqa
            out["synced"] = False
        # 2. 成本报表（量化整批本地化/攒批节省）
        try:
            from hybrid.cost import CostMonitor
            from hybrid.router import HybridResourceRouter
            r = HybridResourceRouter()
            # 为队列里的每个测试估算原云端 CPU（无 registry 时用默认粗估）
            tasks = []
            for res in plan.get("results", []):
                name = res.get("script", "")
                cce = self._est_cloud_cpu(name)
                tasks.append((name, cce, cce))
            decisions = r.route_many(tasks)
            rep = CostMonitor().report(decisions, plan)
            out["cost"] = rep
        except Exception:  # noqa
            pass
        # 3. quota 记账（本地化节省抵扣云端账本）
        try:
            from hybrid.quota import QuotaGuard
            q = QuotaGuard()
            cost = out.get("cost") or {}
            save = float(cost.get("net_save", 0.0) or 0.0)
            if save > 0:
                q.credit_localized(save, note="bus 整批本地化(一次构建摊全批)")
            out["quota"] = q.quota_status()
        except Exception:  # noqa
            pass
        return out

    def _est_cloud_cpu(self, test):
        """为单个测试粗估原云端 CPU 核·分钟（确定性，供 cost 报表）。"""
        try:
            from hybrid.registry import get
            rec = get(test)
            cce = rec.get("cloud_cpu_est") if isinstance(rec, dict) else None
            if cce is not None:
                try:
                    return float(cce)
                except (TypeError, ValueError):
                    pass
        except Exception:  # noqa
            pass
        # 兜底：按确定性粗估（固定 20 核·分钟，保守）
        return 20.0

    # ---------- 定时哨兵发车（tick） ----------
    def tick(self, now=None, extra_tests=None, note="bus tick", diff_fp=None):
        """定时哨兵一次：到点且队列非空 → 发车；否则返回 '等下一班'。

        这是云端 cron / CI 定时器每 interval 调一次的统一入口：
        无需求（队列空）不发车（无空转构建）；有需求到点整批发车。
        """
        if diff_fp:
            d = self._load()
            if diff_fp in set(d.get("processed_fps", []) or []):
                return {"action": "skip", "reason": "该变更指纹已发过车（攒批去重门）",
                        "diff_fp": diff_fp}
            d["pending_fp"] = diff_fp
            self._save(d)
        verdict = self.should_dispatch(now)
        if not verdict["dispatch"]:
            return {"action": "wait", **verdict}
        return {"action": "dispatch", **self.dispatch(now=now,
                                                      extra_tests=extra_tests,
                                                      note=note)}


# 便捷单例
default_bus = BusRunner()
