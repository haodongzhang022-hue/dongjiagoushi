#!/usr/bin/env bash
# ============================================================
# [feature-verify] manager / 平台真碰过没
# ============================================================
# module:   manager（经理真干活 · Issue #239 收尾轮）
# feature:  「平台已激活」与「云端回执」两项判据必须真碰到平台，不许拿本地假设作证
# 五要素:
#   Given    ① 只注入云端真实变量（CNB_REPO_SLUG 等，**没有 CNB_REPO**）
#            ② 一个只回 [接单] 在 Issue 评论里的对端（本地 progress 表零事件）
#   When     经理 activate() 派一条任务 / dispatch_verify() 核回执
#   Then     ① repo 必须探测出来，dry_run 不许被静默置 True；
#            ② dry_run 下 platform_activated 必须为 0（本地登记不算已分工）；
#            ③ 真建出 Issue 才算 platform_activated=1；
#            ④ 云端 [接单] 必须真的进判据（receipt_source=cloud）；
#            ⑤ 评论流读不全 → 显式 degraded，不许静默判「未回执」。
#   Evidence activate() 返回的 state/platform_activated + dispatch_verify 的 receipt_source
#   为什么是"功能级": 单测全用 dry_run=True 跑，天然碰不到平台变量与平台回执。
#     这两条链断在"变量名认错"和"判据没接线"上，单测看不见，只有真环境会现形。
# 用法：bash scripts/feature-verify/manager/平台真碰过没.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }
echo "==== [feature-verify] manager/平台真碰过没 ===="

OUT=$(DB_PATH=$(mktemp --suffix=_fv_platform.db) python3 - <<'EOF' 2>&1
import os, sys, tempfile
sys.path.insert(0, "local-agent")
from data import admin, schema; admin.init(); schema.init_schema()

saved = {k: os.environ.get(k) for k in
         ("CNB_REPO", "CNB_REPO_SLUG", "CNB_GROUP_SLUG", "CNB_REPO_NAME")}

# ------ ① 云端只注入 CNB_REPO_SLUG 系列，没有 CNB_REPO ------
from manager import engine as eng
for k in saved:
    os.environ.pop(k, None)
os.environ["CNB_GROUP_SLUG"] = "someorg"
os.environ["CNB_REPO_NAME"] = "somerepo"
print("REPO", eng._detect_repo())

m = eng.ManagerEngine(dry_run=True)
r = m.activate([{"task_key": "探测任务", "title": "探测任务",
                 "role": "架构·开发", "domain": "自检", "detail": "x"}])
a = r["activated"][0]
print("DRYRUN", r["platform_activated"], a["state"], a["platform_active"], a["issue"])

# ------ ③ 真建出 Issue 才算平台激活 ------
orig_repo = os.environ.get("CNB_REPO")
class FakeRun:
    returncode = 0
    stdout = 'status: 201\ndata:\n  number: "999"\n'
    stderr = ""
import dispatch_engine as D
orig = D.subprocess.run
D.subprocess.run = lambda *a, **k: FakeRun()
try:
    m2 = eng.ManagerEngine(repo="org/repo", dry_run=False)
    r2 = m2.activate([{"task_key": "真建单", "title": "真建单",
                       "role": "架构·开发", "domain": "自检", "detail": "x"}])
    a2 = r2["activated"][0]
    print("REAL", r2["platform_activated"], a2["state"], a2["issue"])
finally:
    D.subprocess.run = orig

# ------ ④⑤ 云端 [接单] 必须真进判据；读不全必须 degraded ------
import comment_stream as cs
cs_read_orig = cs.read_comments
cs.read_comments = lambda **kw: {
    "comments": [{"body": "@org/repo(架构·开发) [接单] 开工",
                  "created_at": "2026-11-15T00:00:00Z"}],
    "count": 1, "pages": 1, "page_size": 100, "has_more": False,
    "complete": True, "truncated": False, "source": "fixture",
    "kind": "issue", "number": 347,
}
try:
    v = D.dispatch_verify([{"task_id": "fv-tk", "agent_id": "fv-ag",
                            "role": "架构·开发", "issue_number": "347"}], cloud=True)
    print("CLOUD", v["detail"][0]["receipt"], v["detail"][0]["receipt_source"],
          v["verified_all_awake"])

    cs.read_comments = lambda **kw: {
        "comments": [], "count": 0, "pages": 5, "page_size": 100,
        "has_more": True, "complete": False, "truncated": True,
        "source": "fixture", "kind": "issue", "number": 347,
    }
    v2 = D.dispatch_verify([{"task_id": "fv-tk2", "agent_id": "fv-ag2",
                             "role": "架构·开发", "issue_number": "347"}], cloud=True)
    print("PARTIAL", bool(v2["cloud_degraded"]), v2["verified_all_awake"])
finally:
    cs.read_comments = cs_read_orig
    for k, val in saved.items():
        if val is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = val
EOF
)
echo "$OUT"

echo "$OUT" | grep -q "^REPO someorg/somerepo$" \
  && ok "云端只注入 CNB_REPO_SLUG 系列也能探测到仓库（不靠不存在的 CNB_REPO）" \
  || bad "repo 探测没认对变量：$(echo "$OUT" | grep '^REPO')"

echo "$OUT" | grep -q "^DRYRUN 0 local_only False None$" \
  && ok "dry_run 未碰平台 → platform_activated=0 / local_only（本地登记 ≠ 已分工）" \
  || bad "dry_run 仍在冒充平台已激活：$(echo "$OUT" | grep '^DRYRUN')"

echo "$OUT" | grep -qE "^REAL 1 activated 999$" \
  && ok "真建出 Issue 才判 platform_activated=1（不误伤真激活）" \
  || bad "真激活口径不对：$(echo "$OUT" | grep '^REAL')"

echo "$OUT" | grep -q "^CLOUD True cloud True$" \
  && ok "云端评论里的 [接单] 真进了判据（receipt_source=cloud）" \
  || bad "云端 [接单] 没进判据：$(echo "$OUT" | grep '^CLOUD')"

echo "$OUT" | grep -q "^PARTIAL True False$" \
  && ok "评论流读不全 → 显式 degraded，不静默判「未回执」" \
  || bad "读不全没暴露：$(echo "$OUT" | grep '^PARTIAL')"

echo
echo "==== [feature-verify] manager/平台真碰过没：PASS=$PASS FAIL=$FAIL ===="
[ "$FAIL" -eq 0 ]
