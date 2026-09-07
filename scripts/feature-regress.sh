#!/usr/bin/env bash
# ============================================================
# feature-regress —— 功能级回归诊断（Issue #109）
# ============================================================
# 作用：崩了 / 升级后全量跑一遍 feature-verify，输出「哪个功能通过 / 哪个崩」，
#       崩的就是坏的那个功能 → 直接定位（恢复能力一部分）。
#
# 本质：scripts/feature-verify.sh --all 的语义别名（回归诊断入口）。
#   feature-verify.sh 是模块主执行器，feature-regress.sh 是其"回归诊断"面向命令——
#   同一套证据库、同一套判据，崩了先全量回归定位坏功能。
#
# 用法：
#   bash scripts/feature-regress.sh            # 全量回归诊断
#   bash scripts/feature-regress.sh --module X # 只回归某模块
#   bash scripts/feature-regress.sh --dry-run  # 只盘点将跑哪些（不执行）
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ARGS=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    *) ARGS+=("$arg") ;;
  esac
done

echo "==== [feature-regress] 功能级回归诊断 ===="
if [ "${DRY:-0}" = "1" ]; then
  bash scripts/feature-verify.sh --list
  exit 0
fi
exec bash scripts/feature-verify.sh --all "${ARGS[@]:-}"
