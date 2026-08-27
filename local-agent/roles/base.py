# -*- coding: utf-8 -*-
"""
角色基类：定义统一执行接口 + 全员通用能力挂载。

三大全员能力：
  - **派发能力（DispatchAbility）**：全员可派发、可接单（L1→L4 四层深度闭环）；
  - **自适应 @ 定位能力（HandleAbility）**：根据当前触发仓库动态识别自身完整
    @ 格式 + 跨库定位目标仓库有权限角色（不写死角色名/承载仓库/org）；
  - **七层协作深度能力（DepthAbility，Issue #47）**：L1表述→L2任务对接→L3开工
    (含路由真实唤醒)→L4成果交互→L5进度可控·自动化维持→L6持续到结果→L7全自动到结果。
    让路由**真唤醒**目标 agent（不是只描述），并可持续推进到结果。

团队因此从「散兵」升级为「可协作体系」：每个 agent 既会「派活接单」，也能
「跨仓库用对权限的 @ 召唤目标角色」，还能「七层深度推进到结果」，
不再依赖写死的角色名，也不再停留于"嘴上说推进"。

使用方式（任意角色实例上）：
    role = DeveloperRole()
    # --- 派发/接单 ---
    role.dispatch(repo, assignments)     # 作为派发方，四层分发
    role.accept(task_key, agent_id)      # 作为被派发方，接单回执
    # --- 自适应 @ 定位 ---
    role.self_handle()                   # 自身完整 @ 格式（身份声明不写死）
    role.resolve("other/repo", "CodeBuddy")  # 跨库定位目标仓库有权限角色
    # --- 七层协作深度（Issue #47）---
    role.awake(task_key, "架构·产品", context=...)  # 路由真实唤醒（校验回执）
    role.persist_to_result(task_key, milestones)    # 一套持续到结果（L6 秘书档位）
"""
import os
import sys

# 确保 local-agent 目录在 sys.path（便于导入 dispatch.ability / handle.resolver）
_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class BaseRole:
    """所有角色继承。子类实现 SYSTEM_PROMPT 与 output_contract()。

    默认挂载三大全员能力：
      - 通用派发能力（DispatchAbility）：全员可派发、可接单；
      - 自适应 @ 定位能力（HandleAbility）：自我识别 + 跨库权限定位；
      - 七层协作深度能力（DepthAbility）：路由真唤醒 + L1-L7 持续推进到结果。
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
        # 懒加载七层协作深度能力（Issue #47：路由真唤醒 + L1-L7 持续到结果）
        try:
            from depth import DepthAbility
            self.depth_ability = DepthAbility(owner=self)
        except Exception:
            self.depth_ability = None
        # 懒加载标签管理全员能力（LabelAbility · Issue #51：查询/打标/提议/审批/自动打标）
        try:
            from label import LabelAbility
            self.label_ability = LabelAbility(owner=self)
        except Exception:
            self.label_ability = None

    # ------------------------------------------------------------
    # 七层协作深度能力透传（全员通用 · Issue #47）
    # ------------------------------------------------------------
    def express(self, task_key, to_agent, message, from_agent=None):
        """L1 表述层：向目标角色传达信息（是否真唤醒由 L3 校验）。"""
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.express(task_key, to_agent, message,
                                          from_agent=from_agent)

    def connect(self, task_key, issue_ref="", role="架构·开发", domain="通用",
                title="", detail="", repo=""):
        """L2 任务对接层：任务落到 Issue + 匹配到 agent。"""
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.connect(task_key, issue_ref=issue_ref,
                                          role=role, domain=domain,
                                          title=title, detail=detail, repo=repo)

    def awake(self, task_key, target_agent, context="", issue_ref="", from_agent=None):
        """L3 路由真实唤醒：投递接力卡并校验目标 agent 是否真回执 [接单]。

        解决"路由其实并没有真实现唤醒"——未回执 = 未唤醒，须重触发或升级。
        """
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.awake(task_key, target_agent,
                                        context=context, issue_ref=issue_ref,
                                        from_agent=from_agent)

    def ack_wake(self, task_key, role="", note="", agent_id=None):
        """L3 被唤醒方回执：确认接管，标记路由真实唤醒成立。"""
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.ack_wake(task_key, role=role, note=note,
                                           agent_id=agent_id)

    def start_work(self, task_key, role="", note="", agent_id=None):
        """L3 开工：接单后正式开工。"""
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.start_work(task_key, role=role, note=note,
                                             agent_id=agent_id)

    def interact(self, task_key, consumer_agent, artifact, producer_agent=None,
                 feedback=None):
        """L4 成果交互：产出交付给消费方，消费方可回读并反馈（双向）。"""
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.interact(task_key, consumer_agent, artifact,
                                           producer_agent=producer_agent,
                                           feedback=feedback)

    def track_round(self, task_key, target, goal_total, current, note="",
                    agent_id=None, role=""):
        """L5 进度可控 + 轮次触发：写进度尺。"""
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.track_round(task_key, target, goal_total,
                                              current, note=note,
                                              agent_id=agent_id, role=role)

    def auto_guard(self, task_key, rule="stall_escalate", timeout_rounds=3,
                   agent_id=None):
        """L5 自动化规则维持流程：哨兵收敛/超时重触发/停滞升级。"""
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.auto_guard(task_key, rule=rule,
                                             timeout_rounds=timeout_rounds,
                                             agent_id=agent_id)

    def persist_to_result(self, task_key, milestones, role="",
                          need_human_gate=False, agent_id=None):
        """L6 持续到结果：一套自动化按里程碑推进到结果（秘书目标档位）。"""
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.persist_to_result(
            task_key, milestones, role=role, need_human_gate=need_human_gate,
            agent_id=agent_id)

    def auto_run_to_result(self, task_key, milestones, role="", max_rounds=10,
                           agent_id=None):
        """L7 全自动到结果：无需人工中断，全自动闭环（体系目标档位）。"""
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.auto_run_to_result(
            task_key, milestones, role=role, max_rounds=max_rounds,
            agent_id=agent_id)

    def depth_of(self, task_key):
        """查询任务当前已达深度层。"""
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.depth_of(task_key)

    def depth_overview(self):
        """按七层深度俯瞰所有任务（二级信息）。"""
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        return self.depth_ability.depth_overview()

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

    # ------------------------------------------------------------
    # 标签管理能力透传（全员通用 · Issue #51）
    # ------------------------------------------------------------
    def query_progress(self, task_id, agent_id=""):
        """程序化查进度（MCP 管线，goal_meters+progress 合并），不靠 AI 对话。"""
        if self.label_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载标签管理能力")
        return self.label_ability.query_progress(task_id, agent_id=agent_id)

    def query_status(self, entity):
        """程序化查实体状态标签。"""
        if self.label_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载标签管理能力")
        return self.label_ability.query_status(entity)

    def query_labels(self, entity):
        """查实体全部标签。"""
        if self.label_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载标签管理能力")
        return self.label_ability.query_labels(entity)

    def apply_label(self, entity, label_key, value="", action="apply", note=""):
        """一线直接打标/去标/刷值（白名单角色，其余须提议审批）。"""
        if self.label_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载标签管理能力")
        return self.label_ability.apply_label(entity, label_key, value=value,
                                              action=action, note=note)

    def remove_label(self, entity, label_key, note=""):
        """一线去标。"""
        if self.label_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载标签管理能力")
        return self.label_ability.remove_label(entity, label_key, note=note)

    def propose_label(self, entity, label_key, reason="", value=""):
        """全员提议加/改标签（标签管理员审批）。"""
        if self.label_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载标签管理能力")
        return self.label_ability.propose_label(entity, label_key, reason=reason,
                                                value=value)

    def review_label_request(self, request_id, decision="approved", note=""):
        """标签管理员审批提议（approved→自动落标）。"""
        if self.label_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载标签管理能力")
        return self.label_ability.review_request(request_id, decision=decision,
                                                 note=note)

    def auto_trigger(self, event, entity, goal_total=None, current=None,
                     note="", value=""):
        """事件驱动自动打标：事件到达即按规则打标，无需 agent 记得去调。

        value 携带事件值（priority.set → p0..p9 / next.trigger → 下一步 issue 编号）。
        """
        if self.label_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载标签管理能力")
        return self.label_ability.auto_trigger(event, entity,
                                               goal_total=goal_total,
                                               current=current, note=note,
                                               value=value)
    def pending_label_requests(self):
        """查看待审批标签提议（标签管理员用）。"""
        if self.label_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载标签管理能力")
        return self.label_ability.pending_requests()

    # ---- 结构化标签（通用模块能力透传：前置依赖 / 下一步 / 优先级 P0-P9 / 流水线节点）----
    def set_depends(self, entity, issue_no, note=""):
        """打前置依赖标签（depends_on → value 存前置 Issue 编号）。"""
        return self.label_ability.set_depends(entity, issue_no, note=note)

    def set_next_step(self, entity, issue_no, note=""):
        """打完成后下一步触发标签（next_step → value 存下一步 Issue 编号）。"""
        return self.label_ability.set_next_step(entity, issue_no, note=note)

    def set_priority(self, entity, p_level, note=""):
        """打优先级标签（P0-P9 大盘：p0 最紧急→p9 最不紧急，正交维度）。"""
        return self.label_ability.set_priority(entity, p_level, note=note)

    def set_pipeline_node(self, entity, node, value="", note=""):
        """打流水线自动化关键节点标签（at_node / trigger_next / gate）。"""
        return self.label_ability.set_pipeline_node(entity, node, value=value,
                                                    note=note)

    def dependencies(self, entity):
        """查某实体的前置依赖（depends_on 标签）。"""
        return self.label_ability.dependencies(entity)

    def next_steps(self, entity):
        """查某实体的完成后下一步触发（next_step 标签）。"""
        return self.label_ability.next_steps(entity)


    def capability(self):
        """返回本角色的能力清单（含三大全员通用能力）。"""
        base = {"role": self.name}
        if self.dispatch_ability is not None:
            base["dispatch_ability"] = self.dispatch_ability.capability()
        if self.handle_ability is not None:
            base["handle_ability"] = self.handle_ability.capability()
        if self.depth_ability is not None:
            base["depth_ability"] = self.depth_ability.capability()
        if self.label_ability is not None:
            base["label_ability"] = self.label_ability.capability()
        return base

    # ---- 既有接口保持兼容 ----
    def system_prompt(self):
        return self.SYSTEM_PROMPT

    def output_contract(self):
        """返回该角色的输出契约（结构化描述），供占位/测试/LLM 统一使用。"""
        return {"role": self.name, "contract": "未定义"}

    def run(self, llm, user_input, use_cache=True):

        """执行角色：调用 llm 后端，返回输出。

        use_cache=True 时启用角色壳层缓存（shell_cache）：
          - 记录本次调用的缓存命中事件（按 agent × 层归因，供命中监控）；
          - 便于 benchmark/编排层统计每个角色的缓存命中率与节省。
        不改变返回语义（仍是 llm.call 的输出）。
        """
        sp = self.system_prompt()
        out = llm.call(sp, user_input)
        if use_cache:
            try:
                from llm import cache as _cache
                prefix, _ = _shell_extract_prefix(sp)
                _cache.record_cache_event(
                    agent=self.name, layer="shell", cache_hit=1 if prefix else 0,
                    prefix_chars=len(prefix),
                    saved_tokens=max(0, len(prefix) // 3),
                )
            except Exception:
                pass
        return out

def _shell_extract_prefix(system_prompt):
    """角色壳共享前缀抽取（复用 roles.shell_cache.extract_shared_prefix）。"""
    try:
        from roles import shell_cache
        return shell_cache.extract_shared_prefix(system_prompt)
    except Exception:
        return system_prompt or "", ""
