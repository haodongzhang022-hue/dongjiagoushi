#!/usr/bin/env bash
# ============================================================
# [feature-verify] manager / 借人从名册派生
# ============================================================
# module:   manager（经理真干活 · Issue #239 收尾轮）
# feature:  跨岗借角色不写死「架构·开发」，从团队名册派生候选 + 按任务相关度排序
# 五要素:
#   Given    本岗位（架构·开发）接不住一条"需要评审"的任务
#   When     经理走启下手段 borrow_role（role 留空）
#   Then     候选来自 roles 名册且不含本岗；相关性最高的是「架构·评审」；
#            真解析出完整 @org/repo(角色) 再召唤（不是写死一个名字反复失败）
#   Evidence 借人结果里的 role/handle/candidates 字段 + manager_actions 留痕
#   为什么是"功能级": 单测只证明"调用了 HandleAbility"——写死角色名也照样能绿。
#     本脚本判的是"借的对象随任务与名册变化"。
# 用法：bash scripts/feature-verify/manager/借人从名册派生.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }
echo "==== [feature-verify] manager/借人从名册派生 ===="

OUT=$(DB_PATH=$(mktemp --suffix=_fv_borrow.db) python3 - <<'EOF' 2>&1
import sys
sys.path.insert(0, "local-agent")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine

m = ManagerEngine(repo="dongdongxiaozu/dongjiagoushi", dry_run=True)
cands = m.borrow_candidates(exclude=["架构·开发"], task="需要评审复评")
b = m.borrow_role("", task_key="t-borrow", task="需要评审复评", exclude=["架构·开发"])
print("CANDS", ",".join(cands[:3]))
print("PICK", b["role"], b["handle"], b["ok"])
EOF
)
echo "$OUT" | sed 's/^/      /'

if echo "$OUT" | grep -q "^CANDS 架构·评审"; then
  ok "候选来自名册、排除本岗、按相关度排序（评审任务先借评审）"
else
  bad "候选没有按名册/相关度派生"
fi
if echo "$OUT" | grep -qE "^PICK 架构·评审 @[^ ]+\(架构·评审\) True"; then
  ok "真解析完整 @ 格式并真召唤成功"
else
  bad "借人没拿到可用的 handle 或没召唤成功"
fi

echo ""
if [ "$FAIL" -gt 0 ]; then
  echo "🔴 manager/借人从名册派生 未达成 → 功能没做完"
  exit 1
else
  echo "🟢 manager/借人从名册派生 通过"
  exit 0
fi
