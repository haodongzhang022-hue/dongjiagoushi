#!/usr/bin/env bash
# ============================================================
# [feature-verify] selector / 模块映射全覆盖（--changed 不漏跑）
# ============================================================
# module:   selector（feature-verify 变更选择器 + 模块→实现源映射，Issue #162）
# feature:  --changed 覆盖证据库全部模块；映射单一事实源；未映射/映射失效即 RED
# 五要素:
#   Given   scripts/feature-verify/modules.map（唯一事实源）+ scripts/feature-verify/<module>/
#           证据库目录（现有 8 个功能模块，含 selector 自身）
#   When    真实跑 `scripts/feature-verify.sh --check-map`（基线），再对映射表做三种
#           **变异**：① 删掉任一模块的映射行 ② 把某模块探针路径改成不存在的路径
#           ③ 用 FEATURE_VERIFY_CHANGED_FILES 注入「仅改某模块实现源」跑 --changed --dry-run
#   Then    1) 基线 --check-map 必须绿（rc=0，全部模块被映射选中）；
#           1b) 跨 PR 雷回归（Issue #162 收口）：映射表**前置登记**了证据目录尚未落地的
#              模块（本 PR 预登记 collab，脚本随 PR #161 落地）时，--check-map 必须
#              **仍绿**（⚠️ 警告不阻断）——否则先合本 PR 再合 #161，主线会因 collab
#              未映射被判红；反向"目录有、映射无"仍必须 RED（牙齿不丢）；
#           2) 删任一模块映射行 → rc=1（未映射即 RED，防退化有牙齿）；
#           3) 探针路径失效 → rc=1（映射过期即 RED）；
#           4) 改 local-agent/collab/closure.py（此前静默漏跑的模块）→ --changed 必须
#              选中 peer-closure（不再假绿「无可选脚本 → 通过」）；
#           5) 改 scripts/feature-verify.sh（选择器自身）→ 选中 selector（自保）；
#           6) S1/R1 回归（Issue #162 复评）：target SHA 不可解析时**不带 / 带 CNB_COMMIT**
#              两种场景都必须保守全量（不得报"变更范围为空"跳过假绿）；
#           7) 收窄来源（仅 HEAD~1..HEAD）不得静默欠选 → 保守全量。
#           fixture 一律 `git init -q -b work` 钉死非 main 分支名，不依赖环境默认分支。
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

# ------------------------------------------------------------
# hermetic git fixture 助手（Issue #175 · CI 假红根因修复）
# fixture 仓库**不继承宿主 git 配置**：CI/开发机的系统级 gitconfig 常带
# `commit.gpgsign=true`（本仓 CNB runner 即如此，gpg.program=cnb-gpgsign），
# 若宿主签名工具不可用，`git commit` 会失败但 **stdout 被丢弃、rc 未检查**，
# 于是 fixture 里根本没有 commit —— 而 `git rev-parse HEAD` 在空仓库里
# **打印字面量 "HEAD" 且 rc=0**（不输出 SHA，只有 --verify 才失败），
# 下游断言全被误导成"目标路径没走到"的假红。
# 故：① 显式关掉签名/钩子（不依赖宿主配置）；② 提交后真核对 HEAD，
#     没提交成功就 `exit 1`（fail-loud，绝不让 fixture 静默空壳）。
# ------------------------------------------------------------
fixture_git() {  # 在 fixture 仓库内固定 git 行为
  git init -q -b work
  git config user.email t@t; git config user.name t
  git config commit.gpgsign false
  git config tag.gpgsign false
  git config core.hooksPath /dev/null
  # 清掉可能残留的 gc/维护进程对仓库的干扰（fixture 极小，无需自动维护）
  git config gc.auto 0
}
fixture_commit() {  # $1=message  —— 真提交 + 真核对，失败即 fail-loud
  git add -A >/dev/null 2>&1
  git commit -qm "$1" >/dev/null 2>&1 || { echo "❌ fixture 提交失败（$1）：宿主 git 配置不可用" >&2; exit 1; }
  git rev-parse --verify --quiet HEAD >/dev/null 2>&1 || { echo "❌ fixture 无 HEAD（$1）" >&2; exit 1; }
}

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
# 合并态修复（Issue #162）：登记判据须 pending 感知——否则 `pending: collab:` 因
#   `^collab:` 不匹配被静默跳过，collab 的"删映射→RED"牙齿在合并态失效。
#   `mods` 仅含**已落地证据目录**，故 #163-only（collab 目录未落地）本就不含 collab，安全。
for m in $mods; do
  grep -qE "^(${m}|pending: ${m}):" "$MAP" || continue
  grep -vE "^(${m}|pending: ${m}):" "$MAP" > "$TMP/mut_del_$m.map"
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

# ---------- Then-7：S1 回归——target SHA 不可解析不得假绿跳过 ----------
# 造最小仓库（单提交，无 main/HEAD~1）→ 全部 diff 来源落空。
# ⚠️ `git init -q -b work` 显式钉死非 main 分支名：否则 init.defaultBranch=main
#    的环境自带可解析 main，前提失效（Issue #162 复评 R2）。
# ⚠️ fixture 用 `fixture_git` / `fixture_commit`：宿主 commit.gpgsign=true 时
#    裸 `git commit` 会静默失败、空仓库 `git rev-parse HEAD` 又回显字面量 HEAD（rc=0），
#    假红就这么来的（Issue #175 CI 根因）。
T7REPO="$(mktemp -d)"
(
  cd "$T7REPO" || exit 1
  fixture_git
  mkdir -p scripts/feature-verify/foo
  printf '#!/usr/bin/env bash\necho ok; exit 0\n' > scripts/feature-verify/foo/a.sh
  printf 'foo: scripts/x.py: scripts/x\\.py\n' > scripts/feature-verify/modules.map
  cp "$OLDPWD/$FV" scripts/feature-verify.sh
  fixture_commit init
)
# ① 不带 CNB_COMMIT
t7out="$(cd "$T7REPO" && CNB_PULL_REQUEST_TARGET_SHA=0000000000000000000000000000000000000000 \
         bash scripts/feature-verify.sh --changed --dry-run 2>&1)"
if printf '%s\n' "$t7out" | grep -q "无法确定变更范围" \
   && ! printf '%s\n' "$t7out" | grep -q "变更范围为空"; then
  ok "Then-7a: target SHA 不可解析 → 保守全量（不假绿跳过，S1 回归）"
else
  bad "Then-7a: target SHA 不可解析仍走'变更范围为空'跳过 → S1 假绿回归"
fi
# ② 带 CNB_COMMIT（真实 CI feature-verify gate 必设此变量）——复评 R1 核心场景：
#    旧实现「来源存在即 resolved=1」在此路径报「变更范围为空 → 跳过」exit 0 假绿。
t7cout="$(cd "$T7REPO" && CNB_COMMIT="$(git -C "$T7REPO" rev-parse HEAD)" \
          CNB_PULL_REQUEST_TARGET_SHA=0000000000000000000000000000000000000000 \
          bash scripts/feature-verify.sh --changed --dry-run 2>&1)"
if printf '%s\n' "$t7cout" | grep -q "无法确定变更范围" \
   && ! printf '%s\n' "$t7cout" | grep -q "变更范围为空"; then
  ok "Then-7b: 带 CNB_COMMIT（真实 CI 变量）→ 保守全量（R1 假绿已清零）"
else
  bad "Then-7b: 带 CNB_COMMIT 仍假绿跳过 → R1 未清零（假绿残留）"
fi
rm -rf "$T7REPO"

# ---------- Then-8：S2 回归——ERE 反斜杠转义不被吞 ----------
# 映射表 ERE 含 `\.`；若被 xargs 吞掉，选择器会把 `.` 当通配，可能误命中/失配。
# 直接验证 map_entries 输出的 ERE 仍保留反斜杠（唯一事实源未被改写）。
t8pat="$(bash -c '
  MAP_FILE="scripts/feature-verify/modules.map"
  trim() { local s="$1"; s="${s#"${s%%[![:space:]]*}"}"; s="${s%"${s##*[![:space:]]}"}"; printf "%s" "$s"; }
  while IFS= read -r line; do
    case "$line" in ""|\#*) continue ;; esac
    m="${line%%:*}"; rest="${line#*:}"; p="${rest%%:*}"; pat="${rest#*:}"
    m="$(trim "$m")"; pat="$(trim "$pat")"
    [ "$m" = "dashboard" ] && { printf "%s" "$pat"; break; }
  done < "$MAP_FILE"
')"
if printf '%s' "$t8pat" | grep -q 'generate-dashboard\\\.py'; then
  ok "Then-8: 映射 ERE 反斜杠转义保留（xargs 吞转义已消除，S2 回归）"
else
  bad "Then-8: 映射 ERE 反斜杠被吞（pat='${t8pat}'）→ S2 未修复"
fi
# ---------- Then-9：跨 PR 雷回归（前置登记映射 / 目录后落地 必须容忍） ----------
# 真实场景：本 PR 预登记 `collab:` 映射行，证据脚本由 PR #161 落地。两 PR 各自
# base=main，谁先合都会出现"有映射行、暂无证据目录"的中间态——此时主线 --check-map
# 必须仍绿（⚠️ 警告），否则后合的那个 PR 一落 main 就把主线判红（跨 PR 雷）。
# 用 hermetic 临时证据库验证：造 "目录有、映射无" 仍 RED（牙齿不丢），
# "映射有、目录无" 必须绿（容忍并发）。
TMPV="$(mktemp -d)"
mkdir -p "$TMPV/only_dir" "$TMPV/_templates"
echo '#!/usr/bin/env bash' > "$TMPV/only_dir/x.sh"
# 关键：临时证据库须带**真实 modules.map**，否则 check_map 在"映射表不存在"就 exit 1
# （永远红，走不到 ①）→ 空转信号灯（复评 S2）。放入 map 后本灯才真测「目录有、映射无」。
cp "$MAP" "$TMPV/modules.map"
# (a) 目录有、映射无 → 必须 RED（真漏跑方向，牙齿不丢）
if FEATURE_VERIFY_DIR="$TMPV" bash "$FV" --check-map >"$TMP/x1.out" 2>&1; then
  bad "Then-9a: 证据目录有、映射表无 → --check-map 仍绿（漏跑守护失效）"
else
  ok "Then-9a: 证据目录有、映射表无 → RED（漏跑方向牙齿不丢）"
fi
# (a2) 有鉴别力：必须真走到 ①「未登记」判据，而非"映射表不存在"提前 exit（空转）
grep -q "模块 \[only_dir\] 未在" "$TMP/x1.out" 2>/dev/null \
  && ok "Then-9a2: 真走到 ①未登记判据（非'映射表不存在'空转红灯）" \
  || bad "Then-9a2: 未走到 ①（空转红灯，S2 未修）"
# (b) **显式 pending 标记**的待落地前置登记（目录后落地）→ 必须绿（容忍跨 PR 中间态）
#     复评 T9：容忍收窄到显式标记；未标记的目录缺失仍 RED（见 Then-11）。
#     探针须用真实存在的实现源（探针检查独立于证据目录，不能靠假路径绕过）
cat > "$TMPV/map_forward.map" <<'MAPEOF'
only_dir: local-agent/collab/engine.py: local-agent/collab/engine\.py
pending: forward_only: local-agent/collab/engine.py: local-agent/collab/engine\.py
MAPEOF
if FEATURE_VERIFY_DIR="$TMPV" FEATURE_VERIFY_MAP="$TMPV/map_forward.map" \
   bash "$FV" --check-map >"$TMP/x2.out" 2>&1; then
  ok "Then-9b: 映射前置登记（目录后落地）→ --check-map 仍绿（跨 PR 雷消除）"
else
  bad "Then-9b: 前置登记映射被判 RED → 跨 PR 合并后主线会变红（雷未消除）"
  sed 's/^/      /' "$TMP/x2.out"
fi
if grep -q "forward_only" "$TMP/x2.out" 2>/dev/null; then
  ok "Then-9c: 前置登记以 ⚠️ 警告显式暴露（不静默、不阻断）"
else
  bad "Then-9c: 前置登记未显式暴露（静默）"
fi
rm -rf "$TMPV"

# ---------- Then-10：collab 预登记与 #161 证据目录状态自洽（跨 PR 两态都绿 · 合并态修复） ----------
# 复评 T9 + 合并态修复（Issue #162）：collab 映射须与「#161 证据目录是否已落地」自洽——
#   目录未落地（#163 先合）→ 必须显式 `pending: collab:`（否则 main+#163 --check-map 判红）；
#   目录已落地（#161 已合）→ 须已登记（`pending: collab:` 或正式 `collab:` 皆可；去前缀是清理目标态）。
if [ -d scripts/feature-verify/collab ]; then
  grep -qE '^(collab|pending: collab):' "$MAP" \
    && ok "Then-10a: collab 证据目录已落地且映射已登记（pending 清理前后皆绿）" \
    || bad "Then-10a: collab 目录已落地但映射缺失 → --changed 静默漏跑"
else
  grep -q '^pending: collab:' "$MAP" \
    && ok "Then-10a: collab 目录未落地已 pending 预登记（合 #163 后主线不判红）" \
    || bad "Then-10a: 未 pending 预登记 collab → 合 #163 后主线 --check-map 判红"
fi
# 模拟 #161 已合：证据目录**全部落地**（含 collab）+ 去掉 collab 的 pending 前缀 → 必须绿。
TMPV2="$(mktemp -d)"
# 把真实证据库整体镜像过去（含全部正式模块目录），再补 collab 目录
cp -r "$(dirname "$MAP")"/. "$TMPV2/" 2>/dev/null
mkdir -p "$TMPV2/collab"
echo '#!/usr/bin/env bash' > "$TMPV2/collab/写时状态中介.sh"
# 去掉 collab 的 pending 前缀 = 脚本已落地转正式登记
sed 's/^pending: collab:/collab:/' "$MAP" > "$TMPV2/post161.map"
if FEATURE_VERIFY_DIR="$TMPV2" FEATURE_VERIFY_MAP="$TMPV2/post161.map" \
   bash "$FV" --check-map >"$TMP/x3.out" 2>&1; then
  ok "Then-10b: 模拟 #161 已合（collab 目录落地 + 去 pending）→ --check-map 绿"
else
  bad "Then-10b: 模拟 #161 已合后 --check-map 红（跨 PR 雷仍在）"
  sed 's/^/      /' "$TMP/x3.out"
fi
# 10c：目录落地但**忘记去掉 pending:** → 必须 ⚠️ 提示 stale（容忍面不得无声扩大）
grep -q "证据目录已落地" "$TMP/x3.out" 2>/dev/null \
  && bad "Then-10c: 去 pending 后仍报 stale（判据有误）" \
  || ok "Then-10c: 去 pending 后不再报 stale（stale 判据准确）"
# 10d：hermetic —— 强制 collab 为 pending 形态（全模块保留）配「目录已落地」→ 必须提示 stale；
#      不依赖仓库真实 map 形态，故合并态去/留 pending 前后都稳定可测（拆 p3 的坑）。
# 夹具意图：把 collab 从「正式登记」改造成「仍挂 pending:」的 stale 形态。
# 旧版第二条 `-e 's/^pending: collab:/pending: collab:/'` 是**恒等替换**（no-op），
# 写出 0 效果却让读者以为做了两步处理 —— 已删，只留真正生效的那一步。
sed 's/^collab:/pending: collab:/' "$MAP" > "$TMPV2/stale.map"
if FEATURE_VERIFY_DIR="$TMPV2" FEATURE_VERIFY_MAP="$TMPV2/stale.map" \
   bash "$FV" --check-map >"$TMP/x4.out" 2>&1; then
  grep -q "证据目录已落地" "$TMP/x4.out" \
    && ok "Then-10d: 目录已落地但仍挂 pending: → ⚠️ 提示 stale（收窄容忍面）" \
    || bad "Then-10d: 目录已落地仍挂 pending: 未提示 stale"
else
  bad "Then-10d: collab 目录落地 + pending 仍绿失败（OUT=$(cat "$TMP/x4.out"))"
fi
rm -rf "$TMPV2"
# ---------- Then-11：T9 核心——未标记 pending 的目录缺失必须 RED（不得静默假绿） ----------
# 复评 T9：旧行为对"目录缺失"一律 ⚠️ 放过 → 无法区分"跨 PR 中间态"与
# "证据目录被误删/改名"。收窄后：**未标记**的目录缺失 → --check-map RED，
# 且 --changed 命中该模块实现源 → 硬失败（不再「无可选脚本 → 通过」）。
TMPV3="$(mktemp -d)"
cp -r "$(dirname "$MAP")"/. "$TMPV3/" 2>/dev/null
rm -rf "$TMPV3/disposition"          # 目录被误删，映射行**未标记** pending
if FEATURE_VERIFY_DIR="$TMPV3" FEATURE_VERIFY_MAP="$MAP" \
   bash "$FV" --check-map >"$TMP/x5.out" 2>&1; then
  bad "Then-11a: 未标记的目录缺失 → --check-map 仍绿（重开 T9 假绿）"
else
  grep -q "正式登记的模块证据目录缺失.*disposition" "$TMP/x5.out" \
    && ok "Then-11a: 未标记的目录缺失 → RED（静默假绿已堵，T9 收窄）" \
    || bad "Then-11a: RED 但未指明缺失模块（OUT=$(cat "$TMP/x5.out"))"
fi
# 11b：--changed 命中该实现源 → 硬失败（旧行为是 ⚠️ + 「无可选脚本 → 通过」exit 0）
TMPV3_OUT="$(FEATURE_VERIFY_DIR="$TMPV3" FEATURE_VERIFY_MAP="$MAP" \
             FEATURE_VERIFY_CHANGED_FILES="local-agent/collab/disposition.py" \
             bash "$FV" --changed 2>&1)"; TMPV3_RC=$?
if [ "$TMPV3_RC" -ne 0 ]; then
  ok "Then-11b: 未标记目录缺失 + 命中实现源 → --changed 硬失败（不再假绿通过）"
else
  bad "Then-11b: 未标记目录缺失仍 --changed exit 0（静默假绿，T9 未收窄）"
fi
printf '%s\n' "$TMPV3_OUT" | grep -q "未标记 pending" \
  && ok "Then-11c: 硬失败原因显式（未标记 pending）" \
  || bad "Then-11c: 硬失败未显式说明原因"
rm -rf "$TMPV3"

if [ "$FAIL" -gt 0 ]; then
  echo "🔴 selector/映射全覆盖 未达成 → 功能没做完（PASS=$PASS FAIL=$FAIL）"
  exit 1
else
  echo "🟢 selector/映射全覆盖 通过（PASS=$PASS）"
  exit 0
fi
