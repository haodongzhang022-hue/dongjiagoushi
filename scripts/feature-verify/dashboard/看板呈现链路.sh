#!/usr/bin/env bash
# ============================================================
# [feature-verify] dashboard / 看板呈现链路（人类俯瞰二级信息）
# ============================================================
# module:  dashboard（看板生成）
# feature: 看板呈现——模块版本演进看板真实产出、内容带真实语义
# 五要素:
#   Given   dashboard 生成能力（scripts/generate-dashboard.py + 已提交 docs/DASHBOARD.md）
#   When    校验看板产出物是否真实落地
#   Then    docs/DASHBOARD.md 必须存在且含「模块版本演进看板 / 里程碑表 / Issue 声明汇总表」；
#           看板内模块演进行必须真实可解析（至少一个 `### 模块 ` 演进块），
#           证明这是"内容化呈现"而非"空文件/占位"。
#   Evidence docs/DASHBOARD.md 中可 grep 到的语义结构行（机器可判产物）
# 为什么是"功能级"：纯断言"文件存在"抓不出"看板内容是空壳"——本脚本校验的是
#   看板呈现的【可感知语义内容】（演进看板/里程碑/声明汇总都真的在），
#   文件在但缺语义段 = 看板呈现功能没做完，脚本红。
# 用法：bash scripts/feature-verify/dashboard/看板呈现链路.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }

echo "==== [feature-verify] dashboard/看板呈现链路 ===="

DF="docs/DASHBOARD.md"
if [ ! -f "$DF" ]; then
  bad "docs/DASHBOARD.md 缺失 → 看板呈现功能未产出（连文件都没有）"
  echo "🔴 dashboard/看板呈现链路 未达成"
  exit 1
else
  ok "docs/DASHBOARD.md 存在"
fi

# Then: 语义段必须都在（缺任一 = 看板是空壳/半成品 → 功能没做完）
for seg in "模块版本演进看板" "里程碑表" "Issue 声明汇总表"; do
  if grep -qF "$seg" "$DF"; then
    ok "看板含「$seg」语义段"
  else
    bad "看板缺「$seg」语义段 → 看板呈现不完整"
  fi
done

# Then: 至少一个真实模块演进块头 `### 模块 ` ——证明演进线真的落进去了
# 用单引号固定 grep 模式，避免反引号被当作命令替换（grep -F 精确匹配）。
NMOD="$(grep -cF '### 模块 ' "$DF" 2>/dev/null || echo 0)"
if [ "${NMOD:-0}" -ge 1 ] 2>/dev/null; then
  ok "看板含 $NMOD 个真实模块演进块（内容化呈现）"
else
  bad "看板无任何模块演进块头 → 演进线未落，仅空壳"
fi

# Then: 里程碑表有 M 系列里程碑行（呈现具备可俯瞰信息）
if grep -qE '^\|?\s*M[0-9]' "$DF" 2>/dev/null || grep -qF "M8" "$DF"; then
  ok "里程碑表含 M 系列里程碑行"
else
  bad "里程碑表缺 M 系列内容 → 看板里程碑未呈现"
fi

echo ""
if [ "$FAIL" -gt 0 ]; then
  echo "🔴 dashboard/看板呈现链路 未达成（存在缺段）→ 看板功能没做完"
  exit 1
else
  echo "🟢 dashboard/看板呈现链路 通过（语义段齐备，呈现功能完成）"
  exit 0
fi
