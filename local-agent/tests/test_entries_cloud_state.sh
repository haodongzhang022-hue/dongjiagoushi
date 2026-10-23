#!/usr/bin/env bash
# 云端完成态自动判定 信号灯（entries.cloud_state · 补 bridge collect 的缺省 done 坑）
#
# 判据：三态分开（confirmed/pending/unknown）+ 自己发的卡不算回执 + 不默认 done
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONIOENCODING=utf-8
pass=0; fail=0
ok(){ echo " ✅ $1"; pass=$((pass+1)); }
no(){ echo " ❌ $1"; [ -n "${2:-}" ] && echo "$2" | tail -5; fail=$((fail+1)); }
run(){ python3 - "$@" 2>&1; }

T1=$(run <<'PY'
import sys
sys.path.insert(0, ".")
from entries.cloud_state import classify_comments
me, role = "me", "架构·开发"
card = {"id": "1", "author": me,
        "body": "[触发:架构·开发] @o/r(架构·开发) 任务 x 请回执 [接单]"}
r = classify_comments([card], role=role, self_author=me)
assert not r["receipts"], "假绿：把自己发的卡当回执"
assert len(r["cards"]) == 1
print("ok")
PY
)
[ "$(echo "$T1" | tail -1)" = "ok" ] && ok "自己发的派发卡不算回执（防假绿）" || no "派发卡不算回执" "$T1"

T2=$(run <<'PY'
import sys
sys.path.insert(0, ".")
from entries.cloud_state import classify_comments
me, role = "me", "架构·开发"
card = {"id": "1", "author": me, "body": "[触发:架构·开发] 请回执 [接单]"}
reply = {"id": "2", "author": "o/r(架构·开发)", "body": "[接单] 已接单"}
r = classify_comments([card, reply], role=role, self_author=me)
assert len(r["receipts"]) == 1, r
print("ok")
PY
)
[ "$(echo "$T2" | tail -1)" = "ok" ] && ok "有真回执则认到" || no "认真回执" "$T2"

T3=$(run <<'PY'
import sys
sys.path.insert(0, ".")
from entries.cloud_state import classify_comments
me, role = "me", "架构·开发"
card = {"id": "1", "author": me, "body": "[触发:架构·开发] 请回执 [接单]"}
# 真实回执常不重复角色名，不能因此漏判
reply = {"id": "2", "author": "o/r(架构·开发)", "body": "[接单] 已接单，但 need_fix"}
r = classify_comments([card, reply], role=role, self_author=me)
assert len(r["receipts"]) == 1, "角色名不该是硬门槛"
print("ok")
PY
)
[ "$(echo "$T3" | tail -1)" = "ok" ] && ok "回执不重复角色名也认（不作硬门槛）" || no "回执角色名门槛" "$T3"

T4=$(run <<'PY'
import sys
sys.path.insert(0, ".")
from entries.cloud_state import to_cloud_state_kw, CONFIRMED, PENDING, UNKNOWN
assert to_cloud_state_kw({"state": PENDING}) is None, "pending 不该产生状态"
assert to_cloud_state_kw({"state": UNKNOWN}) is None, "unknown 不该产生状态"
assert to_cloud_state_kw({"state": CONFIRMED, "label": {"labels": []},
                          "blocked": False}) == "done"
assert to_cloud_state_kw({"state": CONFIRMED, "label": {"labels": []},
                          "blocked": True}) == "need_fix"
print("ok")
PY
)
[ "$(echo "$T4" | tail -1)" = "ok" ] && ok "pending/unknown 不映射为完成（不默认 done）" || no "不默认 done" "$T4"

T5=$(run <<'PY'
import sys, os
sys.path.insert(0, ".")
os.environ.pop("BRIDGE_TRANSPORT", None)
import entries.bridge as b
h = b.request_cloud_dev("mock 句柄不应崩", entry="local")
c = b.collect_cloud_result(h["handle_id"])
assert c["ok"] is False, "mock/sim 锚点不该被当作完成"
assert "sim-issue" in str(c.get("probe")), "应显式说明锚点不是真实编号"
print("ok")
PY
)
[ "$(echo "$T5" | tail -1)" = "ok" ] && ok "mock 锚点（sim-issue）显式 unknown 不崩溃" || no "mock 锚点防御" "$T5"

T6=$(run <<'PY'
import sys, os
sys.path.insert(0, ".")
os.environ.pop("BRIDGE_TRANSPORT", None)
import entries.bridge as b
h = b.request_cloud_dev("显式状态兼容", entry="local")
c = b.collect_cloud_result(h["handle_id"], cloud_state="done")
assert c["ok"] is True
assert c["handle"]["cloud_result"]["state"] == "done"
print("ok")
PY
)
[ "$(echo "$T6" | tail -1)" = "ok" ] && ok "显式传 cloud_state 仍兼容（旧用法）" || no "显式状态兼容" "$T6"

echo ""
echo "===== entries.cloud_state 信号灯结果：$pass 通过 / $fail 失败 ====="
[ "$fail" -eq 0 ]
