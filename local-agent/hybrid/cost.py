# -*- coding: utf-8 -*-
"""
CostMonitor · 成本监测与报表（Issue #57 + Issue #65 T6 扩展）
=============================================================
量化「云端 CPU 本地化 + 测试智能优化」带来的成本收益：

v1.0（Issue #57）能力：
  - report()：本地化路由成本报表（总节省 / 剩余云端 / 回滚量）

v2.0（Issue #65 T6）扩展：
  - report_optimizer()：**三合一节省报表**（增量 + 缓存 + 并行）：
      * 增量节省：未受影响测试原本的云端 CPU 成本
      * 缓存节省：指纹未变化被跳过的测试成本
      * 并行节省：并行 vs 串行的墙钟时间节省（折算成本）
      * 合计节省：三合一净节省 + 命中率/并行加速比

口径（统一）：
  - cloud_cpu_est：某脚本原本在云端消耗的 CPU 核·分钟；
  - 本地化后该笔云端成本归零 → 节省 = 原 cloud_cpu_est；
  - 增量/缓存跳过意味着这些测试本次完全不执行 → 节省全部成本；
  - 并行节省用「墙钟时间差 × 单价」估算（并行越快 = 成本越低）。
"""
import time


class CostMonitor(object):
    """成本监测与报表。"""

    def __init__(self, unit_cost_per_core_min=1.0):
        # 每核·分钟的云端成本单价（默认 1 单位，供相对对比）
        self.unit_cost = unit_cost_per_core_min

    # ---------- v1.0 报表（本地化路由） ----------
    def report(self, decisions, run_result=None):
        """根据路由决策 + 本地执行结果，生成成本报表。

        decisions: router.route_many() 返回的 dict（含 decisions/local/cloud）。
        run_result: worker.run() 返回的 dict（可选，含失败数）。
        """
        d = decisions.get("decisions", {})
        total_cloud_cpu = 0.0     # 全部任务原云端 CPU 核·分钟
        localized_cpu = 0.0       # 被本地化的云端 CPU 核·分钟
        cloud_remain = 0.0        # 仍留云端的 CPU 核·分钟
        for name, dec in d.items():
            cce = dec.cloud_cpu_est
            total_cloud_cpu += cce
            if dec.target == "local":
                localized_cpu += cce
            else:
                cloud_remain += cce

        # 本地失败需回滚的云端成本（本地没跑通就得回云端重跑）
        rollback = 0.0
        if run_result:
            summary = run_result.get("summary", {})
            fail = summary.get("fail", 0)
            # 简化为：失败脚本占本地化成本的比例估算
            total_local = max(summary.get("total", 0), 1)
            rollback = round(localized_cpu * fail / total_local, 3)

        net_save = round(localized_cpu - rollback, 3)
        return {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_cloud_cpu": round(total_cloud_cpu, 3),
            "localized_cpu": round(localized_cpu, 3),
            "cloud_remain": round(cloud_remain, 3),
            "local_fail_rollback": rollback,
            "net_save": net_save,
            "net_save_unit_cost": round(net_save * self.unit_cost, 3),
            "localization_ratio": round(localized_cpu / total_cloud_cpu, 4) if total_cloud_cpu else 0,
        }

    # ---------- v2.0 三合一节省报表（T6 扩展） ----------
    def report_optimizer(self, plan, run_result=None, costs=None):
        """三合一节省报表：增量 + 缓存 + 并行。

        plan: policy.build_plan() 返回的 dict，含 run/skip/reason/mode。
        run_result: 执行结果（可选，含 summary）。
        costs: 可选，{test_script: cloud_cpu_est} 字典，为每个测试预估云端成本。
               未提供时默认每脚本 10 核·分钟。

        返回报表（含三合一节省明细）：
          - incremental_saved: 增量跳过节省（未受影响测试成本）
          - cache_saved: 缓存跳过节省（指纹未变化测试成本）
          - parallel_time_saved: 并行节省的墙钟时间（分钟）
          - parallel_cost_saved: 并行节省折算成本
          - total_saved: 三合一合计节省（核·分钟）
          - hit_rate / speedup: 命中率 / 并行加速比
        """
        if costs is None:
            # 默认成本估算：每测试脚本 10 核·分钟
            costs = {s: 10.0 for s in set(plan.get("run", [])) | set(plan.get("skip", []))}

        total = plan.get("run", []) + plan.get("skip", [])
        total_cpu = sum(costs.get(s, 10.0) for s in total)

        # 1. 增量节省：跳过原因含 "not affected" 的测试
        reason = plan.get("reason", {})
        inc_saved = sum(
            costs.get(s, 10.0)
            for s in plan.get("skip", [])
            if "not affected" in reason.get(s, "")
        )

        # 2. 缓存节省：跳过原因含 "cache hit" 或 "fingerprint" 的测试
        cache_saved = sum(
            costs.get(s, 10.0)
            for s in plan.get("skip", [])
            if "cache hit" in reason.get(s, "") or "fingerprint" in reason.get(s, "")
        )

        # 3. 并行节省：基于 run_result 的时间数据
        parallel_time_saved = 0.0
        if run_result:
            summary = run_result.get("summary", {})
            total_duration = summary.get("total_duration", 0)  # 秒
            total_run = max(summary.get("total", 0), 1)
            # 估算串行时间：每个脚本 2 分钟基准 + 实测平均
            est_serial_min = max(summary.get("total", 0) * 2.0,
                                 total_duration / 60)
            # 并行墙钟时间 = 总时长 / 并行度（估算，至少 1 分钟）
            est_parallel_min = max(total_duration / 60, 0.1)
            parallel_time_saved = round(est_serial_min - est_parallel_min, 3)
        else:
            # 无 run_result 时按跳过比例估算
            skip_ratio = len(plan.get("skip", [])) / max(len(total), 1)
            parallel_time_saved = round(skip_ratio * 10.0, 3)

        # 并行节省折算成本（节省的 CPU 核·分钟 = 节省的时间 × 并行度估算）
        parallel_cost_saved = round(parallel_time_saved * self.unit_cost, 3)

        # 合计
        total_saved = round(inc_saved + cache_saved + parallel_cost_saved, 3)

        # 命中率（跳过数 / 总数）
        hit_rate = round(len(plan.get("skip", [])) / max(len(total), 1), 4)

        # 并行加速比（串行时间 / 并行时间）
        speedup = round(est_serial_min / max(est_parallel_min, 0.1), 2) if run_result else 0.0

        return {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": plan.get("mode", "unknown"),
            # 三合一明细
            "incremental_saved": round(inc_saved, 3),
            "cache_saved": round(cache_saved, 3),
            "parallel_time_saved": parallel_time_saved,
            "parallel_cost_saved": parallel_cost_saved,
            "total_saved": total_saved,
            "total_saved_unit_cost": round(total_saved * self.unit_cost, 3),
            # 指标
            "total_scripts": len(total),
            "run_scripts": len(plan.get("run", [])),
            "skip_scripts": len(plan.get("skip", [])),
            "hit_rate": hit_rate,
            "speedup": speedup,
            # 明细
            "skip_reasons": reason,
        }

    # ---------- 单任务成本 ----------
    def estimate(self, name, cloud_cpu_est, target):
        """返回单任务成本条目（供报表聚合/CLI 展示）。"""
        return {
            "name": name,
            "cloud_cpu_est": cloud_cpu_est,
            "target": target,
            "saved": cloud_cpu_est if target == "local" else 0.0,
            "cost": cloud_cpu_est if target == "cloud" else 0.0,
        }


# 便捷单例
default_monitor = CostMonitor()


class CostReporter(CostMonitor):
    """成本报表扩展（测试智能优化层 T6）——三合一节省。

    在 CostMonitor（v1.0 CPU 本地化报表）基础上，扩展出
    「增量节省 + 缓存节省 + 并行节省」三合一的优化收益报表。
    """

    def report_optimizer(self, policy, exec_result=None, cache_saved_cpu=0.0,
                         baseline_serial_seconds=None, cpu_per_test=1.0):
        """输出测试智能优化层（T3-T5）的三合一节省报表。

        policy:              PolicyEngine.decide() 返回的策略 dict
        exec_result:         ParallelExecutor 执行结果（含 wall_seconds/summary）
        cache_saved_cpu:     缓存命中跳过的 CPU 核·分钟（外部估算，可选）
        baseline_serial_seconds: 全量串行基线耗时（秒）；缺省用 total_duration 估算
        cpu_per_test:        单测试 CPU 核·分钟（默认 1）

        返回 dict：
          {
            incremental: 增量节省（本次相比全量少跑了多少测试）
            cache:       缓存节省（缓存命中跳过的 CPU）
            parallel:    并行节省（墙钟从串行 sum 降到 wall）
            total:       三合一总览
          }
        """
        tests = policy.get("tests", [])
        cache_hits = policy.get("cache_hits", [])
        full_count = policy.get("full_count", 0)

        # 增量节省：本应全量跑 → 实际只跑受影响（含缓存剔除后的）
        if full_count and full_count >= len(tests):
            incr_saved = full_count - (len(tests) + len(cache_hits))
            incr_saved = max(incr_saved, 0)
        else:
            incr_saved = 0
        incr_saved_cpu = round(incr_saved * cpu_per_test, 3)

        # 缓存节省：命中跳过的测试 CPU 归零
        cache_saved = len(cache_hits)
        cache_saved_cpu = round(cache_saved * cpu_per_test, 3)

        # 并行节省：墙钟从串行 total_duration 降到 wall_seconds
        parallel_ratio = 1.0
        wall = exec_result.get("summary", {}).get("wall_seconds") if exec_result else None
        serial_dur = exec_result.get("summary", {}).get("total_duration") if exec_result else None
        if baseline_serial_seconds is not None and baseline_serial_seconds > 0 and wall:
            parallel_ratio = round(wall / baseline_serial_seconds, 4)
        elif serial_dur and wall and serial_dur > 0:
            parallel_ratio = round(wall / serial_dur, 4)

        total_saved_cpu = round(incr_saved_cpu + cache_saved_cpu, 3)
        return {
            "incremental": {
                "mode": policy.get("mode"),
                "full_count": full_count,
                "ran_count": len(tests),
                "skipped": incr_saved,
                "saved_cpu_core_min": incr_saved_cpu,
            },
            "cache": {
                "hit_count": cache_saved,
                "saved_cpu_core_min": cache_saved_cpu,
            },
            "parallel": {
                "parallelism": policy.get("parallel"),
                "serial_seconds": baseline_serial_seconds or serial_dur,
                "wall_seconds": wall,
                "speedup_ratio": parallel_ratio,
            },
            "total": {
                "saved_cpu_core_min": total_saved_cpu,
                "summary": "增量+缓存+并行 三合一节省",
            },
        }


# 便捷单例（扩展版）
default_cost_reporter = CostReporter()
