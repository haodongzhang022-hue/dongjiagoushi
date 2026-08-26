#!/usr/bin/env bash
# ============================================================
# 高尔顿板（Galton Board）MVP 原型测试（test_galton.sh）
# ============================================================
# 验证：「球路由 → 加工 → 合并」闭环
#   T-01: Router 路由正确（round-robin 轮询到 3 个 worker）
#   T-02: Worker 加工正确（打上 [W<id>] 标记）
#   T-03: Aggregator 合并正确（汇总分布统计）
#   T-04: 完整闭环运行成功（run 命令全流程）
#   T-05: 非法策略报错
#   T-06: worker_id 越界报错（Python 版）
#   T-07: 多策略路由分布合理（hash 版）
#   T-08: Python 接口验证（有 python3 时）
#
# 环境：bash 版无需 python3（沙盒可跑）；Python 版需 python3。
# ============================================================
set -euo pipefail

GALTON_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="${GALTON_ROOT}/galton/engine.sh"
PY_ENGINE="${GALTON_ROOT}/galton/engine.py"
RUNTIME="${GALTON_ROOT}/galton/_runtime"

PASS=0
FAIL=0

echo "==== 高尔顿板 MVP 原型测试 ===="

# ---------- T-01: Router 轮询路由 ----------
echo "--- T-01: Router 轮询路由（round-robin） ---"
r0=$(bash "$ENGINE" route round-robin "task" 0)
r1=$(bash "$ENGINE" route round-robin "task" 1)
r2=$(bash "$ENGINE" route round-robin "task" 2)
r3=$(bash "$ENGINE" route round-robin "task" 3)
if [ "$r0" = "1" ] && [ "$r1" = "2" ] && [ "$r2" = "3" ] && [ "$r3" = "1" ]; then
    echo "  ✓ T-01 通过：轮询正确分配 1→2→3→1→..."
    PASS=$((PASS+1))
else
    echo "  ✗ T-01 失败：got r0=$r0 r1=$r1 r2=$r2 r3=$r3"
    FAIL=$((FAIL+1))
fi

# ---------- T-02: Worker 加工 ----------
echo "--- T-02: Worker 加工打标 ---"
w=$(bash "$ENGINE" worker 2 "hello")
if [[ "$w" == *"W2"* ]] && [[ "$w" == *"[W2"* ]] && [[ "$w" == *"hello"* ]]; then
    echo "  ✓ T-02 通过：Worker 2 正确加工并打标"
    PASS=$((PASS+1))
else
    echo "  ✗ T-02 失败：got '$w'"
    FAIL=$((FAIL+1))
fi

# ---------- T-03: Aggregator 汇总 ----------
echo "--- T-03: Aggregator 汇总合并 ---"
# 手动构造 worker 产出
rm -rf "$RUNTIME"
mkdir -p "${RUNTIME}/workers"
echo "[W1]apple" > "${RUNTIME}/workers/w1.out"
echo "[W1]date" >> "${RUNTIME}/workers/w1.out"
echo "[W2]banana" > "${RUNTIME}/workers/w2.out"
echo "[W3]cherry" > "${RUNTIME}/workers/w3.out"
out=$(bash "$ENGINE" aggregate)
if echo "$out" | grep -q "球总数: 4" && \
   echo "$out" | grep -q "Worker 1: 2" && \
   echo "$out" | grep -q "Worker 2: 1" && \
   echo "$out" | grep -q "Worker 3: 1"; then
    echo "  ✓ T-03 通过：汇总统计正确（2+1+1=4）"
    PASS=$((PASS+1))
else
    echo "  ✗ T-03 失败：aggregate 输出异常"
    echo "$out"
    FAIL=$((FAIL+1))
fi

# ---------- T-04: 完整闭环 ----------
echo "--- T-04: 完整闭环（run round-robin） ---"
out=$(bash "$ENGINE" run round-robin "a" "b" "c" "d" "e" "f")
if echo "$out" | grep -q "球总数: 6" && \
   echo "$out" | grep -q "Worker 1: 2" && \
   echo "$out" | grep -q "Worker 2: 2" && \
   echo "$out" | grep -q "Worker 3: 2"; then
    echo "  ✓ T-04 通过：6 球轮询闭环，3 worker 各 2 球"
    PASS=$((PASS+1))
else
    echo "  ✗ T-04 失败：run 闭环异常"
    echo "$out"
    FAIL=$((FAIL+1))
fi

# ---------- T-05: 非法策略报错 ----------
echo "--- T-05: 非法路由策略报错 ---"
errout=$(bash "$ENGINE" run unknown_strategy "a" 2>&1) || true
if echo "$errout" | grep -q "未知路由策略"; then
    echo "  ✓ T-05 通过：非法策略正确报错"
    PASS=$((PASS+1))
else
    echo "  ✗ T-05 失败：非法策略未报错"
    echo "$errout"
    FAIL=$((FAIL+1))
fi

# ---------- T-06: worker_id 越界报错（Python 版） ----------
echo "--- T-06: worker_id 越界报错（Python 版） ---"
if command -v python3 &>/dev/null; then
    err=$(python3 -c "
import sys; sys.path.insert(0, '${GALTON_ROOT}')
from galton.engine import worker_process
try:
    worker_process('x', 99)
    print('NO_ERROR')
except ValueError as e:
    print('VALUE_ERROR')
" 2>&1)
    if echo "$err" | grep -q "VALUE_ERROR"; then
        echo "  ✓ T-06 通过：越界 worker_id 正确报错"
        PASS=$((PASS+1))
    else
        echo "  ✗ T-06 失败：越界 worker_id 未报错"
        FAIL=$((FAIL+1))
    fi
else
    echo "  ⏭ 沙盒无 python3，跳过 T-06（云 CI 验证）"
fi

# ---------- T-07: hash 策略分布 ----------
echo "--- T-07: hash 策略路由分布 ---"
out=$(bash "$ENGINE" run hash "apple" "banana" "cherry" "date" "elderberry" "fig" "grape" "honeydew" "kiwi" "lemon" "mango")
total=$(echo "$out" | grep "球总数:" | grep -oE '[0-9]+')
if [ "$total" = "11" ]; then
    echo "  ✓ T-07 通过：hash 策略 11 球全部处理"
    PASS=$((PASS+1))
else
    echo "  ✗ T-07 失败：hash 策略处理数量异常 total=$total"
    FAIL=$((FAIL+1))
fi

# ---------- T-08: Python 接口验证 ----------
echo "--- T-08: Python 接口验证 ---"
if command -v python3 &>/dev/null; then
    result=$(python3 -c "
import sys; sys.path.insert(0, '${GALTON_ROOT}')
from galton import route_ball, worker_process, aggregate, run_galton
# round-robin
assert route_ball('a', 0, 'round-robin') == 1
assert route_ball('a', 1, 'round-robin') == 2
assert route_ball('a', 2, 'round-robin') == 3
assert route_ball('a', 3, 'round-robin') == 1
# worker
assert worker_process('hello', 2) == '[W2]hello'
# aggregate
res = aggregate({1: ['[W1]a', '[W1]b'], 2: ['[W2]c'], 3: []})
assert res['total'] == 3
assert res['distribution'][1]['count'] == 2
assert len(res['merged']) == 3
# run_galton
res2 = run_galton(['a','b','c','d','e','f'], 'round-robin')
assert res2['total'] == 6
print('PY_OK')
" 2>&1)
    if echo "$result" | grep -q "PY_OK"; then
        echo "  ✓ T-08 通过：Python 接口全部断言通过"
        PASS=$((PASS+1))
    else
        echo "  ✗ T-08 失败：Python 接口断言异常"
        echo "$result"
        FAIL=$((FAIL+1))
    fi
else
    echo "  ⏭ 沙盒无 python3，跳过 T-08（云 CI 验证）"
fi

echo ""
echo "============================================"
echo "高尔顿板测试：PASS=$PASS FAIL=$FAIL"
echo "============================================"

# 清理运行时文件
rm -rf "$RUNTIME"

[ "$FAIL" -eq 0 ] || exit 1
