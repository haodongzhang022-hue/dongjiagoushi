#!/usr/bin/env bash
# ============================================================
# CostMonitor T6 扩展测试（test_hybrid_cost.sh · Issue #65 T6）
# ============================================================
# 验证 CostMonitor.report_optimizer()：
#   1. 增量节省（未受影响测试跳过）
#   2. 缓存节省（指纹未变化跳过）
#   3. 并行节省（时间差折算）
#   4. 三合一合计
#   5. v1.0 report() 仍可用（向后兼容）
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi; }

echo "== CostMonitor T6 扩展测试 =="

# ---------- 1. v1.0 report() 向后兼容 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cost import CostMonitor
from hybrid.router import HybridResourceRouter

router = HybridResourceRouter()
tasks = [('test_cpu.sh', 5, 20), ('llm_knowledge_update', 5, 15)]
res = router.route_many(tasks)
m = CostMonitor()
rep = m.report(res)
print('has_net_save=' + str('net_save' in rep))
print('has_ts=' + str('ts' in rep))
print('net_save=' + str(rep['net_save']))
")
check "v1.0 report 有 net_save" "$(echo "$R" | grep 'has_net_save=' | cut -d'=' -f2)" "True"
check "v1.0 report 有 ts" "$(echo "$R" | grep 'has_ts=' | cut -d'=' -f2)" "True"
check "v1.0 report 净节省=20" "$(echo "$R" | grep '^net_save=' | cut -d'=' -f2)" "20.0"

# ---------- 2. 三合一报表：增量 + 缓存跳过 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cost import CostMonitor

# 模拟 policy.build_plan 输出
plan = {
    'mode': 'incremental+cache',
    'run': ['test_c.sh'],
    'skip': ['test_a.sh', 'test_b.sh'],
    'reason': {
        'test_a.sh': 'not affected by changes',
        'test_b.sh': 'source fingerprint unchanged (cache hit)',
    },
}
# 成本：a=20, b=15, c=10
costs = {'test_a.sh': 20.0, 'test_b.sh': 15.0, 'test_c.sh': 10.0}

m = CostMonitor()
rep = m.report_optimizer(plan, costs=costs)
print('inc_saved=' + str(rep['incremental_saved']))
print('cache_saved=' + str(rep['cache_saved']))
print('total_saved=' + str(rep['total_saved']))
print('hit_rate=' + str(rep['hit_rate']))
print('skip=' + str(rep['skip_scripts']))
print('run=' + str(rep['run_scripts']))
")
check "增量节省=20.0" "$(echo "$R" | grep 'inc_saved=' | cut -d'=' -f2)" "20.0"
check "缓存节省=15.0" "$(echo "$R" | grep 'cache_saved=' | cut -d'=' -f2)" "15.0"
check "跳过数=2" "$(echo "$R" | grep 'skip=' | cut -d'=' -f2)" "2"
check "运行数=1" "$(echo "$R" | grep 'run=' | cut -d'=' -f2)" "1"
check "命中率=0.6667" "$(echo "$R" | grep 'hit_rate=' | cut -d'=' -f2)" "0.6667"

# ---------- 3. 并行节省（有 run_result） ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cost import CostMonitor

plan = {
    'mode': 'incremental+cache',
    'run': ['test_c.sh'],
    'skip': [],
    'reason': {},
}
# run_result 模拟：并行跑了 2 个脚本总耗时 120s
run_result = {
    'summary': {'total': 2, 'pass': 2, 'fail': 0, 'timeout': 0, 'total_duration': 120},
}

m = CostMonitor()
rep = m.report_optimizer(plan, run_result=run_result, costs={'test_c.sh': 10.0})
print('time_saved=' + str(rep['parallel_time_saved']))
print('has_speedup=' + str(rep['speedup'] > 0))
print('mode=' + str(rep['mode']))
")
check "并行节省>0" "$(echo "$R" | grep 'time_saved=' | cut -d'=' -f2 | awk '{print ($1>0)?"True":"False"}')" "True"
check "有加速比" "$(echo "$R" | grep 'has_speedup=' | cut -d'=' -f2)" "True"
check "mode正确" "$(echo "$R" | grep 'mode=' | cut -d'=' -f2)" "incremental+cache"

# ---------- 4. 无 run_result 时估算 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cost import CostMonitor

plan = {
    'mode': 'full',
    'run': ['test_a.sh', 'test_b.sh'],
    'skip': [],
    'reason': {},
}
m = CostMonitor()
rep = m.report_optimizer(plan)
print('has_total_saved=' + str('total_saved' in rep))
print('total_scripts=' + str(rep['total_scripts']))
print('run_scripts=' + str(rep['run_scripts']))
")
check "无run_result也有报表" "$(echo "$R" | grep 'has_total_saved=' | cut -d'=' -f2)" "True"
check "total_scripts=2" "$(echo "$R" | grep 'total_scripts=' | cut -d'=' -f2)" "2"

# ---------- 5. full 模式全量无跳过 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cost import CostMonitor

plan = {
    'mode': 'full',
    'run': ['test_a.sh', 'test_b.sh', 'test_c.sh'],
    'skip': [],
    'reason': {},
}
m = CostMonitor()
rep = m.report_optimizer(plan, costs={'test_a.sh': 10.0, 'test_b.sh': 10.0, 'test_c.sh': 10.0})
print('inc_saved=' + str(rep['incremental_saved']))
print('cache_saved=' + str(rep['cache_saved']))
print('skip=' + str(rep['skip_scripts']))
print('hit_rate=' + str(rep['hit_rate']))
")
check "full增量节省=0" "$(echo "$R" | grep 'inc_saved=' | cut -d'=' -f2)" "0"
check "full缓存节省=0" "$(echo "$R" | grep 'cache_saved=' | cut -d'=' -f2)" "0"
check "full跳过=0" "$(echo "$R" | grep 'skip=' | cut -d'=' -f2)" "0"
check "full命中率=0" "$(echo "$R" | grep 'hit_rate=' | cut -d'=' -f2)" "0.0"

echo ""
echo "=============================="
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ] || exit 1
