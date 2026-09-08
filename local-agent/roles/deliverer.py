# -*- coding: utf-8 -*-
"""架构·交付：全流程呈现与收尾交付角色。

本角色承担两条核心职责：
  1. **呈现/汇报**（传统"做 PPT 的人"的数字化形态）：人类评审前/后，
     快速整理并展示有效信息——完成度、测试成功、还存在的问题
     （一般是🟡可升级但不够重要、不至于阻塞合并的项）。不用 PPT，
     用结构化信息卡片快速呈现。
  2. **收尾交付**（人类确认合并后）：提交 PR、关闭 Issue、处理冲突与合并等
     收尾工作。对应 `youxikaifaxilieagent` 仓库的「仓库调用专员 + 仓库修复专员」，
     负责收尾环节的仓库操作。

触发协议：
  - 人类评审确认后（用户 @ + [触发:架构·交付]）即进入本角色执行收尾；
  - 语义命中「交付/收尾/汇总/汇报/呈现/进度呈现/关闭Issue/提交PR/处理冲突/合并」即切本角色。
"""
from .base import BaseRole


class DelivererRole(BaseRole):
    name = "架构·交付"

    SYSTEM_PROMPT = """
你是「架构·交付」，本团队的呈现与收尾交付角色。你像传统项目里"做 PPT 的那个人"，
但不需要 PPT——你快速整理**有效信息**并呈现给人类，然后在人类确认后执行收尾。

## 输出契约（接手必交）

### 一、全流程呈现（汇报快照）
- **完成度**：按流水线各环节（产品→架构→开发→评审→测试→交付）给出 ✅/⏳/🔄 状态 + 百分比
- **测试成功**：测试矩阵结果（功能/性能/安全/联调/E2E）+ 信号灯
- **还存在的问题**：列出🟡可升级但不够重要的遗留项（一般不至于阻塞合并），
  以及优先级排序（p0..p9），供人类决定是否后续处理

### 二、收尾交付（人类确认合并后）
- **提交 PR**：确认改动已提 PR（base=main，解耦合规），若缺失则补提
- **处理冲突**：merge-tree 预检冲突，有冲突先 rebase main 解决
- **关闭 Issue**：合并完成后关闭关联 Issue，归档进度
- **合并确认**：CP3 人类确认合并 → 执行合并（若平台允许）或提示人类确认

## 协作纪律
- **人类评审后才触发收尾**：🟢 通过（测试信号灯）且人类确认合并（CP3）后才执行
  提交PR/关闭Issue/合并等收尾动作；人类未确认不得自行收尾。
- **呈现信息要"快速有效"**：不堆砌过程细节，只呈现人类决策需要的信息
  （完成度/测试/问题），一屏扫完。
- **遗留问题分级**：🔴阻塞必须打回（[回转]退回:架构·开发，须带完整 `@org/repo(架构·开发)` + `[触发:架构·开发]` 全路径出发）不放行；
  🟡可升级但不够重要的列为"遗留优化"，不影响合并，后续排期处理。
- **收尾动作留痕**：提交/关闭/合并动作在 Issue/PR 评论留痕可核验。

## 触发与回转协议
- 显式触发：收到带 `[触发:架构·交付]` 的接力卡即自动进入本角色执行。
- 语义触发：语义命中「交付/收尾/汇总/汇报/呈现/进度呈现/关闭Issue/提交PR/处理冲突/合并」
  即切本角色；与显式 `[触发]` 冲突时显式优先。
- 回转：被人类或下游打回（`[回转] 退回:架构·交付`）视为重新触发，按"下一步要求"
  返工并交回复评；被打回最多 3 次，超次标 blocked 上报总师。
- 打断：中断须在接力卡 `当前进度` 留续跑点，续跑凭进度无缝接续，不重做已完成部分。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "全流程呈现(progress_report: 完成度/测试成功/遗留问题/优先级)",
                "测试信号灯回显(signal_echo: 🟢/🟡/🔴)",
                "收尾交付(closeout: 提交PR/处理冲突/关闭Issue/合并确认)",
                "**人类确认后才执行收尾(gate: CP3确认才放行)**",
            ],
        }

    # ------------------------------------------------------------
    # 一、全流程呈现（汇报快照）
    # ------------------------------------------------------------
    def progress_report(self, task_key, agent_id="", stages=None, goal_total=100,
                        current=0, note="", issue_ref=""):
        """呈现全流程进度快照：完成度 + 测试结果 + 遗留问题。

        产出结构化"汇报卡片"，供人类一屏俯瞰决策。
        stages: [{name, status(✅/⏳/🔄), pct, note}, ...]
        """
        agent_id = agent_id or self.name
        if stages is None:
            stages = [
                {"name": "产品", "status": "✅", "pct": 100, "note": ""},
                {"name": "架构", "status": "✅", "pct": 100, "note": ""},
                {"name": "开发", "status": "✅", "pct": 100, "note": ""},
                {"name": "评审", "status": "✅", "pct": 100, "note": ""},
                {"name": "测试", "status": "🔄", "pct": 80, "note": ""},
                {"name": "交付", "status": "⏳", "pct": 0, "note": "待人类确认收尾"},
            ]
        progress = self.track_progress(
            task_key, agent_id, target="全流程交付完成",
            goal_total=goal_total, current=current, note=note, role=self.name)

        return {
            "task_key": task_key,
            "issue_ref": issue_ref,
            "stages": stages,
            "completion_pct": current / goal_total if goal_total else 0,
            "progress_meter": progress,
            "agent_id": agent_id,
        }

    def signal_echo(self, signal="🟢", blockers=None, warnings=None):
        """回显测试信号灯 + 遗留问题（供人类俯瞰）。

        signal: 🟢通过 / 🟡有条件 / 🔴阻塞
        blockers: 🔴阻塞项列表
        warnings: 🟡可升级但不够重要的遗留项列表
        """
        return {
            "signal": signal,
            "blockers": blockers or [],
            "warnings": warnings or [],
            "can_merge": signal == "🟢",
            "summary": (
                "🟢 通过，可进入收尾" if signal == "🟢" else
                "🟡 有条件，需处理警告项" if signal == "🟡" else
                "🔴 阻塞，需[回转]退回开发"
            ),
        }

    def remaining_issues(self, warnings, priorities=None):
        """遗留问题清单 + 优先级（🟡可升级但不够重要，人类决定后续处理）。"""
        items = []
        for i, w in enumerate(warnings):
            items.append({
                "id": i + 1,
                "issue": w,
                "priority": priorities[i] if priorities and i < len(priorities) else "p5",
                "blocking": False,  # 🟡遗留不阻塞合并
            })
        return {
            "total": len(items),
            "items": items,
            "recommendation": "均为🟡可升级但不够重要，不影响合并，建议后续排期处理",
        }

    # ------------------------------------------------------------
    # 二、收尾交付（人类确认合并后触发）
    # ------------------------------------------------------------
    def closeout(self, task_key, agent_id="", pr_url="", issue_ref="",
                 merged=False, conflicts=None, note="", goal_total=10, current=0):
        """收尾交付：提交 PR / 处理冲突 / 关闭 Issue / 合并确认。

        仅在人类确认合并（CP3）后调用，负责收尾闭环：
          1. 确认 PR 已提交（base=main，解耦合规）；
          2. 处理冲突（有冲突先 rebase main 解决）；
          3. 关闭 Issue（合并完成后归档）；
          4. 留痕记录。
        对应 `youxikaifaxilieagent` 的「仓库调用专员 + 仓库修复专员」收尾职责。
        """
        agent_id = agent_id or self.name
        progress = self.track_progress(
            task_key, agent_id, target="收尾交付完成（PR+Issue 闭环）",
            goal_total=goal_total, current=current, note=note, role=self.name)

        # 收尾前置检查
        prechecks = {
            "pr_submitted": bool(pr_url),
            "issue_referenced": bool(issue_ref),
            "human_confirmed": merged if merged is not None else False,
        }

        result = {
            "task_key": task_key,
            "pr_url": pr_url,
            "issue_ref": issue_ref,
            "prechecks": prechecks,
            "conflicts": conflicts or [],
            "conflict_resolved": len(conflicts or []) == 0,
            "merged": merged,
            "progress_meter": progress,
        }

        # 冲突处理
        if conflicts:
            result["action"] = "冲突未清零，需先 rebase main 解决再合并"
            result["can_close_issue"] = False
        elif merged:
            result["action"] = "已合并，关闭 Issue 归档"
            result["can_close_issue"] = True
        elif prechecks["pr_submitted"] and prechecks["human_confirmed"]:
            result["action"] = "PR 已提交 + 人类已确认，可执行合并"
            result["can_close_issue"] = False  # 合并完成才关闭
        else:
            result["action"] = "待人类确认合并（CP3），或待提交 PR"
            result["can_close_issue"] = False

        return result


# 便捷函数：判断是否可进入收尾
def can_start_closeout(signal="🟢", human_confirmed=False):
    """判断是否可进入收尾：测试🟢 + 人类确认合并（CP3）。"""
    return signal == "🟢" and human_confirmed
