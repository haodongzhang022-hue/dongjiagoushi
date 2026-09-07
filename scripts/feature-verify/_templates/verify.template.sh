#!/usr/bin/env bash
# ============================================================
# [feature-verify] <module> / <功能名>
# ============================================================
# module:   <模块实现域，如 dispatch / dashboard>
# feature:  <可感知语义的一句话功能名>
# 五要素:
#   Given    <前提 / 前置条件>
#   When     <触发动作——实际跑什么>
#   Then     <机器判据：功能完成才算通过的断言（可感知语义，不是"通畅"）>
#   Evidence <可核验产物：跑完落到哪个可 grep/可查的语义产物>
#   为什么是"功能级": <说明纯 grep/通畅测试抓不到、本脚本如何真实判"功能做完">
# 用法：bash scripts/feature-verify/<module>/<功能名>.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }
echo "==== [feature-verify] <module>/<功能名> ===="
# ---- When + Then：真实执行并断言语义 ----
# ... 你的机器判据 ...
echo ""
if [ "$FAIL" -gt 0 ]; then
  echo "🔴 <module>/<功能名> 未达成 → 功能没做完"
  exit 1
else
  echo "🟢 <module>/<功能名> 通过"
  exit 0
fi
