# -*- coding: utf-8 -*-
"""
成本监测（CostMonitor）
========================
量化本地化改造节省的云端构建-CPU 消耗。

估算模型：
  云端构建-CPU 单价按构建时长计费。通过对比「改造前云端全量执行」与
  「改造后云端仅 LLM 强相关」的构建时长差异，估算节省量。

参考单价：
  - 默认按 0.5 元/分钟 估算（可配置）
  - 37 个测试脚本全量在云端跑约 15-30 分钟
  - 改造后云端仅 1-3 分钟（knowledge:update + npc:go + codewiki）
"""

import json
import time
from pathlib import Path

# 默认估算参数
DEFAULT_CLOUD_MINUTES = 20   # 改造前云端全量构建约 20 分钟
DEFAULT_LOCAL_MINUTES = 2    # 改造后云端仅 2 分钟
DEFAULT_COST_PER_MINUTE = 0.5  # 元/分钟

# 典型命令类型与估算时长（分钟）
CMD_DURATION_ESTIMATES = {
    "tests/test_architect_system.sh": 1.0,
    "tests/test_functional_links.sh": 0.8,
    "tests/test_relay_workflow.sh": 0.8,
    "tests/test_memory_store.sh": 1.2,
    "local-agent/tests/test_local_agent.sh": 0.6,
    "local-agent/tests/test_scale.sh": 0.5,
    "local-agent/tests/test_prescale_entry.sh": 0.4,
    "tests/test_handle_ability.sh": 0.5,
    "local-agent/tests/test_engine.sh": 0.5,
    "local-agent/tests/test_data_layer.sh": 0.8,
    "local-agent/tests/test_collab.sh": 0.7,
    "local-agent/tests/test_peer_collab.sh": 0.8,
    "local-agent/tests/test_peer_closure.sh": 0.6,
    "local-agent/tests/test_disposition.sh": 0.4,
    "local-agent/tests/test_sentinel.sh": 0.5,
    "local-agent/tests/test_external_source.sh": 0.6,
    "local-agent/tests/test_dispatcher.sh": 0.7,
    "local-agent/tests/test_probe.sh": 0.4,
    "local-agent/tests/test_dispatch_engine.sh": 0.5,
    "local-agent/tests/test_depth_engine.sh": 0.5,
    "local-agent/tests/test_ops_sim.sh": 0.6,
    "local-agent/tests/test_topology_comparison.sh": 0.7,
    "local-agent/tests/test_benchmark_ab.sh": 0.9,
    "local-agent/tests/test_topology_hybrid.sh": 0.6,
    "local-agent/tests/test_galton.sh": 0.3,
    "local-agent/tests/test_topology_fusion.sh": 0.5,
    "local-agent/tests/test_topology_slim.sh": 0.4,
    "local-agent/tests/test_secretary_sense.sh": 0.5,
    "local-agent/tests/test_prefix_cache.sh": 0.4,
    "local-agent/tests/test_router_integration.sh": 0.5,
    "local-agent/tests/test_cache_layer.sh": 0.6,
    "tests/test_company_model.sh": 0.4,
    "tests/test_mini_e2e.sh": 0.3,
    "local-agent/tests/test_label_automation.sh": 0.6,
    "local-agent/tests/test_review_tester_handoff.sh": 0.5,
    "local-agent/tests/test_deliverer.sh": 0.4,
    "tests/test_doc_consistency.sh": 0.5,
}

DEFAULT_ESTIMATE = 0.5  # 默认每条命令约 0.5 分钟


class CostMonitor:
    """成本监测与节省量化。"""

    def __init__(self, cost_per_minute=DEFAULT_COST_PER_MINUTE):
        self.cost_per_minute = cost_per_minute

    def estimate_savings(self, cloud_minutes=None, local_minutes=None):
        """估算改造前后成本差异。

        Args:
            cloud_minutes: 改造前云端构建分钟数（默认 20）
            local_minutes: 改造后云端构建分钟数（默认 2）

        Returns:
            dict: 包含节省分钟/金额/百分比
        """
        cloud_minutes = cloud_minutes or DEFAULT_CLOUD_MINUTES
        local_minutes = local_minutes or DEFAULT_LOCAL_MINUTES

        before_cost = cloud_minutes * self.cost_per_minute
        after_cost = local_minutes * self.cost_per_minute
        saved_minutes = cloud_minutes - local_minutes
        saved_cost = before_cost - after_cost
        pct = round(saved_minutes / cloud_minutes * 100, 1) if cloud_minutes else 0

        return {
            "cloud_minutes_before": cloud_minutes,
            "cloud_minutes_after": local_minutes,
            "saved_minutes": saved_minutes,
            "cost_per_minute": self.cost_per_minute,
            "cost_before": round(before_cost, 2),
            "cost_after": round(after_cost, 2),
            "saved_cost": round(saved_cost, 2),
            "saved_pct": pct,
        }

    def estimate_by_scripts(self, scripts):
        """按脚本清单估算总时长。

        Args:
            scripts: 脚本路径列表

        Returns:
            float: 估算总时长（分钟）
        """
        total = 0.0
        for script in scripts:
            total += CMD_DURATION_ESTIMATES.get(script, DEFAULT_ESTIMATE)
        return round(total, 1)

    def full_report(self):
        """生成完整成本报告。

        Returns:
            dict: 完整报告（含按脚本估算 + 改造前后对比）
        """
        from .router import LOCAL_TEST_SCRIPTS

        estimated_minutes = self.estimate_by_scripts(LOCAL_TEST_SCRIPTS)
        savings = self.estimate_savings(
            cloud_minutes=estimated_minutes + 3,  # 云端改造前 = 所有测试 + 3 个 LLM 操作
            local_minutes=3,  # 改造后云端仅 3 个 LLM 操作
        )

        return {
            "estimated_local_minutes": estimated_minutes,
            "script_count": len(LOCAL_TEST_SCRIPTS),
            "savings": savings,
            "report_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }


def estimate_savings(cloud_minutes=None, local_minutes=None):
    """便捷函数：创建 CostMonitor 并估算节省量。"""
    return CostMonitor().estimate_savings(
        cloud_minutes=cloud_minutes, local_minutes=local_minutes
    )
