#!/usr/bin/env bash
# ============================================================
# 事件驱动自动打标脚本（Issue #51 · 标签自动化 MCP 管线）
# ------------------------------------------------------------
# 用途：在 CI 事件钩子（issue.open / issue.update）到达时，程序化
#      给 Issue 自动打标签，无需任何 agent 记得去调。
#
# 用法：
#   bash scripts/auto-label.sh auto --event issue.open --entity "issue-<编号>" --operator 系统
#   bash scripts/auto-label.sh refresh --entity "issue-<编号>" --goal-total <总量> --current <当前>
#
# 依赖：local-agent/label/cli.py（python -m label.cli）
# ============================================================
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/local-agent"

EVENT="${1:-auto}"
shift || true

echo "[auto-label] 事件驱动自动打标：$EVENT $*"
python3 -m label.cli "$EVENT" "$@"
echo "[auto-label] done"
