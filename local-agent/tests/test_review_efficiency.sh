#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 评审效率 · 减 CPU 损耗测试（信号灯 · Issue #150）
# ============================================================
# 用户痛点：项目一大，评审"每次复述项目非常困难"，跑测试也困难；
#   每次"触发评审→跑开发→评审"效率慢，又触发大量 CPU 构建/CPU 开发损耗。
# 验证三条优化真的接上：
#   1. 评审增量上下文（review-context）：稳定骨架冻结复用 → 不再逐轮复述整个项目；
#   2. 攒批触发门控（review-cycle + hybrid.bus）：入列 0 成本 → 一次发车整批跑完
#      → 同一变更指纹不重复触发构建；
#   3. 接线：评审 do_review 主流程内自动接线；评审段大盘可俯瞰省下的构建/复述。
set -e
cd "$(dirname "$0")/.."
PY=python3
TMPDIR_RC="$(mktemp -d)"
export DB_PATH="$TMPDIR_RC/test_review_efficiency.db"
export HYBRID_CACHE=off
# 测试隔离：攒批队列 / 配额账本落到临时目录，不污染工作区共享状态（保证可重复跑）
export BUS_QUEUE_FILE="$TMPDIR_RC/bus_queue.json"
export QUOTA_LEDGER_FILE="$TMPDIR_RC/quota_ledger.json"
# 阶段链门控状态隔离（Issue #150 打断补齐）：不污染工作区共享链状态，保证可重复跑
export REVIEW_STAGE_FILE="$TMPDIR_RC/review_stages.json"
trap 'rm -rf "$TMPDIR_RC"' EXIT

echo "===== [review-eff] 1. 评审增量上下文：稳定骨架冻结后复用，免逐轮复述 ====="
$PY - <<'PYEOF'
from review_context import engine, spec
assert spec.MODULE == "review-context"
stable = {seg: (seg.upper() * 400) for seg in spec.STABLE_SEGMENTS}
p1 = engine.build(stable, {"diff_summary": "x" * 3000}, task_key="T1")
assert p1["rebuilt"] is True, "首轮必须构建冻结骨架"
p2 = engine.build(stable, {"diff_summary": "只加了一行"}, prev=p1, task_key="T1")
assert p2["reuse"]["reusable"] is True, "骨架来源未变应可复用"
assert p2["rebuilt"] is False, "复用轮不应重建骨架"
assert p2["saved_ratio"] > 0.8, f"复用轮压缩比应显著，实际 {p2['saved_ratio']}"
# 骨架来源变了 → 必须失效重建（不做主观判断）
p3 = engine.build({**stable, "goal": "换了目标"}, {"diff_summary": "y"}, prev=p2)
assert p3["reuse"]["reusable"] is False, "骨架来源变化必须失效"
assert "goal" in p3["reuse"]["changed_segments"]
# S1 回归：变更段必须**重建**，不得复用旧引用（否则评审吃到过期骨架）
assert p3["rebuilt"] is True and p3["frozen"] is False
goal_ref = [r for r in p3["stable_refs"] if r.startswith("[goal]")][0]
assert "换了目标" in goal_ref, f"变更段必须用新值重建，实际 {goal_ref}"
assert p3["stable_refs"][0] != p2["stable_refs"][0], "变更段引用不得等于上轮旧引用"
assert "换了目标" in p3["context"], "context 必须随骨架变更更新（不得吃旧摘要）"
# 未变更段仍复用旧引用（增量重建只重建变更段）
assert p3["stable_refs"][1] == p2["stable_refs"][1], "未变更段应复用旧引用"
print("  ✅ 首轮构建 → 次轮复用(压缩比 %.2f) → 骨架变更即失效" % p2["saved_ratio"])
print("  ✅ S1：变更段重建（goal→%s）+ 未变更段复用 + context 随骨架更新" % goal_ref)
print("      指纹判据: %s" % p2["stable_fp"])
PYEOF

echo "===== [review-eff] 2. 攒批去重门：同变更指纹不重复触发构建（演练不写穿） ====="
$PY - <<'PYEOF'
import tempfile
from hybrid.bus import BusRunner
# --- 2a. 演练：整批一次构建测算 + **不写穿**去重门（S2） ---
qf_dry = tempfile.mktemp(suffix=".json")
bd = BusRunner(queue_file=qf_dry, dry_run=True, interval=0)
r = bd.enqueue(["local-agent/tests/test_a.sh", "local-agent/tests/test_b.sh"],
               diff_fp="fp-150")
assert r["queued"] == 2
plan = bd.dispatch(note="批1", diff_fp="fp-150")
assert plan["dispatched"] == 2 and plan["queued_cleared"] is True
# 一次构建摊全批：2 个测试原本要 2 次冷启动，整批只要 1 次
assert plan["summary"]["cold_starts_naive"] == 2
assert plan["summary"]["cold_starts_batched"] == 1
assert plan["summary"]["cold_start_saved"] == 1
# S2：演练发车**不得**写穿持久化去重门
assert plan["gate_written"] is False, "演练发车不得写穿去重门"
assert bd.processed_fps() == set(), f"演练后门必须为空：{bd.processed_fps()}"

# --- 2b. 真实发车：写门 → 同指纹再入列/再 tick 被拦截 ---
qf = tempfile.mktemp(suffix=".json")
b = BusRunner(queue_file=qf, dry_run=False, interval=0)
b.enqueue(["local-agent/tests/test_probe.sh"], diff_fp="fp-real")
plan2 = b.dispatch(note="批2", diff_fp="fp-real")
assert plan2["gate_written"] is True, "真实发车必须写门"
assert plan2["carried_fps"] == ["fp-real"], plan2["carried_fps"]
assert b.processed_fps() == {"fp-real"}
# 同指纹再次入列 → 拦截，不再触发构建
r2 = b.enqueue(["local-agent/tests/test_probe.sh"], diff_fp="fp-real")
assert r2["queued"] == 0 and r2["skipped_fp"] == "fp-real", r2
t = b.tick(diff_fp="fp-real")
assert t["action"] == "skip", t
print("  ✅ 演练一次构建测算(cold_start_saved=%d)+不写穿；真实发车写门并拦截同指纹" %
      plan["summary"]["cold_start_saved"])
PYEOF

echo "===== [review-eff] 3. 评审角色接线：do_review 内自动 增量上下文 + 攒批 ====="
$PY - <<'PYEOF'
from data import admin
admin.init()
from roles import get_role
from review_cycle.gate import StageGate
r = get_role("架构·评审")
assert hasattr(r, "build_review_context")
assert hasattr(r, "prepare_review_batch")
# 阶段链门控（本 Issue 补齐）：先让上游（开发→测试）收口，评审才允许触发
g = StageGate()
g.mark_done("接线任务", "development")
g.mark_done("接线任务", "testing")
rep = r.do_review(
    "接线任务", source="PR #150", spec_ref="Issue #150",
    standards_axis={"🔴": [], "note": "ok"}, spec_axis={"faithful": True},
    stable_parts={"goal": "G" * 600, "boundary": "B" * 600},
    volatile_parts={"diff_summary": "接线校验 diff"},
    extra_tests=["local-agent/tests/test_a.sh",
                 "local-agent/tests/test_b.sh",
                 "local-agent/tests/test_c.sh"],
    gate=g, auto_route=False)
assert rep["context_pack"] is not None, "do_review 应产出增量上下文包"
assert rep["batch"] is not None, "do_review 应产出攒批结果"
assert rep["batch"]["skipped"] is False
assert rep["batch"]["cost_note"].startswith("一次冷启动摊全批")
assert rep["axes_complete"] is True and rep["disposition"] in ("merge", "proceed")
print("  ✅ do_review 内接线成功：context_pack + batch（%s）" % rep["batch"]["cost_note"])
PYEOF

echo "===== [review-eff] 4. 评审段调度器：真实变更下真发车 + 同指纹轮次复用 ====="
$PY - <<'PYEOF'
import os, tempfile
from review_cycle import Scheduler, spec
from review_cycle.gate import StageGate
assert spec.MODULE == "review-cycle"
# 阶段链门控：本组验证的是"发车/复用"，故先让上游（开发→测试）收口
sch = Scheduler(dry_run=True, gate=StageGate(state_file=tempfile.mktemp(suffix=".json")))
sch.reset()
_g = sch._gate_runner()
_g.mark_done("任务A", "development"); _g.mark_done("任务A", "testing")
# S2 回归：root_dir 必须解析到仓库根（原先解析为 "/" → 选测恒空 → 永不发车）
assert sch.root_dir not in ("/", "", None), f"root_dir 解析错误: {sch.root_dir!r}"
assert os.path.exists(os.path.join(sch.root_dir, "local-agent")), \
    f"root_dir 不是仓库根: {sch.root_dir!r}"
# 显式注入真实变更文件（不依赖工作区 git 状态），选测必须真的命中测试
changed = ["local-agent/hybrid/bus.py"]
picked = sch._select_tests("fp-x", changed_files=changed)
assert picked, f"真实变更必须选测出测试，实际 {picked}"
stable = {"goal": "G" * 400, "boundary": "B" * 400}
vol = {"diff_summary": "同一份变更"}
out = sch.run("任务A", stable, vol,
              round_volatiles=[vol, vol], max_rounds=2,
              changed_files=changed)
rounds = out["rounds"]
assert len(rounds) == 2
# S2 回归：真实变更下必须真发车（原缺陷恒 dispatched=False）
assert rounds[0]["dispatched"] is True, f"真实变更必须发车，实际 {rounds[0]}"
assert rounds[0]["tests"] == picked, "发车测试应与选测一致"
assert out["bus"] is not None, "真发车后 bus 站台状态不得为 None（原为死字段）"
assert rounds[0]["reused"] is False
assert rounds[1]["reused"] is True, "同变更指纹第二轮必须复用（免重复开发/构建）"
st = sch.stats()
assert st["dispatched_builds"] >= 1, "必须真实发过车（S2 红灯门）"
assert st["batched_runs"] >= 1, "攒批批次必须 >0（不得恒 0）"
assert st["reused_rounds"] >= 1 and st["avoided_builds"] >= 1
print("  ✅ S2：root_dir=%s，真实变更发车 %d 批（%d 测试），第二轮复用省 %d 次构建"
      % (sch.root_dir, st["batched_runs"], len(picked), st["avoided_builds"]))
PYEOF

echo "===== [review-eff] 5. 批量节省口径：N 轮 N 个测试的构建次数大幅下降 ====="
$PY - <<'PYEOF'
import tempfile
from review_cycle import Scheduler
from review_cycle.gate import StageGate
sch = Scheduler(dry_run=True, gate=StageGate(state_file=tempfile.mktemp(suffix=".json")))
sch.reset()
_g = sch._gate_runner()
_g.mark_done("大项目", "development"); _g.mark_done("大项目", "testing")
stable = {"goal": "G"}
# 10 轮评审，每轮 5 个受影响测试，其中一半轮次是同一份变更（复现场景）
vols = [{"diff_summary": "diff-%d" % (i // 2)} for i in range(10)]
out = sch.run("大项目", stable, None, round_volatiles=vols, max_rounds=10,
              changed_files=["local-agent/hybrid/bus.py"])
st = sch.stats()
naive_builds = 50          # 现状：10 轮 × 5 测试 = 50 次单发构建
# S6 回归：断言必须"真发过车"，取 0 也算过会掩盖"永不发车"（原缺陷）
assert st["dispatched_builds"] > 0, f"必须真实发车，实际 {st}"
assert st["batched_runs"] >= 1, f"攒批批次必须 >0，实际 {st}"
assert st["batched_runs"] <= 10, st
assert st["avoided_builds"] >= 4, st
print("  现状单发构建约 %d 次 → 攒批+复用后真发车 %d 批、复用省 %d 次"
      % (naive_builds, st["batched_runs"], st["avoided_builds"]))
print("  ✅ 构建次数显著下降（同指纹轮次零构建，且确认真发过车）")
PYEOF

echo "===== [review-eff] 6. 增量上下文 token 量化 + 留痕可回溯 ====="
$PY - <<'PYEOF'
from data import admin
admin.init()
from review_context import engine
engine.reset_for_tests()
stable = {k: k * 500 for k in ("goal", "boundary", "acceptance")}
p1 = engine.build(stable, {"diff_summary": "y" * 1000}, task_key="留痕")
p2 = engine.build(stable, {"diff_summary": "z"}, prev=p1, task_key="留痕")
assert engine.estimate_saved_tokens(p2) > 0
recent = engine.trace_recent(limit=5)
assert recent and recent[-1]["reused"] is True, recent
print("  ✅ 省下 token ~%d，留痕 %d 条（reused=%s）"
      % (engine.estimate_saved_tokens(p2), len(recent), recent[-1]["reused"]))
PYEOF

echo "===== [review-eff] 7. false-green 红灯门（返工 S1/S2/S3/S6/S5/S8/S7） ====="
$PY - <<'PYEOF'
import os, tempfile
from roles import get_role
from hybrid.bus import BusRunner
from review_cycle.gate import StageGate

qf = tempfile.mktemp(suffix=".json")
os.environ["BUS_QUEUE_FILE"] = qf
r = get_role("架构·评审")

def _gate(task):
    """隔离的阶段门 + 让上游（开发→测试）先收口，专注验证去重门语义（不受阶段门干扰）。"""
    g = StageGate(state_file=tempfile.mktemp(suffix=".json"))
    g.mark_done(task, "development"); g.mark_done(task, "testing")
    return g

# --- S1-①：缺省 diff_summary → 视为"无指纹"，不占门、跨任务不得互相跳过 ---
a = r.prepare_review_batch(task_key="任务A", extra_tests=["local-agent/tests/test_a.sh"],
                           diff_summary="", dry_run=True, gate=_gate("任务A"))
b = r.prepare_review_batch(task_key="任务B", extra_tests=["local-agent/tests/test_b.sh"],
                           diff_summary="", dry_run=True, gate=_gate("任务B"))
assert a["diff_fp"] is None, f"缺省 diff_summary 必须视为无指纹，实际 {a['diff_fp']!r}"
assert b["diff_fp"] is None
assert b["skipped"] is False and b["selected"] == ["local-agent/tests/test_b.sh"], \
    f"任务B 的真实测试不得被任务A 静默跳过：{b}"
# 常量空串哈希绝不得出现在去重门里
assert "sha256:e3b0c44298fc" not in BusRunner(queue_file=qf).processed_fps()

# --- S1-②：同一变更内容 + 不同 task_key → 去重键不同，不得互相跳过 ---
c = r.prepare_review_batch(task_key="任务C", extra_tests=["local-agent/tests/test_c.sh"],
                           diff_summary="同一份变更", dry_run=True, gate=_gate("任务C"))
d = r.prepare_review_batch(task_key="任务D", extra_tests=["local-agent/tests/test_d.sh"],
                           diff_summary="同一份变更", dry_run=True, gate=_gate("任务D"))
assert c["diff_fp"] and d["diff_fp"] and c["diff_fp"] != d["diff_fp"], \
    "去重键必须掺入 task_key（跨任务同内容不得同键）"
assert d["skipped"] is False, "跨任务同内容不得被静默跳过"

# --- S2：演练（dry-run）不得写穿持久化门 → 后续真实执行照跑 ---
os.environ["BUS_QUEUE_FILE"] = tempfile.mktemp(suffix=".json")
r2 = get_role("架构·评审")
# 用各自独立的阶段门（S2 只验"去重门写穿"这一件事；阶段门的重复触发拦截由第 9 组专测）
dry = r2.prepare_review_batch(task_key="T", extra_tests=["local-agent/tests/test_a.sh"],
                              diff_summary="diff-X", dry_run=True, gate=_gate("T"))
assert dry["gate_written"] is False, f"演练不得写穿去重门：{dry.get('gate_written')}"
real = r2.prepare_review_batch(task_key="T", extra_tests=["local-agent/tests/test_a.sh"],
                               diff_summary="diff-X", dry_run=False, gate=_gate("T"))
assert real["skipped"] is False, "演练后真实执行不得被跳过（S2 false green）"
assert real["selected"], "真实执行必须真的带上测试"

# --- S3-①：空队列发车 + 无关发车不得误记指纹 ---
qf3 = tempfile.mktemp(suffix=".json")
b3 = BusRunner(queue_file=qf3, dry_run=False, interval=0)
empty = b3.dispatch(diff_fp="X-未真跑", note="empty")
assert empty["gate_written"] is False, "空队列发车不得写门"
assert b3.processed_fps() == set(), f"空队列发车后门必须为空：{b3.processed_fps()}"
b3.enqueue(["local-agent/tests/test_probe.sh"])
p3 = b3.dispatch(note="unrelated")
assert "X-未真跑" not in b3.processed_fps(), "无关发车不得误记别的指纹（S3）"
assert p3["carried_fps"] == [], f"本批未携带任何指纹，carried 应为空：{p3['carried_fps']}"
# X 的真实测试不再被静默跳过
e3 = b3.enqueue(["local-agent/tests/test_x.sh"], diff_fp="X-未真跑")
assert e3.get("queued") == 1, "X 的真实测试不得被误记的指纹静默跳过"

# --- S6：选测失败（select_error）→ review_complete=False 且不放行 ---
os.environ["BUS_QUEUE_FILE"] = tempfile.mktemp(suffix=".json")
r3 = get_role("架构·评审")
rep = r3.do_review("选测失败任务", source="PR #x", spec_ref="Issue #x",
                   standards_axis={"🔴": [], "note": "ok"},
                   spec_axis={"faithful": True},
                   changed_files=["不存在的源码路径.py"],  # 命中不了任何测试 → select 空
                   gate=_gate("选测失败任务"), auto_route=False)
# 该路径 select 返回空（非异常）→ 视为"未命中"不阻塞；用显式 select_error 校验真失败路径
import roles.reviewer as rv
orig = rv.ReviewerRole.prepare_review_batch
def _boom(self, *a, **k):
    out = orig(self, *a, **k)
    out["select_error"] = "RuntimeError: 选测器炸了"
    out["blocked"] = True
    return out
rv.ReviewerRole.prepare_review_batch = _boom
try:
    rep2 = r3.do_review("选测真失败", source="PR #y", spec_ref="Issue #y",
                        standards_axis={"🔴": [], "note": "ok"},
                        spec_axis={"faithful": True},
                        extra_tests=["local-agent/tests/test_a.sh"],
                        gate=_gate("选测真失败"), auto_route=False)
finally:
    rv.ReviewerRole.prepare_review_batch = orig
assert rep2["review_complete"] is False, "select_error 非空 → 评审不完整"
assert rep2["disposition"] == "fix_bug", f"select_error 不得照常放行，实际 {rep2['disposition']}"
assert rep2["blocked"] is True

# --- S8：仓库根唯一（评审角色 == 调度器） ---
from review_cycle import Scheduler
assert r3.review_repo_root() == Scheduler(dry_run=True).root_dir, "仓库根解析必须唯一（S8）"
print("  ✅ S1/S2/S3/S6/S8 红灯门全过（缺省不占门 / 演练不写穿 / 只记本批携带 / 选测失败不放行 / 仓库根唯一）")
PYEOF

echo "===== [review-eff] 8. 状态机真接线 + 俯瞰透出 select_error（S5/S7） ====="
$PY - <<'PYEOF'
import os, tempfile
os.environ["BUS_QUEUE_FILE"] = tempfile.mktemp(suffix=".json")
from review_cycle import Scheduler, spec
from review_cycle.cycle import advance_state, walk_to

# S5：STATES/TRIGGERS 声明真被读取驱动状态
assert spec.STATE_TRANSITIONS and spec.TRIGGER_STATE, "状态迁移表必须存在"
class _AllowGate:
    """放行全部触发的门（本组只验状态机推进；阶段门语义由第 9 组专测）。"""
    def should_trigger(self, task_key, stage, force=False, now=None):
        return {"allow": True, "decision": "allow", "reason": "test", "forced": False,
                "task_key": task_key, "stage": stage, "active_stage": None,
                "upstream": None, "upstream_done": True, "actor": ""}
    def mark_active(self, *a, **k):
        return {"ok": True}
sch = Scheduler(dry_run=True, gate=_AllowGate())
sch.reset()
out = sch.run("状态机任务", {"goal": "G" * 200}, None,
              round_volatiles=[{"diff_summary": "d1"}, {"diff_summary": "d1"}],
              max_rounds=2, changed_files=["local-agent/hybrid/bus.py"])
r0, r1 = out["rounds"][0], out["rounds"][1]
assert r0["state"] == "reviewed" and r0["trigger"] == "batch_ready", r0
assert r1["state"] == "reviewed" and r1["trigger"] == "fingerprint_new", r1
assert out["state"] == "done", out["state"]
# 非法迁移显式抛错（不静默放行）
try:
    walk_to("done", "collecting")
    raise AssertionError("done → collecting 应抛非法迁移")
except ValueError:
    pass
# 选测失败 → 停在 collecting（不进 reviewed）
assert advance_state("idle", "diff_changed", select_error="boom") == "collecting"

# S7：overview/stats 透出 select_error（不静默藏）
ov = sch.overview()
assert "select_error_count" in ov, "overview 必须透出 select_error 计数"
assert "select_error_count" in ov["stats"]
print("  ✅ S5 状态机真接线（trigger/state 落轮次 + 非法迁移抛错）+ S7 俯瞰透出 select_error")
PYEOF

echo "===== [review-eff] 9. 文档 CLI 可执行（S9）+ ADR 路径一致（S10） ====="
REPO_ROOT="$(cd .. && pwd)"   # 脚本开头已 cd 到 local-agent，故 .. 即仓库根
PYTHONPATH="$REPO_ROOT/local-agent" $PY -m review_context demo >/dev/null 2>&1 || { echo "  ❌ python -m review_context 跑不通"; exit 1; }
PYTHONPATH="$REPO_ROOT/local-agent" $PY -m review_cycle stats >/dev/null 2>&1 || { echo "  ❌ python -m review_cycle 跑不通"; exit 1; }
PYTHONPATH="$REPO_ROOT/local-agent" $PY -m hybrid.cli bus status >/dev/null 2>&1 || { echo "  ❌ python -m hybrid.cli 跑不通"; exit 1; }
PYTHONPATH="$REPO_ROOT/local-agent" $PY -m review_cycle gate >/dev/null 2>&1 || { echo "  ❌ python -m review_cycle gate 跑不通"; exit 1; }
test -f "$REPO_ROOT/docs/adr/0011-review-incremental-coalesced-cycle.md" || { echo "  ❌ ADR-0011 路径不一致"; exit 1; }
grep -q "0011-review-incremental-coalesced-cycle" "$REPO_ROOT/docs/REVIEW_EFFICIENCY.md" || { echo "  ❌ REVIEW_EFFICIENCY 未引用 ADR-0011"; exit 1; }
grep -q "0011-review-incremental-coalesced-cycle" "$REPO_ROOT/docs/adr/README.md" || { echo "  ❌ ADR README 未登记 0011"; exit 1; }
echo "  ✅ 文档 CLI 均可跑通 + ADR-0011 路径引用一致"

echo "===== [review-eff] 10. 大盘俯瞰：评审段 + 控制页可读省下的成本 ====="
$PY - <<'PYEOF'
from review_cycle import Scheduler
from entries import dashboard as dash
sch = Scheduler(dry_run=True)
ov = sch.overview()
assert ov["module"] == "review-cycle"
assert "stats" in ov and "cycles" in ov
snap = dash.snapshot()
assert snap["review_cycle"]["ok"] is True
assert snap["review_cycle"]["stats"]["module"] == "review-cycle"
ctl = dash.control("review_cycle")
assert ctl["ok"] is True
print("  ✅ 评审段大盘 + 控制页 /review-cycle 路由可读")
PYEOF

echo "===== [review-eff] 8. 阶段链门控：本该串行不得并行/重复触发（打断补齐）====="
$PY - <<'PYEOF8'
import tempfile
from review_cycle.gate import StageGate, gate_stats
from review_cycle import stage_spec

# 顺序 / 上游 唯一事实源
assert stage_spec.STAGE_ORDER == ("development", "testing", "review")
assert stage_spec.UPSTREAM == {"testing": "development", "review": "testing"}

g = StageGate(state_file=tempfile.mktemp(suffix=".json"))
# 1 开发在跑 -> 测试/评审抢跑必须被驳回（这正是"乱触发"要拦下的）
assert g.admit("T1", "development")["decision"] == "allow"
assert g.admit("T1", "testing")["decision"] == "blocked_upstream", "开发未完就测试=抢跑"
assert g.admit("T1", "review")["decision"] == "blocked_upstream", "开发未完就评审=抢跑"
# 2 重复触发同一阶段 -> 复用（不新起任务、不冲进度 = 防进度失衡）
assert g.admit("T1", "development")["decision"] == "blocked_active"
v = g.admit("T1", "development")
assert v["reused"] is True and v["admitted"] is False, "重复触发应复用而非新起"
# 3 链式推进：开发收口 -> 测试放行 -> 测试收口 -> 评审放行
assert g.mark_done("T1", "development")["cleared"] is True
assert g.admit("T1", "testing")["decision"] == "allow"
assert g.admit("T1", "review")["decision"] == "blocked_upstream", "测试未完就评审=抢跑"
assert g.mark_done("T1", "testing")["cleared"] is True
assert g.admit("T1", "review")["decision"] == "allow"
# 4 乱序：从下游那头起头 -> 驳回（防一条链被拆两条并行）
assert g.admit("T2", "review")["decision"] == "blocked_upstream"
# 5 force 是显式逃生门（不静默绕过：留痕 forced=True）
f = g.should_trigger("T1", "development", force=True)
assert f["allow"] is True and f["forced"] is True
print("  OK 顺序门控：抢跑/重复/乱序全拦，链式推进放行，force 逃生门留痕")
PYEOF8

echo "===== [review-eff] 9. 拦截可核验：抢跑不起构建 + 大盘计数 ====="
$PY - <<'PYEOF9'
import tempfile
from review_cycle import Scheduler
from review_cycle.gate import StageGate
from data import admin
admin.init()

sch = Scheduler(dry_run=True, gate=StageGate(state_file=tempfile.mktemp(suffix=".json")))
sch.reset()
changed = ["local-agent/hybrid/bus.py"]

# 上游未收口 -> 评审段触发被阶段门驳回：零构建（dispatched=False）
out = sch.run("链任务", {"goal": "G" * 200}, {"diff_summary": "d1"},
              changed_files=changed)
r0 = out["rounds"][0]
assert r0["state"] == "blocked", r0
assert r0["stage_gate"]["decision"] == "blocked_upstream"
assert r0["dispatched"] is False, "被驳回不得起任何构建"
assert r0["disposition"] == "proceed", "驳回不得假绿放行标签"

# 上游收口后 -> 放行且真发车
g = sch._gate_runner()
g.mark_done("链任务", "development"); g.mark_done("链任务", "testing")
out2 = sch.run("链任务", {"goal": "G" * 200}, {"diff_summary": "d2"},
               changed_files=changed)
assert out2["rounds"][0]["state"] == "reviewed"
assert out2["rounds"][0]["dispatched"] is True

st = sch.stats()
assert st["stage_gates"]["blocked_upstream"] >= 1
assert st["blocked_rounds"] >= 1
assert st["blocked_retriggers"] >= 1
print("  OK 抢跑零构建 + 放行才发车；blocked_rounds=%d / blocked_retriggers=%d"
      % (st["blocked_rounds"], st["blocked_retriggers"]))
PYEOF9

echo "===== [review-eff] ALL PASS ====="
