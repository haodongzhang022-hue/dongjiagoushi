# -*- coding: utf-8 -*-
"""
LeadBrainAbility · 小组长脑子能力（Issue #232）
==============================================
确定性实现（非 LLM 判断）：给定经理的分配方案 / 行动，必然给出同样的缺口清单与
补全方案、同样的犯傻判定。让「小组长当脑子用」这件事**可核验**，不是嘴上说说。

设计边界：
  - 小组长只做**脑子 + 监察**，不替经理拍板、不越权改需求边界；
  - 补全方案是「建议 + 缺口清单」，最终仍由经理确认（留痕），
    但缺口的补齐要求是**硬的**——缺口不齐不许往下派（不带窟窿往下走）；
  - 判不了的不猜，标 unknown 显式暴露。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

# 任务项必须说清的字段（缺口判据 · 唯一事实源）
REQUIRED_FIELDS = {
    "owner": "负责角色（谁来做）",
    "task": "具体做什么（可执行的一句话，不是'开发'这种空词）",
    "input": "输入（拿什么开工）",
    "output": "输出（交什么产物）",
    "done_when": "验收标准（怎么算做完，以测试为准）",
}

# 空词判定：只有这些词等于没说要做什么
VAGUE_TASKS = {"开发", "实现", "做", "干活", "写代码", "优化", "跟进", "处理", "推进"}

# 犯傻判定阈值（确定性）
DEFAULTS = {
    "max_same_task": 2,      # 同一实体重复派发超过该次数 = 重复派发
    "max_rework": 3,         # 同一任务被打回超过该次数 = 超次返工（AGENTS.md 回转协议上限 3）
    "min_required_depth": 4, # 派活目标深度（L1声明→L4工作，低于 4 = 跳深度）
}

DEPTH_LEVELS = {
    1: "L1 声明", 2: "L2 分发", 3: "L3 触发", 4: "L4 工作（接单→开工→进度→交付）",
}


class LeadBrainAbility:
    """小组长脑子：补全经理方案 + 看住经理犯傻。"""

    RULES = {
        "何时用": (
            "经理完成分工/派活方案后，先过小组长这道脑子：诊断缺口→补全→再往下派；"
            "经理每次行动（派发/重派/加派/交付）前也过一遍 watch，跑偏当场拦。"
        ),
        "不越权": (
            "小组长补的是「方案窟窿」不是「需求边界」：改做什么/为何做仍归总师与经理；"
            "小组长只保证「方案可执行、不跑偏、不空转」，重大缺口升总师判断。"
        ),
        "以测试为准": (
            "验收标准(done_when)必须可客观验证（测试/lint/信号灯），不接受'我觉得完成了'。"
        ),
        "防无效": (
            "重复派发/跳深度/超次返工/空转一律拦截并给替代动作，不让团队在同一个错误上打转。"
        ),
    }

    def __init__(self, owner=None, **thresholds):
        self.owner = owner
        self._owner_name = owner if isinstance(owner, str) else getattr(owner, "name", "")
        self.cfg = dict(DEFAULTS)
        self.cfg.update({k: v for k, v in thresholds.items() if k in DEFAULTS})

    # ---------------- ① 诊断：找缺口 ----------------
    def diagnose(self, plan):
        """诊断经理方案缺口。plan: {goal, tasks[{id,owner,task,input,output,done_when,depends_on,depth}]}

        Returns: {ready: bool, gaps: [{task, field, issue, fix}], score: 0-100, summary}
        """
        plan = plan or {}
        tasks = plan.get("tasks") or []
        gaps = []

        if not str(plan.get("goal") or "").strip():
            gaps.append({"task": "-", "field": "goal",
                         "issue": "方案没写清目标（北极星缺失），无法量化到目标的距离",
                         "fix": "补一句可验收的目标；无目标不进小组闭环（goal>0 才能开工）"})
        if not tasks:
            gaps.append({"task": "-", "field": "tasks",
                         "issue": "方案里一个可执行任务项都没有",
                         "fix": "至少拆出一个可执行任务项（做什么/谁做/交什么/怎么算完）"})

        seen_ids = set()
        dup_ids = set()
        for idx, t in enumerate(tasks):
            tid = str(t.get("id") or f"task{idx + 1}")
            if tid in seen_ids:
                dup_ids.add(tid)
            seen_ids.add(tid)
            for field, desc in REQUIRED_FIELDS.items():
                val = str(t.get(field) or "").strip()
                if not val:
                    gaps.append({"task": tid, "field": field,
                                 "issue": f"缺 {desc}",
                                 "fix": f"补上{desc}后再派，别让下游靠猜"})
            task_txt = str(t.get("task") or "").strip()
            if task_txt and task_txt in VAGUE_TASKS:
                gaps.append({"task": tid, "field": "task",
                             "issue": f"任务描述是空词「{task_txt}」，等于没说要做什么",
                             "fix": "改成可执行的一句话（动词+对象+范围），否则下游只能自由发挥"})
            depth = t.get("depth")
            if depth is not None and int(depth) < self.cfg["min_required_depth"]:
                gaps.append({"task": tid, "field": "depth",
                             "issue": f"派活深度只到 {DEPTH_LEVELS.get(int(depth), depth)}，"
                                      "到不了「接单后继续工作」",
                             "fix": "补 L3 触发（等 [接单] 回执）+ 进度尺推进，目标锁 L4"})

        for tid in sorted(dup_ids):
            gaps.append({"task": tid, "field": "id",
                         "issue": "任务编号重复，gid 会撞车，二次触发必然串号",
                         "fix": "给任务编号去重（全局唯一 gid）"})

        total = max(1, len(tasks) * len(REQUIRED_FIELDS))
        score = int(round(100 * (1 - len(gaps) / total))) if tasks else 0
        return {
            "ready": not gaps,
            "gaps": gaps,
            "gap_count": len(gaps),
            "score": max(0, min(100, score)),
            "summary": ("方案可执行，可以往下派" if not gaps
                        else f"方案有 {len(gaps)} 处窟窿，补齐再派（缺口不齐不许往下走）"),
        }

    # ---------------- ② 补全：把窟窿补成可执行 ----------------
    def advise(self, plan):
        """基于诊断结果给出补全方案（改派/补字段/拆细/加派/升总师）。

        Returns: {enhanced_plan, fixes: [{task, field, action, detail}], escalate: [...]}
        """
        plan = plan or {}
        diag = self.diagnose(plan)
        tasks = [dict(t) for t in (plan.get("tasks") or [])]
        by_id = {str(t.get("id") or f"task{i + 1}"): t for i, t in enumerate(tasks)}
        fixes, escalate = [], []

        for g in diag["gaps"]:
            tid, field = g["task"], g["field"]
            target = by_id.get(tid)
            if field in REQUIRED_FIELDS and target is not None:
                placeholder = f"待补：{REQUIRED_FIELDS[field]}"
                target[field] = placeholder
                fixes.append({"task": tid, "field": field, "action": "补字段",
                              "detail": f"{g['issue']} → 先占位标记「{placeholder}」交经理确认，"
                                        "确认前该任务不得派发"})
            elif field == "owner" and target is not None:
                fixes.append({"task": tid, "field": "owner", "action": "改派",
                              "detail": "负责人空缺 → 由经理指定，或按 skill_gap 走同岗补位"})
            elif field == "task" and target is not None:
                fixes.append({"task": tid, "field": "task", "action": "拆细",
                              "detail": "空词任务 → 拆成「动词+对象+范围」的最小可执行项"})
            elif field == "depth":
                fixes.append({"task": tid, "field": "depth", "action": "补深度",
                              "detail": "补 L3 触发 + L4 工作闭环（接单回执、进度尺推进、向上交付）"})
            elif field == "tasks":
                fixes.append({"task": "-", "field": "tasks", "action": "先拆任务",
                              "detail": "无任务项 → 按功能域拆出最小可执行项再走派发"})
            elif field in ("goal", "id"):
                fixes.append({"task": "-", "field": field, "action": "修正方案",
                              "detail": g["fix"]})
            else:
                escalate.append({"task": tid, "field": field, "reason": g["issue"]})

        # 大任务没声明加派 → 给加派建议（不擅自分，申报经理/小组长）
        if len(tasks) >= 5 and not plan.get("split"):
            fixes.append({"task": "-", "field": "split", "action": "加派",
                          "detail": f"共 {len(tasks)} 个子任务，单组易失控 → 建议分形多小组，"
                                    "开发中仍过大由小组长申报加派（apply_more_agents）"})

        # ready 判据：占位字段必须由经理确认；「补字段/补深度」类仍待补齐，不能直接往下派
        pending = [f for f in fixes if f["action"] in ("补字段", "补深度")]
        enhanced = {
            "goal": plan.get("goal", ""),
            "tasks": tasks,
            "split": plan.get("split", len(tasks) >= 5),
            "brain": {"version": "lead_brain/1.0", "by": self._owner_name or "架构·小组长",
                      "gaps": diag["gap_count"], "fixes": len(fixes)},
        }
        return {
            "enhanced_plan": enhanced,
            "fixes": fixes,
            "escalate": escalate,
            "diagnose": diag,
            "ready": not escalate and not pending,
            "summary": (f"补全 {len(fixes)} 处，方案可执行" if not escalate
                        else f"补全 {len(fixes)} 处，{len(escalate)} 处需升总师判断"),
        }

    # ---------------- ③ 看住经理：别犯傻 ----------------
    def watch(self, action, history=None):
        """看住经理的一次行动。action: {type, entity, depth, count, rework, progress_delta}

        Returns: {verdict: pass|block|blocked_escalate, reasons: [...], alternatives: [...], level}
        """
        action = action or {}
        history = history or {}
        atype = action.get("type", "dispatch")
        entity = action.get("entity", "-")
        reasons, alts = [], []

        depth = action.get("depth")
        if depth is not None and int(depth) < self.cfg["min_required_depth"]:
            reasons.append(f"跳深度：只到 {DEPTH_LEVELS.get(int(depth), depth)}，"
                           "经理以为派完就完事，其实下游没接单没开工")
            alts.append("补 L3 真实唤醒（等 [接单] 回执）+ L4 进度尺推进，再判完成")

        cnt = int(action.get("count") or 0)
        if cnt > self.cfg["max_same_task"]:
            reasons.append(f"重复派发：同一实体已派 {cnt} 次（上限 {self.cfg['max_same_task']}），"
                           "同一个错误在反复尝试")
            alts.append("先用 dispatch_verify 查上次是否真接单；未接单→重触发，"
                        "接单即换方案不再重派")

        rework = int(action.get("rework") or 0)
        if rework > self.cfg["max_rework"]:
            reasons.append(f"超次返工：同一任务已打回 {rework} 次（回转协议上限 "
                           f"{self.cfg['max_rework']}）")
            alts.append("标 blocked 上报总师；较大的改框架交总师助理，别让经理硬顶")

        delta = action.get("progress_delta")
        stall = int(action.get("stall_rounds") or 0)
        if (delta is not None and float(delta) == 0) or stall >= 3:
            reasons.append(f"空转：连续 {stall or '多次'} 轮进度零推进（delta="
                           f"{delta if delta is not None else 0}）")
            alts.append("按剩余距离重新规划内容与分配，禁止在同类失败上继续尝试")

        if action.get("conflict"):
            reasons.append("抢单：同一实体同时被派给多个负责人，责任会漂移")
            alts.append("先经经理统一协调定唯一负责人，再派")

        if action.get("no_owner") and not action.get("owner"):
            reasons.append("无主派发：没有指定负责人，等于派给空气")
            alts.append("先定负责人（含备用），或按同岗补位（skill_gap/stall）指定")

        level = 2 if len(reasons) >= 2 else (1 if reasons else 0)
        if not reasons:
            return {"verdict": "pass", "reasons": [], "alternatives": [], "level": 0,
                    "entity": entity, "summary": "这一步没毛病，放行"}

        if action.get("repeat_hit"):
            return {"verdict": "blocked_escalate", "reasons": reasons,
                    "alternatives": alts, "level": 2, "entity": entity,
                    "summary": "二度命中 → 标 blocked 上报总师，别让经理自己扛"}
        return {"verdict": "block", "reasons": reasons, "alternatives": alts,
                "level": level, "entity": entity,
                "summary": f"拦住（{len(reasons)} 条）：先按替代动作改，再往前走"}

    # ---------------- 一站式：当经理的脑子 ----------------
    def enhance(self, plan):
        """经理分工方案 → 小组长诊断+补全 → 交回经理。"""
        adv = self.advise(plan)
        return {
            "plan": adv["enhanced_plan"],
            "fixes": adv["fixes"],
            "escalate": adv["escalate"],
            "ready": adv["ready"],
            "score": adv["diagnose"]["score"],
            "summary": adv["summary"],
        }

    def watch_manager_orders(self, orders, history=None):
        """批量看住经理的一串派活，返回逐条判定 + 汇总。"""
        results = [self.watch(o, history=history) for o in (orders or [])]
        blocked = [r for r in results if r["verdict"] != "pass"]
        return {
            "results": results,
            "blocked_count": len(blocked),
            "escalate_count": len([r for r in results if r["verdict"] == "blocked_escalate"]),
            "summary": (f"{len(results)} 条派活全部放行" if not blocked
                        else f"拦住 {len(blocked)} 条（其中 "
                             f"{len([r for r in results if r['verdict'] == 'blocked_escalate'])} 条要上报总师）"),
        }

    def capability(self):
        return {
            "name": "LeadBrainAbility",
            "desc": "小组长脑子——补全经理方案缺口 + 看住经理别犯傻（确定性判定，非 LLM 自判）",
            "methods": ["diagnose", "advise", "watch", "enhance", "watch_manager_orders"],
            "rules": self.RULES,
        }
