# -*- coding: utf-8 -*-
"""
通用派发能力（DispatchAbility · 全员能力）
============================================
把「派发工作」封装为**可复用的通用能力模块**，供任何 agent 挂载使用。

本能力解决用户拍板的核心诉求：派发工作是高频复用的模块能力，不应只属于经理——
应统一开发后给每个 agent 对接，让全员既会「派发」也会「接单」，从而构成真正
可协作的体系（而非散兵）。

能力维度（双角色合一）：
  ╔═ 作为派发方 ════════════════════════════════════════════════╗
  ║ dispatch(...)         四层分发一站式（L1→L2→L3→L4）          ║
  ║ declare_assignments    L1 声明（登记 gid）                     ║
  ║ assign                 L2 分发（拆分+分配+投池）                ║
  ║ trigger                L3 触发（投递接力卡 [触发:角色]）        ║
  ║ start                  L4 开工（接单后继续工作）                ║
  ╚══════════════════════════════════════════════════════════════╝
  ╔═ 作为被派发方 ════════════════════════════════════════════════╗
  ║ accept([接单])         接单回执 → 标记 in_progress              ║
  ║ track_progress         进度尺推进（供哨兵收敛判定）              ║
  ║ deliver                向上交付（标记 done + 归档）             ║
  ╚══════════════════════════════════════════════════════════════╝

能力时机（何时该用，见 docs/DISPATCH_ABILITY.md 与 AGENTS.md）：
  - 发现工作可拆分为子任务、且已有对应角色可承接 → 可派发（不必等经理）；
  - 收到带 [触发:<角色全称>] 的接力卡 → 必须回执 [接单] 并开工；
  - 面向同一问题多角色协同 / 功能域任务可拆子池 → 用 pool / 派发协同。

用法（任意角色实例上直接调用）：
    role = DeveloperRole()
    ability = DispatchAbility(owner=role)
    result = ability.dispatch(repo, assignments)   # 作为派发方
    ability.accept("T1", agent_id)                  # 作为被派发方
"""
import os
import sys

# 确保 local-agent 目录在 sys.path（便于导入 dispatch_engine）
_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class DispatchAbility:
    """通用派发能力：任何 agent 挂载即得派发+接单双角色能力。

    通过 `owner` 绑定所属 agent（角色名/实例），派发时留痕归因到该 agent。
    """

    # 使用规则（供 AGENTS.md / 文档引用，集中维护一处）
    RULES = {
        "当派发方": (
            "把工作拆为可执行子任务并派发：① 明确 task_key/title/role/domain；"
            "② 通过 dispatch() 走 L1声明→L2分发→L3触发→L4开工；"
            "③ 跟踪到 L4（接单回执+进度尺+交付），不以『分了』为终点；"
            "④ 任务过大拆分 / 功能域投池 / 面向同一问题多角色协同。"
        ),
        "当被派发方": (
            "收到带 [触发:<角色全称>] 的接力卡即触发：① 回复 [接单] 确认接手；"
            "② 到对应 Issue 开工；③ 每次推进写进度尺 goal_meters（distance/delta）；"
            "④ 阶段性成果按小组统一向上交付留痕。"
        ),
        "不越权": (
            "派发须在自己的职责域内；对外跨岗位派发须经经理协调；"
            "收到派发却无法执行须显式上报，不静默失败。"
        ),
        "防无效": (
            "同一任务二次触发仍同一 gid（稳定寻址不漂移）；"
            "命中哨兵停滞/横跳/重复错误判定须按协议处置。"
        ),
    }

    def __init__(self, owner=None):
        """owner: 绑定所属 agent（角色实例或角色名）。用于留痕归因。"""
        self.owner = owner
        self._owner_name = self._resolve_owner_name(owner)

    @staticmethod
    def _resolve_owner_name(owner):
        """把 owner 解析为角色名（实例取 .name，字符串直接用）。"""
        if owner is None:
            return ""
        if isinstance(owner, str):
            return owner
        name = getattr(owner, "name", "")
        return name or getattr(owner, "__class__", object).__name__

    def _engine(self):
        """惰性导入 dispatch_engine（避免模块级依赖，增强可移植性）。"""
        import dispatch_engine
        return dispatch_engine

    # ------------------------------------------------------------
    # 派发方侧（L1→L4）
    # ------------------------------------------------------------
    def declare_assignments(self, assignments):
        """L1 声明：登记任务/角色 gid。"""
        return self._engine().declare_assignments(assignments)

    def assign(self, repo, assignments):
        """L2 分发：拆分任务 + 分配角色 + 投功能域池 + 创建独立 Issue。"""
        return self._engine().dispatch_assign(repo, assignments)

    def trigger(self, assignments, from_agent=None):
        """L3 触发：投递接力卡 [触发:角色]，等待 [接单] 回执。"""
        return self._engine().dispatch_trigger(
            assignments, from_agent=from_agent or self._owner_name or "架构·经理")

    def start(self, assignments, from_agent=None):
        """L4 开工：确认接单后标记 in_progress + 留痕 + 执行 action。"""
        return self._engine().dispatch_start(
            assignments, from_agent=from_agent or self._owner_name or "架构·经理")

    def dispatch(self, repo, assignments, enable_issue=True):
        """四层分发一站式（L1→L2→L3→L4）。任意 agent 都可调用。"""
        return self._engine().dispatch(repo, assignments, enable_issue=enable_issue)

    def dispatch_depth(self, repo, assignments, enable_issue=True):
        """别名：四层分发深度一站式入口（与 dispatch 相同）。"""
        return self.dispatch(repo, assignments, enable_issue=enable_issue)

    # ------------------------------------------------------------
    # 被派发方侧（接单闭环）
    # ------------------------------------------------------------
    def accept(self, task_key, agent_id, role=None, note=""):
        """接单回执：确认 [接单]，标记任务 in_progress，通知派发方。"""
        role = role or self._owner_name or ""
        return self._engine().accept_assignment(
            task_key, agent_id, role=role, note=note)

    def track_progress(self, task_key, agent_id, target, goal_total, current,
                       note="", role=None):
        """进度尺推进：写 goal_meters 刻度，供哨兵收敛判定。"""
        role = role or self._owner_name or ""
        return self._engine().track_progress(
            task_key, agent_id, target=target, goal_total=goal_total,
            current=current, note=note, role=role)

    def deliver(self, task_key, agent_id, output, issue_ref="", role=None):
        """向上交付：标记任务 done + 归档产物 + 留痕。"""
        role = role or self._owner_name or ""
        return self._engine().deliver(
            task_key, agent_id, output, issue_ref=issue_ref, role=role)

    # ------------------------------------------------------------
    # 能力元信息
    # ------------------------------------------------------------
    def capability(self):
        """返回能力声明（供 AGENTS.md / 文档 / 各 agent 人设引用）。"""
        return {
            "name": "通用派发能力 (DispatchAbility)",
            "owner": self._owner_name,
            "as_dispatcher": ["dispatch", "declare_assignments", "assign",
                              "trigger", "start"],
            "as_receiver": ["accept", "track_progress", "deliver"],
            "rules": self.RULES,
            "depth_model": "L1声明→L2分发→L3触发→L4工作交付（目标锁L4）",
        }


# 模块级单例函数便于直接使用
def dispatch_ability(owner=None):
    """便捷工厂：返回绑定 owner 的通用派发能力实例。"""
    return DispatchAbility(owner=owner)


__all__ = ["DispatchAbility", "dispatch_ability"]
