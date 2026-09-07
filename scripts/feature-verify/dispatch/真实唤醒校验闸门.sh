#!/usr/bin/env bash
# ============================================================
# [feature-verify] dispatch / 真实唤醒校验闸门
# ============================================================
# module:   dispatch（分发引擎）
# feature:  真实唤醒校验闸门（Issue #100 决策④·防假装分配）
# 五要素:
#   Given   给一组"只投了 [触发] 接力卡、对端无 [接单] 回执"的派发任务
#   When    调 dispatch_verify() 做真实唤醒回执校验
#   Then    未回执的任务必须落 awaiting_receipt（awaiting_receipt_count>0），
#           verified_all_awake 必须为 False——不允许把"只投卡"当"已真实唤醒全放行"。
#   Evidence dispatch_verify() 返回的 verification.awaiting_receipt / awake_count /
#           verified_all_awake（可程序化断言的语义产物）
# 为什么是"功能级"：纯 grep/断言查不到——必须真实跑 dispatch 引擎，看它对
#   无回执任务是否诚实标 awaiting_receipt、不假装全唤醒。跑不过=防假装分配功能没做完。
#
# 环境守卫：本样例依赖 python3 + local-agent 数据层（CI/本地 python 环境跑），
#   纯 bash 无 python 环境优雅跳过（视为通过），对齐 tests/test_functional_links.sh 模式。
# 用法：bash scripts/feature-verify.sh --feature "dispatch/真实唤醒校验闸门"
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "==== [feature-verify] dispatch/真实唤醒校验闸门 ===="
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ⏭️  python3 缺失，本 python 依赖样例优雅跳过（CI python 环境全量跑）"
  exit 0
fi
export PYTHONPATH="local-agent${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<'PYEOF'
import sys
sys.path.insert(0, "local-agent")
from data import db
from data import repository as data_repo
from dispatch_engine import dispatch_verify

PASS = FAIL = 0
def ok(m): print("  ✅ " + m)
def bad(m): print("  ❌ " + m)

# Given: A 任务有对端 [接单] 回执（真实 accepted 事件），B 任务只投卡无回执
import uuid
suffix = uuid.uuid4().hex[:6]
tid_a, tid_b = "tk-fv-receipt-" + suffix, "tk-fv-noreceipt-" + suffix
ag_a, ag_b = "ag-fv-a-" + suffix, "ag-fv-b-" + suffix
data_repo.record_progress(ag_a, "accepted", detail="fv seed receipt", task_id=tid_a)
assignments = [
    {"task_key": "fv-demo-a", "task_id": tid_a, "agent_id": ag_a,
     "role": "架构·开发", "issue_number": 109},
    {"task_key": "fv-demo-b", "task_id": tid_b, "agent_id": ag_b,
     "role": "架构·开发", "issue_number": 109},
]

res = dispatch_verify(assignments)

# Then-1: B 无回执 → 必须进 awaiting_receipt
if res["awaiting_receipt_count"] == 1 and any(x["task_key"] == "fv-demo-b"
                                              for x in res["awaiting_receipt"]):
    ok("Then-1: 无 [接单] 回执任务被显式暴露到 awaiting_receipt")
else:
    bad("Then-1: 无回执任务未落 awaiting_receipt → 防假装分配功能失效")
    FAIL += 1
# Then-2: A 有回执 → 计入 awake
if res["awake_count"] == 1:
    ok("Then-2: 有 [接单] 回执任务被计为真实唤醒 awake")
else:
    bad("Then-2: 有回执任务未计 awake_count=%s" % res["awake_count"])
    FAIL += 1
# Then-3: 存在未唤醒 → verified_all_awake 必须为 False（不得谎报全放行）
if res["verified_all_awake"] is False:
    ok("Then-3: 存在未唤醒任务 → verified_all_awake=False（不谎报全放行）")
else:
    bad("Then-3: 存在未唤醒却 verified_all_awake=True → 谎报闸门失效")
    FAIL += 1
# 清理演示进度流水
db.execute("DELETE FROM progress WHERE task_id=? OR task_id=?", (tid_a, tid_b))
sys.exit(1 if FAIL else 0)
PYEOF
RC=$?
if [ $RC -ne 0 ]; then
  echo "  🔴 dispatch/真实唤醒校验闸门 未达成 → 功能没做完"
  exit 1
else
  echo "  🟢 dispatch/真实唤醒校验闸门 通过（防假装分配语义成立）"
  exit 0
fi
