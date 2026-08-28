# -*- coding: utf-8 -*-
"""
Hybrid 资源路由 · 核心路由模块
===============================
判断每个任务该跑在本地（纯 CPU 逻辑）还是云端（LLM 强相关操作）。

设计原则：
  - 纯 CPU 逻辑（测试/脚本/管线/dashboard）→ 本地
  - LLM 强相关（embedding/对话/Wiki 生成）→ 云端
  - 未知任务默认走 AUTO（由规则引擎自动分类）

路由规则（RULES 表，可扩展）：
  cloud 关键字：knowledge, embedding, npc, llm, codewiki, wikigen
  local 关键字：test, script, pipeline, dashboard, python, bash, shell
  未命中任何关键字 → AUTO（由 caller 决定默认去向）
"""

RESOURCE_LOCAL = "local"
RESOURCE_CLOUD = "cloud"
RESOURCE_AUTO = "auto"

# 云端保留的 LLM 强相关操作关键字（精确匹配前缀）
CLOUD_KEYWORDS = (
    "knowledge:update",
    "knowledge:query",
    "npc:go",
    "codewiki",
    "llm:",
    "embedding",
)

# 本地化的纯 CPU 操作关键字（前缀匹配）
LOCAL_KEYWORDS = (
    "test",
    "bash ",
    "python",
    "python3",
    "pip ",
    "script",
    "dashboard",
    "pipeline",
    "sh ",
    "sh:",
    "route-ci",
)

# 全量测试脚本清单（.cnb.yml 中可本地化的命令）
LOCAL_TEST_SCRIPTS = [
    "tests/test_architect_system.sh",
    "tests/test_functional_links.sh",
    "tests/test_relay_workflow.sh",
    "tests/test_memory_store.sh",
    "local-agent/tests/test_local_agent.sh",
    "local-agent/tests/test_scale.sh",
    "local-agent/tests/test_prescale_entry.sh",
    "tests/test_handle_ability.sh",
    "local-agent/tests/test_engine.sh",
    "local-agent/tests/test_data_layer.sh",
    "local-agent/tests/test_collab.sh",
    "local-agent/tests/test_peer_collab.sh",
    "local-agent/tests/test_peer_closure.sh",
    "local-agent/tests/test_disposition.sh",
    "local-agent/tests/test_sentinel.sh",
    "local-agent/tests/test_external_source.sh",
    "local-agent/tests/test_dispatcher.sh",
    "local-agent/tests/test_probe.sh",
    "local-agent/tests/test_dispatch_engine.sh",
    "local-agent/tests/test_depth_engine.sh",
    "local-agent/tests/test_ops_sim.sh",
    "local-agent/tests/test_topology_comparison.sh",
    "local-agent/tests/test_benchmark_ab.sh",
    "local-agent/tests/test_topology_hybrid.sh",
    "local-agent/tests/test_galton.sh",
    "local-agent/tests/test_topology_fusion.sh",
    "local-agent/tests/test_topology_slim.sh",
    "local-agent/tests/test_secretary_sense.sh",
    "local-agent/tests/test_prefix_cache.sh",
    "local-agent/tests/test_router_integration.sh",
    "local-agent/tests/test_cache_layer.sh",
    "tests/test_company_model.sh",
    "tests/test_mini_e2e.sh",
    "local-agent/tests/test_label_automation.sh",
    "local-agent/tests/test_review_tester_handoff.sh",
    "local-agent/tests/test_deliverer.sh",
    "tests/test_doc_consistency.sh",
]

# 云端必须保留的 LLM 强相关操作
CLOUD_ONLY_OPERATIONS = [
    "knowledge:update",
    "npc:go",
    "codewiki",
    "knowledge:query",
]


class HybridResourceRouter:
    """本地/云端资源路由决策器。"""

    def __init__(self, cloud_keywords=None, local_keywords=None):
        """初始化路由规则。可传入自定义关键字集合覆盖默认。"""
        self.cloud_keywords = tuple(cloud_keywords or CLOUD_KEYWORDS)
        self.local_keywords = tuple(local_keywords or LOCAL_KEYWORDS)

    def route(self, task_name):
        """路由决策：输入任务名/命令，返回 'local' / 'cloud' / 'auto'。"""
        if not task_name or not isinstance(task_name, str):
            return RESOURCE_AUTO
        name = task_name.strip().lower()

        # 精确匹配测试脚本
        for script in LOCAL_TEST_SCRIPTS:
            if script in name:
                return RESOURCE_LOCAL

        # 云端 LLM 强相关优先
        for kw in self.cloud_keywords:
            if name.startswith(kw.lower()) or kw.lower() in name:
                return RESOURCE_CLOUD

        # 本地纯 CPU
        for kw in self.local_keywords:
            if name.startswith(kw.lower()) or kw.lower() in name:
                return RESOURCE_LOCAL

        return RESOURCE_AUTO

    def route_ci(self, ci_commands):
        """批量路由 CI 命令列表，返回 {local:[], cloud:[], auto:[]} 分桶。"""
        result = {"local": [], "cloud": [], "auto": []}
        for cmd in ci_commands:
            target = self.route(cmd)
            result[target].append(cmd)
        return result

    def analyze_ci_file(self, yml_content):
        """分析 .cnb.yml 内容，统计本地化/云端保留命令分布。"""
        import re
        local_count = 0
        cloud_count = 0
        auto_count = 0
        total = 0

        # 提取 script 块中的命令行
        for line in yml_content.splitlines():
            line = line.strip()
            if line.startswith("bash ") or line.startswith("python") or \
               line.startswith("pip ") or line.startswith("sh ") or \
               line.startswith("test"):
                total += 1
                target = self.route(line)
                if target == RESOURCE_LOCAL:
                    local_count += 1
                elif target == RESOURCE_CLOUD:
                    cloud_count += 1
                else:
                    auto_count += 1

        return {
            "total": total,
            "local": local_count,
            "cloud": cloud_count,
            "auto": auto_count,
            "localization_ratio": round(local_count / total * 100, 1) if total else 0,
        }


def classify_task(task_name):
    """便捷函数：直接调用 HybridResourceRouter 进行单任务分类。"""
    return HybridResourceRouter().route(task_name)
