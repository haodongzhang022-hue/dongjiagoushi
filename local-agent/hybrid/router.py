# -*- coding: utf-8 -*-
"""
HybridResourceRouter · 混合资源路由核心
========================================
解决「云原生构建-CPU 消耗过高」问题（Issue #57）：

云端 CI 的 37 个 CPU 密集测试脚本导致云原生构建-CPU 计费飙升。这些脚本
是**纯 CPU 逻辑**（跑测试断言、比对结果），与 LLM 强相关操作（知识库入库、
CodeWiki、AI 推理）无关。本路由器把这些纯 CPU 脚本**路由到本地执行**，
云端只保留 LLM 强相关操作，从而显著降低云端 CPU 消耗。

路由判定三要素：
  1. **成本收益（成本优先）**：纯 CPU 逻辑本地跑 0 云端 CPU 成本 → 优先本地；
  2. **LLM 强相关（能力保留）**：涉及模型推理/向量化/知识库/AI 生成的保留云端；
  3. **默认/兜底（fail-safe）**：无法判定或需要 LLM 关联的默认保留云端，不误伤。

本模块是**纯逻辑模块**，无外部依赖，可被 worker/sync/cli/tests 稳定复用。
"""

# 本地执行的标记（判定纯 CPU 逻辑）
LOCAL_HINTS = [
    # 明确标"本地执行"的脚本
    "local",
    "cpu",
    "unit",
    "test",
    "assert",
    "benchmark",
    "compare",
    "probe",
]

# LLM 强相关 / 必须留在云端的标记（尽量具体，避免误伤纯 CPU 测试）
CLOUD_HINTS = [
    "llm",
    "ai_model",
    "model_infer",
    "knowledge_update",
    "knowledge:update",
    "embedding",
    "vector",
    "rag",
    "codewiki",
    "npc_task",
    "chat",
    "infer_",
    "generate-dashboard",
]


class RouteDecision(object):
    """一次路由判定的结果（可序列化，供同步留痕）。"""

    def __init__(self, name, target, reason, local_time_est=0.0, cloud_cpu_est=0.0):
        self.name = name            # 任务/脚本名
        self.target = target        # "local" 或 "cloud"
        self.reason = reason        # 判定理由
        self.local_time_est = local_time_est   # 本地预计耗时（分钟）
        self.cloud_cpu_est = cloud_cpu_est     # 云端预计 CPU 消耗（核·分钟）

    def to_dict(self):
        return {
            "name": self.name,
            "target": self.target,
            "reason": self.reason,
            "local_time_est": self.local_time_est,
            "cloud_cpu_est": self.cloud_cpu_est,
        }

    def __repr__(self):
        return "<RouteDecision %s → %s (%s)>" % (self.name, self.target, self.reason)


class HybridResourceRouter(object):
    """核心路由：判定某任务/脚本应跑在本地还是云端。"""

    def __init__(self, cloud_default=True, cost_threshold=1.0):
        # cloud_default=True：默认保留云端（fail-safe，不误伤 LLM 强相关）
        self.cloud_default = cloud_default
        # 仅当可节约云端 CPU 成本 >= threshold（核·分钟）才值得本地化
        self.cost_threshold = cost_threshold

    # ---------- 单任务判定 ----------
    def route(self, name, local_time_est=0.0, cloud_cpu_est=0.0):
        """判定单个任务/脚本的落地（local/cloud）。

        优先级（从高到低）：
          1. LLM 强相关命中 → 云端（能力保留，不可本地化）；
          2. 纯 CPU 命中且成本收益达标 → 本地；
          3. 兜底 → 按 cloud_default。
        """
        low = name.lower()

        # ① LLM 强相关 → 必须留云端
        if any(h in low for h in CLOUD_HINTS):
            return RouteDecision(name, "cloud",
                                 "LLM 强相关，保留云端", local_time_est, cloud_cpu_est)

        # ② 纯 CPU 命中 → 可本地（需成本收益达标）
        if any(h in low for h in LOCAL_HINTS):
            if cloud_cpu_est >= self.cost_threshold:
                return RouteDecision(name, "local",
                                     "纯 CPU 逻辑且云端成本收益达标，本地执行",
                                     local_time_est, cloud_cpu_est)
            # 成本收益不达标：本地节省太少，不值得为之一路改造
            return RouteDecision(name, "cloud",
                                 "纯 CPU 但云端成本收益不达标，暂留云端",
                                 local_time_est, cloud_cpu_est)

        # ③ 兜底
        t = "cloud" if self.cloud_default else "local"
        return RouteDecision(name, t,
                             "默认兜底（%s）" % t, local_time_est, cloud_cpu_est)

    # ---------- 批量路由 ----------
    def route_many(self, tasks):
        """批量判定一组任务。tasks 为 list[(name, local_time_est, cloud_cpu_est)]。

        返回 { name: RouteDecision }，且附带聚合统计。
        """
        decisions = {}
        local_names, cloud_names = [], []
        for item in tasks:
            name = item[0]
            lte = item[1] if len(item) > 1 else 0.0
            cce = item[2] if len(item) > 2 else 0.0
            d = self.route(name, lte, cce)
            decisions[name] = d
            if d.target == "local":
                local_names.append(name)
            else:
                cloud_names.append(name)
        return {
            "decisions": decisions,
            "local": local_names,
            "cloud": cloud_names,
            "summary": {
                "total": len(tasks),
                "local": len(local_names),
                "cloud": len(cloud_names),
            },
        }

    # ---------- 简化判定（供 CLI/脚本快捷使用） ----------
    def classify(self, name):
        """返回 'local' / 'cloud' 字符串（快捷路径）。

        快捷路径下不校验成本阈值——凡纯 CPU 命中即判 local（这些正是
        需要批量本地化的 CPU 密集脚本）；LLM 强相关仍判 cloud。
        """
        low = name.lower()
        if any(h in low for h in CLOUD_HINTS):
            return "cloud"
        if any(h in low for h in LOCAL_HINTS):
            return "local"
        return "cloud" if self.cloud_default else "local"


# 便捷单例
default_router = HybridResourceRouter()
