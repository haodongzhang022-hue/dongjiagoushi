#!/usr/bin/env bash
# ============================================================
# feature-verify —— 功能级校验闸门 / 全量回归入口（Issue #109）
# ============================================================
# 分层定位：
#   tests/test_*.sh             —— 保「框架/机制」畅通（信号灯 / 断言 / 通畅）
#   scripts/feature-verify/**.sh—— 保「具体目标功能按可感知语义真正做完」（本层）
#   review_metrics              —— 分档量化度量「解决/稳定性/通用性」
#
# 机制：每个目标功能在开发前先写一份机器可判的校验脚本（Test-First），
#       一 PR 一脚本，跑不过 = 功能没做完 → 合并闸门标 blocked_on: feature_unverified。
#       脚本留存为功能支撑证据档案库，随模块版本线留痕。
#
# 用法：
#   bash scripts/feature-verify.sh --all            # 全量回归（feature-regress 语义）
#   bash scripts/feature-verify.sh --module dispatch # 只跑某模块的所有 feature-verify
#   bash scripts/feature-verify.sh --feature dispatch/真实唤醒校验闸门  # 精确跑一个功能
#   bash scripts/feature-verify.sh --changed        # 按 git 变更自动选测受影响模块
#   bash scripts/feature-verify.sh --list           # 列出全部功能校验脚本（证据库盘点）
#
# 环境变量（合并闸门用）：
#   CNB_PULL_REQUEST_TARGET_SHA   # PR 目标分支 SHA
#   CNB_COMMIT                     # 本次提交 SHA
# ============================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
VERIFY_DIR="scripts/feature-verify"

MODE="all"
MODULE_SEL=""
FEATURE_SEL=""
prev=""
for i in "$@"; do
  case "$prev" in
    --module) MODULE_SEL="$i" ;;
    --feature) FEATURE_SEL="$i" ;;
  esac
  case "$i" in
    --all) MODE="all" ;;
    --list) MODE="list" ;;
    --changed) MODE="changed" ;;
    --module) MODE="module" ;;
    --feature) MODE="feature" ;;
  esac
  prev="$i"
done

# ------------------------------------------------------------
# 0. 收集所有 feature-verify 脚本（排除 _templates / README）
# ------------------------------------------------------------
declare -a ALL_SCRIPTS=()
if [ -d "$VERIFY_DIR" ]; then
  while IFS= read -r f; do
    [ -n "$f" ] && ALL_SCRIPTS+=("$f")
  done < <(find "$VERIFY_DIR" -name '*.sh' -not -path '*/_templates/*' | sort)
fi

list_mode() {
  echo "==== [feature-verify] 功能证据库盘点 ===="
  if [ "${#ALL_SCRIPTS[@]}" -eq 0 ]; then
    echo "  (空) 尚无 feature-verify 脚本——按 Test-First 为每个目标功能补一份。"
    exit 0
  fi
  local n=0
  for f in "${ALL_SCRIPTS[@]}"; do
    local module fea
    module="$(basename "$(dirname "$f")")"
    fea="$(basename "$f" .sh)"
    echo "  [${module}] ${fea}   → ${f}"
    n=$((n+1))
  done
  echo "  共 $n 份功能校验脚本（功能支撑证据档案库）"
  exit 0
}

# ------------------------------------------------------------
# 1. 确定变更文件列表（复用 change-aware 的 git diff 思路）
# ------------------------------------------------------------
changed_files() {
  local out=""
  if [ -n "${CNB_PULL_REQUEST_TARGET_SHA:-}" ]; then
    out="$(git diff --name-only "$CNB_PULL_REQUEST_TARGET_SHA" "HEAD" 2>/dev/null)"
  elif [ -n "${CNB_COMMIT:-}" ] && [ "$(git rev-parse HEAD 2>/dev/null)" = "$CNB_COMMIT" ]; then
    out="$(git diff --name-only "HEAD~1" "HEAD" 2>/dev/null)"
  fi
  if [ -z "$out" ] && git rev-parse --verify main >/dev/null 2>&1; then
    out="$(git diff --name-only "main...HEAD" 2>/dev/null)"
  fi
  if [ -z "$out" ] && git rev-parse --verify HEAD~1 >/dev/null 2>&1; then
    out="$(git diff --name-only "HEAD~1" "HEAD" 2>/dev/null)"
  fi
  local work="$(git diff --name-only 2>/dev/null; git diff --cached --name-only 2>/dev/null)"
  if [ -n "$work" ]; then
    if [ -n "$out" ]; then out="$out
$work"; else out="$work"; fi
  fi
  CHANGED_FILES="$out"
}

# ------------------------------------------------------------
# 2. 按变更范围选测受影响 feature-verify 模块（--changed）
#    feature-verify/<module>/ 负责验对应实现文件的功能语义
# ------------------------------------------------------------
select_by_changes() {
  changed_files
  if [ -z "$CHANGED_FILES" ]; then
    echo "  [feature-verify] 无变更文件 → 视为空（无目标功能待验）"
    return 0
  fi
  declare -a SEL=()
  for f in "${ALL_SCRIPTS[@]}"; do
    local modpath="$(dirname "$f")"
    local srcmod="$(basename "$modpath")"
    local match=0
    # 命中 feature-verify 模块自身（证据库被改）→ 选测该模块防不自知
    if echo "$CHANGED_FILES" | grep -q "feature-verify/${srcmod}/"; then
      match=1
    fi
    # 命中该 module 的实现源路径 → 选测
    if [ "$match" = "0" ]; then
      case "$srcmod" in
        dashboard)
          if echo "$CHANGED_FILES" | grep -qE "scripts/generate-dashboard\.py|docs/DASHBOARD\.md"; then match=1; fi ;;
        dispatch)
          if echo "$CHANGED_FILES" | grep -qE "local-agent/dispatch_engine\.py|local-agent/dispatch/"; then match=1; fi ;;
      esac
    fi
    if [ "$match" = "1" ]; then SEL+=("$f"); fi
  done
  if [ "${#SEL[@]}" -gt 0 ]; then
    ALL_SCRIPTS=("${SEL[@]}")
  else
    ALL_SCRIPTS=()
  fi
}

# ------------------------------------------------------------
# 3. 按模块/功能过滤
# ------------------------------------------------------------
filter() {
  declare -a OUT=()
  for f in "${ALL_SCRIPTS[@]}"; do
    local module fea
    module="$(basename "$(dirname "$f")")"
    fea="$(basename "$f" .sh)"
    if [ "$MODE" = "module" ] && [ "$module" != "$MODULE_SEL" ]; then continue; fi
    if [ "$MODE" = "feature" ] && [ "$module/$fea" != "$FEATURE_SEL" ] \
       && [ "$fea" != "$FEATURE_SEL" ]; then continue; fi
    OUT+=("$f")
  done
  ALL_SCRIPTS=("${OUT[@]}")
}

# ------------------------------------------------------------
# 4. 逐个跑
# ------------------------------------------------------------
run_all() {
  echo "==== [feature-verify] 功能级回归诊断（feature-regress）===="
  if [ "${#ALL_SCRIPTS[@]}" -eq 0 ]; then
    echo "  (本范围无可选 feature-verify 脚本) → 通过"
    exit 0
  fi
  local PASS=0 FAIL=0
  local -a FAILED_ITEMS=()
  for f in "${ALL_SCRIPTS[@]}"; do
    local module fea label
    module="$(basename "$(dirname "$f")")"
    fea="$(basename "$f" .sh)"
    label="[$module] $fea"
    echo ""
    echo "▶ 功能校验: $label  (${f})"
    if bash "$f"; then
      echo "  ✅ $label 通过（功能完成）"
      PASS=$((PASS+1))
    else
      echo "  ❌ $label 崩溃/未达成 → 坏功能定位: $module/$fea"
      FAIL=$((FAIL+1)); FAILED_ITEMS+=("$label")
    fi
  done
  echo ""
  echo "==== [feature-verify] 汇总: PASS=$PASS FAIL=$FAIL ===="
  if [ "$FAIL" -gt 0 ]; then
    echo "🔴 存在坏功能（回归定位）："
    for it in "${FAILED_ITEMS[@]}"; do echo "  - $it"; done
    echo "  blocked_on: feature_unverified（跑不过 = 功能没做完，禁止合并）"
    exit 1
  else
    echo "🟢 全部目标功能通过（feature_unverified=0）"
    exit 0
  fi
}

case "$MODE" in
  list) list_mode ;;
  module|feature) filter; run_all ;;
  changed) select_by_changes; run_all ;;
  *) run_all ;;
esac
