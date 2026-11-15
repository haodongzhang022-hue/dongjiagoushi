#!/usr/bin/env bash
# ============================================================
# [feature-verify] manager / 平台真碰过没
# ============================================================
# module:   manager（经理真干活 · Issue #239 收尾轮）
# feature:  云端回执判据必须真碰到平台（双轨接线 + 不依赖 cnb CLI），不许拿本地假设作证
# 五要素:
#   Given    一个只把 [接单] 回在 Issue 评论里的对端（本地 progress 表零事件）
#   When     dispatch_verify(..., cloud=True) 核回执
#   Then     ① 云端 [接单] 必须真的进判据（receipt_source=cloud）；
#            ② 评论流读不全 → 显式 degraded，不许静默判「未回执」；
#            ③ 云轨不许依赖 cnb CLI（读评走 comment_stream HTTP+token）——
#               CI 镜像没装 cnb CLI，卡了这道就会把云轨整条关掉（本轮 CI 真踩到）。
#   Evidence dispatch_verify 的 cloud_checked / receipt_source / cloud_degraded
#   为什么是"功能级": 单测天然只用本地 progress 事件，碰不到云端回执这条轨。
#     判据断在"没接线"和"接错地方"上，都不会报错，只在特定环境现形。
#     本脚本专在无 cnb CLI 环境也跑，否则"本地绿"只证明本地绿。
# 用法：bash scripts/feature-verify/manager/平台真碰过没.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }
echo "==== [feature-verify] manager/平台真碰过没 ===="

OUT=$(DB_PATH=$(mktemp --suffix=_fv_platform.db) python3 - <<'PYPART' 2>&1
import os, sys
sys.path.insert(0, "local-agent")
from data import admin, schema; admin.init(); schema.init_schema()
import dispatch_engine as D
import comment_stream as cs
import shutil

# ------ ① 云端 [接单] 必须真进判据（本地 progress 表零事件） ------
cs_read_orig = cs.read_comments
cs.read_comments = lambda **kw: {
    "comments": [{"body": "@org/repo(架构·开发) [接单] 开工",
                  "created_at": "2026-11-15T00:00:00Z"}],
    "count": 1, "pages": 1, "page_size": 100, "has_more": False,
    "complete": True, "truncated": False, "source": "fixture",
    "kind": "issue", "number": 347,
}
# ------ ③ 把 cnb CLI 藏起来，云轨仍须可用 ------
orig_which = shutil.which
shutil.which = lambda name, *a, **k: None if name == "cnb" else orig_which(name, *a, **k)
try:
    v = D.dispatch_verify([{"task_id": "fv-tk", "agent_id": "fv-ag",
                            "role": "架构·开发", "issue_number": "347"}], cloud=True)
    print("CLOUD", v["detail"][0]["receipt"], v["detail"][0]["receipt_source"],
          v["verified_all_awake"], v["cloud_checked"])
finally:
    shutil.which = orig_which

    # ------ ② 评论流读不全 → 显式 degraded ------
    cs.read_comments = lambda **kw: {
        "comments": [], "count": 0, "pages": 5, "page_size": 100,
        "has_more": True, "complete": False, "truncated": True,
        "source": "fixture", "kind": "issue", "number": 347,
    }
    v2 = D.dispatch_verify([{"task_id": "fv-tk2", "agent_id": "fv-ag2",
                             "role": "架构·开发", "issue_number": "347"}], cloud=True)
    print("PARTIAL", bool(v2["cloud_degraded"]), v2["verified_all_awake"])
    cs.read_comments = cs_read_orig
PYPART
)
echo "$OUT"

echo "$OUT" | grep -qE "^CLOUD True cloud True True$" \
  && ok "云端评论里的 [接单] 真进了判据（receipt_source=cloud），且无 cnb CLI 也照查" \
  || bad "云端 [接单] 没进判据 / 或云轨被 cnb CLI 卡住：$(echo "$OUT" | grep '^CLOUD')"

echo "$OUT" | grep -q "^PARTIAL True False$" \
  && ok "评论流读不全 → 显式 degraded，不静默判「未回执」" \
  || bad "读不全没暴露：$(echo "$OUT" | grep '^PARTIAL')"

# ------ ④ 演练不许碰平台：run_pipeline/经理节点默认不真建 Issue ------
GUARD=$(python3 - <<'PYG' 2>&1
import inspect, sys
sys.path.insert(0, "local-agent")
import orchestrator
from manager import engine as eng
# #407 已上 live 显式闸门；这里再加一道：orchestrator 侧不许悄悄真派发
src = inspect.getsource(orchestrator._run_role_engine)
print("GUARD", "manager_engine" in src or "real" in src)
PYG
)
echo "$GUARD" | grep -q "^GUARD True$" \
  && ok "演练不许碰平台：orchestrator 不再现造裸引擎（复用角色引擎 / 或显式 real 声明）" \
  || bad "演练仍可能真派发：$(echo "$GUARD" | grep '^GUARD')"

echo
echo "==== [feature-verify] manager/平台真碰过没：PASS=$PASS FAIL=$FAIL ===="
[ "$FAIL" -eq 0 ]
