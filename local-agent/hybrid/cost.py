# -*- coding: utf-8 -*-
"""
CostMonitor · 成本监测与报表
=============================
量化「云端 CPU 本地化」带来的成本收益：统计被判为 local 的脚本原本
占用的云端 CPU 核·分钟，与本地化后的实际执行情况对比，输出节省报表。

口径（统一）：
  - cloud_cpu_est：某脚本原本在云端消耗的 CPU 核·分钟；
  - 本地化后该笔云端成本归零 → 节省 = 原 cloud_cpu_est；
  - 报表给出 总节省 / 剩余云端成本 / 本地失败需回滚量 三个关键指标。
"""
import time


class CostMonitor(object):
    """成本监测与报表。"""

    def __init__(self, unit_cost_per_core_min=1.0):
        # 每核·分钟的云端成本单价（默认 1 单位，供相对对比）
        self.unit_cost = unit_cost_per_core_min

    # ---------- 报表 ----------
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
            # 防御：cloud_cpu_est 可能缺失/字符串/非 RouteDecision（旧数据/直接 dict）
            cce = getattr(dec, "cloud_cpu_est", 0.0)
            try:
                cce = float(cce)
            except (TypeError, ValueError):
                cce = 0.0
            target = getattr(dec, "target", None)
            if target is None and isinstance(dec, dict):
                target = dec.get("target")
            if target is None:
                target = "cloud"
            total_cloud_cpu += cce
            if target == "local":
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
