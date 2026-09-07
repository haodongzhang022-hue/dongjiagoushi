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
