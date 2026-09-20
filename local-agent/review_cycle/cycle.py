# -*- coding: utf-8 -*-
"""评审段调度器 · 确定性引擎（cycle）—— 见 __init__ 文档。"""
import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from review_cycle import spec
from review_cycle import stage_spec
from review_cycle import gate as _gate_mod
from review_context import engine as ctx_engine
from review_context.paths import repo_root as _repo_root

# 可选依赖（缺失即降级，不崩）：评审角色 / 回写桥 / 哨兵
try:
    from collab import disposition
except Exception:  # noqa: BLE001
    disposition = None


# ---------------------------------------------------------------------------
# 一、评审段状态持久化（本地 JSON；跨项目可抽取，不依赖数据层）
# ---------------------------------------------------------------------------
_STATE_LOCK = threading.Lock()
_STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "state", "review_cycles.json")


def _load_state():
    import json
    try:
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_state(data):
    import json
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 一.5、状态机推进（确定性 · S5：spec.STATES/TRIGGERS 声明必须真被读取）
# ---------------------------------------------------------------------------
def advance_state(current, trigger, dispatched=False, reused=False,
                  select_error=""):
    """依据「触发门控 + 本轮事实」确定性推进评审段状态（不让 LLM 决定下一步）。

    规则（与 spec.TRIGGER_STATE / spec.STATE_TRANSITIONS 同源，不各自取名）：
      - 选测失败（select_error）→ 停在 collecting（拿不到测试信号，不得进 reviewed）；
      - 真发车（dispatched）→ 走到 reviewed（本轮内 collect→dispatched→reviewed）；
      - 复用轮（reused）→ 走到 reviewed（零构建，引用上轮信号）；
      - 其余 → 保持当前状态。
    目标状态若与当前不直接相邻，沿 spec.STATE_TRANSITIONS **逐跳走合法路径**（如
    idle → collecting → dispatched → reviewed）；无合法路径 → 显式抛错，不静默放行。
    """
    if current not in spec.STATES:
        raise ValueError("未知评审段状态: %r" % (current,))
    if trigger not in spec.TRIGGERS:
        raise ValueError("未知触发门控: %r" % (trigger,))
    if select_error:
        target = "collecting"
    elif dispatched or reused:
        target = "reviewed"
    else:
        target = current
    return walk_to(current, target)


def walk_to(current, target):
    """沿 spec.STATE_TRANSITIONS 逐跳走到目标状态（BFS 最短路径，确定性）。

    无合法路径 → 显式抛错（不静默放行）；`current == target` 原样返回。
    """
    if current not in spec.STATES:
        raise ValueError("未知评审段状态: %r" % (current,))
    if target not in spec.STATES:
        raise ValueError("未知目标状态: %r" % (target,))
    if target == current:
        return current
    queue = [current]
    seen = {current}
    while queue:
        node = queue.pop(0)
        for nxt in spec.STATE_TRANSITIONS.get(node, ()):
            if nxt in seen:
                continue
            if nxt == target:
                return nxt
            seen.add(nxt)
            queue.append(nxt)
    raise ValueError("非法状态迁移（无合法路径）: %s → %s" % (current, target))


# ---------------------------------------------------------------------------
# 二、轮次（round）—— 同一评审段的多轮迭代，靠指纹判定"是否真需要跑"
# ---------------------------------------------------------------------------
class Round(object):
    """一轮评审轮次（幂等：同 task_key + 同内容指纹永不重复触发开发/构建）。"""

    def __init__(self, task_key, index, diff_fp, pack_fp,
                 dispatched=False, reused=False, tests=None, disposition_label="",
                 cost=None, state="idle", select_error="", trigger="",
                 stage_gate=None, gate_blocked=False, node=""):
        self.task_key = task_key
        self.index = index
        self.diff_fp = diff_fp
        self.pack_fp = pack_fp
        self.dispatched = dispatched      # 本轮是否真的发了构建（False=复用，省 CPU）
        self.reused = reused              # 是否命中复用（免重复开发/构建）
        self.tests = list(tests or [])
        self.disposition = disposition_label
        self.cost = cost or {}
        self.state = state
        # 本轮命中的触发门控（spec.TRIGGERS 之一，S5：声明真被读取）
        self.trigger = trigger
        # 选测失败显式留痕（不静默吞：空串=无错，非空=真实故障信息）
        self.select_error = select_error
        # 阶段链门控判决（Issue #150 打断补齐）：非 None 表示本轮触发前过了门控
        self.stage_gate = stage_gate or {}
        # 本轮是否**被阶段门驳回**（N4）：驳回轮既非真发车、也非"复用省构建"，
        # 不得计入 reused/avoided_builds（省量口径不得虚增）
        self.gate_blocked = bool(gate_blocked)
        # 本轮落在评审段的哪个节点（读 spec.NODES/STATE_NODE，P5：声明真被读取）
        self.node = node

    def to_dict(self):
        return {
            "task_key": self.task_key, "round": self.index,
            "diff_fp": self.diff_fp, "pack_fp": self.pack_fp,
            "dispatched": self.dispatched, "reused": self.reused,
            "tests": self.tests, "disposition": self.disposition,
            "cost": self.cost, "state": self.state, "trigger": self.trigger,
            "select_error": self.select_error,
            "stage_gate": self.stage_gate,
            "gate_blocked": self.gate_blocked,
            "node": self.node,
        }


# ---------------------------------------------------------------------------
# 三、调度器
# ---------------------------------------------------------------------------
class Scheduler(object):
    """评审段调度器：增量收集 → 攒批触发 → 增量上下文回评审。

    dry_run=True（默认）：不真跑 CPU 密集测试，只产出等效计划与成本账
                          （供本地/CI 确定性单测；真实执行由宿主显式打开）。
    """

    def __init__(self, dry_run=True, root_dir=None, interval=None, bus=None,
                 gate=None, stage="review"):
        self.dry_run = dry_run
        # 变更清单不可用时的显式说明（🟢：git 不可用不静默当"无变更"，留痕区分）
        self.select_note = ""
        # 本调度器驱动的是**阶段链上的哪一环**（默认评审环；测试环传 stage="testing"）
        self.stage = stage
        # 阶段链门控器（Issue #150 打断补齐）：开发未收口即不许抢跑测试/评审
        self._gate = gate
        self.gate = gate
        # 仓库根走**唯一事实源** review_context.paths.repo_root()（S8：与评审角色同口径，
        # 不再两处各自 dirname 导致语义分裂）
        self.root_dir = root_dir or _repo_root()
        self.interval = interval or spec.DEFAULT_INTERVAL_SECONDS
        self._bus = bus

    # ---------- 阶段链门控器（懒加载；允许外部注入做隔离） ----------
    def _gate_runner(self):
        if self._gate is not None:
            return self._gate
        self._gate = _gate_mod.StageGate()
        return self._gate

    # ---------- 评审段节点表（S5/P5：spec.NODES 声明**真被读取**，不各自取名） ----------
    def segment_nodes(self):
        """评审段内部节点表（读唯一事实源 `spec.NODES`）。

        返回 [{"id","role","action","node_order"}]；供 CLI/大盘/测试读取，
        避免"声明了 NODES 却没人用"（复评 P5）。
        """
        return [dict(n, node_order=i) for i, n in enumerate(spec.NODES)]

    @staticmethod
    def node_of_state(state):
        """状态 → 承载节点 id（唯一事实源 `spec.STATE_NODE`）。"""
        return spec.STATE_NODE.get(state, "")

    # ---------- 攒批通道：入列 0 成本，到点/显式 flush 才发车 ----------
    def _bus_runner(self):
        if self._bus is not None:
            return self._bus
        from hybrid.bus import BusRunner
        self._bus = BusRunner(dry_run=self.dry_run, timeout=300)
        return self._bus

    # ---------- 变更感知选测（同 diff 指纹不重复选、不重复跑） ----------
    def _select_tests(self, diff_fp, changed_files=None):
        """按变更文件做增量选测；无增量信息 → 返回空（由评测段跳过构建）。

        changed_files: 显式传入变更文件清单（供测试/调用方注入，替代 git diff）。

        选测失败**不静默吞**（对齐 dev-standard C01「错误处理不吞异常」）：
        异常上抛，由调用方显式降级并留痕，避免"看起来没变更"掩盖真实故障。
        """
        changed = (list(changed_files) if changed_files is not None
                   else self._changed_files())
        if not changed:
            return []
        from hybrid.selector import IncrementalSelector
        # 注意：`default_selector` 是**实例**不是工厂函数，不可当函数调用；
        # 这里显式实例化，避免 TypeError 被吞后恒返回 []（评审段永不发车）。
        sel = IncrementalSelector(root_dir=self.root_dir)
        return list(sel.select(changed) or [])

    @staticmethod
    def _dedup_fp(diff_summary, task_key=""):
        """去重键 = 真实变更内容指纹 + 任务/批次键（与 reviewer._dedup_key 同口径）。

        空/缺省 `diff_summary` → 返回 ""（视为**无指纹**，不占门、不去重），
        避免退化为空串常量哈希造成跨任务静默跳过（S1）。
        """
        text = (diff_summary or "").strip()
        if not text:
            return ""
        return ctx_engine.fingerprint({"diff_summary": text,
                                       "task_key": (task_key or "").strip()})

    def _changed_files(self):
        """变更文件清单（确定性回退链，兼容本地开发与 CI/PR 两种场景）。

        - 本地开发：工作区未提交变更（`git diff` + `--cached`）；
        - CI/PR：工作区干净，回退到与**基线分支**的 diff（origin/main → main → HEAD~1）。
        无任何可用基线/变更 → 返回空（调用方可显式传 `changed_files` 注入）。
        """
        import subprocess
        candidates = (
            ["git", "diff", "--name-only"],
            ["git", "diff", "--cached", "--name-only"],
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            ["git", "diff", "--name-only", "main...HEAD"],
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
        )
        for cmd in candidates:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      cwd=self.root_dir, timeout=30)
            except Exception:  # noqa: BLE001
                continue
            if proc.returncode != 0:
                continue
            files = [x for x in proc.stdout.splitlines() if x.strip()]
            if files:
                return files
        # git 全部候选不可用（返回码非 0 / 异常）与「真的无变更」语义不同：
        # 留一条 self.select_note 显式区分，避免"看起来没变更"掩盖真实故障（C01）。
        self.select_note = ("git 不可用或无基线：变更清单为空（调用方可显式传 "
                            "changed_files 注入）")
        return []

    # ---------- 主入口：跑一轮（或增量多轮）评审段 ----------
    def run(self, task_key, stable=None, volatile=None, prev_pack=None,
            max_rounds=1, round_volatiles=None, force=False, changed_files=None):
        """跑一轮（或多轮）评审段。

        参数：
          task_key:        任务标识（同一任务二次触发不漂移）
          stable:          稳定骨架（构建一次 → 冻结）
          volatile:        本轮变化片段
          prev_pack:       上一轮 review_context pack（用于复用冻结骨架）
          max_rounds:      连续跑几轮（模拟"评审→开发增量→再评审"的可控迭代）
          round_volatiles: 每轮的 volatile 列表（覆盖 volatile）
          force:           强制发车（忽略复用判定，供首次/验证用）
          changed_files:   显式变更文件清单（替代 git diff；供测试/调用方注入）

        返回 {task_key, rounds[], stats, context, bus, state}
        """
        cycles = _load_state()
        rec = cycles.get(task_key) or {"task_key": task_key, "rounds": [],
                                       "processed_fps": [], "state": "idle"}
        processed = set(rec.get("processed_fps", []))
        rounds = []
        pack = prev_pack
        volatiles = round_volatiles or [volatile or {}]
        bus_state = None   # 最后一班车的站台状态（供返回/俯瞰；无发车则 None）
        # 起始状态：上一段已 done（终态）→ 本次是**新评审段**，从 idle 重新走
        # （避免终态后再迁移被状态机拒绝；确定性，不做隐式重置）
        prev_state = rec.get("state") or "idle"
        cur_state = "idle" if prev_state == "done" else prev_state

        for i in range(min(max_rounds, len(volatiles))):
            vol = dict(volatiles[i] or {})
            # ① 增量上下文：只吃 (冻结骨架摘要 + 本轮变化)
            pack = ctx_engine.build(stable or {}, vol, prev=pack, task_key=task_key)
            # ② 触发门控：diff 指纹已处理过且非强制 → 不重复触发开发/构建
            #    去重键掺入 task_key（与 reviewer._dedup_key 同口径，防跨任务误命中）
            diff_fp = self._dedup_fp(vol.get("diff_summary", ""), task_key)
            already = (diff_fp in processed) and not force
            trigger = "diff_changed" if not already else "fingerprint_new"
            select_error = ""
            if already:
                tests = []
            else:
                # 选测失败**不静默吞**（C01）：显式捕获并留痕到本轮，降级为"不拉构建"
                try:
                    tests = self._select_tests(diff_fp, changed_files=changed_files)
                except Exception as e:  # noqa: BLE001
                    tests = []
                    select_error = "%s: %s" % (type(e).__name__, e)

            # ③ 阶段链门控（Issue #150 打断补齐）：本该串行，不得并行抢跑/重复触发
            #    上游（开发）未收口 → 驳回；本阶段已在跑 → 复用（不新起任务/不冲进度）
            gate = self._gate_runner()
            # 走 `admit`（判定 + 判决计数 + 放行才登记活跃）——裸 should_trigger 不计数，
            # 会让 gate.overview() 的 gates 恒为 0（复评 P1）。
            gv = gate.admit(task_key, self.stage, force=force,
                            note="评审段 %s 第 %d 轮" % (task_key, i + 1))
            _gate_mod.record_gate(gv)

            # ④④ 攒批入列（0 成本）→ 本轮调度点整批发车（一次构建跑完一批）
            #    门控驳回 → **不触发任何构建**（这正是"乱触发"要拦下的那部分）
            plan = None
            dispatched = False
            if tests and not already and gv["allow"]:
                bus = self._bus_runner()
                # S3c：本轮 diff_fp 必须**显式交给 bus**（走 enqueue 携带，勿再 dispatch
                # 重复登记）——否则调度路径"同 diff 不重复触发"实际失效，且队列残留他方
                # 指纹时会把别人的指纹记成自己的（复评 S3c）。
                bus.enqueue(tests, source="review_cycle", diff_fp=diff_fp,
                            note="评审段 %s 第 %d 轮" % (task_key, i + 1))
                plan = bus.dispatch(note="review_cycle %s r%d" % (task_key, i + 1))
                dispatched = True
                bus_state = bus.status()
                trigger = "batch_ready"

            # ⑤ 以测试为准：整批信号决定处置（无测试/复用时引用上轮信号）
            #    门控驳回 → 阶段未真正推进，不给 merge/proceed（不假装放行）
            test_signals = self._test_signals(plan, vol, already)
            if not gv["allow"]:
                disp = self._dispose_blocked(gv)
                rnd = Round(task_key, i + 1, diff_fp, pack["stable_fp"],
                            dispatched=False,
                            # N4：驳回轮**既非真发车、也非"复用省构建"**——
                            # 一律不计 reused（否则 reused_rounds/avoided_builds 虚增）
                            reused=False, tests=tests,
                            disposition_label=disp, cost=self._cost(None, pack),
                            state="blocked", select_error=select_error,
                            trigger="gate_blocked", stage_gate=gv,
                            gate_blocked=True,
                            node=self.node_of_state("idle"))
                rounds.append(rnd)
                # N2：被驳回的轮次**不得**把 diff_fp 记入 processed（否则上游事后收口、
                # 同一份 diff 也永不发车 → 门控把主路径打死且不可自愈）
                rec["rounds"].append(rnd.to_dict())
                rec["stage_gate"] = gv
                continue
            disp = self._dispose(test_signals, vol, reused=already)

            # ⑥ 状态机确定性推进（spec.STATES/TRIGGERS 真被读取，S5）
            cur_state = advance_state(cur_state, trigger,
                                      dispatched=dispatched, reused=already,
                                      select_error=select_error)

            # ⑦ 回评审（增量上下文）：评审只吃 pack["context"]
            rnd = Round(task_key, i + 1, diff_fp, pack["stable_fp"],
                        dispatched=dispatched, reused=already, tests=tests,
                        disposition_label=disp, cost=self._cost(plan, pack),
                        state=cur_state, select_error=select_error,
                        trigger=trigger, stage_gate=gv,
                        node=self.node_of_state(cur_state))
            rounds.append(rnd)
            if diff_fp:
                processed.add(diff_fp)
            rec["rounds"].append(rnd.to_dict())
            # 本轮段已跑完 → 登记本阶段收口（链条交回下游；下一轮重新按链推进）。
            # 这样多轮 run 内不会把"自己持有的进行中阶段"误判成外部重复触发
            # （blocked_active），同时保证 run 结束后链条确实是"未在跑"状态。
            if dispatched or already:
                gate.mark_done(task_key, self.stage)

        # N2：本轮段真推进过（有真发车/复用轮）→ 登记**本阶段收口**，把链交回下游。
        # 这是生产路径的 mark_done 接线点（此前只存在于 demo/测试脚本 → 评审段永不发车）。
        advanced = any(r.dispatched or r.reused for r in rounds)
        if advanced:
            gate.mark_done(task_key, self.stage)

        # 跑完本轮段：有轮次则落 done（评审段完成，走合法路径校验），无轮次保持 idle
        if rounds:
            cur_state = walk_to(cur_state, "done")
        rec["processed_fps"] = sorted(processed)
        rec["state"] = cur_state
        rec["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with _STATE_LOCK:
            cycles[task_key] = rec
            full = _load_state()
            full[task_key] = rec
            _save_state(full)

        return {
            "task_key": task_key,
            "rounds": [r.to_dict() for r in rounds],
            "context": pack.get("context") if pack else "",
            "bus": bus_state,
            "state": rec["state"],
            "stats": self.stats(),
        }

    # ---------- 内部：测试信号（以测试为准，不靠看法） ----------
    def _test_signals(self, plan, vol, reused):
        if reused:
            return {"light": "♻️", "note": "同变更指纹已处理 → 复用上轮测试信号，本轮零构建"}
        if plan is None:
            return {"light": "🟡", "note": "无受影响测试（变更未命中/无增量）→ 不拉构建"}
        s = plan.get("summary", {})
        fail = s.get("fail", 0)
        return {"light": "🟢" if not fail else "🔴",
                "total": s.get("total"), "fail": fail,
                "pass": s.get("pass"),
                "note": "整批一次构建跑完：%s 项，fail=%s" % (s.get("total"), fail)}

    # ---------- 内部：被阶段门驳回了该给什么处置标签 ----------
    def _dispose_blocked(self, verdict):
        """门控驳回 ≠ 质量结论：**必须给非放行标签**（复评 N3）。

        此前映射到 `proceed` 是**错的**——`proceed` ∈ `reviewer.PASS_DISPOSITIONS`
        （`passes_to_tester("proceed") is True`），会让"一个测试都没跑"的驳回轮
        照样转交测试、给出假绿放行。

        正确口径：驳回 = 「链条本该按序推进，此刻这一环被门控驳回」→ 规范处置标签
        **`blocked`（链式未推进·待上游收口）**，它是 `collab.disposition` 唯一事实源里的
        非放行标签（`route=resume_chain`），**不**在 PASS_DISPOSITIONS 内，不转交测试。
        """
        if disposition is None:
            return "blocked"
        problem = "阶段链门控驳回(%s)" % verdict.get("decision", "")
        label = disposition.dispose(problem=problem, label="blocked").get(
            "disposition", "blocked")
        # 兜底纠正：任何"放行"语义标签都不得出现在驳回轮（防回归）
        if label in ("merge", "proceed"):
            label = "blocked"
        return label

    # ---------- 内部：处置（复用统一审查处置标签，不各自取名） ----------
    def _dispose(self, signals, vol, reused):
        if disposition is None:
            return "proceed"
        if signals.get("light") == "🔴":
            return disposition.dispose(problem="", signals=["defect"],
                                       severity="🔴").get("disposition", "fix_bug")
        return disposition.dispose(problem="", severity="🟢").get("disposition",
                                                                 "merge")

    # ---------- 内部：成本（省下的 CPU + 省下的复述 token） ----------
    def _cost(self, plan, pack):
        cost = {
            "dispatched": plan is not None,
            "batches": 1 if plan is not None else 0,
            "tests": len(plan.get("summary", {}).get("total", [])) if plan
            and isinstance(plan.get("summary", {}).get("total"), list)
            else plan.get("summary", {}).get("total") if plan else 0,
            "context_saved_chars": pack.get("saved_chars", 0),
            "context_saved_tokens": ctx_engine.estimate_saved_tokens(pack),
        }
        if plan is not None:
            fin = plan.get("finish", {}) or {}
            cost["net_save"] = (fin.get("cost") or {}).get("net_save", 0)
        return cost

    # ---------- 俯瞰：省下的成本报表 ----------
    def stats(self):
        """全局统计：几轮真发了构建 / 几轮复用 / 省下多少（供人类俯瞰）。"""
        cycles = _load_state()
        total_rounds = dispatched = reused = 0
        saved_tokens = 0
        batches = 0
        blocked = 0
        gates = {k: 0 for k in stage_spec.GATE_DECISIONS}
        for rec in cycles.values():
            for r in rec.get("rounds", []):
                total_rounds += 1
                if r.get("dispatched"):
                    dispatched += 1
                    batches += r.get("cost", {}).get("batches", 0)
                # N4：只有**真复用**（同指纹零构建）才计入 reused；
                # 被阶段门驳回的轮次（gate_blocked）既未发车也未省构建，不得虚增省量
                if r.get("reused") and not r.get("gate_blocked"):
                    reused += 1
                if r.get("state") == "blocked" or r.get("gate_blocked"):
                    blocked += 1
                g = r.get("stage_gate") or {}
                d = g.get("decision")
                if d in gates:
                    gates[d] += 1
                saved_tokens += r.get("cost", {}).get("context_saved_tokens", 0)
        avoided = reused  # 被复用拦下的构建次数 = 省下的构建
        select_errors = sum(
            1 for rec in cycles.values() for r in rec.get("rounds", [])
            if r.get("select_error"))
        return {
            "module": spec.MODULE,
            "module_version": spec.MODULE_VERSION,
            "tasks": len(cycles),
            "rounds": total_rounds,
            "dispatched_builds": dispatched,
            "batched_runs": batches,
            "reused_rounds": reused,
            "avoided_builds": avoided,
            "select_error_count": select_errors,   # S7：选测故障不静默
            "context_saved_tokens": saved_tokens,
            # ---- 阶段链门控（Issue #150 打断补齐）：拦下多少"乱触发"（重复/抢跑/乱序）----
            "stage_gates": gates,
            "blocked_rounds": blocked,
            "blocked_retriggers": (gates.get("blocked_active", 0)
                                  + gates.get("blocked_upstream", 0)
                                  + gates.get("blocked_switched", 0)),
            "note": ("攒批把 N 次构建收敛为每轮 1 批；复用把同指纹轮次构建收敛为 0；"
                     "阶段门把「本该串行却并行/重复触发」拦下（blocked_retriggers）"),
        }

    def overview(self):
        """全局俯瞰：每个任务的评审段轮次表 + 成本报表。"""
        cycles = _load_state()
        return {
            "module": spec.MODULE,
            "nodes": self.segment_nodes(),   # P5：NODES 声明真被读取并透出
            "stats": self.stats(),
            "cycles": {
                k: {"state": v.get("state"),
                    "rounds": len(v.get("rounds", [])),
                    "dispatched": sum(1 for r in v.get("rounds", [])
                                      if r.get("dispatched")),
                    "reused": sum(1 for r in v.get("rounds", [])
                                  if r.get("reused")),
                    # S7：选测失败已持久化到轮次，俯瞰必须透出（不静默藏）
                    "select_errors": [
                        r.get("select_error") for r in v.get("rounds", [])
                        if r.get("select_error")],
                    "blocked": sum(1 for r in v.get("rounds", [])
                                   if r.get("state") == "blocked"),
                    "active_stage": (v.get("stage_gate") or {}).get("stage", ""),
                    "updated_at": v.get("updated_at")}
                for k, v in cycles.items()
            },
            # S7：全局 select_error 计数（人类/哨兵一眼看到有无选测故障）
            "select_error_count": sum(
                1 for v in cycles.values() for r in v.get("rounds", [])
                if r.get("select_error")),
        }

    def reset(self):
        """清空调度状态（仅供测试隔离）。"""
        with _STATE_LOCK:
            _save_state({})


default_scheduler = Scheduler()
