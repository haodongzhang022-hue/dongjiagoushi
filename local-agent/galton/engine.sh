#!/usr/bin/env bash
# ============================================================
# 高尔顿板（Galton Board）MVP 原型 · Bash 核心引擎
# ============================================================
# 模拟高尔顿板物理原理的软件流水线：
#   Router（钉子）→ Worker×3（路径加工）→ Aggregator（槽位归集）
#
# 物理对照：
#   - 球（Ball）     = 输入任务中的一个数据项
#   - Router（钉子） = 将每个球按策略路由到 3 个 Worker 之一
#   - Worker（路径） = 对球做「加工」（统计/标记/变换）
#   - Aggregator     = 收集全部 Worker 产出，合并成最终分布结果
#
# 用法：
#   galton/engine.sh route   <strategy> [items...]    # 路由到 worker 列表
#   galton/engine.sh worker  <worker_id> <item>       # 单 worker 加工
#   galton/engine.sh aggregate                        # 汇总合并
#   galton/engine.sh run     <strategy> [items...]    # 跑完整闭环
#   galton/engine.sh demo                             # 跑演示闭环
# ============================================================
set -euo pipefail

GALTON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_COUNT=3
WORKER_DIR="${GALTON_DIR}/_runtime/workers"
OUT_DIR="${GALTON_DIR}/_runtime/out"

# ---------- 工具函数 ----------
mkdir_runtime() {
    mkdir -p "$WORKER_DIR" "$OUT_DIR"
}

# ---------- Router：按策略路由球到 Worker ----------
# 策略：
#   round-robin  : 轮询（每个球依次分配到 worker1/2/3/1/2/3...）
#   hash         : 哈希（按字符串 hash 取模）
#   random       : 随机（随机分配到 1..3）
route_ball() {
    local strategy="$1"
    local item="$2"
    local index="$3"  # 球序号（从 0 开始）
    local worker_id

    case "$strategy" in
        round-robin)
            worker_id=$((index % WORKER_COUNT + 1))
            ;;
        hash)
            # 简单哈希：对字符串逐字符累加
            local hash=0
            local i
            for ((i=0; i<${#item}; i++)); do
                local ch="${item:$i:1}"
                hash=$(( (hash * 31 + $(LC_ALL=C printf '%d' "'$ch")) % 100000 ))
            done
            worker_id=$((hash % WORKER_COUNT + 1))
            ;;
        random)
            worker_id=$((RANDOM % WORKER_COUNT + 1))
            ;;
        *)
            echo "ERROR: 未知路由策略 '$strategy'，可选：round-robin / hash / random" >&2
            exit 1
            ;;
    esac
    echo "$worker_id"
}

# ---------- Worker：加工一个球 ----------
# worker 加工逻辑：给球打上 [W<id>:<原内容>] 标记，并统计自身处理的球数
worker_process() {
    local worker_id="$1"
    local item="$2"
    local stamp

    mkdir_runtime
    # 加工：给球打上 worker 标记
    stamp="[W${worker_id}@$(date +%s%N)]${item}"
    # 写入该 worker 的产出文件
    echo "$stamp" >> "${WORKER_DIR}/w${worker_id}.out"
    echo "$stamp"
}

# ---------- Aggregator：汇总全部 Worker 产出 ----------
# 合并所有 worker 产出，统计每个 worker 处理的球数和分布
aggregate() {
    mkdir_runtime

    local total=0
    local i
    local line

    echo "===== 高尔顿板 · 汇总结果 ====="
    echo ""
    echo "--- 各 Worker 产出明细 ---"

    for ((i=1; i<=WORKER_COUNT; i++)); do
        local wfile="${WORKER_DIR}/w${i}.out"
        local count=0
        if [ -f "$wfile" ]; then
            count=$(wc -l < "$wfile")
            echo "  Worker $i: $count 球"
        else
            echo "  Worker $i: 0 球"
        fi
        total=$((total + count))
    done

    echo ""
    echo "--- 分布统计（高尔顿板分布） ---"
    echo "  球总数: $total"
    for ((i=1; i<=WORKER_COUNT; i++)); do
        local wfile="${WORKER_DIR}/w${i}.out"
        local count=0
        local pct=0
        if [ -f "$wfile" ]; then
            count=$(wc -l < "$wfile")
        fi
        if [ "$total" -gt 0 ]; then
            pct=$((count * 100 / total))
        fi
        echo "  Worker $i: $count 球 ($pct%)"
    done

    echo ""
    echo "--- 合并后的完整产出 ---"
    # 按 worker 顺序合并
    for ((i=1; i<=WORKER_COUNT; i++)); do
        local wfile="${WORKER_DIR}/w${i}.out"
        if [ -f "$wfile" ]; then
            cat "$wfile"
        fi
    done
}

# ---------- 跑完整闭环 ----------
run_galton() {
    local strategy="$1"
    shift
    local items=("$@")

    mkdir_runtime
    # 清理上次运行
    rm -rf "${WORKER_DIR}"/* "${OUT_DIR}"/*

    local idx=0
    local item
    echo "===== 高尔顿板 · 完整闭环 ====="
    echo "  路由策略: $strategy"
    echo "  球数量: ${#items[@]}"
    echo "  Worker 数量: $WORKER_COUNT"
    echo ""

    for item in "${items[@]}"; do
        # Router 路由
        local wid
        wid=$(route_ball "$strategy" "$item" "$idx")
        # Worker 加工
        local processed
        processed=$(worker_process "$wid" "$item")
        echo "  球[$idx] → Worker$wid : $processed"
        idx=$((idx + 1))
    done

    echo ""
    aggregate
}

# ---------- 演示 ----------
demo() {
    run_galton "round-robin" "task-a" "task-b" "task-c" "task-d" "task-e" "task-f" "task-g" "task-h" "task-i"
}

# ---------- 入口 ----------
case "${1:-}" in
    route)
        route_ball "$2" "$3" "${4:-0}"
        ;;
    worker)
        worker_process "$2" "$3"
        ;;
    aggregate)
        aggregate
        ;;
    run)
        shift
        strategy="$1"
        shift
        run_galton "$strategy" "$@"
        ;;
    demo)
        demo
        ;;
    *)
        echo "用法: galton/engine.sh {route|worker|aggregate|run|demo}"
        echo "  route <strategy> <item> [index]  # 路由球到 worker"
        echo "  worker <worker_id> <item>        # 单 worker 加工"
        echo "  aggregate                        # 汇总合并"
        echo "  run <strategy> <items...>        # 跑完整闭环"
        echo "  demo                             # 跑演示闭环"
        exit 1
        ;;
esac
