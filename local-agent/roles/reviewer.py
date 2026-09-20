# -*- coding: utf-8 -*-
"""架构·评审：评审主流程（双轴强制）+ 统一处置标签 + 评审通过后真实转交测试。

与 settings.yml 同源。本角色评审必走**评审主流程统一入口 `do_review()`**：
先把评审拆成**双轴（Standards ∥ Spec）并行独立、互不污染**强制产出，
再按必改优先原则落到统一处置标签，最后路由（🔴必修打回开发 / 通过转交测试）。

评审通过（merge/proceed）后**必须把任务真实转交给「架构·测试」**——用完整
`@org/repo(架构·测试)` + `[触发:架构·测试]` 投接力卡唤醒测试接单，而非只描述"交下游接力"。

修复 Issue #98 遗留（评审机制不全）：双轴评审不再只是"就绪可调能力方法"，
而是**评审必走闸门**——`do_review()` 强制先产出双轴、缺任一轴即评审不完整，
机器可核验（`dual_axis_review` 返回 `axes_complete`），杜绝"评审走单轴混评漏双轴"。

Issue #150（减 CPU 损耗）：评审不再"每次复述整个大项目 / 每轮拉起一次构建"——
`build_review_context` 用**评审上下文增量复用**（冻结骨架摘要 + 本轮变化，免逐轮复述），
`prepare_review_batch` 用**攒批触发门控**（入列 0 成本 + 一次发车整批跑完 + 同变更指纹
不重复触发构建），两者都在 `do_review` 主流程内自动接线（可关）。
"""
import os

from .base import BaseRole

try:
    from collab import disposition
except Exception:  # noqa: BLE001
    disposition = None


# 评审通过 → 可放行转交测试的规范处置标签（其余需回转/调研/会诊/交人/等上游收口）
# 注意（N3）：`blocked`（阶段链门控驳回）**必须不在**此集合内——它非放行、不转交测试。
PASS_DISPOSITIONS = ("merge", "proceed")


class ReviewerRole(BaseRole):
    name = "架构·评审"

    SYSTEM_PROMPT = """
你是「架构·评审」，本团队代码质量守门员。接手必交（**评审主流程统一入口 do_review**）：
- 双轴评审（**必走闸门**）：拆 **Standards 轴**（规范/坏味道：语法/异味/最佳实践/性能/重复）
  与 **Spec 轴**（忠实实现源 issue/spec：目标/做不做边界/验收标准）**并行独立评审、
  互不污染**——任一轴缺失即评审不完整，不视为有效评审，机器可核验 axes_complete。
- 分级：🔴必修 / 🟡建议 / 🟢优化
- 统一处置标签：**每次评审必须给出一个规范处置标签**（不能漏、不能自定义），
  从规范集合中取：merge(适合合并)/proceed(适合推进)/fix_bug(适合改bug)/
  research(适合调研)/human(适合移交人类判断)/consult(适合专家会诊)/vote(适合投票)
- 仅评改动新增/改动行

效率纪律（Issue #150 · 减 CPU 损耗）：
- **不复述整个项目**：评审前先 `build_review_context(stable, volatile, prev)` 拿增量上下文
  （冻结骨架摘要 + 本轮变化），评审只吃 `context` 字段；骨架来源没变则零成本复用；
- **不逐轮拉构建**：测试一律先 `prepare_review_batch` 攒批入列（0 成本），一次发车整批跑完；
  **同一变更指纹已跑过 → 不重复触发开发/构建**（指纹去重门），只引用上轮结论。

协作纪律：
- 🔴必修项必须指出并推动修复，复评至清零才放行；结论发回接力卡供下游接力。
- **评审通过（处置标签=merge/proceed）后必须真实转交「架构·测试」**：用完整
  `@org/repo(架构·测试)` + `[触发:架构·测试]` 投接力卡唤醒测试接单，并校验
  `awakened` 回执——**不得只描述"交测试接力"而不真正唤醒**，转交未回执须重触发或升级。

触达协议：显式[触发:架构·评审]/语义命中"评审/审查/走查/质量"即进入本角色；
发现🔴必修必须打回——评论须带完整 `@org/repo(架构·开发)` + `[触发:架构·开发]` +
`[回转] 退回:架构·开发`（全路径出发，缺完整 @ 即假触发），复评清零才放行。
统一处置标签：处置标签是评审输出契约的**必填字段**，缺标签即评审未完成。
双轴必走：评审须先产出 Standards ∥ Spec 双轴、缺任一轴即评审不完整，禁止单轴混评放行。
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "评审主流程(do_review: 双轴强制→处置→路由 一站式闭环)",
                "双轴评审(dual_axis_review: Standards∥Spec 互不污染, 必走闸门, 缺任一轴即不完整)",
                "分级(severity: 🔴/🟡/🟢)",
                "统一处置标签(disposition: merge/proceed/fix_bug/research/human/consult/vote)",
                "复评结论(recheck)",
                "**评审通过后转交测试(handoff_to_tester: 完整@ + [触发:架构·测试] + 校验回执)**",
            ],
        }

    # ------------------------------------------------------------
    # 评审增量上下文（Issue #150 · 免逐轮复述整个大项目）
    # ------------------------------------------------------------
    def build_review_context(self, stable_parts=None, volatile_parts=None,
                             prev=None, task_key=""):
        """构建**评审增量上下文**：冻结骨架摘要 + 本轮变化（不必复述整个项目）。

        用户痛点（Issue #150）：项目一大，评审"每次复述项目非常困难"。
        解法：稳定骨架（目标/边界/验收/契约/决策）构建一次即**冻结**，评审每轮只引用
        其摘要；本轮变化（diff/测试信号/发现）才逐轮传。骨架来源指纹未变 → 零成本复用。

        返回 review_context.engine.build() 的 pack（含 `context` = 喂给评审的最小上下文）。
        """
        try:
            from review_context import engine as _ctx
        except Exception:  # noqa: BLE001
            return {"available": False, "context": "", "reuse": {"reusable": False}}
        pack = _ctx.build(stable_parts or {}, volatile_parts or {},
                          prev=prev, task_key=task_key)
        pack["available"] = True
        return pack

    # ------------------------------------------------------------
    # 攒批触发门控（Issue #150 · 免逐轮拉构建 / 同指纹不重复触发）
    # ------------------------------------------------------------
    def prepare_review_batch(self, task_key="", changed_files=None,
                             extra_tests=None, diff_summary="", dry_run=True,
                             force=False, flush=True, stage="review",
                             gate=None):
        """评审跑测试前先**攒批**：入列 0 成本 → 一次发车整批跑完；同指纹不重复构建。

        用户痛点（Issue #150）："每次触发评审之后跑开发，然后评审……触发大量的 CPU
        构建和 CPU 开发的损耗"。解法四条：

          ① **攒批**：受影响测试先入列（0 成本），再在本调度点一次发车整批跑完
             —— 一次冷启动摊全批（N 个测试从 N 次构建收敛为 1 次）；
          ② **指纹去重门**：同一变更指纹**已真发过车** → **不重复触发构建**，只引用上轮结论；
          ③ **变更感知选测**：只跑受变更影响的测试（复用 hybrid.selector，不各自取名）；
          ④ **阶段链门控（本 Issue 打断补齐）**：本该串行的链条不得并行触发——
             上游（开发）未收口就抢跑测试/评审 → **直接驳回、不起任何构建**；
             本阶段已在跑（重复触发）→ 复用进行中的任务，**不新起、不冲进度**。
             `force=True` 是显式逃生门（"我知道在抢跑/复用"）。

        去重键控（Issue #150 返工 S1/S2 修正）：
          - 指纹 = `fingerprint(diff_summary)` **且** 掺入 `task_key`（批次键）——
            去重键 = 「真实变更内容指纹 + 任务/批次」，防跨任务误命中；
          - `diff_summary` **缺省/空** → 视为**无指纹**（`diff_fp=None`），**不占门**、
            不做去重（而非退化为空串常量哈希造成跨任务静默跳过）；
          - `dry_run=True`（演练）**不写穿**持久化去重门，真实执行不会被演练静默跳过。

        返回 {ok, diff_fp, selected, bus, plan, skipped, reason, cost_note, gate}
        （返回键同时含 diff_fp 去重键与 gate 阶段门判决）
        """
        # ---- 阶段链门控（先判链、再谈攒批；驳回即零构建，正是"乱触发"要拦下的）----
        # 走 `admit`（判定 + 判决计数 + 放行才登记活跃），不用裸 should_trigger——
        # 否则 overview 的 gates 计数拿不到数据（复评 P1）。
        from review_cycle.gate import StageGate, record_gate
        g = gate or StageGate()
        gv = g.admit(task_key, stage, note="评审攒批触发", force=force)
        record_gate(gv)
        if not gv["allow"]:
            return {"ok": True, "skipped": True, "diff_fp": None,
                    "selected": [], "bus": None, "plan": None,
                    "gate": gv, "reused": gv.get("reused", False),
                    "reason": "[阶段门:%s] %s" % (gv["decision"], gv["reason"]),
                    "cost_note": "阶段门驳回 → 零构建（拦下一次乱触发）"}

        try:
            from hybrid.bus import BusRunner
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": "hybrid.bus 不可用: %s" % e,
                    "selected": [], "skipped": True, "gate": gv}
        # ---- 去重键 = 真实变更内容指纹 + 任务/批次键（S1）----
        diff_fp = self._dedup_key(diff_summary, task_key)

        bus = BusRunner(dry_run=dry_run, timeout=300)
        # ---- 指纹去重门：同一指纹已**真发过车** → 不重复触发构建 ----
        # 无指纹（缺省 diff_summary）不占门，直接放行去跑（S1：缺省不得退化为常量指纹）
        if diff_fp and not force and bus.is_processed(diff_fp):
            return {"ok": True, "skipped": True, "diff_fp": diff_fp,
                    "selected": [], "bus": None, "plan": None, "gate": gv,
                    "reason": "同变更指纹已发过车（指纹去重门）→ 不重复触发构建",
                    "cost_note": "省下一次构建冷启动"}

        # ---- 变更感知选测（失败不静默吞：留痕 select_error 并降级为"不拉构建"）----
        selected = []
        select_error = ""
        if changed_files:
            try:
                from hybrid.selector import IncrementalSelector
                sel = IncrementalSelector(root_dir=self.review_repo_root())
                selected = list(sel.select(changed_files) or [])
            except Exception as e:  # noqa: BLE001
                selected = []
                select_error = "%s: %s" % (type(e).__name__, e)
        if extra_tests:
            selected.extend(extra_tests if isinstance(extra_tests, list)
                            else [extra_tests])
        if not selected:
            # S6：选测失败时**不得**照常放行——显式 blocked，交由 do_review 落 fix_bug
            blocked = bool(select_error)
            return {"ok": True, "skipped": True, "diff_fp": diff_fp,
                    "selected": [], "bus": None, "plan": None, "gate": gv,
                    "select_error": select_error,
                    "blocked": blocked,
                    "reason": ("变更选测失败（%s）→ 不拉构建，且不得放行" % select_error)
                    if select_error else "变更未命中任何测试 → 不拉构建",
                    "cost_note": "省下一次构建冷启动"}

        # ---- 攒批入列（0 成本）然后再发车（一次构建摊全批）----
        bus.enqueue(selected, source="review", note="评审测试攒批(%s)" % task_key,
                    diff_fp=diff_fp)
        plan = None
        if flush:
            plan = bus.dispatch(note="评审整批发车(%s)" % task_key, diff_fp=diff_fp)
        summary = (plan or {}).get("summary", {}) or {}
        return {
            "ok": True, "skipped": False, "diff_fp": diff_fp, "gate": gv,
            "select_error": select_error, "blocked": False,
            "dry_run": bool(dry_run),
            "gate_written": bool((plan or {}).get("gate_written")),
            "selected": selected, "bus": bus.status(), "plan": plan,
            "reason": "攒批：%d 个受影响测试作为一批，一次构建跑完" % len(selected),
            "cost_note": "一次冷启动摊全批，省 %d 次构建冷启动" % max(
                0, len(selected) - 1),
            "summary": summary,
        }

    # ------------------------------------------------------------
    # 去重键控 + 仓库根（Issue #150 返工 S1/S8）
    # ------------------------------------------------------------
    @staticmethod
    def review_repo_root():
        """评审相关模块统一用的**仓库根**（唯一事实源，S8：不再两处各自解析）。"""
        try:
            from review_context.paths import repo_root
            return repo_root()
        except Exception:  # noqa: BLE001
            # 兜底：<repo>/local-agent/roles/reviewer.py → 上溯三级
            return os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))

    @staticmethod
    def _dedup_key(diff_summary, task_key=""):
        """去重键 = 「真实变更内容指纹 + 任务/批次键」（S1）。

        - `diff_summary` 缺省/空白 → 返回 **None**（显式视为"无指纹"，不占门）；
        - 否则 `fingerprint({diff_summary, task_key})`——掺入 task_key，使
          **同一变更内容在不同任务下不会被误判为已处理**（跨任务静默跳过被消除）。
        """
        text = (diff_summary or "").strip()
        if not text:
            return None
        try:
            from review_context import engine as _ctx
        except Exception:  # noqa: BLE001
            return None
        return _ctx.fingerprint({"diff_summary": text,
                                 "task_key": (task_key or "").strip()})

    # ------------------------------------------------------------
    # 双轴评审（必走闸门 · Issue #98 · 借鉴 mattpocock code-review 双轴不互相污染）
    # 机器可核验双轴完整：缺任一轴即 axes_complete=False（评审不完整，禁止放行）
    # ------------------------------------------------------------
    @staticmethod
    def _axis_nonempty(axis):
        """判定单轴是否有实质产出（非空 dict 且含可读结论字段）。"""
        if not isinstance(axis, dict) or not axis:
            return False
        # 含 🔴 列表 / blocking / 结论说明 任一字段视为有产出；空列表也视为"评过且无必修"
        has_blocking_field = any(
            k in axis for k in ("blocking", "🔴", "faithful", "pass",
                                "findings", "notes", "note", "issues"))
        return has_blocking_field

    def dual_axis_review(self, source="", diff_scope="", spec_ref="",
                         standards_axis=None, spec_axis=None):
        """评审拆成两轴，各评各的、互不污染（防止一轴结论带偏另一轴）。

        - **Standards 轴**：是否符合仓库规范 + Fowler 坏味道基线（语法/异味/最佳实践/性能/重复）；
        - **Spec 轴**：是否忠实实现源 issue/spec（目标/做不做边界/验收标准是否覆盖）。

        **双轴必走（机器可核验）**：任一侧轴未给出实质产出（axes_complete=False），
        即判定评审**不完整**、不得放行（禁止走单轴混评漏双轴）；补齐双轴才算完整。

        两轴结论**并行独立产出**，最后按「必改优先原则」合并：
          Standards 🔴 必修 或 Spec 不达标 → fix_bug（打回）；
          两轴均达标 → merge/proceed（放行）。
        返回结构化双轴结论，供 `do_review` 主流程使用；`dispose()` 仍作为最终规范处置标签出口。
        """
        standards = standards_axis or {}
        spec = spec_axis or {}
        # 双轴完整性核验：两轴都必须有实质产出（防"只评了一轴/漏轴"）
        standards_ok = self._axis_nonempty(standards)
        spec_ok = self._axis_nonempty(spec)
        axes_complete = standards_ok and spec_ok

        # 汇总两轴必修/通过（仅当轴完整时统计，缺轴不轻率放行）
        standards_block = standards.get("blocking") or standards.get("🔴") or []
        spec_block = spec.get("blocking") or spec.get("🔴") or []
        spec_faithful = spec.get("faithful", spec.get("pass", True))

        # blocked = 轴不完整(未评审全) 或 有必修 或 spec 未忠实实现
        blocked = (not axes_complete) or bool(standards_block) \
            or (not spec_faithful) or bool(spec_block)

        # 生成可读 note（清晰区分：不完整 / 有必修 / 达标 三种情形）
        if not axes_complete:
            missing = []
            if not standards_ok:
                missing.append("Standards")
            if not spec_ok:
                missing.append("Spec")
            note = ("评审不完整：缺 " + "、".join(missing) + " 轴产出。"
                    "双轴必走（Standards∥Spec 互不污染），缺任一轴即评审不完整，"
                    "禁止放行，须补齐双轴。")
        elif blocked:
            note = "双轴已评全但存在必修/spec 不忠实，按必改优先原则打回。"
        else:
            note = "双轴均达标，可放行。"

        axis_report = {
            "source": source,
            "diff_scope": diff_scope,
            "spec_ref": spec_ref,
            "axes": {
                "standards": standards,   # 规范/坏味道轴
                "spec": spec,             # 忠实实现轴
            },
            "axes_complete": axes_complete,
            "blocked": blocked,
            "recommended_disposition": ("fix_bug" if blocked else "proceed"),
            "note": note,
        }
        return axis_report

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
    # 评审有效性深度集成（Issue #100 决策⑤ · review-metrics 接入评审主流程）
    # 评审每次走 do_review 时，自动对"本次处置"做一次确定性观测留痕，
    # 供"评审有效性监控"统计：多少次放行 merge / 打回 fix_bug / 评审不完整。
    # 注意：此处只留"处置观测"（评审当下客观状态），resolution 的"最终是否
    # 真解决"由后续复评/测试回填（见 settle_review），不虚报评审自判有效。
    # ------------------------------------------------------------
    def _record_review_disposition(self, *, disposition_label, blocked,
                                   axes_complete, task_key, source=""):
        """评审处置观测留痕：确定性映射处置状态 → review-metrics 观测。

        - kind=review_disposition：区分于复评回填(review_settled)；
        - 评审当下只记录处置分派状态，不冒充"已解决"；
        - 返回 {trace_id, disposition, blocked, axes_complete, recorded}。
        """
        if not hasattr(self, "measure_review"):
            return {"recorded": False, "reason": "metrics 能力不可用"}
        label = (disposition_label or "").strip().lower()
        # 确定性状态 → 有效性观测（保守，不虚报解决度；语义按客观状态）
        if not axes_complete:
            # 评审不完整：处置本身无效（缺轴即未评全，禁止放行）
            disp_obs = {"resolution": 0.0, "bug_rate": 1.0,
                        "stability": 0.5, "generality": 0.5, "consistency": 0.5}
        elif label in ("merge", "proceed"):
            # 评审放行：处置建议通过（resolution 保守中性，最终以复评回填）
            disp_obs = {"resolution": 0.6, "bug_rate": 0.1,
                        "stability": 0.7, "generality": 0.6, "consistency": 0.7}
        else:
            # fix_bug / research / human / consult：处置为"未通过需返工"
            disp_obs = {"resolution": 0.3, "bug_rate": 0.4,
                        "stability": 0.6, "generality": 0.6, "consistency": 0.6}

        obs = {
            "target": task_key,
            "kind": "review_disposition",
            "dims": {dim: [{"prob": 1.0, "degree": disp_obs[dim]}]
                     for dim in disp_obs},
        }
        meta = {
            "actor": getattr(self, "name", "架构·评审"),
            "task_key": task_key,
            "source": source,
            "disposition": label,
            "blocked": bool(blocked),
            "axes_complete": bool(axes_complete),
            "phase": "review",
        }
        try:
            out = self.measure_review(obs, trace=True, meta=meta)
            return {"recorded": True, "trace_id": out.get("trace_id"),
                    "disposition": label, "blocked": bool(blocked),
                    "axes_complete": bool(axes_complete),
                    "verdict": out.get("verdict", {})}
        except Exception as e:  # noqa: BLE001
            return {"recorded": False, "reason": f"留痕失败: {e}",
                    "disposition": label}

    # ------------------------------------------------------------
    # 评审主流程统一入口（修复"双轴未接入评审主流程"→ 双轴强制必走闸门）
    # 评审一律走 do_review，机器核验双轴完整 + 处置标签，缺双轴/缺标签即评审不完整
    # ------------------------------------------------------------
    def do_review(self, task_key, source="", diff_scope="", spec_ref="",
                  standards_axis=None, spec_axis=None,
                  severity_hint="", issue_ref="", auto_route=True,
                  stable_parts=None, volatile_parts=None, prev_pack=None,
                  changed_files=None, extra_tests=None, dry_run_batch=True,
                  stage="review", gate=None):
        """评审主流程统一入口（**双轴强制 → 处置 → 路由** 一站式闭环）。

        Issue #150 效率接线（不与契约冲突，均可在主流程内关闭/降级）：
          · 传了 `stable_parts/volatile_parts` → 先 `build_review_context` 拿**增量上下文**
            （冻结骨架摘要 + 本轮变化），本轮不再复述整个项目；
          · 传了 `changed_files/extra_tests` → 先 `prepare_review_batch` **攒批**跑测试
            （入列 0 成本 + 一次发车整批 + 同变更指纹不重复触发构建）。
          两者结果写入返回值的 `context_pack` / `batch` 字段，可核验。

        评审不再"散调各方法"，而是**必走本入口**：先强制产出双轴（缺任一轴即
        评审不完整、不进入放行判定），再落规范处置标签，最后按处置路由。

        路由（auto_route=True 时）：
          - 双轴不完整 / 有必修 / spec 不忠实 → disposition=fix_bug → [回转]退回开发；
          - 双轴均达标 → disposition=merge/proceed → 真实转交测试（handoff_to_tester）。

        返回结构化评审主流程报告，供留痕核验；`axes_complete` 与 `disposition`
        双闸门，缺一即评审不完整（不视为有效评审）。另：变更选测失败（`select_error`
        非空）→ `review_complete=False` 且不放行（S6：不得绕过"以测试为准"）。
        """
        # ⓪ Issue #150：评审增量上下文 + 攒批触发门控（先攒批、再评审，省构建省复述）
        context_pack = None
        batch = None
        if stable_parts is not None or volatile_parts is not None:
            context_pack = self.build_review_context(
                stable_parts=stable_parts, volatile_parts=volatile_parts,
                prev=prev_pack, task_key=task_key)
        if changed_files or extra_tests:
            batch = self.prepare_review_batch(
                task_key=task_key, changed_files=changed_files,
                extra_tests=extra_tests,
                diff_summary=(volatile_parts or {}).get("diff_summary", ""),
                dry_run=dry_run_batch, stage=stage, gate=gate)

        # ① 强制双轴评审（必走闸门，机器核验完整性）
        axis_report = self.dual_axis_review(
            source=source, diff_scope=diff_scope, spec_ref=spec_ref,
            standards_axis=standards_axis, spec_axis=spec_axis)

        # ② 双轴不完整 → 处置直接 fix_bug（不能给 merge/proceed 假装评审过）
        if not axis_report["axes_complete"]:
            disposition_result = {
                "disposition": "fix_bug",
                "reason": "双轴未评全（Standards 或 Spec 缺产出），评审不完整，禁止放行",
                "note": axis_report["note"],
            }
            route = self.revert_to_developer(
                task_key,
                reason="评审双轴不完整：" + axis_report["note"],
                next_requirement="补齐 Standards ∥ Spec 双轴后重新提交评审",
            )
            eff = self._record_review_disposition(
                disposition_label="fix_bug", blocked=False,
                axes_complete=False, task_key=task_key, source=source)
            return {
                "task_key": task_key,
                "source": source,
                "context_pack": context_pack,
                "batch": batch,
                "axis_report": axis_report,
                "axes_complete": False,
                "review_complete": False,
                "disposition": "fix_bug",
                "disposition_result": disposition_result,
                "effectiveness": eff,
                "route": route,
                "note": "评审未走完双轴，不完整，禁止放行（打回补齐双轴）。",
            }

        # ②.5 阶段链门控驳回（N3）：**非质量结论、非放行**——不得给 merge/proceed，
        #     也不得转交测试。驳回说明"链条本该按序推进，此刻这一环被门控驳回"，
        #     统一落规范处置标签 `blocked`（`route=resume_chain`，不在 PASS_DISPOSITIONS）。
        gate_verdict = (batch or {}).get("gate") or {}
        gate_blocked = bool(gate_verdict) and not gate_verdict.get("allow", True)
        if gate_blocked and not gate_verdict.get("forced"):
            label = "blocked"
            if disposition is not None:
                label = disposition.dispose(
                    problem="阶段链门控驳回(%s)" % gate_verdict.get("decision", ""),
                    label="blocked").get("disposition", "blocked")
                if label in PASS_DISPOSITIONS:   # 兜底纠正，防回归
                    label = "blocked"
            eff = self._record_review_disposition(
                disposition_label=label, blocked=True,
                axes_complete=True, task_key=task_key, source=source)
            return {
                "task_key": task_key,
                "source": source,
                "context_pack": context_pack,
                "batch": batch,
                "axis_report": axis_report,
                "axes_complete": True,
                "review_complete": False,
                "disposition": label,
                "gate_blocked": True,
                "gate": gate_verdict,
                "disposition_result": {
                    "disposition": label,
                    "reason": "阶段链门控驳回：%s" % gate_verdict.get("reason", ""),
                    "note": "链条按序推进：等上游收口后再触发，本轮零构建、不转交测试。",
                },
                "effectiveness": eff,
                "route": None,
                "route_type": "blocked_chain",
                "note": ("阶段链门控驳回（%s）→ 本轮零构建、不假绿放行、不转交测试；"
                         "等上游阶段收口后按链重新推进。"
                         % gate_verdict.get("decision", "")),
            }

        # ③ 双轴完整 → 按必改优先原则落规范处置标签
        # S6：变更选测失败（select_error）**不得放行**——以测试为准被绕过即 false green。
        # 口径：选测失败 → 本轮拿不到可信测试信号 → 与"有必修"同等级（fix_bug）。
        select_error = (batch or {}).get("select_error", "") or ""
        batch_blocked = bool((batch or {}).get("blocked")) or bool(select_error)
        blocked = bool(axis_report["blocked"]) or batch_blocked
        severity = severity_hint or ("🔴" if blocked else "🟢")
        disp = self.dispose(problem="", severity=severity,
                            signals=["defect"] if blocked else [],
                            scenario_hint=spec_ref)
        disposition_label = (disp.get("disposition") or "fix_bug").lower()
        # 有必修（双轴 / 选测失败）但 dispose 落回 proceed/merge 时兜底纠正为 fix_bug
        if blocked and disposition_label in PASS_DISPOSITIONS:
            disposition_label = "fix_bug"
            disp = {"disposition": "fix_bug",
                    "reason": ("双轴存在必修/spec 不忠实"
                               if axis_report["blocked"]
                               else "变更选测失败（select_error）不可信")
                              + "，纠正放行标签为 fix_bug"}
        # S6：select_error 非空 → 本轮评审**不完整**（拿不到测试信号，不得当"评完放行"）
        review_complete = not select_error

        # ④ 按处置路由
        if auto_route:
            if disposition_label in PASS_DISPOSITIONS and review_complete:
                route = self.handoff_to_tester(
                    task_key, issue_ref=issue_ref,
                    review_summary=(f"双轴均达标(source={source}) "
                                    f"Standards:{axis_report['axes']['standards']} "
                                    f"Spec:{axis_report['axes']['spec']}"),
                    disposition_label=disposition_label)
                route_type = "handoff_to_tester"
            elif disposition_label in ("merge", "proceed"):
                # 理论不可达（放行分支已在上面处理）；兜底不改道，显式暴露
                route = None
                route_type = "manual"
            elif disposition_label == "blocked":
                # 阶段链未推进：不转交测试、也不当质量结论打回开发（等上游收口）
                route = None
                route_type = "blocked_chain"
            else:
                route = self.revert_to_developer(
                    task_key,
                    reason=(f"评审处置={disposition_label}："
                            + (f"变更选测失败 {select_error}，测试信号不可信"
                               if select_error else axis_report["note"])),
                    next_requirement=("按双轴必修项返工，复评清零再放行"
                                      if disposition_label == "fix_bug"
                                      else "按对应处置推进"))
                route_type = "revert_to_developer"
        else:
            route = None
            route_type = "manual"

        # N2 阶段收口（生产路径接线）：评审这一环做完了 → 把链交回下游
        # （放行 → 测试可触发；打回 → 开发可重新触发）。此前无此调用点 → 链条永不推进。
        try:
            from review_cycle.gate import StageGate
            (gate or StageGate()).mark_done(task_key, stage)
        except Exception:  # noqa: BLE001
            pass

        eff = self._record_review_disposition(
            disposition_label=disposition_label,
            blocked=blocked,
            axes_complete=True,
            task_key=task_key, source=source)
        return {
            "task_key": task_key,
            "source": source,
            "diff_scope": diff_scope,
            "spec_ref": spec_ref,
            "context_pack": context_pack,
            "batch": batch,
            "axis_report": axis_report,
            "axes_complete": True,
            "review_complete": review_complete,
            "select_error": select_error,
            "blocked": blocked,
            "disposition": disposition_label,
            "disposition_result": disp,
            "effectiveness": eff,
            "route_type": route_type,
            "route": route,
            "note": (
                "双轴均达标，已按处置路由。" if not blocked
                else ("变更选测失败（%s）→ 测试信号不可信，不得放行。" % select_error
                      if select_error
                      else "双轴存在必修/spec 不忠实，已打回。")),
        }

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
        # #142 机制加固：转交卡一律带完整路径出发（@org/repo(架构·测试) [触发:架构·测试]），
        # 由 fullpath_relay 动态解析目标仓库完整 @ + relay_card.check 校验。
        body = (
            f"评审已通过（处置={label}），任务正式转交。\n"
            f"评审摘要：{review_summary or '见评审评论'}\n"
            f"请按测试输出契约接手：测试矩阵 + 缺陷分级(🔴P0/🟠P1/🟡P2) + 信号灯(🟢/🟡/🔴)。\n"
            f"收到请回执 [接单]，接手后继续推进到结果（缺回执 = 转交未真实唤醒）。"
        )
        relay = self.fullpath_relay(target_role, body=body)
        target_handle = relay["handle"]
        context = relay["relay_text"]
        handle = target_handle

        result = self.awake(task_key, target_role, context=context,
                            issue_ref=issue_ref, from_agent=self.name)
        return {
            "handed_off": result.get("awakened", False),
            "awakened": result.get("awakened", False),
            "awakened_note": result.get("awakened_note", ""),
            "relay_card": result,
            "relay_text": relay["relay_text"],
            "relay_valid": relay["valid"],
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
        """评审 🔴必修 → [回转] 退回:架构·开发（不转交测试）。

        #142 机制加固：回转=被打回视为**重新触发**，必须**带完整路径出发**——
        正文首行 `@dongdongxiaozu/dongjiagoushi(架构·开发) [触发:架构·开发]`
        真实唤醒开发，正文再写 `[回转] 退回:架构·开发 / 原因 / 下一步要求`。
        只写 `[回转] 退回:架构·开发` 而无完整 @ = 想触发没唤醒（假触发），
        由 fullpath_relay 自动补全路径 + relay_card.check 校验。
        """
        body = (
            f"评审 [回转] 退回:架构·开发。\n"
            f"原因：{reason or '🔴必修项未清零'}\n"
            f"下一步要求：{next_requirement or '按评审必修项返工，复评清零再放行'}"
        )
        relay = self.fullpath_relay("架构·开发", action="revert", body=body)
        result = self.awake(task_key, "架构·开发", context=relay["relay_text"],
                            from_agent=self.name)
        return {
            "reverted": result.get("awakened", False),
            "target_role": "架构·开发",
            "reason": reason,
            "relay_card": result,
            "relay_text": relay["relay_text"],
            "relay_valid": relay["valid"],
        }
