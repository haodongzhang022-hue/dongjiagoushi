# -*- coding: utf-8 -*-
"""
七层协作深度能力（DepthAbility · 全员能力）
============================================
把「协作能走多深、路由是否真实唤醒、能否持续到结果」封装为**可复用通用能力**，
供任何 agent 挂载使用——**不是只给秘书/经理一个 agent**，而是全员对接并会用。

用户 Issue #47 核心诉求：
  - 秘书/很多 agent 其实只在「描述」（L1），并没有真正触发对面角色过来工作；
  - 路由并没有真实现唤醒——甚至不能确认是否给对面传达了足够内容；
  - 需要可量化的深度阶梯，逐层确认「真的在推进」，而不是「嘴上说在推进」；
  - 这是**通用能力**，应做好后以独立模块能力存在，然后给每个 agent 对接并让其会用。

七层阶梯（DepthAbility 全链路，见 docs/DEPTH_MODEL.md）：
  L1 express       表述层：到对应角色拿到信息
  L2 connect       任务对接层：到对应 Issue 接到任务、匹配到 agent
  L3 awake/start   开工层：**路由真实唤醒** + 接受任务开始工作
  L4 interact      成果交互层：成果能和当前 agent 双向交互
  L5 track/auto    进度可控层：进度可控、可来回轮次触发、自动化规则维持流程
  L6 persist       持续到结果层：一套自动化持续到结果（秘书目标档位）
  L7 auto_run      全自动到结果层：全自动闭环到结果（体系目标档位）

设计要点：
  - **唤醒校验（awake）**：路由后检测目标 agent 是否真回执 [接单]，解决「只描述没唤醒」。
  - **防跳层**：某层操作前须已满足前置深度（require_depth），不跳层空谈。
  - **可俯瞰**：depth_overview() 按层统计所有任务，回答「哪些真正走到了深层」。
  - **全员可用**：挂载到 BaseRole，任意角色实例直接调用（无需经理）。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class DepthAbility:
    """通用七层协作深度能力：任何 agent 挂载即得 L1→L7 全链路能力。

    通过 `owner` 绑定所属 agent（角色名/实例），留痕归因到该 agent。
    """

    # 使用规则（供 AGENTS.md / docs/DEPTH_MODEL.md 集中维护）
    RULES = {
        "何时用": (
            "凡是需要与其他角色协作、路由、唤醒、持续推进到结果的场景都用本能力："
            "秘书路由产品/销售、经理派发开发/测试、开发上报小组长、任意 agent 催促进度、"
            "监控是否持续推进到结果。"
        ),
        "唤醒优先": (
            "路由不只是「表述」——L3 必须做 awake() 校验目标 agent 是否真回执 [接单]；"
            "未回执 = 路由未真实唤醒，须重触发或升级，不以『已传达』为终点。"
        ),
        "防跳层": (
            "逐层推进，某层操作前须已满足前置深度；不跳层空谈『到结果』。"
        ),
        "持续到结果": (
            "秘书/派发方要推到 L6（一套持续到结果，收尾确认后交付）；"
            "体系级任务推到 L7（全自动闭环到结果，无需人工中断）。"
            "多数 agent 默认停在 L5（进度可控），须用 auto_guard 自动规则持续维持推进。"
        ),
        "不越权": (
            "跨岗位派发/唤醒须在职责域内；对外跨岗位派发经经理协调。"
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
        name = getattr(owner, "name", "")
        return name or getattr(owner, "__class__", object).__name__

    def _eng(self):
        """惰性导入 depth.engine。"""
        from depth import engine
        return engine

    # ------------------------------------------------------------
    # L1 表述
    # ------------------------------------------------------------
    def express(self, task_key, to_agent, message, from_agent=None):
        """L1 表述层：向目标角色传达信息（最浅层，是否真唤醒由 L3 校验）。"""
        from_agent = from_agent or self._owner_name or "system"
        return self._eng().express(task_key, from_agent, to_agent, message)

    # ------------------------------------------------------------
    # L2 任务对接
    # ------------------------------------------------------------
    def connect(self, task_key, issue_ref="", role="架构·开发", domain="通用",
                title="", detail="", repo=""):
        """L2 任务对接层：任务落到 Issue + 匹配到 agent。"""
        return self._eng().connect(task_key, issue_ref=issue_ref, role=role,
                                   domain=domain, title=title, detail=detail,
                                   repo=repo)

    # ------------------------------------------------------------
    # L3 开工（含路由真实唤醒）
    # ------------------------------------------------------------
    def awake(self, task_key, target_agent, context="", issue_ref="", from_agent=None):
        """L3 路由真实唤醒：投递接力卡并校验目标 agent 是否真回执。

        返回 {awakened: bool}——未唤醒须重触发或升级，不以『已传达』为终点。
        """
        from_agent = from_agent or self._owner_name or "system"
        return self._eng().awake(task_key, target_agent, from_agent,
                                 issue_ref=issue_ref, context=context)

    def ack_wake(self, task_key, role="", note="", agent_id=None):
        """被唤醒方回执：确认接管，标记路由真实唤醒成立。"""
        agent_id = agent_id or self._owner_name or ""
        return self._eng().ack_wake(task_key, agent_id, role=role or agent_id,
                                    note=note)

    def start_work(self, task_key, role="", note="", agent_id=None):
        """L3 开工：接单后正式开工。"""
        agent_id = agent_id or self._owner_name or ""
        return self._eng().start_work(task_key, agent_id, role=role or agent_id,
                                      note=note)

    # ------------------------------------------------------------
    # L4 成果交互
    # ------------------------------------------------------------
    def interact(self, task_key, consumer_agent, artifact, producer_agent=None,
                 feedback=None):
        """L4 成果交互：产出交付给消费方，消费方可回读并反馈（双向）。"""
        producer_agent = producer_agent or self._owner_name or ""
        return self._eng().interact(task_key, producer_agent, consumer_agent,
                                    artifact, feedback=feedback)

    # ------------------------------------------------------------
    # L5 进度可控 + 自动化规则维持
    # ------------------------------------------------------------
    def track_round(self, task_key, target, goal_total, current, note="",
                    agent_id=None, role=""):
        """L5 进度可控 + 轮次触发：写进度尺。"""
        agent_id = agent_id or self._owner_name or ""
        return self._eng().track_round(task_key, agent_id, target, goal_total,
                                       current, note=note, role=role or agent_id)

    def auto_guard(self, task_key, rule="stall_escalate", timeout_rounds=3,
                   agent_id=None):
        """L5 自动化规则维持流程：哨兵收敛/超时重触发/停滞升级。"""
        agent_id = agent_id or self._owner_name or ""
        return self._eng().auto_guard(task_key, agent_id, rule=rule,
                                      timeout_rounds=timeout_rounds)

    # ------------------------------------------------------------
    # L6 持续到结果（秘书目标档位）
    # ------------------------------------------------------------
    def persist_to_result(self, task_key, milestones, role="",
                          need_human_gate=False, agent_id=None):
        """L6 持续到结果：一套自动化按里程碑推进到结果。"""
        agent_id = agent_id or self._owner_name or ""
        return self._eng().persist_to_result(
            task_key, agent_id, milestones, role=role or agent_id,
            need_human_gate=need_human_gate)

    # ------------------------------------------------------------
    # L7 全自动到结果（体系目标档位）
    # ------------------------------------------------------------
    def auto_run_to_result(self, task_key, milestones, role="", max_rounds=10,
                           agent_id=None):
        """L7 全自动到结果：无需人工中断，全自动闭环。"""
        agent_id = agent_id or self._owner_name or ""
        return self._eng().auto_run_to_result(
            task_key, agent_id, milestones, role=role or agent_id,
            max_rounds=max_rounds)

    # ------------------------------------------------------------
    # 俯瞰与查询
    # ------------------------------------------------------------
    def depth_of(self, task_key):
        """查询任务当前已达深度层。"""
        return self._eng().depth_of(task_key)

    def depth_overview(self):
        """按七层深度俯瞰所有任务（二级信息）。"""
        return self._eng().depth_overview()

    def levels_spec(self):
        """七层深度规范（供文档/规则/测试对齐）。"""
        return self._eng().levels_spec()

    # ------------------------------------------------------------
    # 能力元信息
    # ------------------------------------------------------------
    def capability(self):
        """返回能力声明（供 AGENTS.md / 文档 / 各 agent 人设引用）。"""
        return {
            "name": "七层协作深度能力 (DepthAbility)",
            "owner": self._owner_name,
            "L1_表述": ["express"],
            "L2_任务对接": ["connect"],
            "L3_开工": ["awake", "ack_wake", "start_work"],
            "L4_成果交互": ["interact"],
            "L5_进度可控": ["track_round", "auto_guard"],
            "L6_持续到结果": ["persist_to_result"],
            "L7_全自动到结果": ["auto_run_to_result"],
            "rules": self.RULES,
            "target_level": (
                "秘书/派发方推到 L6（持续到结果）；体系级推到 L7（全自动到结果）；"
                "多数 agent 默认 L5（进度可控），须用 auto_guard 维持推进"
            ),
        }


def depth_ability(owner=None):
    """便捷工厂：返回绑定 owner 的七层深度能力实例。"""
    return DepthAbility(owner=owner)


__all__ = ["DepthAbility", "depth_ability"]
