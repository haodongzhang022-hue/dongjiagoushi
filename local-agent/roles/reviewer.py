# -*- coding: utf-8 -*-
"""架构·评审：五维评审/复评 + 统一处置标签 + 评审通过后真实转交测试。

与 settings.yml 同源。本角色除给出统一处置标签外，评审通过（merge/proceed）后
**必须把任务真实转交给「架构·测试」**——用完整 `@org/repo(架构·测试)` +
`[触发:架构·测试]` 投接力卡唤醒测试接单，而非只描述"交下游接力"。
"""
from .base import BaseRole

try:
    from collab import disposition
except Exception:  # noqa: BLE001
    disposition = None


# 评审通过 → 可放行转交测试的规范处置标签（其余需回转/调研/会诊/交人）
PASS_DISPOSITIONS = ("merge", "proceed")


class ReviewerRole(BaseRole):
    name = "架构·评审"

    SYSTEM_PROMPT = """
你是「架构·评审」，本团队代码质量守门员。接手必交：
- 五维评审：语法 / 异味 / 最佳实践 / 性能 / 重复
- 分级：🔴必修 / 🟡建议 / 🟢优化
- 统一处置标签：**每次评审必须给出一个规范处置标签**（不能漏、不能自定义），
  从规范集合中取：merge(适合合并)/proceed(适合推进)/fix_bug(适合改bug)/
  research(适合调研)/human(适合移交人类判断)/consult(适合专家会诊)/vote(适合投票)
- 仅评改动新增/改动行
- **双轴评审（Issue #98）**：拆 Standards（规范/坏味道基线）与 Spec（忠实实现源
  目标/边界/验收）两轴并行独立评审、互不污染，最后按必改优先合并；推荐处置仍走规范标签。

协作纪律：
- 🔴必修项必须指出并推动修复，复评至清零才放行；结论发回接力卡供下游接力。
- **评审通过（处置标签=merge/proceed）后必须真实转交「架构·测试」**：用完整
  `@org/repo(架构·测试)` + `[触发:架构·测试]` 投接力卡唤醒测试接单，并校验
  `awakened` 回执——**不得只描述"交测试接力"而不真正唤醒**，转交未回执须重触发或升级。

触达协议：显式[触发:架构·评审]/语义命中"评审/审查/走查/质量"即进入本角色；
发现🔴必修必须打回（[回转]退回开发），复评清零才放行。
统一处置标签：处置标签是评审输出契约的**必填字段**，缺标签即评审未完成。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "五维评审(five_dimensions)",
                "分级(severity: 🔴/🟡/🟢)",
                "统一处置标签(disposition: merge/proceed/fix_bug/research/human/consult/vote)",
                "复评结论(recheck)",
                "**双轴评审(dual_axis_review: Standards∥Spec 互不污染, Issue #98)**",
                "**评审通过后转交测试(handoff_to_tester: 完整@ + [触发:架构·测试] + 校验回执)**",
            ],
        }

    def dispose(self, problem="", severity=None, signals=None, scenario_hint=""):
        """评审结论 → 规范处置标签 + 自动化流程（强制必有标签）。"""
        if disposition is None:
            # 引擎不可用时兜底：按严重级给一个稳定标签，仍保证必有
            sev = str(severity or "")
            if "🔴" in sev or "red" in sev.lower():
                return {"disposition": "fix_bug"}
            if "🟢" in sev or "green" in sev.lower():
                return {"disposition": "merge"}
            return {"disposition": "proceed"}
        return disposition.route_for_review(problem=problem, severity=severity,
                                            signals=signals, scenario_hint=scenario_hint)

    # ------------------------------------------------------------
    # 评审通过 → 真实转交「架构·测试」（解决"只描述没真交付"）
    # ------------------------------------------------------------
    def passes_to_tester(self, disposition_label=""):
        """判定当前处置标签是否放行转交测试（merge/proceed 才放行）。"""
        label = (disposition_label or "").strip().lower()
        return label in PASS_DISPOSITIONS

    def handoff_to_tester(self, task_key, issue_ref="", review_summary="",
                          disposition_label="", target_role="架构·测试"):
        """评审通过后**真实转交**「架构·测试」：投完整接力卡 + 校验回执。

        这是用户痛点修复：评审不能只描述"交下游接力"，必须真正用
        `@org/repo(架构·测试)` + `[触发:架构·测试]` 唤醒测试接单。
        - 处置标签非 merge/proceed（未通过）时：**不转交**，返回 blocked 提示先回转；
        - 通过时：调用 `awake()` 投递完整 [触发] 接力卡并校验 awakened 回执，
          未回执即转交未真实成立，返回 handed_off=False，须重触发或升级。
        """
        label = (disposition_label or "").strip().lower()
        if not self.passes_to_tester(label):
            return {
                "handed_off": False,
                "reason": (f"处置标签 '{disposition_label}' 未放行转交测试，"
                           "须先 [回转] 退回:架构·开发 修复或走对应处置（fix_bug/research/human/consult/vote）"),
                "disposition": label or "unknown",
                "next_step": "[回转] 退回:架构·开发",
            }

        # 用完整 @org/repo(角色) 定位目标（不写死 org/repo，同仓复用本仓库 @）
        # 目标测试的完整 @：由 HandleAbility 动态解析；解析失败回退本仓库默认格式
        target_handle = "@dongdongxiaozu/dongjiagoushi(架构·测试)"
        try:
            info = self.resolve(target_repo="dongjiagoushi", role="架构·测试")
            # resolve 返回结构化定位信息，handle 字段为完整 @ 字符串
            if isinstance(info, dict):
                h = info.get("handle") or info.get("at") or info.get("target", {}).get("handle")
            else:
                h = info
            if h:
                target_handle = str(h)
        except Exception:
            pass

        # 完整接力卡上下文（含目标完整 @ + [触发:架构·测试] + 评审通过结论）
        context = (
            f"{target_handle} [触发:{target_role}] 评审已通过（处置={label}），任务正式转交。\n"
            f"评审摘要：{review_summary or '见评审评论'}\n"
            f"请按测试输出契约接手：测试矩阵 + 缺陷分级(🔴P0/🟠P1/🟡P2) + 信号灯(🟢/🟡/🔴)。\n"
            f"收到请回执 [接单]，接手后继续推进到结果（缺回执 = 转交未真实唤醒）。"
        )
        handle = target_handle

        result = self.awake(task_key, target_role, context=context,
                            issue_ref=issue_ref, from_agent=self.name)
        return {
            "handed_off": result.get("awakened", False),
            "awakened": result.get("awakened", False),
            "awakened_note": result.get("awakened_note", ""),
            "relay_card": result,
            "target_role": target_role,
            "handle": handle,
            "disposition": label,
            "issue_ref": issue_ref,
            "task_key": task_key,
            "next_step": ("等待 @架构·测试 [接单] 接手；未回执则重触发或升级"
                          if not result.get("awakened", False)
                          else "已转交，测试接单后继续推进到结果"),
        }

    def revert_to_developer(self, task_key, reason="", next_requirement=""):
        """评审 🔴必修 → [回转] 退回:架构·开发（不转交测试）。"""
        context = (
            f"[触发:架构·开发] 评审 [回转] 退回:架构·开发。\n"
            f"原因：{reason or '🔴必修项未清零'}\n"
            f"下一步要求：{next_requirement or '按评审必修项返工，复评清零再放行'}"
        )
        result = self.awake(task_key, "架构·开发", context=context,
                            from_agent=self.name)
        return {
            "reverted": result.get("awakened", False),
            "target_role": "架构·开发",
            "reason": reason,
            "relay_card": result,
        }

    # ------------------------------------------------------------
    # 双轴评审（P1-1 · Issue #98 · 借鉴 mattpocock code-review 双轴不互相污染）
    # ------------------------------------------------------------
    def dual_axis_review(self, source="", diff_scope="", spec_ref="",
                         standards_axis=None, spec_axis=None):
        """评审拆成两轴，各评各的、互不污染（防止一轴结论带偏另一轴）。

        - **Standards 轴**：是否符合仓库规范 + Fowler 坏味道基线（语法/异味/最佳实践/性能/重复）；
        - **Spec 轴**：是否忠实实现源 issue/spec（目标/做不做边界/验收标准是否覆盖）。

        两轴结论**并行独立产出**，最后按「必改优先原则」合并：
          Standards 🔴 必修 或 Spec 不达标 → fix_bug（打回）；
          两轴均达标 → merge/proceed（放行）。
        返回结构化双轴结论，供评审报告使用；`dispose()` 仍作为最终规范处置标签出口。
        """
        standards = standards_axis or {}
        spec = spec_axis or {}
        # 汇总两轴必修/通过
        standards_block = standards.get("blocking") or standards.get("🔴") or []
        spec_block = spec.get("blocking") or spec.get("🔴") or []
        spec_faithful = spec.get("faithful", spec.get("pass", True))

        blocked = bool(standards_block) or (not spec_faithful) or bool(spec_block)

        axis_report = {
            "source": source,
            "diff_scope": diff_scope,
            "spec_ref": spec_ref,
            "axes": {
                "standards": standards,   # 规范/坏味道轴
                "spec": spec,             # 忠实实现轴
            },
            "blocked": blocked,
            "recommended_disposition": ("fix_bug" if blocked else "proceed"),
            "note": (
                "双轴并行独立评审，互不污染；存在必修即打回。"
                if blocked else
                "双轴均达标，可放行。"
            ),
        }
        return axis_report
