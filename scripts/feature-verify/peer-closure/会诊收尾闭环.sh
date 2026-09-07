#!/usr/bin/env bash
# ============================================================
# [feature-verify] peer-closure / 会诊收尾闭环
# ============================================================
# module:   peer-closure（同岗协作收尾闭环）
# feature:  会诊解决不了 ≠ 终局 —— 未收敛自动进 precursor → human_gate → decisions 留痕
# 五要素:
#   Given   同岗多 agent 专家会诊「对错难辨 / 意见分歧」→ consensus_judge 判未收敛
#   When    把未收敛会诊结果喂给 closure.run()（收尾闭环统一编排）
#   Then    ① 未收敛会诊绝不静默放行（不得谎报 resolved_at_consult）
#           ② 走收尾闭环：precursor 审核前置介入（L1/L2 分支摊开）→ 需担责/未自决则
#              打开 human_gate 人类拍板闸门
#           ③ 决策逐层落库留痕（decisions：consult→escalate / precursor_l3→human）
#           负向自证：收敛会诊 → 直返 resolved_at_consult、不误开 human_gate；
#           能自决（L2 命中零负面零成本零风险）→ adopted、不乱开 human_gate。
#   Evidence closure.run() 返回 status（awaiting_human/adopted/resolved_at_consult）+
#           human_gate.list_gates(open) 闸门 + decisions.list_decisions() 落库记录
#           （均可程序化断言的语义产物）
# 为什么是"功能级"：纯 grep/通畅测试抓不到——必须真跑 peer expert_consult→closure
#   收尾链路，看它对"未收敛会诊"是否诚实进 precursor→human_gate、不偷偷当解决；
#   又能抓"能自决却乱交人"的过度打扰。跑不过 = 会诊收尾闭环语义没做完。
#
# 环境守卫：本样例依赖 python3 + local-agent 收尾链路（collab/closure），无 python
#   优雅跳过（视为通过），对齐 tests/test_functional_links.sh / dispatch 样例模式。
# 数据隔离：DB_PATH 指到临时库，跑完即删，不污染真实决策库（decisions/gates）。
# 用法：bash scripts/feature-verify.sh --feature "peer-closure/会诊收尾闭环"
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "==== [feature-verify] peer-closure/会诊收尾闭环 ===="
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ⏭️  python3 缺失，本 python 依赖样例优雅跳过（CI python 环境全量跑）"
  exit 0
fi
export PYTHONPATH="local-agent${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<'PYEOF'
import os, sys, tempfile, uuid, shutil

# ---- 数据隔离：独立临时库（导入任何 data 模块前设 DB_PATH），跑完即删 ----
_TMPDIR = tempfile.mkdtemp(prefix="fv-peer-closure-")
_DB = os.path.join(_TMPDIR, "runtime.db")
os.environ["DB_PATH"] = _DB
sys.path.insert(0, "local-agent")

from data import admin, db
from collab import peer, closure, human_gate, decisions

PASS = FAIL = 0
def ok(m): print("  ✅ " + m)
def bad(m): print("  ❌ " + m); raise AssertionError(m)

def unconverged_result(problem, agents):
    """构造 peer.expert_consult 同型未收敛结果（意见分歧 → resolved=False）。"""
    return {
        "action": "consult", "problem": problem,
        "opinions": [{"agent": a["agent"], "specialty": a["specialty"],
                      "verdict": a["verdict"], "reason": a["reason"]} for a in agents],
        "consensus": False, "summary": "会诊未收敛：同意不足，需复评或走审核前置→人类",
        "resolved": False,
    }

def fresh_task(prefix):
    return f"tk-fv-{prefix}-{uuid.uuid4().hex[:6]}"

# ---- Given：隔离数据层就绪 + 建同岗会诊 cohort ----
admin.init()  # 建表（幂等）
cid = peer.spawn_cohort("架构·开发", "lead-fv-dev", size=3, mode="consult",
                        req="fv peer-closure cohort")
peer.join_cohort(cid, "backup-fv-eng")   # 工程向
peer.join_cohort(cid, "backup-fv-sec")   # 安全向
cohort_members = peer.cohort_members(cid)
assert len(cohort_members) == 3, f"cohort 未建齐: {cohort_members}"

# ---------- 正：未收敛会诊 → 收尾闭环 → precursor → human_gate → decisions 留痕 ----------
print("\n[正向] 未收敛会诊 → closure 收尾闭环 → human_gate + decisions 留痕")
problem = "验收口径采用 A 口径（快但测不全）还是 B 口径（全但慢），对错难辨"
task_pos = fresh_task("pos")

# ① 先用真实 peer.consensus_judge 证明"意见分歧=未收敛"（前置语义成立）
divergent = [
    {"agent": "lead-fv-dev",  "verdict": "可行"},
    {"agent": "backup-fv-eng","verdict": "存疑"},
    {"agent": "backup-fv-sec","verdict": "不可行"},
]
judged = peer.consensus_judge(divergent)
try:
    assert judged["consensus"] is False and judged["disagree"] >= 1, \
        f"分歧意见应判未收敛: {judged}"
    ok("判据0: 真实 consensus_judge 把分歧会诊判为未收敛（consensus=False）")
except AssertionError as e:
    bad(f"判据0 失败: {e}")

# ② 未收敛 consult_result → closure.run
res_unconv = unconverged_result(problem, [
    {"agent": "lead-fv-dev",  "specialty": "算法向", "verdict": "可行", "reason": "覆盖主流场景"},
    {"agent": "backup-fv-eng","specialty": "工程向", "verdict": "存疑", "reason": "存在未覆盖风险"},
    {"agent": "backup-fv-sec","specialty": "安全向", "verdict": "不可行", "reason": "安全/合规未满足，需换道"},
])
out = closure.run(problem, cid, task_id=task_pos, consult_result=res_unconv,
                  option_a="A 口径", option_b="B 口径",
                  scenario_hint="A、B 各自覆盖不同场景", blank="需盘点 A、B 均未覆盖域")

# 判据1：未收敛会诊绝不静默放行（不得谎报 resolved_at_consult / adopted 当已解决）
try:
    assert out["status"] == "awaiting_human", \
        f"未收敛会诊必须进收尾闭环交人拍板，却返回 status={out['status']}"
    assert "precursor" in " ".join(t["stage"] for t in out.get("trace", [])), "trace 无 precursor 阶段"
    ok("判据1: 未收敛会诊不静默放行 → closure 进入收尾闭环（awaiting_human，precursor 介入）")
except AssertionError as e:
    bad(f"判据1 失败: {e}")

# 判据2：打开 human_gate（结果前置交人类拍板）
try:
    open_gates = [g for g in human_gate.list_gates("open") if g.get("task_id") == task_pos]
    assert open_gates, "未收敛且需担责 → 应打开人类拍板闸门"
    assert open_gates[0]["status"] == "open", "闸门应处于 open（等待人类确认）"
    ok(f"判据2: 打开 human_gate（{open_gates[0]['gate_id']}），status=open，结果前置交人")
except AssertionError as e:
    bad(f"判据2 失败: {e}")

# 判据3：决策逐层落库留痕（decisions：consult→escalate 升级 + precursor_l3→human 交人）
try:
    decs = [d for d in decisions.list_decisions(task_id=task_pos) if d.get("action")]
    stages = {(d["stage"], d["action"]) for d in decs}
    assert ("consult", "escalate") in stages, f"未收敛升级决策未落库: {stages}"
    assert ("precursor_l3", "human") in stages, f"交人拍板决策未落库: {stages}"
    # 审核前置助手各层（L1/L2）结论也留痕
    assert any(s == "L1" for s, _ in stages) and any(s == "L2" for s, _ in stages), \
        f"precursor L1/L2 层结论未落库: {stages}"
    ok(f"判据3: 决策逐层落库留痕（stages={sorted(stages)}），含 consult→escalate + precursor_l3→human")
except AssertionError as e:
    bad(f"判据3 失败: {e}")

# ---------- 负向1：收敛会诊 → 直返 resolved_at_consult，不误开 human_gate ----------
print("\n[负向1] 会诊已收敛 → 直返放行，不误开 human_gate（抓'收敛还乱交人'）")
problem_c = "已收敛的常规修改"
task_n1 = fresh_task("neg1")
res_converged = {"action": "consult", "problem": problem_c,
    "opinions": [{"agent": "lead-fv-dev", "verdict": "可行", "reason": "已达成共识"}],
    "consensus": True, "summary": "会诊收敛：1/1 认可，达成集体判断", "resolved": True}
out_c = closure.run(problem_c, cid, task_id=task_n1, consult_result=res_converged,
                    option_a="X", option_b="Y")
try:
    assert out_c["status"] == "resolved_at_consult", \
        f"收敛会诊应直返放行，却 status={out_c['status']} → 可能把收敛会诊误拖进收尾"
    gates_c = [g for g in human_gate.list_gates("open") if g.get("task_id") == task_n1]
    assert not gates_c, "收敛会诊不应打开 human_gate（否则过度打扰人类）"
    ok("负向1: 收敛会诊直返 resolved_at_consult，未误开 human_gate")
except AssertionError as e:
    bad(f"负向1 失败: {e}")

# ---------- 负向2：会诊未收敛但 L2 命中且可自决（零负面/零成本/零风险）→ adopted，不乱开 human_gate ----------
print("\n[负向2] 未收敛但可自决（现成方案零成本零风险）→ adopted，不误开 human_gate（抓'能自决却乱交人'）")
problem_d = "接入通用日志切面（有开源零成本方案）"
task_n2 = fresh_task("neg2")
res_self = unconverged_result(problem_d, [
    {"agent": "lead-fv-dev",  "specialty": "算法向", "verdict": "可行", "reason": "可接入"},
    {"agent": "backup-fv-sec","specialty": "安全向", "verdict": "存疑", "reason": "需确认外部方案安全性"},
])
# known_patterns 无 negative/cost/risk → precursor L2 判 self_decidable → closure adopted
self_dec_hit = [{"source": "opensource", "title": "通用切面库 skeleton-log", "snippet": "零成本零风险零负面",
                 "url": "https://example/skeleton-log"}]
out_d = closure.run(problem_d, cid, task_id=task_n2, consult_result=res_self,
                    option_a="自研", option_b="不接", keyword="日志切面", known_patterns=self_dec_hit)
try:
    assert out_d["status"] == "adopted", \
        f"可自决（零成本零风险）应 adopted 自决采用，却 status={out_d['status']}"
    gates_d = [g for g in human_gate.list_gates("open") if g.get("task_id") == task_n2]
    assert not gates_d, "可自决场景不应打开 human_gate（否则过度打扰人类）"
    ok("负向2: 可自决场景 adopted 直接采用，未误开 human_gate")
except AssertionError as e:
    bad(f"负向2 失败: {e}")

# ---------- 负向3：未收敛会诊若被谎报成"已解决/静默放行"应被抓出来 ----------
print("\n[负向3] 反向探针：未收敛会诊不得被当作 resolved_at_consult（抓'会诊没收敛却偷偷当解决'）")
# 我们喂的确实是 resolved=False → 收尾链路必须识别为未收敛并进收尾，返回 await/adopt，绝不允许 resolved_at_consult
try:
    assert out["status"] != "resolved_at_consult", "未收敛会诊被偷偷当 resolved → 静默放行缺陷"
    ok("负向3: 未收敛 consult_result 不会被收尾链路谎报为已解决（resolved_at_consult）")
except AssertionError as e:
    bad(f"负向3 失败: {e}")

# ---- 清理隔离数据：删除临时库，不污染真实决策库 ----
shutil.rmtree(_TMPDIR, ignore_errors=True)

if FAIL > 0:
    print("\n🔴 peer-closure/会诊收尾闭环 未达成 → 功能没做完")
    sys.exit(1)
else:
    print("\n🟢 peer-closure/会诊收尾闭环 通过（未收敛会诊不静默、可自决不乱交人、决策留痕）")
    sys.exit(0)
PYEOF
RC=$?
if [ $RC -ne 0 ]; then
  echo "  🔴 peer-closure/会诊收尾闭环 未达成 → 功能没做完"
  exit 1
else
  echo "  🟢 peer-closure/会诊收尾闭环 通过（会诊收尾闭环语义成立）"
  exit 0
fi
