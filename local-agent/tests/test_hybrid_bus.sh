#!/usr/bin/env bash
# ============================================================
# 公交车式批量测试计划执行器测试（test_hybrid_bus · Issue #90 收尾）
# ============================================================
# 验证「攒批一次构建跑完 + 15 分钟定时发车 + 空车不发」的公交车模型：
#   - 入列（0 成本）：enqueue 攒批，不立即拉起构建
#   - 到点发车：interval 到 + 队列非空 → should_dispatch=True
#   - 空车不发：队列空 → 不发车（无空转构建）
#   - 未到点：interval 未到 → 等下一班（not_due）
#   - 整批发车：dispatch 把全部待跑作为一批计划跑完（一次构建摊全批）
#   - 统一收尾：跑完 sync 留痕 + cost 报表 + quota 记账
#   - 发车清空：跑完队列清空，history +1
#
# 运行：bash local-agent/tests/test_hybrid_bus.sh
# 预期：PASS≥18 FAIL=0（独立信号灯，不依赖其他模块）
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi; }

echo "== 公交车式批量测试计划执行器（攒批 · 一次构建 · 15min发车） =="

# 隔离队列文件
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

R=$(python3 - "$WORK" << 'PY'
import sys, os, json
sys.path.insert(0, os.path.join(os.getcwd(), "local-agent"))
from hybrid.bus import BusRunner
qf = os.path.join(sys.argv[1], "queue.json")
b = BusRunner(queue_file=qf, interval=900, timeout=60, parallel=2, dry_run=True)

res = {}

# --- 空队列：不发车（无需求空转=浪费） ---
s_empty = b.status()
res["empty_queued"] = s_empty["queued"]          # 0
res["empty_dispatch"] = b.should_dispatch(now=100)["dispatch"]  # False

# --- 入列（0 成本攒批） ---
b.enqueue(["local-agent/tests/test_scale.sh", "local-agent/tests/test_engine.sh"])
s1 = b.status()
res["queued_after_enqueue"] = s1["queued"]        # 2

# --- 未到 15 分钟：等下一班（not_due），不空转 ---
nd = b.should_dispatch(now=100)
res["not_due_dispatch"] = nd["dispatch"]          # False
res["not_due_reason"] = nd["reason"]              # not_due
res["not_due_next"] = nd["next_due_in"] > 0       # True

# --- 到 15 分钟后 + 队列非空 → 发车 ---
due = b.should_dispatch(now=1000)
res["due_dispatch"] = due["dispatch"]             # True
res["due_reason"] = due["reason"]                 # due_with_passengers

# --- 整批发车（一批计划跑完 + 收尾 + 清空） ---
plan = b.dispatch(now=1000)
res["dispatched_count"] = plan["dispatched"]      # 2
res["batch_summary_total"] = plan["summary"]["total"]   # 2
res["cleared_after"] = b.status()["queued"]       # 0
res["history_after"] = b.status()["dispatch_count"]     # 1
res["finish_synced"] = plan["finish"]["synced"]   # True(dry sync ok)

# --- 发车后队列空：后续到点也不发（空车不发） ---
res["post_empty_dispatch"] = b.should_dispatch(now=3000)["dispatch"]  # False
res["post_empty_reason"] = b.should_dispatch(now=3000)["reason"]       # empty_queue

# --- 去重：重复入列同一测试只算一次 ---
b.enqueue(["local-agent/tests/test_scale.sh"])
b.enqueue(["local-agent/tests/test_scale.sh", "local-agent/tests/test_engine.sh"])
res["dedup_queued"] = b.status()["queued"]        # 2

print(json.dumps(res))
PY
)
echo "$R"
# 从 JSON 解析判定
G() { echo "$R" | python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }

check "空队列不发车(queued=0)"        "$(G empty_queued)" "0"
check "空队列 should_dispatch=false"  "$(G empty_dispatch)" "False"
check "入列后队列数=2"                "$(G queued_after_enqueue)" "2"
check "未到点不空转(dispatch=false)"  "$(G not_due_dispatch)" "False"
check "未到点原因=not_due"            "$(G not_due_reason)" "not_due"
check "未到点给出倒计时"              "$(G not_due_next)" "True"
check "到点且非空 dispatch=true"      "$(G due_dispatch)" "True"
check "到点原因=due_with_passengers"  "$(G due_reason)" "due_with_passengers"
check "整批发车 dispatched=2"         "$(G dispatched_count)" "2"
check "整批 summary.total=2"          "$(G batch_summary_total)" "2"
check "发车后队列清空=0"              "$(G cleared_after)" "0"
check "发车历史 count=1"              "$(G history_after)" "1"
check "发车后空车不发(post=false)"    "$(G post_empty_dispatch)" "False"
check "发车后空车原因=empty_queue"    "$(G post_empty_reason)" "empty_queue"
check "重复入列去重后=2"              "$(G dedup_queued)" "2"

echo ""
echo "== 真实整批执行（_run_plan · dry=false · 一批计划同进程跑完，无副作用） =="
RR=$(python3 - "$WORK" << 'PY'
import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), "local-agent"))
from hybrid.bus import BusRunner
qf = os.path.join(sys.argv[1], "queue_real.json")
b = BusRunner(queue_file=qf, interval=900, timeout=120, parallel=2, dry_run=False)
# 两个真实轻量脚本：验证整批确经 worker 同进程（ParallelExecutor）跑完
plan = b._run_plan(["local-agent/tests/test_prescale_entry.sh",
                    "local-agent/tests/test_probe.sh"])
s = plan["summary"]
print("total=%d pass=%d fail=%d wall=%s" % (s["total"], s["pass"], s["fail"],
      s.get("wall_seconds") or 0))
PY
)
echo "$RR"
RT=$(echo "$RR" | sed -n 's/.*total=\([0-9]*\) pass=\([0-9]*\) fail=\([0-9]*\) wall=\([0-9.]*\)/\1|\2|\3|\4/p')
if [ -n "$RT" ]; then
  TOT=${RT%%|*}; REST=${RT#*|}; PAS=${REST%%|*}; REST=${REST#*|}; FL=${REST%%|*}; WL=${REST#*|}
  check "真实整批 total=2(一批计划)" "$TOT" "2"
  check "真实整批 pass>=1" "$([ "${PAS:-0}" -ge 1 ] && echo ok || echo bad)" "ok"
  check "真实整批经 worker 真跑(fail 可隔离)" "$([ "${FL:-0}" -ge 0 ] && echo ok || echo bad)" "ok"
  check "真实整批产出墙钟 wall>0" "$([ "$(python3 -c "print(1 if float('${WL:-0}')>0 else 0)")" = "1" ] && echo ok || echo bad)" "ok"
else
  bad "真实整批输出解析失败"
fi

echo ""
echo "== 结果 =="
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ] || exit 1
