#!/usr/bin/env bash
# ============================================================
# [feature-verify] manager / 平台激活不冒充
# ============================================================
# module:   manager（经理真干活 · Issue #239 五轮）
# feature:  经理「激活」口径三档分明：平台真建 Issue / 只本地登记 / 该建却没建成，
#           没写平台就不许说"平台激活"；真写平台必须显式开（不可逆副作用）。
# 五要素:
#   Given    一条计划（repo 探测得到，但没开 live）
#   When     经理 activate()/execute_plan() 跑一遍
#   Then     ① 状态是 local_only 而非 activated，platform_activated=0；
#            ② summary 说"平台真建 Issue 0/N"，不说"平台激活 N 条"；
#            ③ 真建成 Issue（假 CLI 返回 9001）才 platform_active=True；
#            ④ CNB_MANAGER_LIVE 未开时，有 repo 也不去写平台。
#   Evidence activate() 的 state/platform_activated/local_only + summary 文本
#   为什么是"功能级": 单测只断言"跑通了没报错"。上一版 `platform_active =
#     bool(issue_no) or self.dry_run` 在 dry_run 下恒 True，单测全绿而平台一条 Issue
#     都没有——判据自己在给自己作证。本脚本判的是"口径与事实是否一致"。
# 用法：bash scripts/feature-verify/manager/平台激活不冒充.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }
echo "==== [feature-verify] manager/平台激活不冒充 ===="

OUT=$(DB_PATH=$(mktemp --suffix=_fv_platform.db) python3 - <<'EOF' 2>&1
import os, sys
sys.path.insert(0, "local-agent")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine
import manager.engine as E

# ① 没开 live：有 repo 也不许写平台
m = ManagerEngine()
print("DRY", m.dry_run, "LIVE", m.live_requested, "REPO", bool(m.repo))
act = m.activate([{"task_key": "开发A", "title": "开发A", "role": "架构·开发",
                   "domain": "自检", "detail": "x"}])
rec = act["activated"][0]
print("STATE", rec["state"], "PLATFORM_ACTIVE", rec["platform_active"],
      "PLATFORM_ACTIVATED", act["platform_activated"], "LOCAL_ONLY", act["local_only"])
print("SUMMARY", m.execute_plan("1. 开发B", push=False, supervise=False)["summary"])

# ② 真建成才许说平台激活
class FakeRun:
    returncode = 0
    stdout = 'status: 201' + chr(10) + 'data:' + chr(10) + '  number: "9001"'
    stderr = ""
import dispatch_engine as D
orig = D.subprocess.run
D.subprocess.run = lambda *a, **k: FakeRun()
try:
    m2 = ManagerEngine(repo="org/repo", dry_run=False)
    act2 = m2.activate([{"task_key": "回归", "title": "回归任务（平台真建）",
                         "role": "架构·开发", "domain": "自检", "detail": "x"}])
    print("REAL_STATE", act2["activated"][0]["state"],
          "REAL_PLATFORM", act2["platform_activated"],
          "ISSUE", act2["activated"][0]["issue"])
finally:
    D.subprocess.run = orig
EOF
)
echo "$OUT" | sed 's/^/      /'

echo "$OUT" | grep -q "^DRY True LIVE False" \
  && ok "默认 dry_run + 未开 live（探测到仓库也不写平台）" \
  || bad "默认就放行写平台（不可逆副作用未加闸）"
echo "$OUT" | grep -q "^STATE local_only PLATFORM_ACTIVE False PLATFORM_ACTIVATED 0 LOCAL_ONLY 1" \
  && ok "没写平台 → local_only / platform_activated=0（不冒充平台激活）" \
  || bad "没写平台却被算成平台激活（口径自证）"
echo "$OUT" | grep -q "^SUMMARY .*平台真建 Issue 0/1" \
  && ok "summary 三档分明，说清「平台真建 0/1」" \
  || bad "summary 仍把本地登记说成平台激活"
echo "$OUT" | grep -q "^REAL_STATE activated REAL_PLATFORM 1 ISSUE 9001" \
  && ok "真建成 Issue → state=activated / platform_activated=1（判据只认 Issue 编号）" \
  || bad "建成 Issue 后仍未认作平台激活"

echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "  ✅ [manager] 平台激活不冒充 通过（功能完成）"; exit 0
fi
echo "  ❌ [feature-verify] manager/平台激活不冒充 失败：PASS=$PASS FAIL=$FAIL"; exit 1
