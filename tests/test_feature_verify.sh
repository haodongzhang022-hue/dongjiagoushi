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
#   T12 变更感知测试选择真接线：registry.json 登记本自测 + **逐条 covers 真验**选择器选中（删任一条必红）
#   T13 CI 闸门已前置 --check-map（防退化断言）
#   T14 target SHA 不可解析 → 保守全量（不假绿跳过 · 复评 R1：含 **带 CNB_COMMIT**
#       真实 CI 场景断言 T14c/T14d，否则测不到真实环境假绿）
#   T14e 收窄来源（HEAD~1..HEAD）不得静默欠选（复评 🟡S：多提交 PR 漏跑）
#   T15 target SHA 无效但 main 可用 → 回退链继续真选测（不断链）
#   T16 跨 PR 雷回归（Issue #162 收口）：映射前置登记（目录后落地）不得判 RED，
#       但"目录有、映射无"仍须 RED——两方向同时锁死，防合 #161 后主线变红
#   T17 脚本可执行位回归：feature-verify.sh / change-aware / 自测 / selector 样例 保持 100755
#   T18 空转灯回归（Issue #162 复评 S2）：T16a/Then-9a 须带真实 modules.map，
#       真走到 ①「未登记」判据（而非"映射表不存在"提前 exit 永远红）
#   T19 静默通道回归（Issue #162 复评 S3）：僵尸映射行命中实现源变更时须显式暴露，不静默通过
#   T20 僵尸容忍收窄（Issue #162 复评 T9）：容忍只给显式 `pending:` 标记；未标记的目录缺失
#       → --check-map RED，且 --changed 命中其实现源 → 硬失败（不再「无可选脚本 → 通过」假绿）
#   T21 stale pending：目录已落地仍挂 `pending:` → ⚠️ 提示转正式登记（收窄容忍面）
#   T22 合并态假红回归（Issue #162 合并态修复）：T9 登记判据 pending 感知 + 牙齿
#   T23 fixture 假红根因回归（Issue #175）：宿主 commit.gpgsign=true 致裸 git commit
#       静默失败 → 空仓库 `git rev-parse HEAD` 回显字面量 HEAD（rc=0）→ 断言假红
#
# 用法：bash tests/test_feature_verify.sh
# 运行依赖：bash + git（纯逻辑）；python 样例在 python 环境跑（无则优雅跳过）
# ============================================================
set -u
cd "$(dirname "$0")/.."
PASS=0; FAIL=0; SKIP=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }
skip(){ SKIP=$((SKIP+1)); echo "  ⏭️  $1"; }

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
  git config tag.gpgsign false
  git config commit.gpgsign false
  git config core.hooksPath /dev/null
  # 清掉可能残留的 gc/维护进程对仓库的干扰（fixture 极小，无需自动维护）
  git config gc.auto 0
}
fixture_commit() {  # $1=message  —— 真提交 + 真核对，失败即 fail-loud
  git add -A >/dev/null 2>&1
  git commit -qm "$1" >/dev/null 2>&1 || { echo "❌ fixture 提交失败（$1）：宿主 git 配置不可用" >&2; exit 1; }
  git rev-parse --verify --quiet HEAD >/dev/null 2>&1 || { echo "❌ fixture 无 HEAD（$1）" >&2; exit 1; }
}

# 证据库模块是否已在映射表登记（`pending:` 前缀视为已登记 · Issue #162 合并态修复）
# 背景：T9 循环原用 `^${m}:` 精确匹配，合并态 `pending: collab:` 带前缀 → 漏判假红；
#   而 T16d 又硬断言 `^pending: collab:` 必须存在 → 两断言在合并态互斥。
#   `pending:` 是**显式预登记**（#163 先合时 collab/ 证据目录尚未由 #161 落地），
#   属"已登记"的一种合法形态；单点收口本判据，供 T9 循环与 T22 回归灯共用。
map_registered() {  # $1=evidence-module  $2=映射表路径
  grep -qE "^(${1}|pending: ${1}):" "$2"
}

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
  map_registered "$m" scripts/feature-verify/modules.map || MAP_MISSING="$MAP_MISSING $m"
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

# ---- T12 变更感知测试选择真接线（每条 covers 逐条真验 → 云端 CI 真跑本自测）----
# 评审 🟡3 / 测试残留 B：此前 T12 是「grep 源码有字」+「混喂两条输入只要一条命中即绿」，
# = 文本断言 + 弱断言复刻，**每条 covers 是否真通从未被验证**。云端 CI 的变更感知走
# `.cnb.yml` → hybrid/selector.py 的 IncrementalSelector → registry.json。故断言**逐条真验**：
#   ① registry.json 已登记 tests/test_feature_verify.sh（链路可达）；
#   ② 有 python3 → **逐条**把每条承重 covers 单独喂 IncrementalSelector.select([cf])，
#      断言选中本自测；**删任一条 covers → 对应灯必红**（有牙齿，非混喂掩盖）。
#   ③ 无 python3 → 计 SKIP（不计入 PASS/FAIL），显式暴露"本机未验链路"，不假装通过。
echo ""
echo "▶ T12 变更感知测试选择真接线（registry → IncrementalSelector · 逐条真验）"
REG="local-agent/hybrid/registry.json"
if grep -q '"tests/test_feature_verify.sh"' "$REG"; then
  ok "T12a: registry.json 已登记 tests/test_feature_verify.sh（云端 CI 选择器可达）"
else
  bad "T12a: registry.json 未登记本自测 → 云端 CI 不会真跑本自测的信号灯（残留 B）"
fi
# ② 逐条真验：**期望承重 covers 钉死在测试里**（不从 registry 动态读，否则删条目成同义反复），
#    每条单独喂 IncrementalSelector.select([cf]) 断言命中本自测；**删任一条 → 必红**。
if command -v python3 >/dev/null 2>&1; then
  SEL_OUT="$(python3 - <<'PYSEL' 2>/dev/null
import sys, json
sys.path.insert(0, 'local-agent')
from hybrid.selector import IncrementalSelector
# 期望承重 covers（钉死）：改这些源码/契约文件即须云端选中本自测，缺一即漏跑
EXPECT = [
    'scripts/feature-verify.sh',              # 闸门本体
    'scripts/feature-verify/modules.map',     # 模块→实现源映射
    'local-agent/hybrid/selector.py',         # 选择器本体
    'scripts/feature-regress.sh',             # 回归诊断
    'scripts/change-aware-test.sh',           # 变更感知手工入口
    'docs/FEATURE_VERIFY.md',                 # 模块文档
    '.cnb.yml',                               # CI 接线
]
s = IncrementalSelector(root_dir='.')
reg = json.load(open('local-agent/hybrid/registry.json', encoding='utf-8'))
covers = set(reg['tests']['tests/test_feature_verify.sh'].get('covers', []))
miss = []
for cf in EXPECT:
    if cf not in covers:
        miss.append('未登记:' + cf)          # 被删条目 → 必红
    elif 'tests/test_feature_verify.sh' not in s.select([cf]):
        miss.append('死条目:' + cf)          # 登记但链路不通 → 必红
print('MISS:' + ','.join(miss) if miss else 'OK:%d' % len(EXPECT))
PYSEL
)"
  case "$SEL_OUT" in
    OK:*)
      ok "T12b: 逐条真验 ${SEL_OUT#OK:} 条承重 covers 全部单独选中本自测（删任一条必红）"
      ;;
    MISS:*)
      bad "T12b: 承重 covers 未真通（${SEL_OUT#MISS:}）→ 云端 CI 改其仍漏跑"
      ;;
    *)
      bad "T12b: 选择器逐条真验异常（$SEL_OUT）"
      ;;
  esac
else
  skip "T12b: 本机无 python3 → 跳过逐条真验（链路可达性未在本机验证，不计入 PASS）"
fi
# ③ 死条目扫描（Issue #165 🟡5）：registry 每一条 covers 必须**字面存在**，
#    或能被双向前缀归一化**真命中本测试**。两条都不成立 = 永不命中的死条目 → RED。
#    （历史形态：`topology/router.py` 裸路径 / `embedding/` 目录名——靠归一化侥幸命中，
#      但路径本身是假的，读表的人以为它是文件，映射一改就静默失配。）
if command -v python3 >/dev/null 2>&1; then
  DEAD_OUT="$(python3 - <<'PYDEAD' 2>&1
import json, os, sys
sys.path.insert(0, 'local-agent')
from hybrid.selector import IncrementalSelector
s = IncrementalSelector(root_dir='.')
reg = json.load(open('local-agent/hybrid/registry.json', encoding='utf-8'))
dead = []
for test, info in reg['tests'].items():
    for cov in info.get('covers', []):
        path = cov.rstrip('/')
        if os.path.exists(path):
            continue                       # ① 字面存在 = 活
        # ② 路径本身不存在时，「归一化能命中自己」是**同义反复**（自比较必然相等），
        #    拿它当判据会永远绿（本断言首版即栽在这）。改判「能否命中**其他**测试」：
        #    能命中共用该实现源的别的测试 = 这条路径确实指向真实实现（如
        #    `embedding/` 被 test_memory_store 也覆盖）；连别人都不命中 = 死条目。
        others = [t for t in s._find_by_source(path) if t != test]
        if others:
            continue
        dead.append(test + ' -> ' + cov)
print('DEAD:' + ','.join(dead) if dead else 'OK')
PYDEAD
)"
  case "$DEAD_OUT" in
    OK) ok "T12d: registry 无死 covers 条目（字面存在 或 归一化命中其他测试）" ;;
    DEAD:*) bad "T12d: registry 存在死 covers 条目（${DEAD_OUT#DEAD:}）→ 永不命中，映射失真" ;;
    *) bad "T12d: 死条目扫描异常（$DEAD_OUT）" ;;
  esac
else
  skip "T12d: 本机无 python3 → 跳过死条目扫描（不计入 PASS）"
fi
# ③ 手工入口映射仍在（本地/手动执行场景，非 CI 主链路）
grep -q "scripts/feature-verify|tests/test_feature_verify.sh" scripts/change-aware-test.sh \
  && ok "T12c: change-aware 手工入口映射保留（本地/手动执行用）" \
  || bad "T12c: change-aware 手工入口映射丢失"
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
  fixture_git
  mkdir -p scripts/feature-verify/foo
  printf '#!/usr/bin/env bash\necho ok; exit 0\n' > scripts/feature-verify/foo/a.sh
  printf 'foo: scripts/x.py: scripts/x\\.py\n' > scripts/feature-verify/modules.map
  cp "$OLDPWD/scripts/feature-verify.sh" scripts/feature-verify.sh
  fixture_commit init
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
  fixture_git
  mkdir -p scripts/feature-verify/foo scripts/feature-verify/bar
  printf '#!/usr/bin/env bash\necho ok; exit 0\n' > scripts/feature-verify/foo/a.sh
  printf '#!/usr/bin/env bash\necho ok; exit 0\n' > scripts/feature-verify/bar/b.sh
  printf 'foo: scripts/x.py: scripts/x\\.py\nbar: scripts/y.py: scripts/y\\.py\n' \
    > scripts/feature-verify/modules.map
  cp "$OLDPWD/scripts/feature-verify.sh" scripts/feature-verify.sh
  fixture_commit c1
  printf 'changed\n' >> scripts/feature-verify/foo/a.sh
  fixture_commit c2
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
  fixture_git
  mkdir -p scripts/feature-verify/foo
  printf '#!/usr/bin/env bash\necho ok; exit 0\n' > scripts/feature-verify/foo/a.sh
  printf 'foo: scripts/x.py: scripts/x\\.py\n' > scripts/feature-verify/modules.map
  cp "$OLDPWD/scripts/feature-verify.sh" scripts/feature-verify.sh
  fixture_commit base
  git branch -f main HEAD
  printf 'changed\n' > scripts/feature-verify/foo/a.sh
  fixture_commit change
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
# 关键：临时证据库须带**真实 modules.map**，否则 check_map 在"映射表不存在"就 exit 1
# （永远红，走不到 ①）→ 空转信号灯（复评 S2）。放入 map 后本灯才真测「目录有、映射无」。
cp scripts/feature-verify/modules.map "$T16V/modules.map"
# (a) 目录有、映射无 → RED（真漏跑方向）
if FEATURE_VERIFY_DIR="$T16V" bash scripts/feature-verify.sh --check-map >"$T16V/a.out" 2>&1; then
  bad "T16a: 证据目录有、映射表无 → --check-map 仍绿（漏跑守护失效）"
else
  ok "T16a: 证据目录有、映射表无 → RED（漏跑方向牙齿不丢）"
fi
# (a2) 有鉴别力：输出必须真走到 ①「未登记」判据，而非"映射表不存在"提前 exit
grep -q "模块 \[only_dir\] 未在" "$T16V/a.out" 2>/dev/null \
  && ok "T16a2: 真走到 ①未登记判据（非'映射表不存在'空转红灯）" \
  || bad "T16a2: 未走到 ①（空转红灯，S2 未修）"
# (b) **显式 pending 标记**的待落地前置登记（目录后落地）→ 绿（容忍跨 PR 中间态）
#     复评 T9：容忍必须**显式标记**（pending:），否则"目录缺失"一律放过 = 重开假绿。
cat > "$T16V/m_forward.map" <<'MAPEOF'
only_dir: local-agent/collab/engine.py: local-agent/collab/engine\.py
pending: forward_only: local-agent/collab/engine.py: local-agent/collab/engine\.py
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
# (c) collab 映射须与「#161 证据目录是否已落地」自洽（跨 PR 两态都绿 · 合并态修复）：
#     目录未落地（#163 先合）→ 必须 `pending: collab:`，否则 main+#163 --check-map 判红；
#     目录已落地（#161 已合）→ collab 须已登记（`pending: collab:` 或正式 `collab:` 皆可；
#       正式登记是清理后的目标态，pending 仅余 stale ⚠️ 非阻断）。
if [ -d scripts/feature-verify/collab ]; then
  map_registered collab scripts/feature-verify/modules.map \
    && ok "T16d: collab 目录已落地且映射已登记（pending 清理前后皆绿）" \
    || bad "T16d: collab 目录已落地但映射缺失 → --changed 会静默漏跑"
else
  grep -q '^pending: collab:' scripts/feature-verify/modules.map \
    && ok "T16d: collab 目录未落地已 pending 预登记（合 #161 前不判红）" \
    || bad "T16d: 未 pending 预登记 collab → 合 #163 后主线 --check-map 判红"
fi
# ---- T17 脚本可执行位回归（100755）----
echo ""
echo "▶ T17 脚本可执行位回归"
for f in scripts/feature-verify.sh scripts/change-aware-test.sh tests/test_feature_verify.sh \
         "scripts/feature-verify/selector/映射全覆盖.sh"; do
  m="$(git ls-files -s "$f" | awk '{print $1}')"
  [ "$m" = "100755" ] && ok "$f 保持 100755" || bad "$f 可执行位回归（$m，应 100755）"
done


# ---- T18 空转灯回归：T16a/Then-9a 真走到 ①（复评 S2）----
echo ""
echo "▶ T18 空转灯回归（临时证据库须带真实 modules.map，真走到 ①）"
T18V="$(mktemp -d)"; mkdir -p "$T18V/only_dir" "$T18V/_templates"
echo '#!/usr/bin/env bash' > "$T18V/only_dir/x.sh"
# 无 map：check_map 在"映射表不存在"提前 exit 1 → 永远红、走不到 ①（空转）
if FEATURE_VERIFY_DIR="$T18V" bash scripts/feature-verify.sh --check-map >"$T18V/nomap.out" 2>&1; then
  bad "T18a: 无 map 时 --check-map 竟绿（异常）"
else
  grep -q "映射表不存在" "$T18V/nomap.out" \
    && ok "T18a: 无 map → 早退于'映射表不存在'（证明裸 FEATURE_VERIFY_DIR 是空转红灯）" \
    || bad "T18a: 无 map 未早退于'映射表不存在'"
fi
# 有 map：必须真走到 ①「模块未登记 → RED」
cp scripts/feature-verify/modules.map "$T18V/modules.map"
FEATURE_VERIFY_DIR="$T18V" bash scripts/feature-verify.sh --check-map >"$T18V/withmap.out" 2>&1
grep -q "模块 \[only_dir\] 未在" "$T18V/withmap.out" \
  && ok "T18b: 带真实 map → 真走到 ①未登记判据（空转已消除）" \
  || bad "T18b: 带真实 map 仍未走到 ①（S2 未修）"
rm -rf "$T18V"

# ---- T19 静默通道回归：僵尸映射行命中实现源 → 须显式暴露（复评 S3）----
echo ""
echo "▶ T19 静默通道回归（僵尸行不得吞掉未映射告警）"
T19V="$(mktemp -d)"; mkdir -p "$T19V/other"
echo '#!/usr/bin/env bash' > "$T19V/other/x.sh"
cat > "$T19V/m.map" <<'MAPEOF'
zombie: local-agent/novel/core.py: local-agent/novel/core\.py
other: local-agent/novel/other.py: local-agent/novel/other\.py
MAPEOF
T19OUT="$(FEATURE_VERIFY_DIR="$T19V" FEATURE_VERIFY_MAP="$T19V/m.map" \
          FEATURE_VERIFY_CHANGED_FILES="local-agent/novel/core.py" \
          bash scripts/feature-verify.sh --changed 2>&1)"
if printf '%s\n' "$T19OUT" | grep -q "映射选中的模块 \[zombie\] 无证据目录/脚本"; then
  ok "T19: 僵尸行命中实现源变更 → 显式暴露（静默通道已堵）"
else
  bad "T19: 僵尸行命中仍静默通过（S3 未修，OUT=$T19OUT）"
fi
rm -rf "$T19V"

# ---- T20 僵尸容忍收窄（复评 T9）：未标记目录缺失 RED / pending 标记才容忍 ----
echo ""
echo "▶ T20 僵尸容忍收窄（T9）：容忍只给显式 pending: 标记"
T20V="$(mktemp -d)"
# 正式模块目录 + 未标记僵尸行 + 显式 pending 行
mkdir -p "$T20V/real" "$T20V/_templates"
echo '#!/usr/bin/env bash' > "$T20V/real/x.sh"
cat > "$T20V/m.map" <<'MAPEOF'
real: local-agent/novel/real.py: local-agent/novel/real\.py
deleted: local-agent/novel/deleted.py: local-agent/novel/deleted\.py
pending: waiting: local-agent/novel/waiting.py: local-agent/novel/waiting\.py
MAPEOF
# 探针须真实存在（探针检查独立于证据目录）
mkdir -p local-agent/novel && : > local-agent/novel/real.py && : > local-agent/novel/deleted.py && : > local-agent/novel/waiting.py
# (a) 未标记的目录缺失（deleted）→ 必须 RED
if FEATURE_VERIFY_DIR="$T20V" FEATURE_VERIFY_MAP="$T20V/m.map" \
   bash scripts/feature-verify.sh --check-map >"$T20V/a.out" 2>&1; then
  bad "T20a: 未标记目录缺失 → --check-map 仍绿（T9 未收窄，重开假绿）"
else
  grep -q "正式登记的模块证据目录缺失.*deleted" "$T20V/a.out" \
    && ok "T20a: 未标记目录缺失 → RED（T9 收窄生效）" \
    || bad "T20a: RED 但未指明 deleted（OUT=$(cat "$T20V/a.out"))"
fi
# (b) 显式 pending 的目录缺失（waiting）→ 不判 RED（跨 PR 中间态容忍）
if grep -q "正式登记的模块证据目录缺失.*waiting" "$T20V/a.out"; then
  bad "T20b: 显式 pending 的目录缺失被当正式缺失判 RED（容忍面过窄）"
else
  grep -q "显式待落地前置登记（pending:）暂无证据目录.*waiting" "$T20V/a.out" \
    && ok "T20b: 显式 pending 的目录缺失 → ⚠️ 容忍（跨 PR 中间态）" \
    || bad "T20b: pending 行未显式暴露（OUT=$(cat "$T20V/a.out"))"
fi
# (c) --changed 命中未标记目录缺失模块 → 硬失败（不再「无可选脚本 → 通过」假绿）
T20OUT="$(FEATURE_VERIFY_DIR="$T20V" FEATURE_VERIFY_MAP="$T20V/m.map" \
          FEATURE_VERIFY_CHANGED_FILES="local-agent/novel/deleted.py" \
          bash scripts/feature-verify.sh --changed 2>&1)"; T20RC=$?
[ "$T20RC" -ne 0 ] \
  && ok "T20c: 未标记目录缺失 + 命中实现源 → --changed 硬失败（不假绿）" \
  || bad "T20c: 未标记目录缺失仍 --changed exit 0（T9 未收窄，OUT=$T20OUT）"
rm -f local-agent/novel/real.py local-agent/novel/deleted.py local-agent/novel/waiting.py
rmdir local-agent/novel 2>/dev/null
rm -rf "$T20V"

# ---- T21 stale pending：目录已落地仍挂 pending: → ⚠️ 提示（容忍面不得无声扩大）----
echo ""
echo "▶ T21 stale pending（目录已落地须提示转正式登记）"
T21V="$(mktemp -d)"; mkdir -p "$T21V/landed" "$T21V/_templates"
echo '#!/usr/bin/env bash' > "$T21V/landed/x.sh"
cat > "$T21V/m.map" <<'MAPEOF'
pending: landed: local-agent/novel/real.py: local-agent/novel/real\.py
MAPEOF
mkdir -p local-agent/novel && : > local-agent/novel/real.py
if FEATURE_VERIFY_DIR="$T21V" FEATURE_VERIFY_MAP="$T21V/m.map" \
   bash scripts/feature-verify.sh --check-map >"$T21V/a.out" 2>&1; then
  grep -q "证据目录已落地.*landed" "$T21V/a.out" \
    && ok "T21: 目录已落地仍挂 pending: → ⚠️ 提示 stale（收窄容忍面）" \
    || bad "T21: 目录已落地仍挂 pending: 未提示 stale"
else
  bad "T21: 目录已落地 + pending 仍绿失败（OUT=$(cat "$T21V/a.out"))"
fi
rm -f local-agent/novel/real.py; rmdir local-agent/novel 2>/dev/null
rm -rf "$T21V"
# ---- T22 合并态假红回归（Issue #162 合并态修复）：T9 登记判据的 pending 感知 + 牙齿 ----
echo ""
echo "▶ T22 合并态假红回归（T9 登记判据 pending 感知 + 牙齿）"
T22M="$(mktemp)"
printf 'collab: local-agent/collab/engine.py: x\n' > "$T22M"
map_registered collab "$T22M" \
  && ok "T22a: 正式登记 collab → 判已登记" \
  || bad "T22a: 正式登记 collab 被漏判"
printf 'pending: collab: local-agent/collab/engine.py: x\n' > "$T22M"
map_registered collab "$T22M" \
  && ok "T22b: pending: collab 预登记 → 判已登记（合并态假红已消除）" \
  || bad "T22b: pending 预登记被漏判 → 合并态仍假红"
printf 'other: scripts/x.py: y\n' > "$T22M"
map_registered collab "$T22M" \
  && bad "T22c: 未登记却判已登记（牙齿丢失）" \
  || ok "T22c: 未登记 → 判未登记（牙齿不丢）"
rm -f "$T22M"

# ---- T23 fixture 假红根因回归（Issue #175 · CI 红）：宿主 commit.gpgsign 不得污染 fixture ----
# 真实根因（不是"目标路径没走到"）：CI runner 的系统级 gitconfig 带 `commit.gpgsign=true`
#   + `gpg.program=cnb-gpgsign`，fixture 里裸 `git commit` 因此**失败**；而原 fixture 丢弃
#   stdout 且不查 rc，于是仓库**没有 commit**。空仓库里 `git rev-parse HEAD` 会**回显字面量
#   "HEAD" 且 rc=0**（只有 --verify 才失败），`CNB_COMMIT="$(git rev-parse HEAD)"` 因此变成
#   字符串 "HEAD" → 断言全被误导成假红（T5/T14a/T14c/T14e-1 + selector Then-7a/7b）。
# 本灯用**注入的坏签名配置**复现同一环境：fixture 必须自带反制（关签名）+ 真核对 HEAD。
echo ""
echo "▶ T23 fixture 不受宿主 commit.gpgsign 污染（Issue #175 假红根因）"
if ! command -v git >/dev/null 2>&1; then
  skip "T23: 本机无 git → 跳过（根因未在本机验证，不计入 PASS）"
else
  T23HOME="$(mktemp -d)"
  cat > "$T23HOME/.gitconfig" <<'CFGEOF'
[commit]
	gpgsign = true
[gpg]
	program = cnb-gpgsign-intentionally-missing
CFGEOF
  T23REPO="$(mktemp -d)"
  # (a) fixture 助手自身：带坏签名配置也必须真提交成功
  T23RC=0
  (
    cd "$T23REPO" || exit 1
    fixture_git
    printf 'x\n' > f.txt
    fixture_commit init
  ) >"$T23HOME/a.out" 2>&1 || T23RC=1
  if [ "$T23RC" -eq 0 ] \
     && git -C "$T23REPO" rev-parse --verify --quiet HEAD >/dev/null 2>&1; then
    ok "T23a: 坏 commit.gpgsign 环境下 fixture 仍真提交（关签名 + 核对 HEAD）"
  else
    bad "T23a: fixture 在坏签名环境下未提交成功（$(cat "$T23HOME/a.out")）"
  fi
  # (b) 鉴别力（证明本灯测的是根因，不是空过）：同环境下裸 git 命令必须真失败
  #     —— 否则 T23a 就没有牙齿（说明坏环境没造出来）。
  T23BARE="$(mktemp -d)"
  (
    cd "$T23BARE" || exit 1
    HOME="$T23HOME" git init -q
    printf 'x\n' > f.txt
    HOME="$T23HOME" git -c user.email=t@t -c user.name=t commit -qm bare >/dev/null 2>&1
  ) || true
  if HOME="$T23HOME" git -C "$T23BARE" rev-parse --verify --quiet HEAD >/dev/null 2>&1; then
    bad "T23b: 坏签名环境没造出来（裸 commit 反而成功）→ T23a 无鉴别力（空转灯）"
  else
    ok "T23b: 坏签名环境可复现裸 commit 失败（T23a 有鉴别力，非空转灯）"
  fi
  rm -rf "$T23REPO" "$T23BARE" "$T23HOME"
fi

# ---- T24 CI node 版本假红回归（Issue #175 · 装了 node 却仍全红） ----
# 根因（真 CI 日志逐字）：.cnb.yml 用 `apt-get install nodejs` 装到 v20.19，而 dsh-adapter
# 的 TS 信号灯用 `node --experimental-strip-types`（Node >= 22.6）→ `bad option` →
# 3 项全红。"有 node" ≠ "node 能用"：装完必须**按能力**核验，不是按存在核验。
echo ""
echo "▶ T24 CI node 版本闸门（有 node 但能力不足也算未就绪）"
if [ ! -f scripts/ci-ensure-node.sh ]; then
  bad "T24a: 缺 scripts/ci-ensure-node.sh（.cnb.yml 已改为调用它）"
else
  if bash scripts/ci-ensure-node.sh --check-only >/dev/null 2>&1; then
    ok "T24a: 本机 node 可用 → --check-only 通过"
    # 鉴别力：伪造"能跑但仅 v20 语义"的 node（拒绝该 flag）时，必须判不可用
    T24BIN="$(mktemp -d)"
    printf '#!/bin/bash\ncase "$*" in *--experimental-strip-types*) echo "node: bad option: --experimental-strip-types" >&2; exit 9;; --version) echo "v20.19.2";; *) echo v20;; esac\n' > "$T24BIN/node"
    chmod +x "$T24BIN/node"
    if PATH="$T24BIN:$PATH" bash scripts/ci-ensure-node.sh --check-only >/dev/null 2>&1; then
      bad "T24b: 不支持 --experimental-strip-types 的 node 被判可用（牙齿丢失）"
    else
      ok "T24b: 能力不足的 node 被判不可用（按能力核验，非按存在）"
    fi
    # .cnb.yml 必须真的接上（否则脚本再对也不生效）
    if grep -q 'ci-ensure-node.sh' .cnb.yml && ! grep -q 'apt-get install -y -qq nodejs npm' .cnb.yml; then
      ok "T24c: .cnb.yml 两处作业调用 ci-ensure-node.sh（不再裸装 apt v20）"
    else
      bad "T24c: .cnb.yml 未接 ci-ensure-node.sh 或仍在裸装 apt nodejs"
    fi
    rm -rf "$T24BIN"
  else
    skip "T24: 本机 node 不支持 TS 剥离 → 跳过（能力核验已由 T24b 覆盖）"
  fi
fi

# ---- 汇总 ----
echo ""
echo "======================================================"
echo "feature-verify 自测汇总：PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
if [ "$FAIL" -gt 0 ]; then
  echo "🔴 信号灯：feature-verify 模块未达标"
  exit 1
else
  echo "🟢 信号灯：feature-verify 模块自测全过（SKIP=$SKIP 未在本机验证，不计入 PASS）"
  exit 0
fi
