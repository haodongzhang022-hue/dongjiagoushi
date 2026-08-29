#!/usr/bin/env bash
# ============================================================
# 开发规范 CI 接线脚本（Issue #83 · M5 MCP 宿主接入）
# ------------------------------------------------------------
# 用途：在 CI 流水线（pull_request 等事件）到达时，程序化执行开发规范
#      检查（standard.check / standard.check-pr / standard.check-code），
#      无需任何 agent 记得去调——规范随流水线强制落地。
#
# 用法：
#   bash scripts/standard-check.sh list                        # 规范清单
#   bash scripts/standard-check.sh enforced --stage pre_pr     # 阶段强制规范
#   bash scripts/standard-check.sh check-pr --target main --source auto/x-1 \
#       --test-files "tests/a.sh,tests/b.sh" --docs-files "docs/A.md"
#   bash scripts/standard-check.sh check-code --file local-agent/x.py
#   bash scripts/standard-check.sh check-all '{"pr_info": {...}}'  # 全量 target
#   bash scripts/standard-check.sh host                          # 宿主工具清单
#
# 依赖：local-agent/dev_standard/host.py + cli.py
# 说明：任何检查硬失败(hard) → 退出码 1（阻断流水线）；全过 → 0。
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/local-agent"

CMD="${1:-list}"
shift || true

# 沙盒差异兼容：优先 python3，回退 python
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi

blocked_exit() {
  echo "[standard-check] ❌ 硬失败（hard）：规范阻断，须整改后重新提交" >&2
  exit 1
}

case "$CMD" in
  list|get|enforced|summary)
    echo "[standard-check] 查询规范：$CMD $*"
    "$PY" -m dev_standard.cli "$CMD" "$@"
    ;;
  check-pr)
    echo "[standard-check] PR 规范检查（确定性 · hard 阻断）"
    out="$("$PY" -m dev_standard.cli check-pr "$@")"
    echo "$out"
    echo "$out" | grep -q '"overall": "blocked"' && blocked_exit
    ;;
  check-code)
    echo "[standard-check] 代码规范检查（确定性 · hard 阻断）"
    out="$("$PY" -m dev_standard.cli check-code "$@")"
    echo "$out"
    echo "$out" | grep -q '"overall": "blocked"' && blocked_exit
    ;;
  check-all)
    echo "[standard-check] 全量规范检查（确定性 · hard 阻断）"
    out="$("$PY" -m dev_standard.cli check-all --target "$@")"
    echo "$out"
    echo "$out" | grep -q '"overall": "blocked"' && blocked_exit
    ;;
  host)
    echo "[standard-check] MCP 宿主工具清单"
    "$PY" -m dev_standard.host list
    ;;
  *)
    echo "[standard-check] 未知命令：$CMD"
    echo "可用：list / get / enforced / summary / check-pr / check-code / check-all / host" >&2
    exit 2
    ;;
esac
echo "[standard-check] done"
