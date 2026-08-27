# -*- coding: utf-8 -*-
"""
标签管理能力（LabelAbility · 全员通用能力 · Issue #51）
=========================================================
把「标签管理 + 程序化进度获取（MCP 管线）」封装为**可复用的通用能力模块**，
默认挂载到所有角色基类 BaseRole，每个 agent 都能：
  - 查询任何实体进度/状态/标签（走数据库，程序化，不靠 AI 对话告知）；
  - 一线角色直接打标/刷进度（最常见，无需绕道他人）；
  - 全员可提议「为某 Issue 加标签/改标签」，由标签管理员（数据管理员）审批。

能力维度（双角色合一）：
  ╔═ 查询（MCP 管线 · 全员开放）═══════════════════════════════╗
  ║ query_progress(task)   程序化查进度（goal_meters+progress 合并） ║
  ║ query_status(entity)   程序化查状态标签                          ║
  ║ query_labels(entity)   查实体全部标签                           ║
  ╚══════════════════════════════════════════════════════════════╝
  ╔═ 打标（一线直接 · 白名单角色）═════════════════════════════════╗
  ║ apply_label(entity,key)   直接打标/刷值                        ║
  ║ auto_trigger(event,...)   事件驱动自动打标（AutoLabelEngine）    ║
  ╚══════════════════════════════════════════════════════════════╝
  ╔═ 提议（全员 · 管理员审批）═════════════════════════════════════╗
  ║ propose_label(entity,key,reason)   提议加/改标签                ║
  ║ review_request(...)               （标签管理员）审批            ║
  ╚══════════════════════════════════════════════════════════════╝

规范标签集（LABEL_SPECS · 唯一规范来源，非规范即 INVALID_LABEL 拦截）：
  progress    : blocked / in_progress / review / done / merged
  type        : feature / bug / refactor / docs / infra / research
  priority    : p0..p9（P0-P9 大盘：p0 最紧急 → p9 最不紧急，正交维度）★扩展
  status      : open / stale / verified / invalid
  disposition : merge_ready / need_fix / need_review / need_human
  deps        : depends_on（前置依赖 Issue 编号，value 存编号）★新增
  next        : next_step（完成后下一步触发 Issue 编号，value 存编号）★新增
  pipeline    : pipeline 自动化关键节点标签（at_node / trigger_next / gate）★新增
  progress_pct: 0%..100%（人可读进度百分比，机器判定仍用哨兵 distance）

解耦调用（★用户强调）：LabelAbility 是**通用模块能力**，由所有角色基类 BaseRole
统一挂载，各角色**无需各自声明用法**，直接调用 role.apply_label/query_progress 等。
单一规范来源在 LABEL_SPECS，各角色/迭代都从这里对齐，不产生版本差异。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class LabelAbility:
    """标签管理 + 程序化进度查询全员能力。

    通过 owner 绑定所属 agent（角色名/实例），打标/提议时留痕归因到该 agent。
    """

    # ---- 规范标签集（唯一规范来源，防乱标）----
    # P0-P9 大盘：p0 最紧急 → p9 最不紧急（正交维度，不与规模/拓扑耦合）
    PRIORITY_SCALE = [f"p{i}" for i in range(10)]
    # 流水线自动化关键节点标签（供 DAG/编排引擎快速读取调度位）
    PIPELINE_NODE_LABELS = ["at_node", "trigger_next", "gate"]

    LABEL_SPECS = {
        "progress": ["blocked", "in_progress", "review", "done", "merged"],
        "type": ["feature", "bug", "refactor", "docs", "infra", "research"],
        "priority": PRIORITY_SCALE,                      # P0-P9 大盘
        "status": ["open", "stale", "verified", "invalid"],
        "disposition": ["merge_ready", "need_fix", "need_review", "need_human"],
        # 前置依赖（depends_on）→ value 存前置 Issue 编号
        "deps": ["depends_on"],
        # 完成后下一步触发（next_step）→ value 存下一步 Issue 编号
        "next": ["next_step"],
        # 流水线自动化关键节点
        "pipeline": PIPELINE_NODE_LABELS,
        "progress_pct": ["0", "5", "10", "15", "20", "25", "30", "35", "40",
                         "45", "50", "55", "60", "65", "70", "75", "80",
                         "85", "90", "95", "100"],
    }
    VALID_LABELS = {lb for group in LABEL_SPECS.values() for lb in group}

    # ---- 一线可直接打标（白名单，其余角色只能提议）----
    DIRECT_OPERATORS = {
        "架构·开发", "架构·评审", "架构·测试", "架构·经理", "架构·总师",
        "架构·产品", "架构·秘书", "架构·数据管理员", "架构·小组长",
        "架构·进度推手", "CodeBuddy", "系统", "data_admin",
    }

    RULES = {
        "查询": "程序化优先——任何角色查进度/状态/标签走 query_* 接口（数据库/MCP 管线），"
                "不依赖 AI 对话告知，也不自造口径。",
        "直接打标": "一线角色（开发/评审/测试/经理/总师/产品/秘书/数据管理员/小组长/进度推手）"
                    "可直接 apply_label；非白名单角色走 propose_label 提议→管理员审批。",
        "提议审批": "全员可 propose_label（为某 Issue 加/改标签/提需求），"
                    "由标签管理员（数据管理员）review_request 审批，approved 自动落标。",
        "规范标签": "标签必须来自 LABEL_SPECS 规范集合，非规范即 INVALID_LABEL 拦截；"
                    "progress_pct 由进度推手/事件引擎自动折算，人可读层，机器判定仍用哨兵 distance。",
        "一线会操作": "一线处理代码的 agent 最知道进度，必须会调 apply_label/auto_trigger 及时刷新标签。",
        "评审打标签替代推送": "评审结论不靠推送消息表达，统一走打标签：review.pass→merge_ready、"
                          "review.merge→merged、review.need_fix→need_fix+blocked，AutoLabelEngine 事件自动落标。",
        "跨仓CodeBuddy打标签替代推送": "非本仓库的 CodeBuddy（跨仓被召唤）的评审/反馈结论也一律打标签替代推送——"
                          "CodeBuddy 在白名单可直接 apply_label，落地到本仓 labels 表即留痕，不靠推送跨仓传结论。",
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

    # ---- 数据访问（惰性导入 data 层，增强可移植性）----
    def _repo(self):
        from data import repository as repo
        return repo

    # ---- MCP 管线：程序化查询（全员开放）----
    def query_progress(self, task_id, agent_id=""):
        """程序化查进度（goal_meters + progress 合并），不靠 AI 对话。"""
        return self._repo().query_progress(task_id, agent_id=agent_id)

    def query_status(self, entity):
        """程序化查实体状态标签 + 全部标签。"""
        return self._repo().query_status(entity)

    def query_labels(self, entity):
        """查实体全部标签。"""
        return self._repo().get_labels(entity)

    # ---- 直接打标（一线白名单角色）----
    def apply_label(self, entity, label_key, value="", action="apply", note=""):
        """一线直接打标/去标/刷值。非白名单角色越权即拦截。"""
        if not self._check_permission():
            return {"ok": False, "error": "NO_PERMISSION",
                    "operator": self._owner_name,
                    "label_key": label_key,
                    "entity": entity,
                    "hint": "非一线白名单角色只能走 propose_label 提议，由标签管理员审批"}
        if label_key not in self.VALID_LABELS:
            return {"ok": False, "error": "INVALID_LABEL",
                    "label_key": label_key,
                    "valid": sorted(self.VALID_LABELS)}
        label_id = self._repo().apply_label(
            entity, label_key, operator=self._owner_name, value=value,
            action=action, source="direct", note=note)
        return {"ok": True, "label_id": label_id, "entity": entity,
                "label_key": label_key, "action": action, "operator": self._owner_name}

    def remove_label(self, entity, label_key, note=""):
        """一线直接去标。"""
        return self.apply_label(entity, label_key, action="remove", note=note)

    # ---- 全员提议 + 管理员审批 ----
    def propose_label(self, entity, label_key, reason="", value=""):
        """全员提议：为某实体加/改标签，进入审批队列。"""
        if label_key not in self.VALID_LABELS:
            return {"ok": False, "error": "INVALID_LABEL",
                    "label_key": label_key,
                    "valid": sorted(self.VALID_LABELS)}
        request_id = self._repo().propose_label(
            entity, label_key, self._owner_name, reason=reason, value=value)
        return {"ok": True, "request_id": request_id, "entity": entity,
                "label_key": label_key, "proposer": self._owner_name,
                "status": "pending"}

    def review_request(self, request_id, decision="approved", note=""):
        """标签管理员审批提议（approved→自动落标）。"""
        return self._repo().review_label_request(
            request_id, self._owner_name, decision=decision, note=note)

    def pending_requests(self):
        """查看待审批标签提议。"""
        return self._repo().list_label_requests(status="pending")

    # ---- 结构化标签（前置依赖 / 下一步触发 / 优先级 P0-P9 / 流水线节点）----
    def set_depends(self, entity, issue_no, note=""):
        """打「前置依赖」标签：depends_on，value 存前置 Issue 编号。"""
        return self.apply_label(entity, "depends_on", value=str(issue_no),
                                note=note or "前置依赖")

    def set_next_step(self, entity, issue_no, note=""):
        """打「完成后下一步触发」标签：next_step，value 存下一步 Issue 编号。"""
        return self.apply_label(entity, "next_step", value=str(issue_no),
                                note=note or "完成后下一步触发")

    def set_priority(self, entity, p_level, note=""):
        """打优先级标签：p0..p9（P0-P9 大盘，p0 最紧急→p9 最不紧急，正交维度）。"""
        if p_level not in self.PRIORITY_SCALE:
            return {"ok": False, "error": "INVALID_PRIORITY", "priority": p_level,
                    "valid": self.PRIORITY_SCALE}
        return self.apply_label(entity, p_level, note=note or "P0-P9 优先级大盘")

    def set_pipeline_node(self, entity, node, value="", note=""):
        """打流水线自动化关键节点标签（at_node / trigger_next / gate）。"""
        if node not in self.PIPELINE_NODE_LABELS:
            return {"ok": False, "error": "INVALID_PIPELINE_NODE", "node": node,
                    "valid": self.PIPELINE_NODE_LABELS}
        return self.apply_label(entity, node, value=value,
                                note=note or "流水线关键节点")

    def dependencies(self, entity):
        """查某实体的前置依赖（depends_on 标签列表）。"""
        labels = self._repo().list_labels(label_key="depends_on", entity=entity)
        return [l["value"] for l in labels if l.get("action", "apply") != "remove"]

    def next_steps(self, entity):
        """查某实体的完成后下一步触发（next_step 标签列表）。"""
        labels = self._repo().list_labels(label_key="next_step", entity=entity)
        return [l["value"] for l in labels if l.get("action", "apply") != "remove"]

    # ---- 事件驱动自动打标（AutoLabelEngine 透传）----
    def auto_trigger(self, event, entity, goal_total=None, current=None,
                     note="", value=""):
        """事件驱动自动打标：事件到达即按规则打标，无需 agent 记得去调。

        value 携带事件值（priority.set → p0..p9 / next.trigger → 下一步 issue 编号）。
        """
        from label.auto import AutoLabelEngine
        return AutoLabelEngine(owner=self).trigger(
            event=event, entity=entity, goal_total=goal_total,
            current=current, note=note, value=value)

    # ---- 权限判定 ----
    def _check_permission(self):
        return self._owner_name in self.DIRECT_OPERATORS

    def capability(self):
        """返回能力声明（含使用规则）。"""
        return {
            "name": "LabelAbility",
            "desc": "标签管理 + 程序化进度/状态/标签查询（MCP 管线）+ 事件驱动自动打标",
            "methods": ["query_progress", "query_status", "query_labels",
                        "apply_label", "remove_label", "propose_label",
                        "review_request", "auto_trigger",
                        "set_depends", "set_next_step", "set_priority",
                        "set_pipeline_node", "dependencies", "next_steps"],
            "priority_scale": self.PRIORITY_SCALE,
            "pipeline_nodes": self.PIPELINE_NODE_LABELS,
            "direct_operators": sorted(self.DIRECT_OPERATORS),
            "rules": self.RULES,
        }
