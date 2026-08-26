#!/usr/bin/env bash
# ============================================================
# 拓扑对比测试（test_topology_comparison.sh）
# 验证：topology 模块能列出拓扑 / 跑对比 / 记录指标 / 输出摘要
# 环境：无 python3 时跳过（沙盒限制，云 CI 验证）
# ============================================================
set -e

echo "==== 拓扑对比测试（topology comparison）===="

# 检查 python3
if ! command -v python3 &>/dev/null; then
    echo "⚠️  沙盒无 python3，跳过拓扑对比测试（须在云 CI 验证）"
    echo "    验证项：T-01 拓扑列表 / T-02 对比执行 / T-03 指标记录 / T-04 摘要输出"
    echo "  SKIPPED"
    exit 0
fi

TOPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$TOPO_DIR"

PASS=0
FAIL=0
RUNNER="python3 topology/runner.py"

# T-01: 列出拓扑
echo "--- T-01: 列出拓扑 ---"
OUT=$($RUNNER --list 2>&1) || true
if echo "$OUT" | grep -q "linear" && echo "$OUT" | grep -q "dag" && echo "$OUT" | grep -q "event"; then
    echo "  ✓ T-01 通过：列出 3 条拓扑"
    PASS=$((PASS+1))
else
    echo "  ✗ T-01 失败：未能列出全部拓扑"
    echo "$OUT"
    FAIL=$((FAIL+1))
fi

# T-02: 无 LLM 模式下跑一次对比（验证调度逻辑）
echo "--- T-02: 跑一次对比（--no-llm） ---"
OUT=$($RUNNER --req "做一个登录系统" --topologies linear,dag --no-llm 2>&1) || true
if echo "$OUT" | grep -q "对比结果" && echo "$OUT" | grep -q "linear" && echo "$OUT" | grep -q "dag"; then
    echo "  ✓ T-02 通过：两条拓扑对比执行成功"
    PASS=$((PASS+1))
else
    echo "  ✗ T-02 失败：对比执行未成功"
    echo "$OUT"
    FAIL=$((FAIL+1))
fi

# T-03: 指标已持久化
echo "--- T-03: 指标持久化 ---"
OUT=$($RUNNER --compare "做一个登录系统" 2>&1) || true
if echo "$OUT" | grep -q "跨拓扑\|linear" && echo "$OUT" | grep -q "dag"; then
    echo "  ✓ T-03 通过：指标持久化并可按需求查询"
    PASS=$((PASS+1))
else
    echo "  ✗ T-03 失败：指标持久化/查询异常"
    echo "$OUT"
    FAIL=$((FAIL+1))
fi

# T-04: 摘要输出
echo "--- T-04: 历史汇总摘要 ---"
OUT=$($RUNNER --summary 2>&1) || true
if echo "$OUT" | grep -q "拓扑对比" && echo "$OUT" | grep -q "linear" && echo "$OUT" | grep -q "dag"; then
    echo "  ✓ T-04 通过：摘要汇总输出正常"
    PASS=$((PASS+1))
else
    echo "  ✗ T-04 失败：摘要输出异常"
    echo "$OUT"
    FAIL=$((FAIL+1))
fi

echo ""
echo "============================================"
echo "拓扑对比测试：PASS=$PASS FAIL=$FAIL"
echo "============================================"

[ "$FAIL" -eq 0 ] || exit 1
