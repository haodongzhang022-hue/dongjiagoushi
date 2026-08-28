#!/usr/bin/env bash
# ============================================================
# 本地执行入口 · Hybrid 资源路由
# ============================================================
# 将纯 CPU 密集操作（37 个测试脚本）从云端移到本地执行，
# 云端只保留 LLM 强相关操作（knowledge:update / npc:go / codewiki）。
#
# 用法：
#   bash scripts/local-exec.sh              # 全流程（测试+同步+成本）
#   bash scripts/local-exec.sh --no-sync    # 只跑测试不推送
#   bash scripts/local-exec.sh --quick      # 只跑关键测试（前 10 个）
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SYNC="true"
QUICK="false"

for arg in "$@"; do
  case "$arg" in
    --no-sync) SYNC="false" ;;
    --quick)   QUICK="true" ;;
  esac
done

echo "=============================================="
echo " Hybrid 资源路由 · 本地执行"
echo "=============================================="
echo "工作目录: $ROOT"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 构建测试脚本列表
if [ "$QUICK" = "true" ]; then
  TEST_SCRIPTS=(
    "tests/test_doc_consistency.sh"
    "tests/test_mini_e2e.sh"
    "local-agent/tests/test_galton.sh"
    "local-agent/tests/test_router_integration.sh"
    "local-agent/tests/test_scale.sh"
    "local-agent/tests/test_dispatch_engine.sh"
    "local-agent/tests/test_depth_engine.sh"
    "tests/test_architect_system.sh"
    "tests/test_company_model.sh"
    "local-agent/tests/test_local_agent.sh"
  )
else
  TEST_SCRIPTS=(
    "tests/test_architect_system.sh"
    "tests/test_functional_links.sh"
    "tests/test_relay_workflow.sh"
    "tests/test_memory_store.sh"
    "local-agent/tests/test_local_agent.sh"
    "local-agent/tests/test_scale.sh"
    "local-agent/tests/test_prescale_entry.sh"
    "tests/test_handle_ability.sh"
    "local-agent/tests/test_engine.sh"
    "local-agent/tests/test_data_layer.sh"
    "local-agent/tests/test_collab.sh"
    "local-agent/tests/test_peer_collab.sh"
    "local-agent/tests/test_peer_closure.sh"
    "local-agent/tests/test_disposition.sh"
    "local-agent/tests/test_sentinel.sh"
    "local-agent/tests/test_external_source.sh"
    "local-agent/tests/test_dispatcher.sh"
    "local-agent/tests/test_probe.sh"
    "local-agent/tests/test_dispatch_engine.sh"
    "local-agent/tests/test_depth_engine.sh"
    "local-agent/tests/test_ops_sim.sh"
    "local-agent/tests/test_topology_comparison.sh"
    "local-agent/tests/test_benchmark_ab.sh"
    "local-agent/tests/test_topology_hybrid.sh"
    "local-agent/tests/test_galton.sh"
    "local-agent/tests/test_topology_fusion.sh"
    "local-agent/tests/test_topology_slim.sh"
    "local-agent/tests/test_secretary_sense.sh"
    "local-agent/tests/test_prefix_cache.sh"
    "local-agent/tests/test_router_integration.sh"
    "local-agent/tests/test_cache_layer.sh"
    "tests/test_company_model.sh"
    "tests/test_mini_e2e.sh"
    "local-agent/tests/test_label_automation.sh"
    "local-agent/tests/test_review_tester_handoff.sh"
    "local-agent/tests/test_deliverer.sh"
    "tests/test_doc_consistency.sh"
  )
fi

echo "待执行测试脚本: ${#TEST_SCRIPTS[@]} 个"
echo ""

# 逐条执行并汇总
PASSED=0
FAILED=0
FAILED_NAMES=()
TOTAL=${#TEST_SCRIPTS[@]}

for i in "${!TEST_SCRIPTS[@]}"; do
  script="${TEST_SCRIPTS[$i]}"
  name="$(basename "$script")"
  printf "[%3d/%3d] %-50s " "$((i+1))" "$TOTAL" "$name"
  if [ -f "$ROOT/$script" ]; then
    if bash "$ROOT/$script" > /tmp/hybrid-test-out.log 2>&1; then
      PASSED=$((PASSED+1))
      echo "✅ PASS"
    else
      FAILED=$((FAILED+1))
      FAILED_NAMES+=("$script")
      echo "❌ FAIL"
      echo "      $(tail -3 /tmp/hybrid-test-out.log | head -1)"
    fi
  else
    echo "⚠️  SKIP (不存在)"
  fi
done

echo ""
echo "=============================================="
echo " 本地测试结果汇总"
echo "=============================================="
echo "  总数: $TOTAL"
echo "  通过: $PASSED"
echo "  失败: $FAILED"

if [ ${#FAILED_NAMES[@]} -gt 0 ]; then
  echo ""
  echo "失败列表:"
  for name in "${FAILED_NAMES[@]}"; do
    echo "  ✗ $name"
  done
fi

# 写出结果 JSON（供 sync 使用）
mkdir -p .cnb-results
cat > .cnb-results/results.json << 'JSONEOF'
{
  "timestamp": "$(date '+%Y-%m-%d %H:%M:%S')",
  "total": $TOTAL,
  "passed": $PASSED,
  "failed": $FAILED,
  "skipped": 0,
  "duration": 0,
  "tests": []
}
JSONEOF

# 同步到云端
if [ "$SYNC" = "true" ]; then
  echo ""
  echo "同步结果到云端..."
  git add .cnb-results/ 2>/dev/null || true
  if git diff --cached --quiet .cnb-results/ 2>/dev/null; then
    echo "无变更，跳过 commit"
  else
    git config user.name "hybrid-sync-bot" 2>/dev/null || true
    git config user.email "hybrid-sync@cnb.cool" 2>/dev/null || true
    git commit -m "chore(hybrid): 本地测试结果同步 (PASS=$PASSED/FAIL=$FAILED)"
    git push origin HEAD 2>/dev/null || echo "push 失败（忽略，本地已完成）"
  fi
fi

echo ""
if [ "$FAILED" -gt 0 ]; then
  echo "⚠️  有失败项，请检查。"
  exit 1
else
  echo "✅ 全部通过！"
  exit 0
fi
