#!/usr/bin/env bash
# ============================================================
# [feature-verify] manager / 证据不认模拟器
# ============================================================
# module:   manager（经理/小组长真干活 · Issue #239）
# feature:  派发"安排成功"的判据是承接方真上工，演练/模拟回执不算干活
# 五要素:
#   Given    一个能"只回执不开工"的演练承接方（simulate=accept）
#   When     经理 execute_plan 派一条任务并监督结果
#   Then     该任务证据必须分级为 simulated 且**不判 real**（credential_ready=False）
#            换成真承接方（RoleWorkFace 写 progress 事件 + goal_meters）后必须判 real
#   Evidence manager_actions / progress 事件 / goal_meters / credential_of 分级结果
#   为什么是"功能级": 纯单测只要"回执存在"就能绿——绿的其实是模拟器。
#     本脚本判的是"证据来源分级"，模拟器全绿也会被这条拦死。
# 用法：bash scripts/feature-verify/manager/证据不认模拟器.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }
echo "==== [feature-verify] manager/证据不认模拟器 ===="

OUT=$(DB_PATH=$(mktemp --suffix=_fv_mgr.db) python3 - <<'EOF' 2>&1
import sys
sys.path.insert(0, "local-agent")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine
from manager.work import RoleWorkFace, WorkerRegistry

m = ManagerEngine(dry_run=True, simulate={"*": "accept"})
v = m.execute_plan("1. 开发登录模块")["supervise"]["verdicts"][0]
print("SIM", v["credential"], v["verdict"], v["credential_ready"])

reg = WorkerRegistry().register("架构·开发",
                                RoleWorkFace(role="架构·开发", agent_id="ag-real"))
m2 = ManagerEngine(dry_run=True, workers=reg)
v2 = m2.execute_plan("1. 开发登录模块")["supervise"]["verdicts"][0]
print("REAL", v2["credential"], v2["verdict"], v2["credential_ready"])
EOF
)
echo "$OUT" | sed 's/^/      /'

if echo "$OUT" | grep -q "^SIM simulated fake False"; then
  ok "演练回执判 simulated / 不判 real（绿的不能是模拟器）"
else
  bad "演练回执被当成干活（模拟器绿 = 假绿）"
fi
if echo "$OUT" | grep -qE "^REAL (role|external) real True"; then
  ok "真承接方上工 → 判 real（role/external 凭据）"
else
  bad "真承接方上工未被判 real"
fi

echo ""
if [ "$FAIL" -gt 0 ]; then
  echo "🔴 manager/证据不认模拟器 未达成 → 功能没做完"
  exit 1
else
  echo "🟢 manager/证据不认模拟器 通过"
  exit 0
fi
