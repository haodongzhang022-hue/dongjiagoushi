#!/usr/bin/env bash
# ============================================================
# [feature-verify] selector / 模块映射全覆盖（--changed 不漏跑）
# ============================================================
# module:   selector（feature-verify 变更选择器 + 模块→实现源映射，Issue #162）
# feature:  --changed 覆盖证据库全部模块；映射单一事实源；未映射/映射失效即 RED
# 五要素:
#   Given   scripts/feature-verify/modules.map（唯一事实源）+ scripts/feature-verify/<module>/
#           证据库目录（现有 7 个功能模块 + selector 自身）
#   When    真实跑 `scripts/feature-verify.sh --check-map`（基线），再对映射表做三种
#           **变异**：① 删掉任一模块的映射行 ② 把某模块探针路径改成不存在的路径
#           ③ 用 FEATURE_VERIFY_CHANGED_FILES 注入「仅改某模块实现源」跑 --changed --dry-run
#   Then    1) 基线 --check-map 必须绿（rc=0，全部模块被映射选中）；
#           2) 删任一模块映射行 → rc=1（未映射即 RED，防退化有牙齿）；
#           3) 探针路径失效 → rc=1（映射过期即 RED）；
#           4) 改 local-agent/collab/closure.py（此前静默漏跑的模块）→ --changed 必须
#              选中 peer-closure（不再假绿「无可选脚本 → 通过」）；
#           5) 改 scripts/feature-verify.sh（选择器自身）→ 选中 selector（自保）。
#   Evidence --check-map 的 rc + 输出行；--changed --dry-run 的选定脚本清单（可 grep）
# 为什么是"功能级"：纯 grep 只能证明"映射表里有这行字"，抓不出"选择器真的按它选、
#   少一行真的会 RED"。必须真实跑选择器 + 真实变异映射表，看它在缺口存在时是否诚实报红
#   ——这正是 PR #161 评审 🟡P1 的缺口（未覆盖模块实现源变更静默漏跑、exit 0 假绿）。
# 用法：bash scripts/feature-verify/selector/映射全覆盖.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }

FV="scripts/feature-verify.sh"
MAP="scripts/feature-verify/modules.map"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==== [feature-verify] selector/映射全覆盖 ===="

# ---------- Then-1：基线 --check-map 必须绿 ----------
if bash "$FV" --check-map >"$TMP/base.out" 2>&1; then
  ok "Then-1: 基线 --check-map 通过（全部证据模块被映射覆盖）"
else
  bad "Then-1: 基线 --check-map 失败 → 存在未映射/失效映射模块"
  sed 's/^/      /' "$TMP/base.out"
fi

# 证据库模块清单（排除 _templates）
mods="$(find scripts/feature-verify -mindepth 1 -maxdepth 1 -type d -not -name '_templates' \
        | sed 's#.*/##' | sort)"
n_mods="$(printf '%s\n' "$mods" | grep -c .)"
echo "  (证据库模块 $n_mods 个: $(printf '%s' "$mods" | tr '\n' ' '))"

# ---------- Then-2：删任一模块映射行 → RED（防退化有牙齿） ----------
for m in $mods; do
  grep -q "^${m}:" "$MAP" || continue
  grep -v "^${m}:" "$MAP" > "$TMP/mut_del_$m.map"
  if FEATURE_VERIFY_MAP="$TMP/mut_del_$m.map" bash "$FV" --check-map >"$TMP/del_$m.out" 2>&1; then
    bad "Then-2: 删掉 [$m] 映射行后 --check-map 仍绿 → 防退化断言没牙齿"
  else
    ok "Then-2: 删掉 [$m] 映射行 → RED（rc=1，防退化有牙齿）"
  fi
done

# ---------- Then-3：探针路径失效 → RED（映射过期即红） ----------
probe="$(awk -F: '/^[a-z]/{gsub(/ /,"",$1);gsub(/^ +| +$/,"",$2);print $2;exit}' "$MAP")"
if [ -n "$probe" ]; then
  awk -v old="$probe" '{ if (index($0, old":")>0) sub(old":", "scripts/__nope__.py:"); print }' \
    "$MAP" > "$TMP/mut_probe.map"
  if FEATURE_VERIFY_MAP="$TMP/mut_probe.map" bash "$FV" --check-map >"$TMP/probe.out" 2>&1; then
    bad "Then-3: 探针路径失效后 --check-map 仍绿 → 映射过期抓不出"
  else
    ok "Then-3: 探针路径失效 → RED（映射过期即红）"
  fi
fi

# ---------- Then-4：此前静默漏跑的模块，--changed 必须选中 ----------
declare -A PROBE=(
  [dashboard]="scripts/generate-dashboard.py"
  [dev-team]="local-agent/dev_team.py"
  [dispatch]="local-agent/dispatch_engine.py"
  [disposition]="local-agent/collab/disposition.py"
  [entry-guard]="local-agent/scale/profile.py"
  [peer-closure]="local-agent/collab/closure.py"
  [review]="local-agent/roles/reviewer.py"
)
for m in "${!PROBE[@]}"; do
  src="${PROBE[$m]}"
  out="$(FEATURE_VERIFY_CHANGED_FILES="$src" bash "$FV" --changed --dry-run 2>&1)"
  if grep -q "feature-verify/${m}/" <<< "$out"; then
    ok "Then-4: 改 ${src} → --changed 选中 [${m}]（不再静默漏跑）"
  else
    bad "Then-4: 改 ${src} 未选中 [${m}] → 静默漏跑（假绿）"
  fi
done

# ---------- Then-5：选择器自身变更 → 自保选测 ----------
out="$(FEATURE_VERIFY_CHANGED_FILES="scripts/feature-verify.sh" bash "$FV" --changed --dry-run 2>&1)"
if grep -q "feature-verify/selector/" <<< "$out"; then
  ok "Then-5: 改选择器自身 → 选中 [selector]（自保）"
else
  bad "Then-5: 改选择器自身未选中 [selector] → 选择器改动无证据守护"
fi

# ---------- Then-6：缺口回归自证——旧行为必须已被消除 ----------
# 旧选择器只覆盖 dashboard/dispatch/entry-guard 3 个 case 分支，改 collab/engine.py
# 会「无可选脚本 → 通过」(exit 0)。现映射覆盖 collab 域（peer-closure），必须不再假绿。
out="$(FEATURE_VERIFY_CHANGED_FILES="local-agent/collab/engine.py" bash "$FV" --changed --dry-run 2>&1)"
if grep -q "feature-verify/peer-closure/" <<< "$out"; then
  ok "Then-6: 改 local-agent/collab/engine.py（评审复现的漏跑源）→ 选中 peer-closure（假绿消除）"
else
  bad "Then-6: 改 local-agent/collab/engine.py 仍无可选脚本 → 评审 🟡P1 缺口未收口"
fi

echo ""
if [ "$FAIL" -gt 0 ]; then
  echo "🔴 selector/映射全覆盖 未达成 → 功能没做完（PASS=$PASS FAIL=$FAIL）"
  exit 1
else
  echo "🟢 selector/映射全覆盖 通过（PASS=$PASS）"
  exit 0
fi
