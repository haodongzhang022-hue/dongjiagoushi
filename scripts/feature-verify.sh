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
# 模块→实现源映射（Issue #162）：唯一事实源 = scripts/feature-verify/modules.map，
#       本脚本只读该表，不再散落硬编码 `case`；未映射即 --check-map 判 RED（防退化）。
#
# 用法：
#   bash scripts/feature-verify.sh --all            # 全量回归（feature-regress 语义）
#   bash scripts/feature-verify.sh --module dispatch # 只跑某模块的所有 feature-verify
#   bash scripts/feature-verify.sh --feature dispatch/真实唤醒校验闸门  # 精确跑一个功能
#   bash scripts/feature-verify.sh --changed        # 按 git 变更自动选测受影响模块
#   bash scripts/feature-verify.sh --changed --dry-run  # 只打印将跑哪些（不执行）
#   bash scripts/feature-verify.sh --check-map      # 映射防退化断言（未映射/映射失效即 RED）
#   bash scripts/feature-verify.sh --list           # 列出全部功能校验脚本（证据库盘点）
#
# 环境变量（合并闸门用）：
#   CNB_PULL_REQUEST_TARGET_SHA   # PR 目标分支 SHA（可靠来源：真 PR 范围）
#   CNB_COMMIT                     # 本次提交 SHA（**不再单独用作回退来源**：
#                                  #   只覆盖最后一个提交，多提交 PR 会欠选 → 走保守全量）
# 环境变量（测试用，确定性注入）：
#   FEATURE_VERIFY_CHANGED_FILES   # 直接指定变更文件（换行/逗号分隔），跳过 git 探测
#   FEATURE_VERIFY_MAP             # 指定映射表路径（默认 scripts/feature-verify/modules.map）
#   FEATURE_VERIFY_DIR             # 指定证据库根目录（默认 scripts/feature-verify，hermetic 测试注入）
# ============================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
# 证据库根目录（FEATURE_VERIFY_DIR 供 hermetic 测试注入临时目录，默认仓库内路径）
VERIFY_DIR="${FEATURE_VERIFY_DIR:-scripts/feature-verify}"
MAP_FILE="${FEATURE_VERIFY_MAP:-$VERIFY_DIR/modules.map}"

MODE="all"
MODULE_SEL=""
FEATURE_SEL=""
DRY_RUN=0
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
    --check-map) MODE="check_map" ;;
    --module) MODE="module" ;;
    --feature) MODE="feature" ;;
    --dry-run) DRY_RUN=1 ;;
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

# 证据库模块清单（目录名，排除 _templates）
evidence_modules() {
  [ -d "$VERIFY_DIR" ] || return 0
  find "$VERIFY_DIR" -mindepth 1 -maxdepth 1 -type d -not -name '_templates' \
    | sed 's#.*/##' | sort
}

# ------------------------------------------------------------
# 0.1 映射表读取（唯一事实源）
#     格式: <evidence-module>: <探针实现源路径>: <实现源选择 ERE>
#     输出: TSV（module \t probe \t pattern）
# ------------------------------------------------------------
# 安全 trim：只去首尾空白，不解释反斜杠（xargs 会吞掉 ERE 里的 \ 转义）
trim() { local s="$1"; s="${s#"${s%%[![:space:]]*}"}"; s="${s%"${s##*[![:space:]]}"}"; printf '%s' "$s"; }

map_entries() {
  [ -f "$MAP_FILE" ] || return 0
  local line m p pat rest
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    m="${line%%:*}"; rest="${line#*:}"
    p="${rest%%:*}"; pat="${rest#*:}"
    m="$(trim "$m")"; p="$(trim "$p")"; pat="$(trim "$pat")"
    [ -n "$m" ] || continue
    printf '%s\t%s\t%s\n' "$m" "$p" "$pat"
  done < "$MAP_FILE"
}

map_lookup() {  # $1=module → TSV 行（无则空）
  map_entries | awk -F'\t' -v m="$1" '$1==m{print; exit}'
}

# 给定变更文件清单 → 选中的证据模块名（每行一个）
select_modules_for() {
  local changed="$1" m p pat
  while IFS=$'\t' read -r m p pat; do
    [ -n "$m" ] || continue
    local match=0
    # 命中 feature-verify 模块自身（证据库被改）→ 选测该模块防不自知
    case "$changed" in *"feature-verify/${m}/"*) match=1 ;; esac
    # 命中该 module 声明的实现源路径（唯一事实源 modules.map）→ 选测
    if [ "$match" = "0" ] && [ -n "$pat" ]; then
      if grep -qE "$pat" <<< "$changed"; then match=1; fi
    fi
    if [ "$match" = "1" ]; then echo "$m"; fi
  done < <(map_entries)
  return 0
}

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
  echo ""
  echo "  模块→实现源映射（唯一事实源 ${MAP_FILE}）:"
  while IFS=$'\t' read -r m p pat; do
    [ -n "$m" ] && echo "    [${m}] ← ${pat}"
  done < <(map_entries)
  exit 0
}

# ------------------------------------------------------------
# 1. 确定变更文件列表（复用 change-aware 的 git diff 思路）
#    CHANGED_KNOWN=1 表示范围可确定；=0 表示无法确定（保守全量）
#
#    回退链分两级（Issue #162 复评 R1 + 🟡欠选）：
#      可靠来源（给出**真实 PR 范围**）：注入变量 / PR 目标 SHA / main...HEAD
#      收窄来源（只覆盖**最后一个提交**）：HEAD~1..HEAD → 多提交 PR 会欠选，
#        故不静默收窄，改判「范围不可确定」走保守全量（宁可多跑，绝不漏跑）。
#    判据：**以 git diff 真成功（rc=0）为准**，不以「来源存在」为准——
#      旧实现只要来源被尝试就 resolved=1，导致「diff 失败但来源在」→
#      resolved=1 → 报「变更范围为空 → 跳过」→ exit 0 假绿（S1 残留）。
# ------------------------------------------------------------
CHANGED_FILES=""
CHANGED_KNOWN=1
CHANGED_NARROWED=0
changed_files() {
  local out="" resolved=0 settled=0 narrowed=0
  if [ -n "${FEATURE_VERIFY_CHANGED_FILES:-}" ]; then
    # 测试注入：确定性指定变更文件，跳过 git 探测
    out="$(printf '%s' "$FEATURE_VERIFY_CHANGED_FILES" | tr ',' '\n')"
    resolved=1; settled=1
  else
    # 可靠来源 ①：PR 目标 SHA（真 PR 范围）——diff 真成功（rc=0）才算数；
    #   rc=0 且为空 = 权威「确无变更」，settled 后不再回退。
    if [ "$settled" = 0 ] && [ -n "${CNB_PULL_REQUEST_TARGET_SHA:-}" ] \
       && git rev-parse --verify --quiet "${CNB_PULL_REQUEST_TARGET_SHA}^{commit}" >/dev/null 2>&1; then
      if out="$(git diff --name-only "$CNB_PULL_REQUEST_TARGET_SHA" "HEAD" 2>/dev/null)"; then
        resolved=1; settled=1
      fi
    fi
    # 可靠来源 ②：main...HEAD（本分支相对 main 的真 PR 范围）——有 merge base 才成功；
    #   main 可解析 ≠ main...HEAD 可 diff（无共同祖先时 git 报错 rc≠0）→ 继续回退。
    if [ "$settled" = 0 ] && git rev-parse --verify --quiet main >/dev/null 2>&1; then
      if out="$(git diff --name-only "main...HEAD" 2>/dev/null)"; then
        resolved=1; settled=1
      fi
    fi
    # 收窄来源：HEAD~1..HEAD 只覆盖最后一个提交，多提交 PR 静默欠选（漏跑）→
    #   不静默收窄，仅标记 narrowed，交 CHANGED_KNOWN=0 走保守全量。
    if [ "$settled" = 0 ] && git rev-parse --verify --quiet HEAD~1 >/dev/null 2>&1; then
      narrowed=1
    fi
  fi
  local work; work="$(git diff --name-only 2>/dev/null; git diff --cached --name-only 2>/dev/null)"
  if [ -n "$work" ]; then
    if [ -n "$out" ]; then out="$out
$work"; else out="$work"; fi
    resolved=1; settled=1
  fi
  CHANGED_FILES="$(printf '%s\n' "$out" | sed '/^$/d')"
  # 全链落空（无任何可靠 diff 来源）或仅剩收窄来源（可能欠选）
  # → 变更范围不可确定 → CHANGED_KNOWN=0 → 保守全量回归，绝不当"无变更"跳过（假绿）。
  if [ "$resolved" = "0" ] || [ "$narrowed" = "1" ]; then
    CHANGED_KNOWN=0
    [ "$narrowed" = "1" ] && CHANGED_NARROWED=1
  fi
}


# ------------------------------------------------------------
# 2. 按变更范围选测受影响 feature-verify 模块（--changed）
#    feature-verify/<module>/ 负责验对应实现文件的功能语义；
#    映射来自唯一事实源 modules.map（不再硬编码 case）。
# ------------------------------------------------------------
select_by_changes() {
  changed_files
  if [ "$CHANGED_KNOWN" = "0" ]; then
    if [ "$CHANGED_NARROWED" = "1" ]; then
      echo "  [feature-verify] 仅剩 HEAD~1..HEAD 收窄来源（可能欠选整个 PR 范围）→ 保守全量回归（不漏跑优先）"
    else
      echo "  [feature-verify] 无法确定变更范围 → 保守全量回归（不漏跑优先）"
    fi
    return 0
  fi
  if [ -z "$CHANGED_FILES" ]; then
    echo "  [feature-verify] 变更范围为空 → 无目标功能待验（跳过，非假绿）"
    ALL_SCRIPTS=()
    return 0
  fi
  local sel_modules
  sel_modules="$(select_modules_for "$CHANGED_FILES")"
  declare -a SEL=()
  if [ -n "$sel_modules" ]; then
    while IFS= read -r m; do
      [ -n "$m" ] || continue
      local _hit=0
      for f in "${ALL_SCRIPTS[@]}"; do
        [ "$(basename "$(dirname "$f")")" = "$m" ] && { SEL+=("$f"); _hit=1; }
      done
      # 选中的模块若无证据目录/脚本（僵尸映射行：有行无目录）→ 显式 ⚠️，不静默：
      # 否则该实现源变更既不被选测、也不落进下面"未映射"告警 → 静默通过（复评 S3 静默通道）。
      if [ "$_hit" = "0" ]; then
        echo "  ⚠️ 映射选中的模块 [$m] 无证据目录/脚本（${VERIFY_DIR}/$m/）→ 本实现源变更未真正选测"
        echo "     → 跨 PR 中间态（先登记映射、后落脚本）可容忍；长期须补证据脚本或移除僵尸映射行。"
      fi
    done <<< "$sel_modules"
  fi
  # 未登记映射的证据模块：显式暴露（不静默），--check-map 会判 RED
  local _em _em_missing=""
  while IFS= read -r _em; do
    [ -n "$_em" ] || continue
    [ -n "$(map_lookup "$_em")" ] || _em_missing="$_em_missing $_em"
  done < <(evidence_modules)
  if [ -n "$_em_missing" ]; then
    echo "  ⚠️ 证据库模块未登记 modules.map:${_em_missing} → 其实现源变更会被静默漏跑"
    echo "     → 请补 ${MAP_FILE} 映射；CI --check-map 会硬拦（RED）。"
  fi

  # 未映射的实现源变更：显式暴露（不静默），供 --check-map 收口
  local unmapped=""
  while IFS= read -r cf; do
    case "$cf" in local-agent/*) ;; *) continue ;; esac
    local hit=0
    while IFS=$'\t' read -r m p pat; do
      [ -n "$pat" ] || continue
      if grep -qE "$pat" <<< "$cf"; then hit=1; break; fi
    done < <(map_entries)
    [ "$hit" = "0" ] && unmapped="$unmapped
    $cf"
  done <<< "$CHANGED_FILES"
  if [ -n "$unmapped" ]; then
    echo "  ⚠️ 以下 local-agent 实现源变更未被任何 feature-verify 模块映射（本次未选测）:$unmapped"
    echo "     → 若属既有功能，请在 ${MAP_FILE} 登记映射；--check-map 会拦未映射的【模块】。"
  fi
  if [ "${#SEL[@]}" -gt 0 ]; then
    ALL_SCRIPTS=("${SEL[@]}")
  else
    ALL_SCRIPTS=()
  fi
}

# ------------------------------------------------------------
# 2.1 映射防退化断言（--check-map · 有牙齿）
#     ① 证据库每个模块必须在 modules.map 登记（未映射即 RED）
#     ② 探针实现源路径必须真实存在（映射过期即 RED）
#     ③ 模拟「改该模块实现源」→ 选择器必须选中它（映射失效即 RED，防静默漏跑）
#     ④ 僵尸条目（映射行指向暂无证据目录的模块）→ 仅 ⚠️ 警告，不阻断：
#        真漏跑方向是 ①「目录有、映射无」；且跨 PR 并发（A 先登记映射 / B 后落脚本）
#        必须容忍，否则后合的 PR 一落 main 就把主线判红（跨 PR 雷 · Issue #162 收口）
# ------------------------------------------------------------
check_map() {
  local RED=0
  echo "==== [feature-verify] 模块→实现源映射防退化断言（--check-map）===="
  if [ ! -f "$MAP_FILE" ]; then
    echo "  ❌ 映射表不存在: $MAP_FILE（唯一事实源缺失 = 选择器无从映射）"
    exit 1
  fi
  echo "  唯一事实源: $MAP_FILE（$(map_entries | grep -c . ) 条映射）"

  # ① 证据库模块 ↔ 映射表 双向覆盖
  local mods; mods="$(evidence_modules)"
  while IFS= read -r m; do
    [ -n "$m" ] || continue
    local row pat probe
    row="$(map_lookup "$m")"
    if [ -z "$row" ]; then
      echo "  ❌ 模块 [$m] 未在 ${MAP_FILE} 登记 → --changed 会静默漏跑（RED）"
      RED=1; continue
    fi
    probe="$(printf '%s' "$row" | cut -f2)"
    pat="$(printf '%s' "$row" | cut -f3)"
    # ② 探针存在
    if [ -z "$probe" ] || [ ! -e "$probe" ]; then
      echo "  ❌ 模块 [$m] 探针实现源不存在: '${probe}'（映射过期，RED）"
      RED=1
    fi
    # ③ 模拟改该模块实现源 → 必须被选中
    if [ -n "$probe" ]; then
      local _sel_m; _sel_m="$(select_modules_for "$probe")"
      if grep -qx "$m" <<< "$_sel_m"; then
        echo "  ✅ 模块 [$m] 映射有效（改 ${probe} → 选中 [$m]）"
      else
        echo "  ❌ 模块 [$m] 映射失效（改 ${probe} 未选中 [$m]）→ 静默漏跑，RED"
        RED=1
      fi
    fi
    if [ -z "$pat" ]; then
      echo "  ❌ 模块 [$m] 选择 ERE 为空（RED）"
      RED=1
    fi
  done <<< "$mods"

  # ④ 僵尸条目（映射行指向暂无证据目录的模块）→ ⚠️ 警告，**不阻断**：
  #    - 真漏跑方向是 ①「目录有、映射无」（那才 RED）；僵尸行选中的模块无脚本
  #      = 无贡献，不造成静默漏跑；
  #    - 跨 PR 并发下必须容忍：A PR 先登记映射、B PR 后落证据脚本（或反之），
  #      中间态"有行无目录"属正常顺序，不该把主线判红（Issue #162 跨 PR 雷）。
  local zombie=""
  while IFS=$'\t' read -r m p pat; do
    [ -n "$m" ] || continue
    if [ ! -d "$VERIFY_DIR/$m" ]; then
      zombie="$zombie $m"
    fi
  done < <(map_entries)
  if [ -n "$zombie" ]; then
    echo "  ⚠️ 映射条目指向暂无证据目录的模块:${zombie}"
    echo "     （非阻断：跨 PR 并发中间态 / 待落脚本；不影响 ① 的漏跑守护）"
  fi

  echo ""
  if [ "$RED" -gt 0 ]; then
    echo "🔴 映射防退化断言未通过（未映射/映射失效）→ blocked_on: feature_unverified"
    exit 1
  fi
  echo "🟢 映射防退化断言通过：证据库模块 100% 被 --changed 覆盖"
  exit 0
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
  if [ "$DRY_RUN" = "1" ]; then
    echo "  --dry-run：将跑 ${#ALL_SCRIPTS[@]} 份脚本（不执行）"
    for f in "${ALL_SCRIPTS[@]}"; do echo "    $f"; done
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
  check_map) check_map ;;
  module|feature) filter; run_all ;;
  changed) select_by_changes; run_all ;;
  *) run_all ;;
esac
