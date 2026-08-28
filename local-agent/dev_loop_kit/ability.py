# -*- coding: utf-8 -*-
"""
DevLoopAbility · 开发闭环能力（Goose 四维闭环适配 · 通用复用能力）
====================================================================
把「开发自循环」从「单 Agent 自己写码 + 自己判断继续/结束」升级为
**确定性代码控制流程**（参考 Goose 的 Orchestrator），避免陷入死循环。

核心价值（对标 Goose）：
  - **执行-验证分离**：Coder 只负责做，不负责判；合格与否由客观验证器裁定；
  - **确定性状态机**：不让 LLM 决定「下一步做什么/是否结束」，只有验证 APPROVED 才放行；
  - **硬性熔断**：重做超 max_attempts 上报 Leader，总迭代超上限熔断，防资源耗尽；
  - **进度北极星监督**：接入 sentinel goal_meters，停滞/横跳/重复错误由哨兵拦截。

用法（任意角色实例上）：
    role = DeveloperRole()
    ability = DevLoopAbility(owner=role)
    engine = ability.create_loop(goal_total=10.0)      # 目标门控
    ability.run_loop(task_id, agent_id, goal_total,     # 确定性编排单轮
                     current, approved, evidence)
    ability.overview(engine)                            # 二级信息俯瞰
"""
import os
import sys

# 确保 local-agent 目录在 sys.path
_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class DevLoopAbility:
    """通用开发闭环能力：任何 agent 挂载即得 Goose 风格闭环控制。

    通过 `owner` 绑定所属 agent，留痕归因。
    """

    RULES = {
        "何时用": (
            "开发任务需要多轮自循环推进且任务目标明确(goal>0)时："
            "用确定性闭环控制，分离执行与验证，防单 Agent 无限循环。"
        ),
        "不越权": (
            "闭环控制是确定性 Orchestrator，不替代 Leader 决策；"
            "超过 max_attempts 后必须上报 Leader，禁止自行无限重试。"
        ),
        "防无效": (
            "验证必须用客观结果(测试/lint)，不用主观判断；"
            "进度推进走哨兵 goal_meters，停滞/横跳/重复错误由哨兵拦截。"
        ),
    }

    def __init__(self, owner=None):
        self.owner = owner
        self._owner_name = self._resolve_owner_name(owner)

    @staticmethod
    def _resolve_owner_name(owner):
        if owner is None:
            return ""
        if isinstance(owner, str):
            return owner
        return getattr(owner, "name", "") or getattr(owner, "__class__", object).__name__

    def _engine(self):
        import dev_loop
        return dev_loop

    def create_loop(self, goal_total=0.0, **kwargs):
        """创建一次开发闭环（Planner 门控：goal>0 才允许）。返回 DevLoopEngine。"""
        eng = self._engine().DevLoopEngine(goal_total=goal_total, **kwargs)
        # 归因到 owner
        eng.owner = self._owner_name
        return eng

    def run_loop(self, task_id, agent_id, goal_total, current,
                 approved, evidence="", max_attempts=3, target=""):
        """确定性编排一次「执行→验证→决策」单轮（Orchestrator 控制）。"""
        return self._engine().run_single_round(
            task_id, agent_id, goal_total, current, approved,
            evidence=evidence, max_attempts=max_attempts, target=target)

    def overview(self, engine):
        """二级信息：闭环运行俯瞰。"""
        return engine.overview()

    def capability(self):
        """能力声明（供监控/文档引用）。"""
        return {
            "name": "dev_loop",
            "owner": self._owner_name,
            "description": "Goose 四维闭环适配：执行-验证分离 + 确定性状态机 + 硬性熔断 + 进度北极星监督",
            "rules": self.RULES,
            "methods": ["create_loop", "run_loop", "overview"],
        }
