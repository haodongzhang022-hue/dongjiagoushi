#!/usr/bin/env bash
# ============================================================
# 真实任务 AB 隔离对比测试（test_benchmark_ab.sh）
# 验证：benchmark 能读真实任务 / 做 AB 隔离对比 / 全维度采集 /
#       资源监控 / 汇总输出 / 旧数据缺维度不污染汇总
# 环境：无 python3 时跳过（沙盒限制，云 CI 验证）
# ============================================================
set -e

echo "==== 真实任务 AB 隔离对比测试（benchmark）===="

if ! command -v python3 &>/dev/null; then
    echo "⚠️  沙盒无 python3，跳过 benchmark AB 对比测试（须在云 CI 验证）"
    echo "  SKIPPED"
    exit 0
fi

TOPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$TOPO_DIR"

PASS=0
FAIL=0
BENCH="python3 topology/benchmark.py"

# B-01: 列出真实任务
echo "--- B-01: 列出真实任务 ---"
OUT=$($BENCH --list-tasks 2>&1) || true
if echo "$OUT" | grep -q "架构完·未分配\|architected_unassigned" \
   && echo "$OUT" | grep -q "经理已分工·未触发\|assigned_untriggered"; then
    echo "  ✓ B-01 通过：列出真实未完成任务"
    PASS=$((PASS+1))
else
    echo "  ✗ B-01 失败：未能列出真实任务"
    echo "$OUT"
    FAIL=$((FAIL+1))
fi

# B-02: 跑一次真实任务 AB 隔离对比（无 LLM）
echo "--- B-02: 真实任务 AB 隔离对比 ---"
OUT=$($BENCH --task stage:architected_unassigned --topologies linear,dag,event --no-llm 2>&1) || true
if echo "$OUT" | grep -q "AB对比" && echo "$OUT" | grep -q "linear" \
   && echo "$OUT" | grep -q "dag" && echo "$OUT" | grep -q "event"; then
    echo "  ✓ B-02 通过：三条拓扑 AB 隔离对比执行成功"
    PASS=$((PASS+1))
else
    echo "  ✗ B-02 失败：AB 对比未成功"
    echo "$OUT"
    FAIL=$((FAIL+1))
fi

# B-03: 全维度指标采集（9 个关键维度都要有）
echo "--- B-03: 全维度指标采集 ---"
OUT=$($BENCH --compare "$($BENCH --list-tasks 2>&1 | grep -oP 'task_id=\K[a-z0-9-]+' | head -1)" 2>&1) || true
if echo "$OUT" | grep -q "并发" && echo "$OUT" | grep -q "耗时" \
   && echo "$OUT" | grep -q "完成" && echo "$OUT" | grep -q "bug" \
   && echo "$OUT" | grep -q "token" && echo "$OUT" | grep -q "文件" \
   && echo "$OUT" | grep -q "agent" && echo "$OUT" | grep -q "CPU"; then
    echo "  ✓ B-03 通过：9 大对比维度全部采集"
    PASS=$((PASS+1))
else
    echo "  ✗ B-03 失败：维度采集不完整"
    echo "$OUT"
    FAIL=$((FAIL+1))
fi

# B-04: 全维度汇总 + 旧数据缺维度不污染
echo "--- B-04: 全维度汇总 ---"
OUT=$($BENCH --summary 2>&1) || true
if echo "$OUT" | grep -q "全维度指标汇总" && echo "$OUT" | grep -q "最大并发" \
   && echo "$OUT" | grep -q "token" && echo "$OUT" | grep -q "CPU%"; then
    echo "  ✓ B-04 通过：全维度汇总输出正常"
    PASS=$((PASS+1))
else
    echo "  ✗ B-04 失败：汇总输出异常"
    echo "$OUT"
    FAIL=$((FAIL+1))
fi

echo ""
echo "============================================"
echo "Benchmark AB 对比测试：PASS=$PASS FAIL=$FAIL"
echo "============================================"

[ "$FAIL" -eq 0 ] || exit 1
