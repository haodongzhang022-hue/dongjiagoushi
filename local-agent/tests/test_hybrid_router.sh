#!/usr/bin/env bash
# ============================================================
# Hybrid 资源路由模块 · 测试
# ============================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
ROOT="$(pwd)"
export PYTHONPATH="$ROOT/local-agent:${PYTHONPATH:-}"

PASS=0
FAIL=0

check() {
  local desc="$1"
  local expected="$2"
  local actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  ✅ $desc"
    PASS=$((PASS+1))
  else
    echo "  ❌ $desc (期望: $expected, 实际: $actual)"
    FAIL=$((FAIL+1))
  fi
}

echo "==== Hybrid 资源路由模块测试 ===="
echo ""

# ============================================
echo "1. 路由决策测试"
# ============================================
ROUTE=$(python3 -c "
from hybrid.router import HybridResourceRouter
r = HybridResourceRouter()
print(r.route('bash tests/test_architect_system.sh'))
print(r.route('bash local-agent/tests/test_scale.sh'))
print(r.route('knowledge:update'))
print(r.route('npc:go'))
print(r.route('codewiki'))
print(r.route('python3 scripts/local-exec.sh'))
")
readarray -t ROUTES <<< "$ROUTE"

check "测试脚本→local" "local" "${ROUTES[0]}"
check "测试脚本→local" "local" "${ROUTES[1]}"
check "knowledge→cloud" "cloud" "${ROUTES[2]}"
check "npc→cloud" "cloud" "${ROUTES[3]}"
check "codewiki→cloud" "cloud" "${ROUTES[4]}"
check "脚本→local" "local" "${ROUTES[5]}"

# ============================================
echo ""
echo "2. classify_task 便捷函数测试"
# ============================================
RES=$(python3 -c "
from hybrid.router import classify_task
print(classify_task('bash tests/test_doc_consistency.sh'))
print(classify_task('knowledge:update'))
print(classify_task('unknown_task'))
")
readarray -t CLASSES <<< "$RES"
check "classify→local" "local" "${CLASSES[0]}"
check "classify→cloud" "cloud" "${CLASSES[1]}"
check "classify→auto" "auto" "${CLASSES[2]}"

# ============================================
echo ""
echo "3. 本地执行器测试"
# ============================================
WORKER=$(python3 -c "
from hybrid.worker import LocalWorker
w = LocalWorker()
rc, stdout, stderr = w.run_command('echo hello')
print(f'rc={rc}')
print(f'out={stdout.strip()}')
")
if echo "$WORKER" | grep -q "rc=0" && echo "$WORKER" | grep -q "out=hello"; then
  echo "  ✅ run_command 执行成功"
  PASS=$((PASS+1))
else
  echo "  ❌ run_command 执行失败"
  echo "$WORKER"
  FAIL=$((FAIL+1))
fi

# ============================================
echo ""
echo "4. 成本估算测试"
# ============================================
COST=$(python3 -c "
from hybrid.cost import CostMonitor
m = CostMonitor()
r = m.estimate_savings(cloud_minutes=20, local_minutes=2)
print(f\"saved_pct={r['saved_pct']}\")
print(f\"saved_cost={r['saved_cost']}\")
print(f\"saved_minutes={r['saved_minutes']}\")
")
if echo "$COST" | grep -q "saved_pct=90.0"; then
  echo "  ✅ 成本节省 90% 正确"
  PASS=$((PASS+1))
else
  echo "  ❌ 成本节省计算错误: $COST"
  FAIL=$((FAIL+1))
fi
if echo "$COST" | grep -q "saved_cost=9.0"; then
  echo "  ✅ 节省金额正确"
  PASS=$((PASS+1))
else
  echo "  ❌ 节省金额错误: $COST"
  FAIL=$((FAIL+1))
fi
if echo "$COST" | grep -q "saved_minutes=18"; then
  echo "  ✅ 节省分钟正确"
  PASS=$((PASS+1))
else
  echo "  ❌ 节省分钟错误: $COST"
  FAIL=$((FAIL+1))
fi

# ============================================
echo ""
echo "5. CLI 入口测试"
# ============================================
CLI1=$(PYTHONPATH="$ROOT/local-agent" python3 local-agent/hybrid/cli.py route "bash tests/test_galton.sh" 2>&1 | tail -1)
check "CLI route→local" "路由: local" "$CLI1"

CLI2=$(PYTHONPATH="$ROOT/local-agent" python3 local-agent/hybrid/cli.py route "knowledge:update" 2>&1 | tail -1)
check "CLI route→cloud" "路由: cloud" "$CLI2"

CLI3=$(PYTHONPATH="$ROOT/local-agent" python3 local-agent/hybrid/cli.py cost-report 2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['script_count'])" 2>/dev/null || echo "error")
if [ "$CLI3" != "error" ]; then
  echo "  ✅ CLI cost-report 可用 (script_count=$CLI3)"
  PASS=$((PASS+1))
else
  echo "  ❌ CLI cost-report 失败"
  FAIL=$((FAIL+1))
fi

# ============================================
echo ""
echo "6. 模块导入完整性"
# ============================================
IMPORT=$(python3 -c "
from hybrid import HybridResourceRouter, LocalWorker, ResultSyncer, CostMonitor
from hybrid import RESOURCE_LOCAL, RESOURCE_CLOUD, RESOURCE_AUTO
from hybrid import classify_task, run_tests_local, sync_results, estimate_savings
print('ok')
" 2>&1)
check "模块导入" "ok" "$IMPORT"

# ============================================
echo ""
echo "==== 测试结果 ===="
echo "  通过: $PASS"
echo "  失败: $FAIL"
if [ "$FAIL" -gt 0 ]; then
  exit 1
else
  echo "✅ 全部通过"
  exit 0
fi
