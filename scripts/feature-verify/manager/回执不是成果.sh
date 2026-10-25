#!/usr/bin/env bash
# ============================================================
# [feature-verify] manager / 回执不是成果
# ============================================================
# module:   manager（经理真干活 · Issue #239 收尾轮）
# feature:  判"干了"只看推进/交付成果；接单回执、以及派发方唤醒时带出的"开工"都不算
# 五要素:
#   Given    对端回执 + 派发方唤醒副产物 `work_started`，但没有任何推进刻度
#   When     经理 supervise 判这条任务的成色
#   Then     不得判 real（回执是动作、开工是动作，progressed/delivered 才是成果）
#   Evidence credential_of 分级 / verdict+reason / progress 事件序列
#   为什么是"功能级": 单测只看"有没回执"就绿——这正是 Issue #239 反复被抓的病灶。
# 用法：bash scripts/feature-verify/manager/回执不是成果.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }
echo "==== [feature-verify] manager/回执不是成果 ===="

OUT=$(DB_PATH=$(mktemp --suffix=_fv_recv.db) python3 - <<'EOF' 2>&1
import sys
sys.path.insert(0, "local-agent")
from data import admin, schema
admin.init(); schema.init_schema()
from manager import ManagerEngine

m = ManagerEngine(dry_run=True, simulate={"*": "accept"})
r = m.execute_plan("1. 开发登录模块", supervise=False)
v = m.supervise(r["activated"])["verdicts"][0]
print("VERDICT", v["verdict"], v["credential"])
print("REASON", v["reason"])
EOF
)
echo "$OUT" | sed 's/^/      /'

if echo "$OUT" | grep -qE "^VERDICT (fake|awaiting|stall) (simulated|none)"; then
  ok "只有回执/唤醒副产物 → 不判 real（回执不算成果）"
else
  bad "只有回执被判成了 real（这就是旧的假绿）"
fi
if echo "$OUT" | grep -qE "^REASON .*(假装|未落地|不算|停滞)"; then
  ok "判词与证据一致（明确说没成果，不含糊）"
else
  bad "判词与证据不一致"
fi

echo ""
if [ "$FAIL" -gt 0 ]; then
  echo "🔴 manager/回执不是成果 未达成 → 功能没做完"
  exit 1
else
  echo "🟢 manager/回执不是成果 通过"
  exit 0
fi
