#!/usr/bin/env bash
# ============================================================
# 本地执行入口（scripts/local-exec.sh）
# ============================================================
# Issue #57「云原生构建-CPU 本地化开发」：
#   云端 CI 只保留 LLM 强相关操作，37 个 CPU 密集测试脚本本地执行。
#   本脚本是本地的统一入口：route 判定 → run 批量执行 → sync 同步留痕 → cost 报表。
#
# 用法：
#   bash scripts/local-exec.sh                # 完整链路（dry-run 演练）
#   bash scripts/local-exec.sh --real         # 真实执行（不演练，真跑测试）
#   bash scripts/local-exec.sh --only cost    # 只看成本报表
#   bash scripts/local-exec.sh --help
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/local-agent"    # hybrid 包在 local-agent 下，需切到此目录执行

MODE=dry        # 默认演练（不真跑，避免 CI/本地误执行耗时测试）
ONLY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --real) MODE=real ;;
    --only) ONLY="$2"; shift ;;
    --help|-h)
      echo "用法: bash scripts/local-exec.sh [--real] [--only cost]"
      exit 0 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
  shift
done

# 演练标志：传给 cli
DRY_FLAG=""
[ "$MODE" = "real" ] || DRY_FLAG="--dry"

echo "==== 云原生构建-CPU 本地化 · 本地执行入口 ===="
echo "模式: $MODE | 工作根: $ROOT"

if [ "$ONLY" = "cost" ]; then
  echo "== 成本报表 =="
  python3 -m hybrid.cli cost
  exit 0
fi

echo "== 完整链路：route → run → sync → cost =="
python3 -m hybrid.cli all $DRY_FLAG --timeout 600

echo ""
echo "==== 本地执行完成 ===="
echo "提示：云端 .cnb.yml 已移除这些 CPU 密集命令，结果已由 sync 同步留痕。"
