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

        # 懒加载开发小组闭环能力（DevTeamAbility · Issue #74：小组整体确定性编排）
        try:
            from dev_team_kit import DevTeamAbility
            self.dev_team_ability = DevTeamAbility(owner=self)
        except Exception:
            self.dev_team_ability = None
        # 懒加载开发规范全员能力（StandardAbility · Issue #83：确定性检查 + 阶段强制清单 + 合规留痕）
        try:
            from dev_standard import StandardAbility
            self.standard_ability = StandardAbility(owner=self)
        except Exception:
            self.standard_ability = None
        # 懒加载有效性度量全员能力（ReviewMetricsAbility · Issue #100 决策⑤：维度化+概率×程度分档+留痕）
        try:
            from review_metrics import ReviewMetricsAbility
            self.review_metrics_ability = ReviewMetricsAbility(owner=self)
        except Exception:
            self.review_metrics_ability = None
        # 懒加载秘书层动态扩展能力（SecretaryScaleAbility · Issue #100 决策①：识别/注册/路由+权限护栏）
        try:
            from scale import secretary_ability as _ssa_mod
            self.secretary_scale_ability = _ssa_mod.SecretaryScaleAbility(owner=self)
        except Exception:
            self.secretary_scale_ability = None

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

        #142 机制加固：所有接力动作**带着路径出发**——context 不以完整
        `@org/repo(角色) [触发:角色]` 开头时，自动前置完整 @ 路径
        （fullpath_relay），杜绝"写了 [回转] 退回:X 却没 @ X、唤醒不了对端"
        的假触发。
        """
        if self.depth_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载七层协作深度能力")
        # 全路径前置：context 缺完整 @ 召唤时自动补（保证能真实唤醒对端角色）
        ctx = context or ""
        if not ctx.lstrip().startswith("@"):
            ctx = self.fullpath_relay(target_agent, body=ctx)["relay_text"]
        return self.depth_ability.awake(task_key, target_agent,
                                        context=ctx, issue_ref=issue_ref,
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

    # ------------------------------------------------------------
    # 全路径出发（回转/触发/转交 带完整 @org/repo(角色) 路径 · Issue #142 机制加固）
    # ------------------------------------------------------------
    def fullpath_relay(self, target_agent, action="", body="", target_org=None,
                       target_repo=None):
        """生成**带完整 @ 路径出发**的合规接力卡正文。

        背景（用户 #142 拍板）：『回转』只在评论写 `[回转] 退回:架构·开发`
        或 `[触发:架构·开发]` 而不带完整 `@org/repo(架构·开发)`，等于想触发
        却没真实唤醒——评论里没有被 @ 的角色不会收到平台推送。故本体系所有
        接力动作（回转/触发/转交）一律**带着路径出发**：正文首行必须是
        `@org/repo(角色) [触发:角色]` 完整召唤，缺全路径即视为无效接力。

        实现：复用 HandleAbility 动态解析目标仓库有权限的完整 @（不写死
        org/repo/角色名）；action 缺省自动按动作类型标 `[触发:角色]` 或
        `[回转] 退回:角色`；生成后经 relay_card.check 校验，缺标记显式暴露。

        返回：{ handle, mark, relay_text, valid, reasons }
        """
        # ① 动态解析目标完整 @（失败回退探测仓库默认格式）
        handle = None
        try:
            if self.handle_ability is not None:
                info = self.handle_ability.resolve(
                    target_org=target_org, target_repo=target_repo,
                    role=target_agent)
                if isinstance(info, dict) and info.get("handle"):
                    handle = info["handle"]
        except Exception:
            handle = None
        if not handle:
            try:
                from handle import resolver as _hr
                handle = _hr.resolve(target_repo=target_repo or "dongjiagoushi",
                                     role=target_agent)["handle"]
            except Exception:
                handle = "@dongdongxiaozu/dongjiagoushi(%s)" % target_agent

        # ② 动作类型 → 触发标记
        #    约定（AGENTS.md 触发强制化 + #142 全路径出发）：
        #      - 回转卡 = 被打回视为**重新触发**，首行必须同时含
        #        `[触发:<角色>]`（唤醒）+ 正文 [回转] 退回:<角色>（打回语义）；
        #      - 触发/转交卡 = 首行 `[触发:<角色>]`。
        action = (action or "").strip()
        body = (body or "").strip()
        if not action:
            # 缺省动作按正文语义判定：正文已含回转打回语义 → revert；其余 trigger
            action = ("revert" if ("[回转]" in body or "退回:" in body
                                   or body.startswith("评审 [回转]"))
                      else "trigger")
        is_revert = ("退回" in action or action.startswith("revert")
                     or "[回转]" in body or "退回:" in body)
        mark = "[触发:%s]" % target_agent

        # ③ 组装正文：首行 = 完整 @ 路径 + [触发] 标记，保证"带着路径出发"
        if body.startswith("@"):
            relay_text = body  # 已自带路径，保持原样
        else:
            first_line = "%s %s。" % (handle, mark)
            if is_revert and "[回转]" not in body and "退回:" not in body:
                body = "[回转] 退回:%s。\n%s" % (target_agent, body)
            relay_text = "%s\n%s" % (first_line, body) if body else first_line

        # ④ relay_card.check 校验（缺完整 @ / [触发] 即 INVALID）
        valid, reasons = False, ["relay_card 不可用"]
        try:
            from relay_card import check
            valid, reasons = check(relay_text, role=target_agent)
        except Exception:
            pass
        return {
            "handle": handle,
            "mark": mark,
            "relay_text": relay_text,
            "valid": valid,
            "reasons": reasons,
        }

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

    def dispatch_verify(self, assignments):
        """真实唤醒核验（L4 闸门）：核验已分发任务的对端是否真实回执 [接单]。
        未回执的任务暴露为 awaiting_receipt——派发方/哨兵据此重触发或升级，
        不把"列了清单/只投了接力卡"当派发完成。"""
        if self.dispatch_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载通用派发能力")
        return self.dispatch_ability.dispatch_verify(assignments)

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

    def handoff_status(self, task_ids=None):
        """对结果负责核验：检查本角色派发的子任务交接链是否闭环。

        上级派发后应调用：broken>0 = 有下级未真实接单 → 链条断裂，
        须重触发/升级，不得凭『列了清单』自认为完成。任何上下级均适用。
        """
        if self.dispatch_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载通用派发能力")
        return self.dispatch_ability.handoff_status(task_ids=task_ids)

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



    # ------------------------------------------------------------
    # 开发小组闭环能力透传（DevTeamAbility · Issue #74 · 全员通用）
    # ------------------------------------------------------------
    def create_dev_team(self, goal_total=0.0, devs_per_team=2, **kwargs):
        """创建一次开发小组闭环（Planner 门控：goal>0 才允许）。返回 DevTeamEngine。"""
        if self.dev_team_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发小组闭环能力")
        return self.dev_team_ability.create_team(goal_total=goal_total,
                                                 devs_per_team=devs_per_team, **kwargs)

    def run_dev_team_round(self, team, dev_outputs, task_id="", max_attempts=None):
        """确定性编排一轮小组循环（小组长发起 + 各开发客观验证 + 决策）。"""
        if self.dev_team_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发小组闭环能力")
        return self.dev_team_ability.run_team_round(team, dev_outputs,
                                                    task_id=task_id, max_attempts=max_attempts)

    def advance_dev_team(self, team, delta):
        """推进开发小组进度（目标北极星），写 goal_meters。"""
        if self.dev_team_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发小组闭环能力")
        return self.dev_team_ability.advance_team(team, delta)

    def dev_team_overview(self, team):
        """开发小组闭环俯瞰（二级信息）。"""
        if self.dev_team_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发小组闭环能力")
        return self.dev_team_ability.team_overview(team)


    # ------------------------------------------------------------
    # 开发规范全员能力透传（StandardAbility · Issue #83 · 全员通用）
    # ------------------------------------------------------------
    def list_standards(self, level=None, category=None):
        """列出规范条目（按级别/类别过滤）。"""
        if self.standard_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发规范能力")
        return self.standard_ability.list_standards(level=level, category=category)

    def get_standard(self, spec_id):
        """获取单条规范详情。"""
        if self.standard_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发规范能力")
        return self.standard_ability.get_standard(spec_id)

    def get_enforced_specs(self, stage):
        """获取某开发阶段的强制规范清单。"""
        if self.standard_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发规范能力")
        return self.standard_ability.get_enforced_specs(stage)

    def standards_summary(self):
        """规范注册表概览（二级信息）。"""
        if self.standard_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发规范能力")
        return self.standard_ability.standards_summary()

    def check_standard(self, target, spec_ids=None):
        """检查合规性（确定性检查器，非 LLM 判断）。"""
        if self.standard_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发规范能力")
        return self.standard_ability.check_standard(target, spec_ids=spec_ids)

    def check_pr(self, pr_info):
        """PR 规范检查。"""
        if self.standard_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发规范能力")
        return self.standard_ability.check_pr(pr_info)

    def check_code(self, code_file, repo_path=""):
        """代码规范检查。"""
        if self.standard_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发规范能力")
        return self.standard_ability.check_code(code_file, repo_path=repo_path)

    def check_deliver(self, deliver_info):
        """交付规范检查（自测上报/变更范围）。"""
        if self.standard_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发规范能力")
        return self.standard_ability.check_deliver(deliver_info)

    def report_compliance(self, entity, results, format="json"):
        """生成合规报告并留痕（供评审/测试核验）。"""
        if self.standard_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载开发规范能力")
        return self.standard_ability.report_compliance(entity, results, format=format)

    # ------------------------------------------------------------
    # 有效性度量全员能力透传（ReviewMetricsAbility · Issue #100 决策⑤）
    # ------------------------------------------------------------
    def _rm(self):
        if self.review_metrics_ability is None:
            raise RuntimeError(f"角色 {self.name} 未加载有效性度量能力")
        return self.review_metrics_ability

    def metrics_dims(self):
        """列出有效性维度（唯一事实源）。"""
        return self._rm().metrics_dims()

    def metrics_spec(self):
        """机器可读规范摘要。"""
        return self._rm().metrics_spec()

    def metrics_band_names(self):
        """返回档位名。"""
        return self._rm().metrics_band_names()

    def measure_review(self, observation, trace=True, meta=None):
        """提交一次评审/交付观测，分档度量并留痕。"""
        return self._rm().measure_review(observation, trace=trace, meta=meta)

    def metrics_aggregate(self, observations):
        """归并多次观测 → 每维 + 总体有效度。"""
        return self._rm().metrics_aggregate(observations)

    def metrics_judge(self, observations):
        """确定性达标判定（对照测试信号灯等客观事实）。"""
        return self._rm().metrics_judge(observations)

    def metrics_trace_recent(self, limit=20):
        """最近有效性度量留痕。"""
        return self._rm().metrics_trace_recent(limit=limit)

    # ------------------------------------------------------------
    # 秘书层动态扩展能力透传（SecretaryScaleAbility · Issue #100 决策①）
    # ------------------------------------------------------------
    def _ssa(self):
        if getattr(self, "secretary_scale_ability", None) is None:
            raise RuntimeError(f"角色 {self.name} 未加载秘书层动态扩展能力")
        return self.secretary_scale_ability

    def secretary_scale_suggest(self, domain, reuse_count=0, scores=None,
                                requires_execution=False):
        """识别层：判定某场景/信息流是否值得设一个秘书。"""
        return self._ssa().secretary_scale_suggest(
            domain, reuse_count=reuse_count, scores=scores,
            requires_execution=requires_execution)

    def register_secretary_service(self, domain, desc="", handoff_to="", reuse=0,
                                   interfaces=None):
        """注册层：动态挂载一个秘书服务（交接域）。"""
        return self._ssa().register_secretary_service(
            domain, desc=desc, handoff_to=handoff_to, reuse=reuse, interfaces=interfaces)

    def unregister_secretary_service(self, domain):
        """注册层：动态卸载一个秘书服务。"""
        return self._ssa().unregister_secretary_service(domain)

    def list_secretary_services(self, status=None):
        """注册表：列出秘书服务。"""
        return self._ssa().list_secretary_services(status=status)

    def secretary_route(self, request, duty=None):
        """路由层：层间路由请求到匹配秘书域（未命中回终端开发线）。
        duty: 请求职责类型（可选），终端执行类职责在路由入口即被护栏拦截。"""
        return self._ssa().secretary_route(request, duty=duty)

    def secretary_guard(self, duty):
        """权限护栏：判定某职责是否秘书可合法承担（越权接终端任务即拦）。"""
        return self._ssa().secretary_guard(duty)

    def secretary_scale_logs(self, limit=50):
        """秘书层动作留痕（可回溯）。"""
        return self._ssa().secretary_scale_logs(limit=limit)

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
        if getattr(self, "dev_team_ability", None) is not None:
            base["dev_team_ability"] = self.dev_team_ability.capability()
        if getattr(self, "standard_ability", None) is not None:
            base["standard_ability"] = self.standard_ability.capability()
        if getattr(self, "review_metrics_ability", None) is not None:
            base["review_metrics_ability"] = self.review_metrics_ability.capability()
        if getattr(self, "secretary_scale_ability", None) is not None:
            base["secretary_scale_ability"] = self.secretary_scale_ability.capability()
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
