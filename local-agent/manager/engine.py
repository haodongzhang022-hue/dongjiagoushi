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

## 二轮升级（Issue #239 用户二轮评论）：承上启下，不是刚性传达

用户二轮原话：

> 「经理应该做的是承上启下……经理是找进度 找通路，安排和看反馈，
>   寻找能行得通的方式安排下去后看看效果反馈，进一步调整，
>   不够还能调整人员，跨部门找角色过来帮忙都行。」

也就是说：**如果经理只是把上级计划程序化地分槽投卡，这个岗位就不需要存在**。
所以本引擎在「激活/督促/监督」之外，补上两块：

- `manager/lanes.py` —— **找通路**：多通路穷举（平台 Issue / 完整 @ 接力 / @CodeBuddy /
  直接 handle / 调配小组长 / 自己兜底）+ 可核验就绪 + **权责内自决**；
- `manager/flow.py`  —— **承上启下**：承上（复述北极星/翻译/裁不可执行项）→
  行下（派发+换路线）→ 启下（调人员/跨岗借角色）→ 反馈（多轮，直到收敛或显式上交）。

判定口径不变：**成功标准** = 对端有 `[接单]` 回执 + 有开工/进度证据；
达不到就换路线，不是"申请授权"也不是"做不了"。

## 用法

```python
from manager import ManagerEngine
m = ManagerEngine(repo="dongdongxiaozu/dongjiagoushi", dry_run=True)
m.carry(plan)                     # 承上启下四段全跑（首选，Issue #239 二轮）
r = m.execute_plan(plan)          # 计划 → 激活 → 督促 → 监督，一站式
m.try_lanes("架构·开发", handlers) # 找通路：一条断了换下一条
m.authorize("调配小组长")          # 权责内自决判定（SELF / HUMAN）
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
MAX_FLOW_ROUNDS = 4               # 承上启下默认调整轮数（超限显式上交，不静默）
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
    m = re.search(r'角色\s*[:：]\s*([^\s，,；;、）)]+)', text)
    if m:
        role = _clean_role(m.group(1))
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


def _clean_role(role):
    """规范化角色名：去引号/括号/尾随标点，保留「架构·X」形态。"""
    r = str(role or "").strip().strip("`'\"（）()[]【】")
    r = re.sub(r'[，,；;、。.]+$', '', r).strip()
    return r


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
                 devs_per_team=2, simulate=None, transport=None, workers=None,
                 max_rounds=None):
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
        # 承接方注册表：给了 workers 就**真驱动对方上工**（不再只投卡等回执）；
        # simulate 只是演练，二者互斥使用（有 workers 时忽略 simulate）。
        self.workers = workers
        self.max_rounds = max_rounds
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
            # ①b 有承接方 → **真驱动它上工**（回执 + 开工 + 推进），拿到真凭据再判
            drift = self.drive_worker(rec)
            if drift.get("driven"):
                rec["drive"] = drift
                from .work import is_ready
                if is_ready(drift.get("credential")):
                    accepted.append(rec)
                    rec["state"] = "accepted"
                    continue
            # 演练/测试：模拟对端回执（**simulated 级，不算干活**，仅让链路可离线跑）
            if self._simulated_accept(rec):
                rec["state"] = "simulated_ack"
                awaiting.append(rec)
                continue
            # ② 真实唤醒一次（投接力卡）；唤醒本身失败 → 立刻换下一条通路（不空等）
            awake = self._reawake(rec)
            rec["reawake"] = awake
            if not awake.get("sent"):
                rec["lane_fallback"] = self._fallback_lane(rec)
            # ③ 仍无回执 → 交小组长落实（活不掉地上）
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

    def _fallback_lane(self, rec):
        """再唤醒发不出去 → **换下一条通路**（不把"我认为应该能"当已试过）。

        用户原话「没成功尝试其他路线，而不是默认就没能力做，相当于挤牙膏」——
        一条通路在发送层就失败时，经理必须自己往下一跳：完整 @ 格式 → @CodeBuddy
        → 直接 handle 召唤。逐条留痕，全断才算真做不到。
        """
        tried = [{"lane": "fullpath", "ok": None, "note": "唤醒失败后的下一跳"}]
        target = rec.get("role", "")
        lanes = [("fullpath", f"@{self.owner}({target})"),
                 ("codebuddy", "@CodeBuddy"),
                 ("direct_handle", target)]
        out = {"target": target, "candidates": [], "tried": tried}
        for lane, handle in lanes:
            try:
                from .lanes import readiness
                ready = readiness(lane, repo=self.repo, cnb=not self.dry_run,
                                  handle=handle)
            except Exception:  # noqa: BLE001 探测失败显式降级为未就绪
                ready = {"ready": False, "missing": ["探测异常"]}
            out["candidates"].append({"lane": lane, "handle": handle,
                                      "ready": ready["ready"],
                                      "missing": ready.get("missing", [])})
        out["next_lane"] = next((c["lane"] for c in out["candidates"] if c["ready"]), "")
        self._log("lane_fallback", out)
        return out

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
        """演练：按 simulate 配置让对端"回执"，**但不算干活**。

        四轮修正：`simulate` 的产出是 `simulated` 级证据，`supervise()` 不认它。
        它只是让「无人接单 → 调人 → 上工」的升级链路能离线跑通，**不是分工完成**。
        """
        mode = self.simulate.get(rec["role"], self.simulate.get("*"))
        if mode != "accept":
            return False
        try:
            import dispatch_engine
            dispatch_engine.accept_assignment(
                rec["task_key"], rec["agent_id"], role=rec["role"],
                note="[接单] （演练回执，不算干活）")
            return True
        except Exception:  # noqa: BLE001
            return False

    # ---------------- 承接方：真驱动对方上工（不是只投卡） ----------------
    def _worker(self, role):
        """取该角色可真正干活的承接方（注册表里没有 → None，如实暴露）。"""
        if callable(getattr(self.workers, "get", None)):
            return self.workers.get(role)
        return (self.workers or {}).get(role) if isinstance(self.workers, dict) else None

    def drive_worker(self, rec, rounds=1):
        """真驱动承接方干活：accept → [start → progress → deliver] × rounds。

        返回 {"driven", "did", "credential", "note"}。**没有承接方**时诚实返回
        driven=False（经理据此去调人/换通路，而不是假装推进了）。
        """
        worker = self._worker(rec.get("role"))
        if worker is None:
            out = {"driven": False, "did": [],
                   "note": f"未注册可干活的承接方（{rec.get('role')}）→ 须换通路或调人"}
            self._log("drive_worker", {**out, "task_key": rec.get("task_key")})
            return out
        task_key, task_id = rec.get("task_key", ""), rec.get("task_id", "")
        kwargs = {"task_id": task_id}
        did = []
        try:
            if callable(getattr(worker, "accept", None)):
                worker.accept(task_key, **kwargs)
                did.append("accepted")
            for i in range(max(1, int(rounds))):
                run_round = getattr(worker, "run_round", None)
                if callable(run_round):
                    r = run_round(task_key, task_id=task_id, round_no=i + 1) or {}
                    did.extend(r.get("did") or [])
                else:
                    if callable(getattr(worker, "start", None)):
                        worker.start(task_key, **kwargs)
                        did.append("started")
                    if callable(getattr(worker, "progress", None)):
                        worker.progress(task_key, **kwargs)
                        did.append("progressed")
            driven = True
        except Exception as e:  # noqa: BLE001 驱动失败显式暴露，不静默当做过
            driven = False
            did.append(f"error:{type(e).__name__}")
        from .work import credential_of
        cred = credential_of(task_id)
        out = {"driven": driven, "did": did, "credential": cred,
               "note": "真驱动承接方上工" if driven else "驱动失败"}
        self._log("drive_worker", {**out, "task_key": task_key,
                                   "role": rec.get("role")})
        return out

    def delegate_to_lead(self, rec, lead_role="架构·小组长", drive=True):
        """无人接单 → 调配小组长：**真开组干活**，不是生成一张安排表。

        四轮修正的关键一处：上一版此处只返回一个 `leader_plan` 字典，小组长引擎
        （LeadEngine）从未被调用——于是"交给小组长"实际等于"换了个承接主体，
        活照样停在原地"。现在 `drive=True` 时直接驱动 `LeadEngine`：
        派开发 → 跑确定性闭环（客观验证）→ 整合交付 / 超限上报。

        返回可执行的组安排 + `drive` 结果（`status` = delivered/continue/escalated）。
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
        if drive:
            plan["drive"] = self._drive_lead(rec)
        self._log("delegate_to_lead", plan)
        return plan

    def _drive_lead(self, rec):
        """真驱动小组长：派开发 → 跑闭环 → 收口。无承接方则只编排（诚实标注）。"""
        try:
            from .lead_engine import LeadEngine
            lead = LeadEngine(devs_per_team=self.devs_per_team, owner="架构·小组长")
            p = lead.dispatch_devs({
                "task_key": rec["task_key"], "goal_total": 1.0,
                "issue": rec.get("issue"),
                "title": rec.get("task_key"),
            })
            outputs = None
            # 组内每个开发都要有**客观验证结果**才放行；经理不替验证器下结论，
            # 有承接方就让它真跑，没有就如实把这一步标为待验证（不默认通过）。
            if self._worker("架构·开发") is not None:
                outputs = []
                for d in p["devs"]:
                    sub = {**rec, "task_key": d["task_key"],
                           "task_id": d.get("agent_id") or d["task_key"]}
                    r = self.drive_worker(sub)
                    # dev_id 必须用组引擎的键（dev0/dev1…），不能拿任务键代填
                    outputs.append((d["dev_id"], bool(r.get("driven")),
                                    f"承接方执行 evidence={r.get('did')}"))
            rd = lead.run_round(p, dev_outputs=outputs)
            agg = lead.aggregate(p, rd)
            return {"status": agg.get("status"), "verdict": rd.get("verdict"),
                    "rounds": len(lead.rounds),
                    "approved": rd.get("approved_devs"),
                    "total": rd.get("total_devs"),
                    "next": agg.get("next")}
        except Exception as e:  # noqa: BLE001 小组驱动失败显式暴露
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    # ---------------- 启下：真动作（不是动作名） ----------------

    def wake_role(self, role, *, task_key="", issue=None, note=""):
        """真唤醒一个角色：走「多通路穷举」而不是只投一张卡。

        与 `try_lanes()` 的区别：这里把**每条通路的真实执行**都接上了 handler，
        而不是只传一个空字典让所有通路 skipped_no_handler。
        治「一条路断了就默认没能力做」——逐条真试，全断才返回 ok=False。
        """
        import dispatch_engine
        repo = self.repo

        def _via_fullpath():
            msg = dispatch_engine.dispatch_trigger(
                [{"task_key": task_key or role, "task_id": f"lane-{role}",
                  "agent_id": "", "role": role, "title": task_key or role,
                  "issue_number": issue}],
                from_agent=self.owner)
            return {"ok": bool(msg), "msg_id": (msg[0].get("msg_id", "")
                                               if msg else "")}

        def _via_codebuddy():
            # @CodeBuddy 兜底：走同一条 dispatch_trigger，把承接角色换成 CodeBuddy
            msg = dispatch_engine.dispatch_trigger(
                [{"task_key": task_key or role, "task_id": f"cb-{role}",
                  "agent_id": "", "role": "CodeBuddy",
                  "title": f"{task_key or role}（原角色 {role} 未响应）",
                  "issue_number": issue}],
                from_agent=self.owner)
            return {"ok": bool(msg), "msg_id": (msg[0].get("msg_id", "")
                                               if msg else "")}

        def _via_lead():
            plan = self.delegate_to_lead({"task_key": task_key or role,
                                          "task_id": f"lane-{role}",
                                          "issue": issue, "role": role})
            return {"ok": bool(plan), "leader_plan": plan}

        def _via_self():
            return {"ok": True, "note": "经理自己承接不越界部分（组织/催办/整理）"}

        handlers = {"fullpath": _via_fullpath, "codebuddy": _via_codebuddy,
                    "lead": _via_lead, "self": _via_self}
        res = self.try_lanes(role, handlers=handlers, handle=role)
        res["role"] = role
        res["note"] = note
        return res

    def add_devs(self, rec, extra=None):
        """真加派：组内追加并行开发（不是记一个 "add_devs" 名字）。

        用 ops.apply_more_agents 把任务拆分给新挂载的开发，返回新增的 agent gid。
        """
        extra = extra if extra is not None else self.devs_per_team
        added = []
        try:
            import ops
            for i in range(1, extra + 1):
                key = f"{rec['task_key']}·加派{i}"
                split = ops.apply_more_agents(rec.get("task_id", rec["task_key"]),
                                              reason="经理加派：原承接人未响应",
                                              branch_name=f"加派{i}",
                                              submitter=self.owner)
                added.append({"task_key": split.get("branch_task", key),
                              "agent_id": split.get("agent_id", ""),
                              "role": "架构·开发", "issue": rec.get("issue"),
                              "split_id": split.get("split_id", "")})
            self._log("add_devs", {"task_key": rec["task_key"], "added": added})
        except Exception as e:  # noqa: BLE001 失败显式暴露
            self._log("add_devs_failed", {"task_key": rec["task_key"],
                                          "error": f"{type(e).__name__}: {e}"})
        return added

    def borrow_role(self, role, *, task_key=""):
        """真跨岗借角色：用 HandleAbility 解析目标仓库里有权限的 @ 格式再召唤。

        不是写一句"调用 HandleAbility 定位"——真调用，真拿到 handle，真去唤醒。
        """
        handle = ""
        try:
            from handle import HandleAbility
            ha = HandleAbility(agent_name=self.owner, repo=self.repo)
            org, _, repo_name = self.repo.partition("/")
            resolved = ha.resolve(org, repo_name, role)
            handle = resolved.get("handle", "") if isinstance(resolved, dict) else str(resolved)
        except Exception as e:  # noqa: BLE001 解析失败降级为手写 @ 并留痕
            handle = f"@{self.repo}({role})" if self.repo else f"@{role}"
            self._log("borrow_role_resolve_failed",
                      {"role": role, "error": f"{type(e).__name__}: {e}"})
        wake = self.wake_role(role, task_key=task_key,
                              note=f"跨岗借角色，handle={handle}")
        out = {"role": role, "handle": handle, "wake": wake,
               "ok": wake.get("ok", False)}
        self._log("borrow_role", out)
        return out

    def split_task(self, rec, parts=None):
        """真拆分：把过大的任务拆成若干可独立承接的子任务（不是记名字）。"""
        parts = parts or 2
        import ops
        subs = []
        try:
            for i in range(1, parts + 1):
                subs.append(ops.split_task(rec.get("task_id", rec["task_key"]),
                                           reason="initial",
                                           branch_name=f"part{i}",
                                           submitter=self.owner))
        except Exception as e:  # noqa: BLE001
            self._log("split_failed", {"task_key": rec.get("task_key"),
                                       "error": f"{type(e).__name__}: {e}"})
        out = {"task_key": rec.get("task_key"), "parts": len(subs) or parts,
               "subtasks": subs}
        self._log("split_task", out)
        return out

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

        # 四轮闸门：证据必须过「凭据分级」。演练注入的 simulated 一律不算干活——
        # 否则 `simulate={"*": "accept"}` 就能让整条链变绿，绿的其实是模拟器。
        from .work import credential_of, is_ready
        cred = credential_of(task_id)
        simulated_only = (cred["level"] == "simulated")

        base = {"task_key": rec["task_key"], "task_id": task_id,
                "role": rec["role"], "issue": rec.get("issue"),
                "events": sorted(set(events)), "meter_rounds": len(meters),
                "credential": cred["level"], "credential_ready": is_ready(cred)}

        if simulated_only and not is_ready(cred):
            return {**base, "verdict": "fake", "disposition": "hand_to_lead",
                    "reason": "只有演练回执（simulated），没有真实承接方开工 —— 不算分工"}

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

    # ---------------- 二轮：找通路（不是一条路断了就说做不到） ----------------
    def try_lanes(self, role, handlers=None, allow_self=True, repo=None,
                  cnb=None, handle=None):
        """多通路穷举：按「平台 Issue → 完整 @ 接力 → @CodeBuddy → 直接 handle →
        调配小组长 → 自己兜底」顺序真试，任一条成功即停。

        handlers: {lane: callable() -> {"ok": bool, ...}}；缺 handler 的通路会标
        skipped_no_handler（不假装试过）。
        """
        from . import lanes as lane_mod
        cnb_ok = (not self.dry_run) if cnb is None else bool(cnb)
        res = lane_mod.attempt(
            role, handlers or {}, repo=repo if repo is not None else self.repo,
            cnb=cnb_ok, handle=handle if handle is not None else role,
            allow_self=allow_self, log=self._log)
        self._log("try_lanes", {"role": role, "ok": res["ok"],
                                "lane": res["lane"],
                                "tried": res["tried"]})
        return res

    def lanes(self, role="架构·开发"):
        """列出该角色所有可用通路 + 每条是否就绪（给人类看的"还有哪些路"）。"""
        from . import lanes as lane_mod
        return lane_mod.lanes_for(role, repo=self.repo, cnb=not self.dry_run,
                                  handle=role)

    def authorize(self, action, **kwargs):
        """权责边界判定：权责内一律自决（SELF），只有不可逆/超成本/敏感/越级才 HUMAN。

        治用户点名的「职责范围内的还在申请授权」——判 SELF 就必须自己干。
        """
        from . import lanes as lane_mod
        res = lane_mod.authorize(action, **kwargs)
        self._log("authorize", res)
        return res

    # ---------------- 二轮：承上启下（不是刚性传达） ----------------
    def carry(self, plan, north_star="", max_rounds=None):
        """承上启下四段全跑：承上 → 行下 → 启下 → 反馈（多轮直到收敛或显式上交）。

        这是经理的**标准动作**：上级给的意图在这里被翻译成执行、被盯到有证据、
        没人接就调人、调不动就带证据上交。不是把计划分槽投卡（那是程序的事）。
        """
        from .flow import ManagerFlow
        flow = ManagerFlow(self, max_rounds=max_rounds or MAX_FLOW_ROUNDS)
        res = flow.run(plan, north_star=north_star)
        self._log("carry", {"north_star": res["north_star"],
                            "escalated": res["escalated"],
                            "unresolved": [v["task_key"] for v in res["unresolved"]]})
        return res

    def self_check(self):
        """经理自检：这五件事做到没有（供人类/总师快速判定岗位是否及格）。

        口径（四轮修正）：一次任务本来就不需要把六个手段全用一遍——
        **"启下/找通路/自决"证明的是能力，不是"每单必用"**。所以：
          - 承上 / 行下 / 反馈：本单必须做过（缺一即不及格）；
          - 启下 / 找通路 / 自决：本单做过 **或** 已具备（有承接方/已注册通路/
            授权判定函数可用）即算具备，`capability_ready` 里说明来源。
        """
        kinds = [a["kind"] for a in self.actions]
        has_workers = any(self._worker(r) is not None
                           for r in ("架构·开发", "架构·评审", "架构·测试",
                                     "架构·小组长", "架构·交付"))
        from . import lanes as lane_mod
        lanes_available = bool(lane_mod.LANE_ORDER)
        engaged = {
            "承上": "take_over" in kinds or "carry" in kinds,
            "行下": "activate" in kinds,
            "启下": ("staffing" in kinds or "delegate_to_lead" in kinds
                     or "drive_worker" in kinds),
            "反馈": "adjust_round" in kinds or "carry" in kinds,
            "找通路": "try_lanes" in kinds or "lane_attempt" in kinds,
            "自决": "authorize" in kinds,
        }
        ready = {
            "启下": "本单已调人" if engaged["启下"] else (
                "已具备（有承接方可调）" if has_workers else "缺承接方"),
            "找通路": "本单已换过通路" if engaged["找通路"] else (
                "已具备（多通路已注册）" if lanes_available else "缺通路表"),
            "自决": "本单已自决" if engaged["自决"] else "已具备（权责判定可用）",
        }
        return {
            "role": self.owner,
            **{k: engaged[k] or (k in ready and not ready[k].startswith("缺"))
               for k in engaged},
            "engaged": engaged,
            "capability_ready": ready,
            "note": "四段缺一段即不及格：承上（翻译不是复述）/ 行下（派到有证据）/"
                    "启下（调人跨岗）/ 反馈（回看再调整）；找通路/自决看是否具备。",
        }

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
            "entry": ["carry", "execute_plan", "activate", "push", "supervise",
                      "status", "guard", "delegate_to_lead",
                      "try_lanes", "lanes", "authorize", "self_check"],
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
