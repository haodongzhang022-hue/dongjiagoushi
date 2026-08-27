# -*- coding: utf-8 -*-
"""
角色基类：定义统一执行接口 + 全员通用能力挂载。

两大全员能力（Issue #33 用户拍板）：
  - **派发能力（DispatchAbility）**：全员可派发、可接单（L1→L4 四层深度闭环）；
  - **自适应 @ 定位能力（HandleAbility）**：根据当前触发仓库动态识别自身完整
    @ 格式 + 跨库定位目标仓库有权限角色（不写死角色名/承载仓库/org）。

团队因此从「散兵」升级为「可协作体系」：每个 agent 既会「派活接单」，也能
「跨仓库用对权限的 @ 召唤目标角色」，不再依赖写死的角色名。

使用方式（任意角色实例上）：
    role = DeveloperRole()
    # --- 派发/接单 ---
    role.dispatch(repo, assignments)     # 作为派发方，四层分发
    role.accept(task_key, agent_id)      # 作为被派发方，接单回执
    # --- 自适应 @ 定位 ---
    role.self_handle()                   # 自身完整 @ 格式（身份声明不写死）
    role.resolve("other/repo", "CodeBuddy")  # 跨库定位目标仓库有权限角色
"""
import os
import sys

# 确保 local-agent 目录在 sys.path（便于导入 dispatch.ability / handle.resolver）
_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class BaseRole:
    """所有角色继承。子类实现 SYSTEM_PROMPT 与 output_contract()。

    默认挂载两大全员能力：
      - 通用派发能力（DispatchAbility）：全员可派发、可接单；
      - 自适应 @ 定位能力（HandleAbility）：自我识别 + 跨库权限定位。
    """

    name = ""
    SYSTEM_PROMPT = ""

    def __init__(self, at_str=None, current_org=None, current_repo=None):
        """at_str: 会话注入的 @ 触发串（用于自适应识别自身角色承载仓库）；
        current_org/current_repo: 当前操作仓库（缺省自动探测）。"""
        self._at_str = at_str
        self._current_org = current_org
        self._current_repo = current_repo
        # 懒加载通用派发能力（绑定到自身角色名，留痕归因）
        try:
            from dispatch import DispatchAbility
            self.dispatch_ability = DispatchAbility(owner=self)
        except Exception:
            # 能力加载失败不阻断角色可用（环境差异容错）
            self.dispatch_ability = None
        # 懒加载自适应 @ 定位能力（自我识别 + 跨库定位）
        try:
            from handle import HandleAbility
            self.handle_ability = HandleAbility(
                owner=self, at_str=at_str,
                current_org=current_org, current_repo=current_repo,
            )
        except Exception:
            self.handle_ability = None

    # ------------------------------------------------------------
    # 自适应 @ 定位能力透传（全员通用）
    # ------------------------------------------------------------
    def set_trigger(self, at_str):
        """运行期注入触发串（agent 被触发后才知自身 @ 格式时调用）。"""
        self._at_str = at_str
        if self.handle_ability is not None:
            self.handle_ability.at_str = at_str

    def self_handle(self):
        """返回本 agent 自身的完整 @ 格式（身份声明/汇报落款用，不写死）。"""
        if self.handle_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载自适应 @ 定位能力")
        return self.handle_ability.self_handle()

    def identity(self):
        """返回 {触发承载仓库, 当前操作仓库, target, role, handle}。"""
        if self.handle_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载自适应 @ 定位能力")
        return self.handle_ability.identity()

    def resolve(self, target_org=None, target_repo=None, role=None):
        """跨库定位目标仓库有权限 @ 格式（权限更高，不写死）。"""
        if self.handle_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载自适应 @ 定位能力")
        return self.handle_ability.resolve(
            target_org=target_org, target_repo=target_repo, role=role)

    def is_cross(self, target_org=None, target_repo=None):
        """判定目标仓库是否跨仓库（同仓可复用本仓库 @，防冗余）。"""
        if self.handle_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载自适应 @ 定位能力")
        return self.handle_ability.is_cross(target_org, target_repo)

    def codebuddy(self, target_org=None, target_repo=None):
        """目标仓库 CodeBuddy 兜底 @ 格式。"""
        if self.handle_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载自适应 @ 定位能力")
        return self.handle_ability.codebuddy(target_org, target_repo)

    # ------------------------------------------------------------
    # 派发能力透传（全员通用）
    # ------------------------------------------------------------
    def dispatch(self, repo, assignments, enable_issue=True):
        """四层分发一站式（L1→L2→L3→L4）。任意 agent 均可派发子任务。"""
        if self.dispatch_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载通用派发能力")
        return self.dispatch_ability.dispatch(repo, assignments,
                                               enable_issue=enable_issue)

    def dispatch_depth(self, repo, assignments, enable_issue=True):
        """别名：四层分发深度一站式入口（与 dispatch 相同）。"""
        return self.dispatch(repo, assignments, enable_issue=enable_issue)

    def accept(self, task_key, agent_id, role=None, note=""):
        """接单回执：收到 [触发:<角色>] 接力卡后回执 [接单] 确认接手。"""
        if self.dispatch_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载通用派发能力")
        return self.dispatch_ability.accept(
            task_key, agent_id, role=role or self.name, note=note)

    def track_progress(self, task_key, agent_id, target, goal_total, current,
                       note="", role=None):
        """进度尺推进：每次推进写 goal_meters 刻度，供哨兵收敛判定。"""
        if self.dispatch_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载通用派发能力")
        return self.dispatch_ability.track_progress(
            task_key, agent_id, target=target, goal_total=goal_total,
            current=current, note=note, role=role or self.name)

    def deliver(self, task_key, agent_id, output, issue_ref="", role=None):
        """向上交付：标记任务 done + 归档产物 + 留痕。"""
        if self.dispatch_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载通用派发能力")
        return self.dispatch_ability.deliver(
            task_key, agent_id, output, issue_ref=issue_ref, role=role or self.name)

    def capability(self):
        """返回本角色的能力清单（含两大全员通用能力）。"""
        base = {"role": self.name}
        if self.dispatch_ability is not None:
            base["dispatch_ability"] = self.dispatch_ability.capability()
        if self.handle_ability is not None:
            base["handle_ability"] = self.handle_ability.capability()
        return base

    # ---- 既有接口保持兼容 ----
    def system_prompt(self):
        return self.SYSTEM_PROMPT

    def output_contract(self):
        """返回该角色的输出契约（结构化描述），供占位/测试/LLM 统一使用。"""
        return {"role": self.name, "contract": "未定义"}

    def run(self, llm, user_input):
        """执行角色：调用 llm 后端，返回输出。"""
        return llm.call(self.system_prompt(), user_input)
