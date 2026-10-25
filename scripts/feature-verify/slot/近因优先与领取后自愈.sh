#!/usr/bin/env bash
# ============================================================
# [feature-verify] slot / 近因优先与领取后自愈
# ============================================================
# module:   slot（执行体槽位池 · Issue #271）
# feature:  近因优先取件 + 加长队列 + 领取后自愈接回（PR #247 用户原话）
# 五要素:
#   Given   池子里有一批按先后入队的活，第一件领走后卡住
#   When    后续 reserve() 继续领件，并观察卡住活的接回
#   Then    近因优先应领到最新入队活（被卡住的只跨过不堵）；
#           领走一件后 stuck 的活被自动接回（repairs 自增）；超限标 dead 不静默
#   Evidence SlotPool 的状态机产物（state / repairs / stats），可程序化断言
# 为什么是"功能级"：纯 grep 查不到——必须真实跑槽位池，看取件顺序与自愈是否真成立。
#   跑不过=「最新优先 + 领取后把其他接上」功能没做完。
#
# 环境守卫：依赖 python3 跑槽位池逻辑（CI/本地 python 环境全量跑），
#   纯 bash 无 python3 优雅跳过（视为通过）。
# 用法：bash scripts/feature-verify.sh --feature "slot/近因优先与领取后自愈"
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "==== [feature-verify] slot/近因优先与领取后自愈 ===="
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ⏭️  python3 缺失，本 python 依赖样例优雅跳过（CI python 环境全量跑）"
  exit 0
fi
export PYTHONPATH="local-agent${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<'PYEOF'
import sys
sys.path.insert(0, "local-agent")
from slot import SlotPool

PASS = 0
FAIL = 0
def ok(m):
    global PASS
    PASS += 1
    print("  ✅ " + m)
def bad(m):
    global FAIL
    FAIL += 1
    print("  ❌ " + m)

# Given: 一批按先后入队的活
p = SlotPool(capacity=16, slots=2, max_repairs=2)
for i in range(1, 5):
    p.enqueue("job-%d" % i)
    p._tasks["job-%d" % i].enqueued_at = float(i)   # job-4 最新

# When: 领最新一件并卡住
first = p.reserve()
# Then-1: 近因优先应领到最新入队 job-4
if first["task"] is not None and first["task"].task_id == "job-4":
    ok("Then-1: 近因优先领取到最新入队 job-4（卡住的不堵池头）")
else:
    bad("Then-1: 未领到最新入队活，实际=%s" % (first["task"].task_id if first["task"] else None))
    FAIL += 1
p.mark_stuck("job-4")

# When: 继续领，并观察卡住活是否被自动接回
second = p.reserve()
if second["task"] is not None and second["task"].task_id == "job-3":
    ok("Then-2: 卡住后仍能领到 job-3（跨过卡死的 job-4）")
else:
    bad("Then-2: 卡住后未能继续出活，实际=%s" % (second["task"].task_id if second["task"] else None))
    FAIL += 1
if "job-4" in second["repairs"]:
    ok("Then-3: 领取后自愈接回 —— job-4 被重新入队（repairs 自增）")
else:
    bad("Then-3: 领取后未自动接回卡住的 job-4: %s" % second["repairs"])
    FAIL += 1

# When/Then-4: 超限应显式 dead（不静默）
for _ in range(4):
    p.mark_stuck("job-4")
    p.repair_rest()
st = p._tasks["job-4"]
if st.state == "dead" and st.repairs >= 2:
    ok("Then-4: 自愈超限显式 dead（不静默重试），repairs=%d" % st.repairs)
else:
    bad("Then-4: 超限未显式 dead，state=%s repairs=%d" % (st.state, st.repairs))
    FAIL += 1

# Then-5: 三类状态分开报，不混成一个「都挺好」
ov = p.overview()
if ov["stats"]["dead"] >= 1 and "recency-first" in ov["order_policy"]:
    ok("Then-5: 状态分开报（dead=%d）+ 近因优先策略生效" % ov["stats"]["dead"])
else:
    bad("Then-5: 状态未分开报或策略缺失: %s" % ov["order_policy"])
    FAIL += 1

sys.exit(1 if FAIL else 0)
PYEOF
RC=$?
if [ $RC -ne 0 ]; then
  echo "  🔴 slot/近因优先与领取后自愈 未达成 → 功能没做完"
  exit 1
else
  echo "  🟢 slot/近因优先与领取后自愈 通过（近因优先 + 领取后自愈语义成立）"
  exit 0
fi
