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

echo "===== [review-eff] 2. 攒批去重门：同变更指纹不重复触发构建 ====="
$PY - <<'PYEOF'
import tempfile
from hybrid.bus import BusRunner
qf = tempfile.mktemp(suffix=".json")
b = BusRunner(queue_file=qf, dry_run=True, interval=0)
r = b.enqueue(["local-agent/tests/test_a.sh", "local-agent/tests/test_b.sh"],
              diff_fp="fp-150")
assert r["queued"] == 2
plan = b.dispatch(note="批1")
assert plan["dispatched"] == 2 and plan["queued_cleared"] is True
# 一次构建摊全批：2 个测试原本要 2 次冷启动，整批只要 1 次
assert plan["summary"]["cold_starts_naive"] == 2
assert plan["summary"]["cold_starts_batched"] == 1
assert plan["summary"]["cold_start_saved"] == 1
# 同指纹再次入列 → 拦截，不再触发构建
r2 = b.enqueue(["local-agent/tests/test_a.sh"], diff_fp="fp-150")
assert r2["queued"] == 0 and r2["skipped_fp"] == "fp-150", r2
t = b.tick(diff_fp="fp-150")
assert t["action"] == "skip", t
print("  ✅ 整批一次构建(cold_start_saved=%d) + 同指纹再入列被拦截" %
      plan["summary"]["cold_start_saved"])
PYEOF

echo "===== [review-eff] 3. 评审角色接线：do_review 内自动 增量上下文 + 攒批 ====="
$PY - <<'PYEOF'
from data import admin
admin.init()
from roles import get_role
r = get_role("架构·评审")
assert hasattr(r, "build_review_context")
assert hasattr(r, "prepare_review_batch")
rep = r.do_review(
    "接线任务", source="PR #150", spec_ref="Issue #150",
    standards_axis={"🔴": [], "note": "ok"}, spec_axis={"faithful": True},
    stable_parts={"goal": "G" * 600, "boundary": "B" * 600},
    volatile_parts={"diff_summary": "接线校验 diff"},
    extra_tests=["local-agent/tests/test_a.sh",
                 "local-agent/tests/test_b.sh",
                 "local-agent/tests/test_c.sh"],
    auto_route=False)
assert rep["context_pack"] is not None, "do_review 应产出增量上下文包"
assert rep["batch"] is not None, "do_review 应产出攒批结果"
assert rep["batch"]["skipped"] is False
assert rep["batch"]["cost_note"].startswith("一次冷启动摊全批")
assert rep["axes_complete"] is True and rep["disposition"] in ("merge", "proceed")
print("  ✅ do_review 内接线成功：context_pack + batch（%s）" % rep["batch"]["cost_note"])
PYEOF

echo "===== [review-eff] 4. 评审段调度器：真实变更下真发车 + 同指纹轮次复用 ====="
$PY - <<'PYEOF'
import os
from review_cycle import Scheduler, spec
assert spec.MODULE == "review-cycle"
sch = Scheduler(dry_run=True)
sch.reset()
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
from review_cycle import Scheduler
sch = Scheduler(dry_run=True)
sch.reset()
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

echo "===== [review-eff] 7. 大盘俯瞰：评审段 + 控制页可读省下的成本 ====="
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

echo "===== [review-eff] ALL PASS ====="
