# -*- coding: utf-8 -*-
"""
开发持续推进能力（DevIterationAbility · 全员能力 · Issue #74）
================================================================
把「开发没开发完 → 继续接开发（自循环推进）」封装为**可复用通用能力**，
供任何 agent（尤其开发）挂载使用。

用户 Issue #74 核心诉求：
  - 开发后面不一定接评审或经理，可能是没开发完继续接开发；
  - 但会导致陷入循环 → 用进度北极星（goal_meters）管住；
  - 任务明确才自循环，持续开发推进度，不一定要触发经理；
  - 回传信息可能是记录（存档），不一定得对话，先存起来；
  - 干完一起给经理，而不是每次汇报都经理重新处理跟进。

能力维度：
  ╔═ 作为开发 ═══════════════════════════════════════════════╗
  ║ continue_dev()         开发自循环推进（记录进度 + 哨兵判定）║
  ║ can_continue()         判断是否可继续（任务明确/未完成/未拦截）║
  ║ record_progress()      记录推进度（goal_meters + archives） ║
  ║ run_iterations()       批量自循环（脚本/测试/自动化）        ║
  ║ deliver_to_manager()   完成统一交付给经理                    ║
  ║ progress_history()     进度记录回放                         ║
  ║ iteration_overview()   迭代俯瞰（二级信息）                  ║
  ╚═══════════════════════════════════════════════════════════╝

能力时机：
  - 开发接单后任务明确 → 可持续 continue_dev() 自循环推进；
  - 每次推进写 goal_meters + archives（不对话，经理零打扰）；
  - 哨兵命中（停滞/横跳/重复错误）→ handle_sentinel_hit() 处置；
  - 完成（current>=goal_total）→ deliver_to_manager() 统一交付。

用法（任意角色实例上直接调用）：
    role = DeveloperRole()
    ability = DevIterationAbility(owner=role)
    res = ability.continue_dev("登录模块", agent_id, target="实现登录",
                               goal_total=10, current=8)
    ability.deliver_to_manager("登录模块", agent_id, output="已完成")
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class DevIterationAbility:
    """通用开发持续推进能力：任何 agent 挂载即得自循环推进能力。

    通过 `owner` 绑定所属 agent（角色名/实例），留痕归因到该 agent。
    """

    # 使用规则（供 AGENTS.md / docs/DEV_ITERATION.md 集中维护）
    RULES = {
        "何时用": (
            "开发接单后任务目标明确（goal_total>0）时，可持续 continue_dev() 自循环推进，"
            "不必每次交回评审/经理；任务不明确（无北极星目标）时不能自循环，须先澄清。"
        ),
        "记录优先": (
            "过程中只写 goal_meters 进度尺 + 存 archives 记录（kind=dev_progress），"
            "不投递对话消息给经理/评审——经理在开发完成前零打扰。"
        ),
        "哨兵拦截": (
            "哨兵命中（停滞/横跳/重复错误）→ handle_sentinel_hit() 按级别处置"
            "（1级打断重规划 / 2级上报总师助理 + blocked），防自循环陷入死循环。"
        ),
        "完成交付": (
            "current>=goal_total 时调 deliver_to_manager()——归档产物 + 标记 done + "
            "一次性通知经理（含完整 progress_history 回放），不反复汇报。"
        ),
        "防无效": (
            "自循环必须有明确北极星目标；进度无实质推进（distance 不降）会被哨兵拦截；"
            "同一失败反复提交（note 显式标错）触发重复错误判定。"
        ),
    }

    def __init__(self, owner=None):
        """owner: 绑定所属 agent（角色实例或角色名）。用于留痕归因。"""
        self.owner = owner
        self._owner_name = self._resolve_owner_name(owner)

    @staticmethod
    def _resolve_owner_name(owner):
        if owner is None:
            return ""
        if isinstance(owner, str):
            return owner
        name = getattr(owner, "name", "")
        return name or getattr(owner, "__class__", object).__name__

    def _eng(self):
        import dev_iteration
        return dev_iteration

    # ---------------- 自循环推进 ----------------
    def can_continue(self, task_key, goal_total=0.0, current=0.0):
        """判断开发是否可继续自循环推进。"""
        return self._eng().can_continue(task_key, goal_total, current)

    def continue_dev(self, task_key, agent_id, target, goal_total, current,
                     note="", archive_detail="", max_iterations=20):
        """开发自循环入口：记录推进度 + 哨兵判定 + 判断是否继续。"""
        return self._eng().continue_dev(
            task_key, agent_id, target, goal_total, current,
            note=note, archive_detail=archive_detail, max_iterations=max_iterations,
        )

    def record_progress(self, task_key, agent_id, target, goal_total, current,
                        note="", archive_detail=""):
        """记录一次开发推进度（goal_meters + archives，非对话）。"""
        return self._eng().record_progress(
            task_key, agent_id, target, goal_total, current,
            note=note, archive_detail=archive_detail,
        )

    def run_iterations(self, task_key, agent_id, target, goal_total,
                       steps, notes=None, archive_details=None):
        """批量执行多轮开发自循环。"""
        return self._eng().run_iterations(
            task_key, agent_id, target, goal_total,
            steps, notes=notes, archive_details=archive_details,
        )

    # ---------------- 完成交付 ----------------
    def deliver_to_manager(self, task_key, agent_id, output,
                           issue_ref="", manager_msg=""):
        """任务完成时统一交付给经理。"""
        return self._eng().deliver_to_manager(
            task_key, agent_id, output,
            issue_ref=issue_ref, manager_msg=manager_msg,
        )

    # ---------------- 哨兵处置 ----------------
    def handle_sentinel_hit(self, task_key, agent_id, hit_result):
        """哨兵命中处置：按级别执行协议（1级打断 / 2级上报）。"""
        return self._eng().handle_sentinel_hit(task_key, agent_id, hit_result)

    # ---------------- 二级信息 ----------------
    def progress_history(self, task_key):
        """某任务的全部开发进度记录（回放）。"""
        return self._eng().progress_history(task_key)

    def iteration_overview(self):
        """全部开发自循环的俯瞰（二级信息）。"""
        return self._eng().iteration_overview()

    def capability(self):
        """返回能力声明（供其他 agent 查询）。"""
        return {
            "name": "DevIterationAbility",
            "owner": self._owner_name,
            "rules": self.RULES,
            "methods": [
                "can_continue", "continue_dev", "record_progress",
                "run_iterations", "deliver_to_manager",
                "handle_sentinel_hit", "progress_history", "iteration_overview",
            ],
        }
