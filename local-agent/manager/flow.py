# -*- coding: utf-8 -*-
"""
经理承上启下编排（ManagerFlow · Issue #239 二轮）
=================================================
经理这个岗位**不是**「把架构师的计划程序化地塞进槽位」——如果是那样，
架构师分完直接程序自动分槽投交接卡就行了，这个岗位根本不需要存在。

## 用户二轮原话（钉在墙上）

> 「经理应该做的是承上启下，不是被安排了任务后挤牙膏，戳一戳动一动。」
> 「架构师传达下来的任务，经理如果只分下去，那架构师分完了直接程序自动分槽位
>   去交接卡就行了，这里经理岗位直接不需要存在了，这就是刚性传达。」
> 「实际上经理是找进度、找通路，安排和看反馈，寻找能行得通的方式安排下去后
>   看看效果反馈，进一步调整，不够还能调整人员，跨部门找角色过来帮忙都行。」

## 所以这个岗位的活儿分四段，缺一段就是失职

| 段 | 名字 | 干什么 | 输出（可核验） |
|----|------|--------|----------------|
| ① | **承上** | 接住上级意图：复述北极星、翻译计划、裁掉不可执行项 | `north_star` + `dropped`（被裁的必须给理由与替代路线） |
| ② | **行下** | 真派发 + 按成功标准核验 + 没达到就**换路线/调人员** | 每条任务的 `verdict` |
| ③ | **启下** | 单人派不动就调人：加派、调配小组长、**跨岗借角色** | `staffing` 动作清单（逐轮升级） |
| ④ | **反馈** | 拿效果反馈回来再调整一轮，直到收敛或**显式上交** | `rounds[]` + `escalated` |

## 一条硬约束（治"戳一戳动一动"）

`run()` 内部是**多轮**循环：核验 → 不达标 → 换手段/换通路 → 再核验 ……
只有两种情况会停：**全部达到成功标准**，或者**穷尽所有手段后显式上交人类**。

「卡住了就汇报」不是合格输出；「卡住了还试了 A/B/C 都没成，因此需要 X」才是。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

from . import lanes as lane_mod

#: 默认最大调整轮数（防无限循环；超限显式上交，不静默）
MAX_ROUNDS = 4

#: 启下阶段的人员手段（按代价排序，先便宜后贵，最后才越出本组）
STAFFING_ACTIONS = (
    ("requeue", "同一角色再唤醒一次（可能是漏看，先别急着换人）"),
    ("split", "把任务拆小，降低单点承接难度"),
    ("add_devs", "加派：组内增加并行开发（改配比）"),
    ("delegate_lead", "调配小组长：带编制承接（1 组长 + N 开发）"),
    ("borrow_role", "跨岗借角色：从其他功能域借有权限的角色来帮"),
    ("self_take", "经理自己承接不越界的那部分（拆解/组织/催办/整理）"),
)

#: 手段升级梯（按轮次递进，不是每轮重复同一个动作 —— 那还是挤牙膏）
ESCALATION_LADDER = (
    ("requeue", "同一角色再唤醒一次（可能是漏看，先别急着换人）"),
    ("delegate_lead", "调配小组长：带编制承接（1 组长 + N 开发）"),
    ("add_devs", "加派：组内增加并行开发，改配比再试"),
    ("borrow_role", "跨岗借角色：本组没人接得住，从其他功能域借有权限的角色"),
    ("split", "把任务拆小，降低单点承接难度后再派"),
    ("self_take", "经理自己承接不越界的那部分（拆解/组织/催办/整理），其余留待分派"),
)

#: 计划项里能指向承接角色的线索（显式「角色: X」或动作/角色关键词）
_ROLE_CLUES = (
    "角色", "开发", "实现", "代码", "修复", "重构", "文档",
    "评审", "走查", "复评", "测试", "联调", "验收",
    "架构", "方案", "设计", "需求", "澄清",
    "合并", "交付", "收尾", "调研", "选型", "监控", "进度",
)


def translate(plan, *, north_star="", repo="", cnb=False):
    """① 承上：把上级给的计划**翻译**成经理自己的执行计划。

    翻译不是复述：要复述北极星、把每条落成可派发项、并且**裁掉不可执行项**——
    裁掉必须给理由 + 替代路线（不是默默丢掉，也不是原样下发）。

    Returns: {"north_star", "items", "dropped", "source"}
    """
    from .engine import parse_plan

    items = parse_plan(plan) if not _is_assignments(plan) else list(plan)
    # parse_plan 的 _infer_role 有兜底（认不出就落开发）——那会让"这件事你们看着办"
    # 这种空话也变成一条开发任务。承上的职责是**识别出来裁掉**，所以这里按原文
    # 重判一次：既无显式「角色: X」、也无任何动作/角色线索 → 判不可执行。
    for it in items:
        raw = str(it.get("detail") or it.get("title") or "")
        if not _has_role_clue(raw):
            it["_no_role_clue"] = True

    # 北极星：没显式给就从计划内容自己提炼一句（经理得知道自己在往哪儿使劲）
    if not north_star:
        north_star = _infer_north_star(items)

    kept, dropped = [], []
    for idx, a in enumerate(items, start=1):
        item = dict(a)
        item["planned_index"] = idx
        title = item.get("title") or item.get("task_key") or ""
        role = item.get("role") or ""
        # 不可执行判据：无任何承接线索（空话）→ 裁掉；不许硬塞给开发冒充分工
        if not role or item.get("_no_role_clue"):
            dropped.append({
                "task_key": item.get("task_key", ""),
                "reason": "没有任何可承接线索 —— 原样下发等于把球踢回上级",
                "alt_lane": "borrow_role：先按语义匹配角色，匹配不到由经理拆成更小的可派项",
            })
            continue
        item["role"] = role
        item["title"] = title or f"任务{idx}"
        item.setdefault("domain", "通用")
        item.setdefault("priority", "P1")
        item.setdefault("detail", title or f"任务{idx}")
        kept.append(item)

    return {
        "north_star": north_star,
        "items": kept,
        "dropped": dropped,
        "source": "translated",
        "readiness": lane_mod.lanes_for("架构·开发", repo=repo, cnb=cnb,
                                        handle=True),
    }


#: 计划项里能指向承接角色的线索（显式「角色: X」或动作/角色关键词）
_ROLE_CLUES = (
    "角色", "开发", "实现", "代码", "修复", "重构", "文档",
    "评审", "走查", "复评", "测试", "联调", "验收",
    "架构", "方案", "设计", "需求", "澄清",
    "合并", "交付", "收尾", "调研", "选型", "监控", "进度",
)


def _has_role_clue(text):
    """这条计划项能不能指向一个承接角色（不能 → 承上阶段裁掉，不硬塞给开发）。"""
    t = str(text or "")
    return any(k in t for k in _ROLE_CLUES)


def _is_assignments(plan):
    return (isinstance(plan, list) and plan and isinstance(plan[0], dict)
            and "task_key" in plan[0])


def _infer_north_star(items):
    """从计划里提炼北极星（没有就诚实说没给，不编）。"""
    if not items:
        return "上级未给出可执行计划 —— 先要计划，不空转"
    titles = [i.get("title") or i.get("task_key") for i in items[:3]]
    return "把以下事项真正落地到有人在做：" + "；".join(t for t in titles if t)


def staffing_options(verdict, *, rounds=1, group_size=2):
    """③ 启下：按当前轮次给出**这一轮该动用的手段**（升级梯，逐轮往上）。

    不是重复问同一个人，也不是每轮都做同一件事：第 1 轮再唤醒，第 2 轮调小组长，
    第 3 轮加派、第 4 轮跨岗借人……直到手段用完才上交。这才是"寻找能行得通的方式"。
    """
    if verdict in ("real", "accepted"):
        return []
    idx = min(max(rounds, 1) - 1, len(ESCALATION_LADDER) - 1)
    pick = ESCALATION_LADDER[idx]
    opts = [pick]
    # 后面的手段也一并给出（上报时说明"没在原地打转、还剩哪些没试"）
    opts.extend(ESCALATION_LADDER[idx + 1:])
    return opts


class ManagerFlow:
    """承上启下编排器：把经理的四段活接成一条确定性流程。

    用法：
        flow = ManagerFlow(engine)      # engine 是 ManagerEngine
        r = flow.run(plan)
        r["north_star"] / r["verdicts"] / r["unresolved"] / r["report"]
    """

    def __init__(self, engine, max_rounds=MAX_ROUNDS):
        self.engine = engine
        self.max_rounds = max(1, int(max_rounds))

    # ---------------- ① 承上 ----------------
    def take_over(self, plan, north_star=""):
        """接住上级意图：复述北极星 + 翻译成可派项 + 裁掉不可执行项。"""
        tr = translate(plan, north_star=north_star, repo=self.engine.repo,
                       cnb=not self.engine.dry_run)
        self.engine._log("take_over", {
            "north_star": tr["north_star"],
            "kept": len(tr["items"]), "dropped": len(tr["dropped"]),
        })
        return tr

    # ---------------- ② 行下 + ④ 反馈（多轮） ----------------
    def run(self, plan, north_star="", max_rounds=None):
        """完整跑一遍承上启下：承上 → 行下（派发+换路线）→ 反馈（多轮调人）。

        停的条件只有两个：全部达到成功标准，或者穷尽手段后显式上交。
        """
        rounds = max_rounds or self.max_rounds
        upstream = self.take_over(plan, north_star=north_star)
        if not upstream["items"]:
            return {
                "north_star": upstream["north_star"],
                "upstream": upstream,
                "rounds": [],
                "verdicts": [],
                "unresolved": [],
                "report": self.report(upstream, [], [], upstream["dropped"]),
                "escalated": False,
                "note": "承上阶段判定：没有任何可执行项 —— 须向上一级要计划，不空转",
            }

        history, verdicts, unresolved = [], [], []
        activated = None
        for r in range(1, rounds + 1):
            act = self.engine.activate(upstream["items"]) if activated is None \
                else self._re_activate(upstream["items"], activated)
            fresh = act.get("activated", []) if isinstance(act, dict) else []
            # 第二轮起不重建 Issue，activate 只有派发记录 —— 沿用它保住 issue/agent 字段，
            # 否则 supervise 拿到空列表会「零条未达标」假收敛（不许谎报收敛）。
            activated = fresh or activated
            self.engine.push(activated)
            sup = self.engine.supervise(activated)

            verdicts = sup["verdicts"]
            unresolved = [v for v in verdicts if v["verdict"] != "real"]
            history.append({
                "round": r,
                "activated": len(activated),
                "real": sup["summary"]["real"],
                "unresolved": [v["task_key"] for v in unresolved],
                "staffing": self._apply_staffing(unresolved, rounds=r,
                                                 group_size=self.engine.devs_per_team),
            })
            if not unresolved:
                break
            # 未收敛 → 下一轮换手段（换通路/调人员），不是原地再问一次
            self.engine._log("adjust_round", {
                "round": r, "unresolved": [v["task_key"] for v in unresolved]})

        escalated = bool(unresolved)
        if escalated:
            self._escalate(unresolved, rounds=rounds)
        report = self.report(upstream, verdicts, history, upstream["dropped"])
        return {
            "north_star": upstream["north_star"],
            "upstream": upstream,
            "rounds": history,
            "verdicts": verdicts,
            "unresolved": unresolved,
            "report": report,
            "escalated": escalated,
            "note": ("全部任务达到成功标准（有回执 + 有开工证据）" if not escalated else
                     f"已试 {len(history)} 轮（含换通路/调人员），仍有 {len(unresolved)} "
                     f"条无客观证据 —— 显式上交，不假装推动"),
        }

    def _re_activate(self, items, activated=None):
        """第二轮起：不重建 Issue（避免重复刷平台），只重新派发+催。"""
        import dispatch_engine
        try:
            res = dispatch_engine.dispatch(self.engine.repo, items,
                                           enable_issue=False)
            # 把原激活记录（issue/agent/task_id）回填，供本轮监督用
            keep = {a["task_key"]: a for a in (activated or [])}
            rebound = []
            for rec in res.get("L2_dispatch", []):
                rec = {**keep.get(rec.get("task_key"), {}), **rec}
                rebound.append(rec)
            res["activated"] = rebound
            return res
        except Exception as e:  # noqa: BLE001 失败显式暴露
            self.engine._log("re_activate_failed", {"error": f"{type(e).__name__}: {e}"})
            return {"activated": [], "L2_dispatch": []}

    def _apply_staffing(self, unresolved, *, rounds, group_size):
        """③ 启下：按未达标任务逐条落地人员手段（**真执行**，不是记一个动作名）。

        这里每个 code 都必须落到一个**可核验的外部动作**上：
          requeue       → 真唤醒一次（多通路穷举，逐条留痕）
          delegate_lead → 真唤醒小组长（不是只生成一个 leader_plan 字典）
          add_devs      → 真加派开发（ops.apply_more_agents，拿到新 agent gid）
          borrow_role   → 真用 HandleAbility 解析 handle 并真召唤
          split         → 真拆分（ops.split_task，拿到子任务 gid）
          self_take     → 真过职责护栏，只承接不越界部分

        治「挤牙膏」：上一版每个手段只写了一个名字，下一轮换个名字，等于原地不动。
        """
        applied = []
        for v in unresolved:
            opts = staffing_options(v["verdict"], rounds=rounds,
                                    group_size=group_size)
            if not opts:
                continue
            code, desc = opts[0]
            rec = {"task_key": v["task_key"], "task_id": v["task_id"],
                   "issue": v.get("issue"), "role": v["role"]}
            # 权责判定先过一遍：谓 SELF 就必须自己干（不再生成"要不要授权"的疑问）
            auth = self.engine.authorize(desc, reversible=True, cost="low",
                                         sensitive=False, in_duty=True)
            action = {"task_key": v["task_key"], "action": code, "desc": desc,
                      "verdict": v["verdict"], "authority": auth["decision"],
                      "executed": False}

            if auth["decision"] != "SELF":
                # 权责外的动作不由经理做，显式上交，不假装做了
                action["note"] = f"超出经理自决范围：{auth['reason']}"
                applied.append(action)
                self.engine._log("staffing", action)
                continue

            try:
                if code == "requeue":
                    wake = self.engine.wake_role(v["role"], task_key=v["task_key"],
                                                 issue=v.get("issue"),
                                                 note="未接单：再唤醒一次")
                    action["wake"] = wake
                    action["executed"] = bool(wake.get("ok"))
                elif code == "delegate_lead":
                    action["leader_plan"] = self.engine.delegate_to_lead(rec)
                    lead_wake = self.engine.wake_role(
                        "架构·小组长", task_key=v["task_key"], issue=v.get("issue"),
                        note="调配小组长带编制承接")
                    action["lead_wake"] = lead_wake
                    action["executed"] = bool(lead_wake.get("ok"))
                elif code == "add_devs":
                    added = self.engine.add_devs(rec)
                    action["added"] = added
                    action["executed"] = bool(added)
                elif code == "borrow_role":
                    borrow = self.engine.borrow_role("架构·开发",
                                                     task_key=v["task_key"])
                    action["borrow"] = borrow
                    action["executed"] = bool(borrow.get("ok"))
                elif code == "split":
                    subs = self.engine.split_task(rec)
                    action["split"] = subs
                    action["executed"] = bool(subs.get("subtasks"))
                elif code == "self_take":
                    action["guard"] = self.engine.guard(v["task_key"])
                    action["executed"] = bool(action["guard"].get("allowed"))
                    action["note"] = ("自己只承接不越界部分（拆解/组织/催办/整理）；"
                                      "写码/评审/测试仍归对应角色")
            except Exception as e:  # noqa: BLE001 手段失败显式暴露，不静默当做过
                action["error"] = f"{type(e).__name__}: {e}"
                action["executed"] = False

            applied.append(action)
            self.engine._log("staffing", action)
        return applied

    def _escalate(self, unresolved, *, rounds):
        """穷尽手段后显式上交（带上试过什么，不是空手说"做不了"）。"""
        payload = {
            "reason": f"{rounds} 轮内未达成功标准（含换通路、调人员）",
            "unresolved": [{"task_key": v["task_key"], "role": v["role"],
                            "verdict": v["verdict"], "reason": v["reason"]}
                           for v in unresolved],
            "tried": ["activate", "push", "re-wake", "delegate_lead", "borrow_role",
                      "self_take"],
            "need": "人类确认是否换目标/换资源/降范围",
        }
        self.engine._log("escalate", payload)
        try:
            import sentinel.engine as sentinel
            for v in unresolved:
                sentinel.interrupt(f"gm-{v['task_id']}", v["task_id"], v["role"],
                                   "escalate", {"reason": v["reason"]})
        except Exception:  # noqa: BLE001
            pass
        return payload

    # ---------------- 二级信息（人类俯瞰） ----------------
    def report(self, upstream, verdicts, history, dropped):
        """经理给人类的汇报：承上接下在哪、进度到哪、还缺什么。"""
        real = sum(1 for v in verdicts if v.get("verdict") == "real")
        return {
            "north_star": upstream.get("north_star", ""),
            "承上": {
                "接收条数": len(upstream.get("items", [])) + len(dropped or []),
                "可执行": len(upstream.get("items", [])),
                "裁掉": len(dropped or []),
                "裁掉明细": dropped or [],
            },
            "行下": {
                "条数": len(verdicts),
                "真在推进": real,
                "待处置": len(verdicts) - real,
            },
            "反馈": {"轮次": len(history or []),
                     "每轮手段": [h.get("staffing", []) for h in (history or [])]},
            "结论": ("已承上启下、全部落地" if verdicts and real == len(verdicts)
                     else "尚未全部落地：已在轮内换通路/调人员，仍缺客观证据会显式上交"),
        }
