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
