# -*- coding: utf-8 -*-
"""
经理引擎（ManagerEngine · Issue #239）
======================================
把「架构·经理」从**只会声明分工的嘴**变成**真干活的手**。

## 病灶（用户原话 · Issue #239）

> 「会假装分工，实际上不激活其他 issue……只声明分工，相当于经理只原地当嘴，不及格。」
> 「只有一条路，计划都给他了，要求他推进度，他会纠结要不要按计划走……原地纠结要不要做。」
> 「他看起来不知道自己职责是什么。」

三个病根，对应三个必须用**代码判定的机制**（不是靠 LLM 自觉）：

| 病根 | 机制 | 落地 |
|------|------|------|
| ① 假装分工：只声明、不激活 | **ACTIVATE 闸门**：计划=命令，逐条建任务 Issue 并真实派发 | `activate()` |
| ② 原地纠结：给了计划还纠结做不做 | **EXECUTE 闸门**：计划即命令 / 有方案直接落，不产生"要不要做"的分支 | `decide()` + `resolve_choice()` |
| ③ 不知职责：原地打转 | **职责硬表**：不属于自己职责的动作一律拦截，指向正确角色 | `guard()` |

## 核心洞见

经理的病不是"不会规划"，而是**规划和执行之间没接线**——
`dispatch_engine.dispatch()` 早就存在（L1→L4），但经理节点被调用时只 `llm.call()` 出段
文字就返回，于是"列了个表"=「分工完成」。**嘴在规划，手没接上**。

本引擎把三件事变成确定性代码：

```
计划输入
  ↓ guard()       职责校验（不是经理的活 → 拦截并指出正确角色，不硬做）
  ↓ activate()    ACTIVATE 闸门：每条任务建 Issue + L1→L4 真实派发（不可跳过）
  ↓ 无人接单？     manager 自己把活干了（活不能掉地上 · solo_fallback）
  ↓ push()        督促进度：小组成员无人接单 → 自动调配小组长（1 次，防震）
  ↓ supervise()   监督结果：真干/假装/停滞/横跳 → 处置 dispositions + 升级
```

## 确定性保证

- `execute_plan()` 是**唯一入口**：给定计划必然走 ACTIVATE→PUSH→SUPERVISE，无"要不要做"分支；
- `decide()` / `resolve_choice()` 把"纠结"变成**纯函数查表**：单路计划 → 必然 EXECUTE；
- 每次动作写 `manager_actions` 留痕 + goal_meters 进度尺，可核验、可回放、不假装。

## 用法

```python
from manager import ManagerEngine
m = ManagerEngine(repo="dongdongxiaozu/dongjiagoushi", dry_run=True)
r = m.execute_plan(plan)          # 计划 → 激活 → 督促 → 监督，一站式
m.status()                        # 二级信息：谁真干了、谁还没接单
```
"""
import os
import re
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

# ------------------------------------------------------------
# ① 职责硬表（病根③：他不知道自己职责是什么）
# ------------------------------------------------------------
DUTIES = {
    "activate": "把计划拆成任务并在平台真建 Issue 派出去（不是写个表）",
    "dispatch": "任务分到具体角色（L1声明→L2分发→L3触发→L4开工）",
    "push": "督促进度：接单回执、开工证据、进度尺推进、停滞打断",
    "coordinate": "调配小组长/加派/拆任务，让活有承接人",
    "escalate": "升级：无人接单/二度停滞 → 上报总师、人类",
    "supervise": "监督结果：真干 / 假装 / 停滞 / 横跳，逐一给处置",
}

# 明确不属于经理的动作 → 归属角色（经理拦住，不硬做、不装作会做）
NOT_MANAGER = {
    "需求澄清": "架构·产品",
    "写代码": "架构·开发",
    "实现功能": "架构·开发",
    "修 bug": "架构·开发",
    "评审": "架构·评审",
    "走查": "架构·评审",
    "复评": "架构·评审",
    "跑测试": "架构·测试",
    "架构设计": "架构·总师",
    "定架构": "架构·总师",
    "合并": "架构·交付",
    "关闭 Issue": "架构·交付",
}

# 真实唤醒判据（progress 事件 / 平台评论两种载体）
_ACCEPT_EVENTS = ("accepted", "awake_ack")
_WORK_EVENTS = ("work_started", "delivered")
_FAKE_RECEIPT = "[接单]"          # 只有梗概、没有后续动作 = 假装
_STALL_ROUNDS = 2                 # 连续无进展轮数阈值 → 判停滞
_JUMP_ROUNDS = 3                  # 连续回退 delta 轮数阈值 → 判横跳


# ------------------------------------------------------------
# 计划归一化：把各种形状的计划文本/结构，统一成 assignment 清单
# ------------------------------------------------------------
_ROLE_KEYS = ("架构·", "市场·", "CodeBuddy")

_NUMBERED = re.compile(r'(?:^|[\s，,、。;；)\]])\s*(\d{1,2})\s*[\.、)）]\s*([^\n]+)')


def parse_plan(plan):
    """把计划（str / list / dict）解析为 assignment 清单。

    支持三种输入：
      1. str：编号列表、或者"每行一条"的计划文本；行内可带「角色: X」标注；
      2. list：每项是 str（转成项）或 dict（视为 assignment，补齐默认字段）；
      3. dict：取 items/tasks/list 字段，否则当成单条 assignment。

    这是**唯一的计划入口**：进来的东西一定变成可派发的清单——
    不做"要不要按计划走"的讨论，计划就是命令（病根②的正解）。
    """
    items = _coerce_items(plan)
    if not items:
        return []
    assignments = []
    for idx, raw in enumerate(items, start=1):
        assignments.append(_normalize_item(raw, idx))
    return assignments


def _coerce_items(plan):
    if plan is None:
        return []
    if isinstance(plan, dict):
        for key in ("assignments", "items", "tasks", "list", "plan"):
            if isinstance(plan.get(key), (list, tuple)):
                return list(plan[key])
        return [plan] if plan else []
    if isinstance(plan, (list, tuple)):
        return list(plan)
    text = str(plan)
    # ① 结构化编号：1. xxx / 2、xxx / 3) xxx
    numbered = _NUMBERED.findall(text)
    if len(numbered) >= 2:
        return [f"{num}. {body.strip()}" for num, body in numbered if body.strip()]
    # ② 否则按行切（跳过空行 / markdown 分隔）
    lines = [ln.strip(" \t-*·") for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not set(ln) <= set("-—=+| ")]
    if len(lines) > 1:
        return lines
    # ③ 单行：按顿号/分号切
    parts = [p.strip() for p in re.split(r'[；;]', text) if p.strip()]
    return parts or ([text] if text.strip() else [])


def _normalize_item(raw, idx):
    """单条计划项 → assignment（缺角色则按关键字推断，仍缺则落开发）。"""
    if isinstance(raw, dict):
        item = dict(raw)
        title = item.get("title") or item.get("task") or item.get("name") or f"任务{idx}"
        item.setdefault("task_key", item.get("key") or title)
        item.setdefault("title", title)
        item.setdefault("role", _infer_role(title))
        item.setdefault("domain", item.get("module") or "通用")
        item.setdefault("priority", item.get("priority") or "P1")
        item.setdefault("detail", item.get("detail") or title)
        return item
    text = str(raw).strip()
    text = re.sub(r'^\s*\d{1,2}\s*[\.、)）]\s*', '', text)
    # 行内「角色: 架构·评审」显式标注优先
    role = None
    m = re.search(r'角色\s*[:：]\s*([^\s，,；;、]+)', text)
    if m:
        role = m.group(1).strip()
    role = role or _infer_role(text)
    title = text[:120]
    return {
        "task_key": title,
        "title": title,
        "role": role,
        "domain": _infer_domain(text),
        "priority": "P1",
        "detail": text,
    }


def _infer_role(text):
    """按关键字推断承接角色（计划里写清角色时最准，没写就用语义兜底）。"""
    t = text or ""
    for key, role in (
        ("评审", "架构·评审"), ("走查", "架构·评审"), ("复评", "架构·评审"),
        ("测试", "架构·测试"), ("联调", "架构·测试"), ("验收", "架构·测试"),
        ("文档", "架构·开发"), ("实现", "架构·开发"), ("开发", "架构·开发"),
        ("代码", "架构·开发"), ("修复", "架构·开发"), ("重构", "架构·开发"),
        ("架构", "架构·总师"), ("方案", "架构·总师"), ("设计", "架构·总师"),
        ("需求", "架构·产品"), ("澄清", "架构·产品"),
        ("合并", "架构·交付"), ("交付", "架构·交付"), ("收尾", "架构·交付"),
        ("调研", "架构·找工具"), ("选型", "架构·找工具"),
        ("监控", "架构·监控哨兵"), ("进度", "架构·进度推手"),
    ):
        if key in t:
            return role
    return "架构·开发"


def _infer_domain(text):
    t = text or ""
    for key in ("登录", "结算", "报表", "搜索", "支付", "权限", "数据", "前端",
                "后端", "接口", "文档", "测试", "部署", "配置"):
        if key in t:
            return key
    return "通用"


# ------------------------------------------------------------
# ② 纠结消解（病根②：只有一条路还在纠结要不要走）
# ------------------------------------------------------------
def resolve_choice(options, context=""):
    """把「要不要做 / 走哪条路」变成**确定性查表**，不允许原地纠结。

    规则（不是建议，是判定）：
      - 无选项 → 返回 BLOCKED（没有路才该停，且要显式说要什么，不是纠结）；
      - 单选项 → 直接 EXECUTE（**只有一条路就没有"要不要"这个分支**）；
      - 多选项 → 按 context 显式指定则选之；否则选第一个非空项（计划优先）；
      - 任意情况都不会返回 "纠结/再想想/暂缓" —— 这些不是合法决策结果。
    """
    opts = [o for o in (options or []) if o not in (None, "")]
    if not opts:
        return {"decision": "BLOCKED", "choice": None,
                "reason": "没有任何可执行项——须显式补齐计划，不是纠结"}
    if len(opts) == 1:
        return {"decision": "EXECUTE", "choice": opts[0],
                "reason": "唯一路径，按计划直接执行（单路无抉择分支）"}
    if context:
        for o in opts:
            if str(context) in str(o) or str(o) in str(context):
                return {"decision": "EXECUTE", "choice": o,
                        "reason": "按上下文命中的路径执行"}
    return {"decision": "EXECUTE", "choice": opts[0],
            "reason": "多路径默认取首个（计划优先级），执行中可纠偏"}


class ManagerEngine:
    """经理引擎：把计划变成真派发、把进度盯到底、把假装的分工揪出来。"""

    name = "架构·经理"

    # 使用规则（供 AGENTS.md / 文档 / 角色人设引用，集中一处维护）
    RULES = {
        "职责边界": (
            "经理只做四件事：拆计划 → 真派发（建 Issue）→ 督促到有回执有进展 → "
            "监督并给处置。需求澄清/写代码/评审/测试/合并都不自己做，派给对应角色。"
        ),
        "计划即命令": (
            "拿到计划就执行，不存在『要不要按计划走』这个分支；"
            "只有一条路时更没有抉择——单路=直接干（resolve_choice 返回 EXECUTE）。"
        ),
        "激活判据": (
            "『列了表』不算分工。真激活 = 平台上建出可认领的 Issue + L1→L4 派发完成；"
            "建不出 Issue 一律标 blocked_no_issue，不得当作已分工。"
        ),
        "督促判据": (
            "督促看客观证据（[接单] 回执 / 开工事件 / 进度尺推进），"
            "无证据 → 再唤醒一次 → 仍无 → 调配小组长落实，活不掉地上。"
        ),
        "监督判据": (
            "回执了却没下文 = 假装（本轮核心病灶）；连续两轮距离不变 = 停滞；"
            "连续三轮回退 = 横跳。假装/停滞/横跳 一律处置，不放行。"
        ),
    }

    def __init__(self, repo="", owner="架构·经理", dry_run=None,
                 devs_per_team=2, simulate=None, transport=None):
        """
        repo:      仓库（org/repo），空则取 CNB_REPO 环境变量
        dry_run:   True=只走本地登记不碰平台（默认：无 repo 或非云端时自动 True）
        simulate:  测试/演练注入 —— {role: "accept"|"ignore"|"deliver"} 模拟对端真实行为
        transport: 平台传输层注入（离线可测），缺省用 cnb CLI
        """
        self.repo = repo or os.environ.get("CNB_REPO") or ""
        self.owner = owner
        self.devs_per_team = max(1, int(devs_per_team))
        self.simulate = simulate or {}
        self.transport = transport
        if dry_run is None:
            dry_run = not (self.repo and _cnb_available())
        self.dry_run = bool(dry_run)
        self.activated = []      # 已激活任务（task_id/issue/role/...）
        self.actions = []        # 本轮全部动作留痕（内存镜像，落库见 manager_actions）

    # ---------------- 留痕（不假装执行） ----------------
    def _log(self, kind, payload):
        """记一条经理动作：写库 manager_actions（尽力落 data/archives）+ 内存镜像。"""
        record = {"kind": kind, "payload": payload}
        self.actions.append(record)
        try:
            from data import admin, schema
            schema.init_schema()
            admin.record_event(self.owner, f"manager:{kind}", payload,
                               str(payload.get("task_id", "")) if isinstance(payload, dict) else "")
            admin.archive(
                f"manager_{kind}_{len(self.actions)}", f"manager_{kind}",
                f"{self.owner} · {kind}", payload, source=self.owner,
            )
        except Exception:  # noqa: BLE001 留痕失败不影响主流程，但绝不静默改判
            pass
        return record

    # ---------------- ③ 职责护栏 ----------------
    def guard(self, action):
        """职责校验：不属于经理的动作 → 拦截并指出正确承接角色。

        用户原话「他看起来不知道自己职责是什么」的正解：不是让他"记住"，
        而是让他**越界当场被拦**，并把活指向对的人。
        """
        text = str(action or "")
        for key, role in NOT_MANAGER.items():
            if key in text:
                res = {"allowed": False, "action": text, "hand_to": role,
                       "reason": f"「{key}」是 {role} 的活，不是经理的职责；"
                                 f"经理负责派给它并督促，不自己硬做"}
                self._log("guard", res)
                return res
        return {"allowed": True, "action": text, "hand_to": "", "reason": "在经理职责域内"}

    # ---------------- ① ACTIVATE 闸门：真激活 ----------------
    def activate(self, plan_or_assignments):
        """把计划真派出去：逐条建任务 Issue + L1→L4 四层分发。

        **这是硬闸门**：不接受"只声明"的返回。每条任务要么拿到 issue 编号，
        要么在结果里显式标 blocked_no_issue —— 不允许"列了个表就当完成"。
        """
        assignments = (plan_or_assignments
                       if isinstance(plan_or_assignments, list)
                       and plan_or_assignments
                       and isinstance(plan_or_assignments[0], dict)
                       and "task_key" in plan_or_assignments[0]
                       else parse_plan(plan_or_assignments))
        if not assignments:
            # 没有计划 → 唯一合法输出是显式要计划，不是原地纠结
            self._log("activate_refused", {"reason": "计划为空"})
            return {"activated": [], "count": 0, "refused": True,
                    "reason": "计划为空：须显式给出计划项，否则经理无事可派"}

        import dispatch_engine
        for idx, a in enumerate(assignments, start=1):
            a.setdefault("priority", "P1")
            a.setdefault("domain", "通用")
            a.setdefault("detail", a.get("title", ""))
            a["planned_index"] = idx

        # dry_run 时 enable_issue=False（不碰平台），真实模式才建 Issue
        result = dispatch_engine.dispatch(
            self.repo, assignments, enable_issue=not self.dry_run,
        )

        activated = []
        for a, l2 in zip(assignments, result["L2_dispatch"]):
            issue_no = l2.get("issue_number")
            rec = {
                "task_key": a["task_key"],
                "task_id": l2.get("task_id", ""),
                "agent_id": l2.get("agent_id", ""),
                "role": a["role"],
                "domain": a["domain"],
                "issue": issue_no,
                # 判据：真激活 = 平台上有可被对端认领的 issue；dry_run 显式标明未碰平台
                "platform_active": bool(issue_no) or self.dry_run,
                "dry_run": self.dry_run,
                "state": "activated",
            }
            if not rec["platform_active"]:
                rec["state"] = "blocked_no_issue"
                rec["blocked_reason"] = (
                    "计划项未在平台建出 Issue —— 对端 agent 无载体可认领，"
                    "等于没激活；须修平台通道后重试，不得当作已分工"
                )
            activated.append(rec)

        self.activated.extend(activated)
        payload = {
            "count": len(activated),
            "platform_activated": sum(1 for x in activated if x["platform_active"]),
            "blocked_no_issue": sum(1 for x in activated if x["state"] == "blocked_no_issue"),
            "dry_run": self.dry_run,
            "tasks": activated,
        }
        self._log("activate", payload)
        return {"activated": activated, **payload, "refused": False,
                "dispatch": result}

    # ---------------- ④ PUSH 督促：无人接单就调配小组长 ----------------
    def push(self, activated=None):
        """督促进度：逐条核真实回执 → 未接单的追一次 → 仍不接则交由小组长落实。

        用户原话「不激活其他 issue，这是他职责内的分工和督促进度」——
        督促的判据是**平台/库里有没有接单回执与开工证据**，不是"我问了他"。
        """
        activated = activated if activated is not None else self.activated
        if not activated:
            return {"pushed": 0, "awaiting": [], "delegated": []}

        import dispatch_engine
        verify = dispatch_engine.dispatch_verify(activated)
        receipts = {d["task_id"]: d["receipt"] for d in verify["detail"]}

        accepted, awaiting, delegated = [], [], []
        for rec in activated:
            if receipts.get(rec["task_id"]):
                rec["state"] = "accepted"
                accepted.append(rec)
                continue
            # 演练/测试：模拟对端真实回执，让链路可离线验证
            if self._simulated_accept(rec):
                accepted.append(rec)
                rec["state"] = "accepted"
                continue
            # ② 真实唤醒一次（投接力卡），仍无回执 → 交小组长落实
            awake = self._reawake(rec)
            rec["reawake"] = awake
            plan = self.delegate_to_lead(rec)
            rec["state"] = "delegated_to_lead"
            rec["leader_plan"] = plan
            awaiting.append(rec)
            delegated.append({"task_key": rec["task_key"], "role": rec["role"],
                              "leader_plan": plan})

        payload = {
            "pushed": len(activated),
            "accepted": len(accepted),
            "awaiting": [x["task_key"] for x in awaiting],
            "delegated": delegated,
            "verified_all_awake": verify["verified_all_awake"],
        }
        self._log("push", payload)
        return {"pushed": len(activated), "accepted": accepted,
                "awaiting": awaiting, "delegated": delegated,
                "verification": verify, "verified_all_awake": verify["verified_all_awake"]}

    def _reawake(self, rec):
        """再唤醒一次（投 [触发:角色] 接力卡）——不静默，留痕。"""
        try:
            import dispatch_engine
            msg = dispatch_engine.dispatch_trigger(
                [{"task_key": rec["task_key"], "task_id": rec["task_id"],
                  "agent_id": rec["agent_id"], "role": rec["role"],
                  "title": rec["task_key"], "issue_number": rec["issue"]}],
                from_agent=self.owner,
            )
            return {"sent": True, "msg_id": msg[0].get("msg_id", "") if msg else ""}
        except Exception as e:  # noqa: BLE001 唤醒失败显式暴露
            return {"sent": False, "error": f"{type(e).__name__}: {e}"}

    def _simulated_accept(self, rec):
        """演练：按 simulate 配置让对端"真实回执"，用于离线验证整条链路。"""
        mode = self.simulate.get(rec["role"], self.simulate.get("*"))
        if mode != "accept":
            return False
        try:
            import dispatch_engine
            dispatch_engine.accept_assignment(
                rec["task_key"], rec["agent_id"], role=rec["role"],
                note="[接单] （演练回执）已接手")
            return True
        except Exception:  # noqa: BLE001
            return False

    def delegate_to_lead(self, rec, lead_role="架构·小组长"):
        """无人接单 → 调配小组长：把这条任务交给小组长带去落实开发。

        返回可执行的小组安排（小组长据此开工，不是又一张"分工表"）：
          - 组内多少开发、目标量、首轮要做什么、验收口径谁定。
        """
        plan = {
            "lead_role": lead_role,
            "task_key": rec["task_key"],
            "task_id": rec["task_id"],
            "issue": rec["issue"],
            "devs_per_team": self.devs_per_team,
            "goal_total": 1.0,
            "first_action": f"认领任务「{rec['task_key']}」→ 组内 {self.devs_per_team} 个开发开工",
            "acceptance": "客观验证器（测试/lint）判定，非自判完成",
            "why": "该任务派发后未获 [接单] 回执 —— 由小组长承接落实，不把活掉在地上",
        }
        self._log("delegate_to_lead", plan)
        return plan

    # ---------------- ⑤ SUPERVISE 监督：揪出假装 ----------------
    def supervise(self, activated=None, plan=None):
        """监督每个任务有没有真在推进，逐条给处置。

        判据（全部客观可查，不靠经理"感觉"）：
          - 有回执无动作、或只有 [接单] 梗概 → **fake**（假装分工，本轮核心病灶）
          - 连续 _STALL_ROUNDS 轮 distance 不变 → **stall**（停滞）
          - 连续 _JUMP_ROUNDS 轮 delta 为负 → **jump**（横跳）
          - 有回执 + 有开工/交付证据 → **real**
        处置：fake/awaiting → 调配小组长；stall/jump → 哨兵打断；二度 → 升级。
        """
        activated = activated if activated is not None else self.activated
        plan = plan or _plan_guess(activated)
        verdicts = []
        for rec in activated:
            v = self._verdict(rec, plan)
            verdicts.append(v)
            self._apply_disposition(v)
        summary = {
            "total": len(verdicts),
            "real": sum(1 for v in verdicts if v["verdict"] == "real"),
            "fake": sum(1 for v in verdicts if v["verdict"] == "fake"),
            "awaiting": sum(1 for v in verdicts if v["verdict"] == "awaiting"),
            "stall": sum(1 for v in verdicts if v["verdict"] == "stall"),
            "jump": sum(1 for v in verdicts if v["verdict"] == "jump"),
        }
        summary["ok"] = summary["real"] == summary["total"] and summary["total"] > 0
        payload = {"summary": summary, "verdicts": verdicts}
        self._log("supervise", payload)
        return {"verdicts": verdicts, "summary": summary,
                "note": ("全部任务真实推进" if summary["ok"] else
                         "存在未真实推进的任务——已按处置协议处理，不得当作分工完成")}

    def _verdict(self, rec, plan):
        task_id = rec.get("task_id", "")
        events, meters = _task_activity(task_id)
        has_receipt = any(e in _ACCEPT_EVENTS for e in events)
        has_work = any(e in _WORK_EVENTS for e in events)

        base = {"task_key": rec["task_key"], "task_id": task_id,
                "role": rec["role"], "issue": rec.get("issue"),
                "events": sorted(set(events)), "meter_rounds": len(meters)}

        # 停滞 / 横跳（量化距离说话）
        stall, jump = _judge_series(meters)
        if has_work and stall:
            return {**base, "verdict": "stall", "disposition": "interrupt",
                    "reason": f"连续 {_STALL_ROUNDS}+ 轮到目标距离不变"}
        if has_work and jump:
            return {**base, "verdict": "jump", "disposition": "interrupt",
                    "reason": f"连续 {_JUMP_ROUNDS}+ 轮进度回退（横跳不收敛）"}
        if has_work:
            return {**base, "verdict": "real", "disposition": "keep",
                    "reason": "有接单回执 + 开工/交付证据，真在推进"}
        if has_receipt:
            # 最典型的假装：回了 [接单] 就没下文
            return {**base, "verdict": "fake", "disposition": "hand_to_lead",
                    "reason": "回执了 [接单] 但无开工证据、无进度尺推进 —— 假装分工"}
        return {**base, "verdict": "awaiting", "disposition": "hand_to_lead",
                "reason": "无接单回执、无开工证据 —— 派发未落地"}

    def _apply_disposition(self, v):
        """按判定落地处置（调配小组长 / 哨兵打断 / 升级），全部留痕。"""
        if v["disposition"] == "keep":
            return
        if v["disposition"] == "hand_to_lead":
            v["leader_plan"] = self.delegate_to_lead({
                "task_key": v["task_key"], "task_id": v["task_id"],
                "issue": v["issue"], "role": v["role"]})
            return
        # interrupt：交哨兵按协议打断/重规划（1 级），二度命中由哨兵升级（2 级）
        try:
            import sentinel.engine as sentinel
            meter_id = f"gm-{v['task_id']}"
            sentinel.interrupt(meter_id, v["task_id"], v["role"],
                               v["verdict"], {"reason": v["reason"]})
            v["sentinel"] = "interrupted"
        except Exception as e:  # noqa: BLE001 打断失败显式暴露
            v["sentinel"] = f"error: {type(e).__name__}"

    # ---------------- 一站式：计划 → 激活 → 督促 → 监督 ----------------
    def execute_plan(self, plan, push=True, supervise=True):
        """**唯一执行入口**：计划进来必然走到「激活 + 督促 + 监督」。

        不存在"要不要按计划走"这个分支——给了计划就走，这是病根②的正解。

        ⚠️ 职责校验的位置很关键：**计划里的任务本来就是要派给别人的**，
        不能因为计划提到"评审/测试/写代码"就整体拒绝（那是把派活当越界）。
        越界校验针对的是**经理自己要执行的单个动作**（`guard()` 直接调用），
        计划进入本入口即视为"派发意图"，一律走激活。
        """
        guard = {"allowed": True, "action": "派发计划", "hand_to": "",
                 "reason": "计划进入执行入口即视为派发意图：经理负责派出去并督促"}

        # 1. ACTIVATE（硬闸门）
        act = self.activate(plan)
        if act.get("refused"):
            return {"refused": True, "guard": guard, **act}
        activated = act["activated"]

        # 2. PUSH（无人接单 → 调配小组长）
        pushed = self.push(activated) if push else None

        # 3. SUPERVISE（假装分工现形）
        supervised = self.supervise(activated) if supervise else None

        return {
            "refused": False,
            "guard": guard,
            "activated": activated,
            "count": act["count"],
            "platform_activated": act["platform_activated"],
            "blocked_no_issue": act["blocked_no_issue"],
            "push": pushed,
            "supervise": supervised,
            "summary": _digest(act, pushed, supervised),
        }

    # ---------------- 能力声明 ----------------
    def capability(self):
        """返回引擎能力声明（供角色/文档/测试统一引用）。"""
        return {
            "name": "ManagerEngine",
            "role": self.owner,
            "duties": DUTIES,
            "not_manager": NOT_MANAGER,
            "entry": ["execute_plan", "activate", "push", "supervise",
                      "status", "guard", "delegate_to_lead"],
            "decisions": {"single_path": "EXECUTE", "multi_path": "EXECUTE",
                          "empty": "BLOCKED"},
            "rules": self.RULES,
        }

    # ---------------- 二级信息 ----------------
    def status(self):
        """经理视角俯瞰：哪些任务真干了、哪些还停在嘴上（供人类/总师看）。"""
        sup = self.supervise(self.activated) if self.activated else None
        return {
            "role": self.owner,
            "repo": self.repo,
            "dry_run": self.dry_run,
            "duties": DUTIES,
            "activated": len(self.activated),
            "supervise": sup["summary"] if sup else None,
            "actions": [a["kind"] for a in self.actions],
            "verdicts": sup["verdicts"] if sup else [],
        }


# ------------------------------------------------------------
# 内部工具
# ------------------------------------------------------------
def _cnb_available():
    """平台通道是否可用（可用才允许真实建 Issue）。"""
    from shutil import which
    return bool(which("cnb"))


def _task_activity(task_id):
    """取某任务的 progress 事件 + goal_meters 序列（客观判据来源）。"""
    if not task_id:
        return [], []
    events, meters = [], []
    try:
        from data import db
        for row in db.query(
                "SELECT event FROM progress WHERE task_id=? ORDER BY id", (task_id,)):
            events.append(row["event"] if not isinstance(row, tuple) else row[0])
    except Exception:  # noqa: BLE001
        pass
    try:
        from sentinel import store
        # 跨 agent 汇总该任务的全部刻度（经理不该只盯某一个 agent 的尺）；
        # 兼容 dev_team 用的 gm-<team> 与 dispatch 用的 g-<task> 两种 meter 前缀。
        meters = list(store.meters_for_task(task_id) or [])
        for mid in (f"gm-{task_id}", f"g-{task_id}"):
            for m in store.meter_series(mid) or []:
                if m not in meters:
                    meters.append(m)
        meters.sort(key=lambda m: m.get("id") or 0)
    except Exception:  # noqa: BLE001 读不到刻度不臆断，交给上层判 awaiting
        meters = []
    return events, meters


def _judge_series(meters):
    """从 progress 尺序列判（停滞, 横跳）。完全确定性：同输入同输出。

    - 停滞：最近 _STALL_ROUNDS 轮 distance 完全不变（没动）；
    - 横跳：最近 _JUMP_ROUNDS 轮**净进展 <= 0**——来回打转、距离没净缩小
      （如 1→2→1、当前值涨落但 distance 不降）；单调推进（净进展为负）绝不误伤。
    """
    if len(meters) < 2:
        return False, False
    dists = [m.get("distance") for m in meters
             if isinstance(m, dict) and m.get("distance") is not None]
    deltas = [m.get("delta") or 0 for m in meters if isinstance(m, dict)]
    stall = len(dists) >= _STALL_ROUNDS and len(set(dists[-_STALL_ROUNDS:])) == 1
    tail = deltas[-_JUMP_ROUNDS:]
    # delta 是"距离变化"：<0 在靠近，>0 在远离。一段窗口净进展<=0 = 没在收敛。
    net_progress = sum(tail)
    jump = len(tail) >= _JUMP_ROUNDS and net_progress >= 0
    return stall, jump


def _plan_guess(activated):
    """给监督提供一个计划快照（不依赖外部传入，保证 supervise 可独立调用）。"""
    return {"tasks": [{"task_key": r["task_key"], "role": r["role"]}
                      for r in (activated or [])]}


def _digest(act, pushed, supervised):
    """一句话结论（先给结论再给依据）。"""
    parts = [f"激活 {act['platform_activated']}/{act['count']} 条任务"]
    if act["blocked_no_issue"]:
        parts.append(f"{act['blocked_no_issue']} 条未拿到 Issue（等于没激活）")
    if pushed:
        parts.append(f"真实接单 {len(pushed['accepted'])} 条，"
                     f"转小组长落实 {len(pushed['delegated'])} 条")
    if supervised:
        s = supervised["summary"]
        parts.append(f"监督：真干 {s['real']} / 假装 {s['fake']} / 待接单 {s['awaiting']}"
                     f" / 停滞 {s['stall']} / 横跳 {s['jump']}")
        parts.append("结论：" + ("分工真落地了" if s["ok"] else
                                 "有活停在嘴上，已转小组长+哨兵处置"))
    return "；".join(parts)
