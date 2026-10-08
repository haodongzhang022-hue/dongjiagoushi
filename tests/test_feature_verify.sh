#!/usr/bin/env bash
# ============================================================
# feature-verify 模块自测信号灯（Issue #109 · module v0.1.0 init）
#
# 验证 feature-verify 功能级校验机制的六项产出齐备且可用：
#   T1 目录 + 真实功能样例脚本存在（纯 bash 可离线跑）
#   T2 样例脚本头部带机器可读"五要素"（Given/When/Then/Evidence）
#   T3 feature-verify.sh --list 证据库盘点能列出全部样例
#   T4 纯 bash 样例真实跑通（dashboard 看板呈现链路）
#   T5 feature-regress.sh 回归诊断能跑出"通过/崩"定位
#   T6 合并闸门已接入 .cnb.yml（feature-verify gate 阶段）
#   T7 文档 docs/FEATURE_VERIFY.md + CAPABILITY_INDEX 登记
#   T8 五要素"功能级 > 断言"自证：缺语义段即判功能没做完（抓'假完成'）
#   T9 模块→实现源映射收口唯一事实源（Issue #162）
#   T10 变异验证：移除任一模块映射 → --check-map RED（防退化有牙齿）
#   T11 缺口回归自证：collab 实现源变更不再假绿（评审 🟡P1）
#   T12 变更感知测试选择接线（选择器改动 → 功能级自测）
#   T13 CI 闸门已前置 --check-map（防退化断言）
#   T14 target SHA 不可解析 → 保守全量（不假绿跳过 · 复评 R1：含 **带 CNB_COMMIT**
#       真实 CI 场景断言 T14c/T14d，否则测不到真实环境假绿）
#   T14e 收窄来源（HEAD~1..HEAD）不得静默欠选（复评 🟡S：多提交 PR 漏跑）
#   T15 target SHA 无效但 main 可用 → 回退链继续真选测（不断链）
#   T16 跨 PR 雷回归（Issue #162 收口）：映射前置登记（目录后落地）不得判 RED，
#       但"目录有、映射无"仍须 RED——两方向同时锁死，防合 #161 后主线变红
#   T17 脚本可执行位回归：feature-verify.sh / change-aware / 自测 / selector 样例 保持 100755
#
# 用法：bash tests/test_feature_verify.sh
# 运行依赖：bash + git（纯逻辑）；python 样例在 python 环境跑（无则优雅跳过）
# ============================================================
set -u
cd "$(dirname "$0")/.."
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }

echo "======================================================"
echo "feature-verify 模块自测信号灯 (Issue #109)"
echo "======================================================"

# ---- T1 目录 + 真实样例存在 ----
echo ""
echo "▶ T1 目录与真实样例脚本"
[ -d scripts/feature-verify ] && ok "scripts/feature-verify/ 目录存在" || bad "缺 scripts/feature-verify/ 目录"
[ -f scripts/feature-verify/dashboard/看板呈现链路.sh ] && ok "dashboard 真实样例存在" || bad "缺 dashboard 样例"
[ -f scripts/feature-verify/dispatch/真实唤醒校验闸门.sh ] && ok "dispatch 真实样例存在" || bad "缺 dispatch 样例"
[ -f scripts/feature-verify/_templates/verify.template.sh ] && ok "新功能模板存在" || bad "缺模板"

# ---- T2 五要素头 ----
echo ""
echo "▶ T2 样例脚本带机器可读五要素"
for f in scripts/feature-verify/dashboard/看板呈现链路.sh scripts/feature-verify/dispatch/真实唤醒校验闸门.sh; do
  missing=""
  for kw in "module:" "feature:" "Given" "When" "Then" "Evidence"; do
    grep -q "$kw" "$f" || missing="$missing $kw"
  done
  if [ -z "$missing" ]; then ok "$f 含五要素声明"; else bad "$f 缺要素:$missing"; fi
done

# ---- T3 证据库盘点 ----
echo ""
echo "▶ T3 feature-verify.sh --list 证据库盘点"
LIST_OUT="$(bash scripts/feature-verify.sh --list 2>&1)"
if echo "$LIST_OUT" | grep -q "真实唤醒校验闸门" && echo "$LIST_OUT" | grep -q "看板呈现链路"; then
  ok "盘点列出全部样例"
else
  bad "盘点未列出样例"
fi

# ---- T4 纯 bash 样例真实跑通 ----
echo ""
echo "▶ T4 纯 bash 样例真实跑通（dashboard）"
if bash scripts/feature-verify/dashboard/看板呈现链路.sh >/dev/null 2>&1; then
  ok "dashboard 样例真实跑通（看板呈现功能完成）"
else
  bad "dashboard 样例跑失败"
fi

# ---- T5 回归诊断 ----
echo ""
echo "▶ T5 feature-regress.sh 回归诊断能定位"
REGRESS_OUT="$(bash scripts/feature-regress.sh 2>&1)"
RC=$?
if [ $RC -eq 0 ]; then
  ok "feature-regress.sh 回归通过（rc=$RC）"
else
  bad "feature-regress.sh 失败（rc=$RC）"
fi
if echo "$REGRESS_OUT" | grep -qE "看板呈现链路.*通过"; then
  ok "回归输出含逐功能通过明细"
else
  bad "回归未输出逐功能明细"
fi

# ---- T6 合并闸门已接入 .cnb.yml ----
echo ""
echo "▶ T6 feature-verify 合并闸门已接入 .cnb.yml"
if grep -q "feature-verify gate" .cnb.yml && grep -q "scripts/feature-verify.sh --changed" .cnb.yml; then
  ok "pull_request 流水线含 feature-verify gate（跑不过=blocked_on: feature_unverified）"
else
  bad ".cnb.yml 缺 feature-verify gate 阶段"
fi
if grep -q "feature_unverified" .cnb.yml; then
  ok ".cnb.yml 标注 blocked_on: feature_unverified"
else
  bad ".cnb.yml 未标 feature_unverified"
fi

# ---- T7 文档 + 索引 ----
echo ""
echo "▶ T7 文档与 CAPABILITY_INDEX 登记"
[ -f docs/FEATURE_VERIFY.md ] && ok "docs/FEATURE_VERIFY.md 存在" || bad "缺文档"
if grep -q "feature-verify" docs/CAPABILITY_INDEX.md && grep -q "docs/FEATURE_VERIFY.md" docs/CAPABILITY_INDEX.md; then
  ok "CAPABILITY_INDEX 已登记 feature-verify（含文档位置）"
else
  bad "CAPABILITY_INDEX 未登记"
fi

# ---- T8 功能级 > 断言：缺语义段即判功能没做完（自证抓"假完成"）----
echo ""
echo "▶ T8 功能级 > 断言（缺语义段抓'假完成'）"
# 造一个只有空文件（无语义段）的假看板，feature-verify 必须判功能没做完——证明它
# 抓得住"断言过了但功能没做完"，而非只看文件存在。
TMPF="$(mktemp --suffix=.md)"
echo "# 假看板（空壳，无模块演进/里程碑语义段）" > "$TMPF"
OUT="$(DF="$TMPF" bash -c '
DF="'"$TMPF"'"
PASS=0; FAIL=0
for seg in "模块版本演进看板" "里程碑表" "Issue 声明汇总表"; do
  grep -qF "$seg" "$DF" && PASS=$((PASS+1)) || FAIL=$((FAIL+1))
done
echo "FAIL=$FAIL"
')"
rm -f "$TMPF"
if echo "$OUT" | grep -q "FAIL=3"; then
  ok "空壳看板被判缺语义段 → 功能级判据能抓'假完成'（非只看文件在）"
else
  bad "空壳看板未被判缺语义段（OUT=$OUT）"
fi

# ---- T9 模块→实现源映射收口唯一事实源（Issue #162）----
echo ""
echo "▶ T9 模块→实现源映射唯一事实源（不再散落硬编码 case）"
[ -f scripts/feature-verify/modules.map ] && ok "modules.map 唯一事实源存在" || bad "缺 scripts/feature-verify/modules.map"
# 选择器不得再散落硬编码 case "$srcmod" 分支
if grep -q 'case "\$srcmod"' scripts/feature-verify.sh; then
  bad "feature-verify.sh 仍残留硬编码 case 分支（未收口唯一事实源）"
else
  ok "feature-verify.sh 已无硬编码 case 分支（只读 modules.map）"
fi
# 证据库每个模块都必须在映射表登记
MAP_MISSING=""
for d in scripts/feature-verify/*/; do
  m="$(basename "$d")"
  [ "$m" = "_templates" ] && continue
  grep -q "^${m}:" scripts/feature-verify/modules.map || MAP_MISSING="$MAP_MISSING $m"
done
if [ -z "$MAP_MISSING" ]; then
  ok "证据库全部模块已在 modules.map 登记（无未映射模块）"
else
  bad "证据库模块未登记映射:$MAP_MISSING → --changed 会静默漏跑"
fi
if bash scripts/feature-verify.sh --check-map >/dev/null 2>&1; then
  ok "--check-map 防退化断言通过（基线绿）"
else
  bad "--check-map 基线失败"
fi

# ---- T10 变异验证：移除任一模块映射 → 断言 RED（有牙齿）----
echo ""
echo "▶ T10 变异验证（移除映射 → RED）"
TMPMAP="$(mktemp)"
grep -v '^dispatch:' scripts/feature-verify/modules.map > "$TMPMAP"
if FEATURE_VERIFY_MAP="$TMPMAP" bash scripts/feature-verify.sh --check-map >/dev/null 2>&1; then
  bad "移除 dispatch 映射后 --check-map 仍绿 → 断言没牙齿"
else
  ok "移除 dispatch 映射 → --check-map RED（防退化有牙齿）"
fi
rm -f "$TMPMAP"

# ---- T11 缺口回归自证：collab 实现源变更不再假绿 ----
echo ""
echo "▶ T11 缺口回归自证（评审 🟡P1 漏跑源不再假绿）"
OUT_CHANGED="$(FEATURE_VERIFY_CHANGED_FILES="local-agent/collab/engine.py" bash scripts/feature-verify.sh --changed --dry-run 2>&1)"
if printf '%s\n' "$OUT_CHANGED" | grep -q "feature-verify/peer-closure/"; then
  ok "改 local-agent/collab/engine.py → 选中 peer-closure（假绿消除）"
else
  bad "改 local-agent/collab/engine.py 仍无可选脚本（OUT=$OUT_CHANGED）"
fi

# ---- T12 变更感知测试选择已接线（选择器改动 → 功能级自测）----
echo ""
echo "▶ T12 变更感知测试选择接线（Issue #162）"
if grep -q "scripts/feature-verify|tests/test_feature_verify.sh" scripts/change-aware-test.sh; then
  ok "change-aware 已将 feature-verify 证据库/选择器变更映射到 test_feature_verify.sh"
else
  bad "change-aware 未接线 feature-verify 变更 → 选择器改动无自测守护"
fi

# ---- T13 CI 闸门已跑 --check-map（防退化断言前置）----
echo ""
echo "▶ T13 CI 闸门接线 --check-map"
if grep -q "feature-verify.sh --check-map" .cnb.yml; then
  ok "CI feature-verify gate 已前置 --check-map（未映射即 RED）"
else
  bad "CI 闸门未跑 --check-map → 未映射模块仍可能静默漏跑"
fi
# ---- T14 回归断言：target SHA 不可解析 → 不得假绿跳过（S1 修复防退化）----
echo ""
echo "▶ T14 target SHA 不可解析 → 回退链继续/保守全量（不假绿）"
# 造最小仓库：单提交（无 main、无 HEAD~1）→ 全部 diff 来源落空。
# ⚠️ 用 `git init -q -b work` **显式钉死非 main 分支名**：若依赖环境默认分支名
#    （init.defaultBranch=main 的环境 git ≥2.28 常见配置），fixture 会自带可解析
#    main，前提失效、测的不是目标路径（Issue #162 复评 R2）。
T14REPO="$(mktemp -d)"
(
  cd "$T14REPO" || exit 1
  git init -q -b work; git config user.email t@t; git config user.name t
  mkdir -p scripts/feature-verify/foo
  printf '#!/usr/bin/env bash\necho ok; exit 0\n' > scripts/feature-verify/foo/a.sh
  printf 'foo: scripts/x.py: scripts/x\\.py\n' > scripts/feature-verify/modules.map
  cp "$OLDPWD/scripts/feature-verify.sh" scripts/feature-verify.sh
  git add -A >/dev/null 2>&1; git commit -qm init >/dev/null 2>&1
)
# ① 不带 CNB_COMMIT：全部来源落空 → 保守全量
T14OUT="$(cd "$T14REPO" && CNB_PULL_REQUEST_TARGET_SHA=0000000000000000000000000000000000000000 \
          bash scripts/feature-verify.sh --changed --dry-run 2>&1)"
if printf '%s\n' "$T14OUT" | grep -q "无法确定变更范围"; then
  ok "T14a: 全链落空 → 保守全量回归（不跳过，不漏跑）"
else
  bad "T14a: 全链落空未走保守全量（OUT=$T14OUT）"
fi
if printf '%s\n' "$T14OUT" | grep -q "变更范围为空"; then
  bad "T14b: 全链落空仍报'变更范围为空' → S1 假绿回归"
else
  ok "T14b: 全链落空不再误报'变更范围为空'（S1 假绿已消除）"
fi
# ② **带 CNB_COMMIT（真实 CI feature-verify gate 必设此变量）**：旧实现此路径
#    「来源存在即 resolved=1」→ 报「变更范围为空 → 跳过」exit 0 假绿（S1 残留根因）。
#    必须以「diff 真成功」为准 → 走保守全量。这是复评 R1 的核心回归断言。
T14COUT="$(cd "$T14REPO" && CNB_COMMIT="$(git -C "$T14REPO" rev-parse HEAD)" \
           CNB_PULL_REQUEST_TARGET_SHA=0000000000000000000000000000000000000000 \
           bash scripts/feature-verify.sh --changed --dry-run 2>&1)"
if printf '%s\n' "$T14COUT" | grep -q "无法确定变更范围"; then
  ok "T14c: 带 CNB_COMMIT（真实 CI 变量）→ 保守全量（S1 假绿已消除）"
else
  bad "T14c: 带 CNB_COMMIT 仍走'变更范围为空'跳过 → S1 假绿未清零（R1）"
fi
if printf '%s\n' "$T14COUT" | grep -q "变更范围为空"; then
  bad "T14d: 带 CNB_COMMIT 报'变更范围为空' → R1 假绿残留"
else
  ok "T14d: 带 CNB_COMMIT 不再误报'变更范围为空'（R1 已修）"
fi
rm -rf "$T14REPO"

# ---- T14e 收窄来源不得静默欠选（🟡S 复评：多提交 PR 漏跑）----
echo ""
echo "▶ T14e 仅剩 HEAD~1..HEAD 收窄来源 → 保守全量（不静默欠选）"
# 造 2 提交仓库、无 main、target SHA 不可解析 → 只剩 HEAD~1..HEAD。
# 旧实现会静默收窄到单提交（多提交 PR 漏跑）；现须偏保守走全量。
T14BREPO="$(mktemp -d)"
(
  cd "$T14BREPO" || exit 1
  git init -q -b work; git config user.email t@t; git config user.name t
  mkdir -p scripts/feature-verify/foo scripts/feature-verify/bar
  printf '#!/usr/bin/env bash\necho ok; exit 0\n' > scripts/feature-verify/foo/a.sh
  printf '#!/usr/bin/env bash\necho ok; exit 0\n' > scripts/feature-verify/bar/b.sh
  printf 'foo: scripts/x.py: scripts/x\\.py\nbar: scripts/y.py: scripts/y\\.py\n' \
    > scripts/feature-verify/modules.map
  cp "$OLDPWD/scripts/feature-verify.sh" scripts/feature-verify.sh
  git add -A >/dev/null 2>&1; git commit -qm c1 >/dev/null 2>&1
  printf 'changed\n' >> scripts/feature-verify/foo/a.sh
  git add -A >/dev/null 2>&1; git commit -qm c2 >/dev/null 2>&1
)
T14BOUT="$(cd "$T14BREPO" && CNB_COMMIT="$(git -C "$T14BREPO" rev-parse HEAD)" \
           CNB_PULL_REQUEST_TARGET_SHA=0000000000000000000000000000000000000000 \
           bash scripts/feature-verify.sh --changed --dry-run 2>&1)"
if printf '%s\n' "$T14BOUT" | grep -q "收窄来源"; then
  ok "T14e-1: 仅剩收窄来源 → 显式暴露（不静默）"
else
  bad "T14e-1: 收窄来源未显式暴露（OUT=$T14BOUT）"
fi
if printf '%s\n' "$T14BOUT" | grep -q "feature-verify/bar/"; then
  ok "T14e-2: 收窄场景走保守全量（bar 未漏跑，🟡欠选已处理）"
else
  bad "T14e-2: 收窄场景欠选（bar 静默漏跑，🟡未处理）"
fi
rm -rf "$T14BREPO"


# ---- T15 回归断言：target SHA 无效但回退源可用 → 继续回退真选测（不断链）----
echo ""
echo "▶ T15 target SHA 无效但 main 可用 → 回退链继续（不因首个来源失效即跳过）"
T15REPO="$(mktemp -d)"
(
  cd "$T15REPO" || exit 1
  git init -q -b work; git config user.email t@t; git config user.name t
  mkdir -p scripts/feature-verify/foo
  printf '#!/usr/bin/env bash\necho ok; exit 0\n' > scripts/feature-verify/foo/a.sh
  printf 'foo: scripts/x.py: scripts/x\\.py\n' > scripts/feature-verify/modules.map
  cp "$OLDPWD/scripts/feature-verify.sh" scripts/feature-verify.sh
  git add -A >/dev/null 2>&1; git commit -qm base >/dev/null 2>&1
  git branch -f main HEAD
  printf 'changed\n' > scripts/feature-verify/foo/a.sh
  git add -A >/dev/null 2>&1; git commit -qm change >/dev/null 2>&1
)
T15OUT="$(cd "$T15REPO" && CNB_PULL_REQUEST_TARGET_SHA=0000000000000000000000000000000000000000 \
          bash scripts/feature-verify.sh --changed --dry-run 2>&1)"
if printf '%s\n' "$T15OUT" | grep -q "feature-verify/foo/"; then
  ok "T15: target SHA 无效 → 回退 main 真选测（回退链不断，非假绿跳过）"
else
  bad "T15: target SHA 无效后未继续回退选测（OUT=$T15OUT）"
fi
rm -rf "$T15REPO"
# ---- T16 跨 PR 雷回归：前置登记容忍 + 漏跑方向牙齿不丢 ----
echo ""
echo "▶ T16 跨 PR 雷回归（映射前置登记 vs 目录有映射无）"
T16V="$(mktemp -d)"; mkdir -p "$T16V/only_dir" "$T16V/_templates"
echo '#!/usr/bin/env bash' > "$T16V/only_dir/x.sh"
# (a) 目录有、映射无 → RED（真漏跑方向）
if FEATURE_VERIFY_DIR="$T16V" bash scripts/feature-verify.sh --check-map >/dev/null 2>&1; then
  bad "T16a: 证据目录有、映射表无 → --check-map 仍绿（漏跑守护失效）"
else
  ok "T16a: 证据目录有、映射表无 → RED（漏跑方向牙齿不丢）"
fi
# (b) 映射有、目录无（前置登记）→ 绿（容忍跨 PR 中间态）
cat > "$T16V/m_forward.map" <<'MAPEOF'
only_dir: local-agent/collab/engine.py: local-agent/collab/engine\.py
forward_only: local-agent/collab/engine.py: local-agent/collab/engine\.py
MAPEOF
if FEATURE_VERIFY_DIR="$T16V" FEATURE_VERIFY_MAP="$T16V/m_forward.map" \
   bash scripts/feature-verify.sh --check-map >"$T16V/f.out" 2>&1; then
  ok "T16b: 映射前置登记（目录后落地）→ --check-map 绿（跨 PR 雷消除）"
else
  bad "T16b: 前置登记被判 RED → 合 #161 后主线会变红（雷未消除）"
fi
grep -q "forward_only" "$T16V/f.out" 2>/dev/null \
  && ok "T16c: 前置登记以 ⚠️ 警告显式暴露（不静默）" \
  || bad "T16c: 前置登记未显式暴露"
rm -rf "$T16V"
# (c) 本 PR 已真实预登记 collab（与 #161 证据目录对齐）
grep -q '^collab:' scripts/feature-verify/modules.map \
  && ok "T16d: modules.map 已预登记 collab（合 #161 后不判红）" \
  || bad "T16d: 未预登记 collab → 合 #161 后主线 --check-map 判红"

# ---- T17 脚本可执行位回归（100755）----
echo ""
echo "▶ T17 脚本可执行位回归"
for f in scripts/feature-verify.sh scripts/change-aware-test.sh tests/test_feature_verify.sh \
         "scripts/feature-verify/selector/映射全覆盖.sh"; do
  m="$(git ls-files -s "$f" | awk '{print $1}')"
  [ "$m" = "100755" ] && ok "$f 保持 100755" || bad "$f 可执行位回归（$m，应 100755）"
done

# ---- 汇总 ----
echo ""
echo "======================================================"
echo "feature-verify 自测汇总：PASS=$PASS FAIL=$FAIL"
if [ "$FAIL" -gt 0 ]; then
  echo "🔴 信号灯：feature-verify 模块未达标"
  exit 1
else
  echo "🟢 信号灯：feature-verify 模块自测全过"
  exit 0
fi
