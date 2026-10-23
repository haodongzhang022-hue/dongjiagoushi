#!/usr/bin/env bash
# collect 附探查结论 信号灯（bridge.collect_cloud_result × entries.probe）
#
# 纪律：collect 在「没拿到确定状态」时**只给结论，不做动作**。
# 判据：verdict 必带 / auto_resent 恒 False / 开关可关 / 显式状态路径不变
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONIOENCODING=utf-8
unset BRIDGE_TRANSPORT BRIDGE_PROBE 2>/dev/null || true
pass=0; fail=0
ok(){ echo " ✅ $1"; pass=$((pass+1)); }
no(){ echo " ❌ $1"; [ -n "${2:-}" ] && echo "$2" | tail -5; fail=$((fail+1)); }
run(){ python3 - "$@" 2>&1; }

T1=$(run <<'PY'
import sys, os
sys.path.insert(0, ".")
os.environ.pop("BRIDGE_TRANSPORT", None); os.environ.pop("BRIDGE_PROBE", None)
import entries.bridge as b
h = b.request_cloud_dev("verdict 必带", entry="local")
c = b.collect_cloud_result(h["handle_id"])
assert c["ok"] is False, "mock 锚点不该判完成"
assert "verdict" in c, "pending 时必须附探查结论"
assert c["auto_resent"] is False, "绝不能自动重发"
print("ok")
PY
)
[ "$(echo "$T1" | tail -1)" = "ok" ] && ok "无确定状态时附 verdict 且 auto_resent=False" || no "附 verdict" "$T1"

T2=$(run <<'PY'
import sys, os
sys.path.insert(0, ".")
os.environ.pop("BRIDGE_TRANSPORT", None)
os.environ["BRIDGE_PROBE"] = "off"
import entries.bridge as b
h = b.request_cloud_dev("开关关闭", entry="local")
c = b.collect_cloud_result(h["handle_id"])
assert c["ok"] is False
assert c.get("verdict") is None, "关闭时不该探查"
print("ok")
PY
)
[ "$(echo "$T2" | tail -1)" = "ok" ] && ok "BRIDGE_PROBE=off 跳过探查" || no "探查开关" "$T2"

T3=$(run <<'PY'
import sys, os
sys.path.insert(0, ".")
os.environ.pop("BRIDGE_TRANSPORT", None); os.environ.pop("BRIDGE_PROBE", None)
import entries.bridge as b
h = b.request_cloud_dev("显式状态", entry="local")
c = b.collect_cloud_result(h["handle_id"], cloud_state="done")
assert c["ok"] is True
assert c["handle"]["cloud_result"]["state"] == "done"
print("ok")
PY
)
[ "$(echo "$T3" | tail -1)" = "ok" ] && ok "显式 cloud_state 路径不变（不跑探查）" || no "显式状态" "$T3"

T4=$(run <<'PY'
import sys, os
sys.path.insert(0, ".")
import entries.bridge as b
# 探查异常不得影响 collect 主流程
h = b.request_cloud_dev("探查异常兜底", entry="local")
orig = b._probe_verdict
b._probe_verdict = lambda handle, self_author=None: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    try:
        c = b.collect_cloud_result(h["handle_id"])
    except Exception as e:
        raise AssertionError(f"collect 被探查异常带崩：{e}")
finally:
    b._probe_verdict = orig
assert c["ok"] is False
print("ok")
PY
)
[ "$(echo "$T4" | tail -1)" = "ok" ] && ok "探查抛错不影响 collect（不崩）" || no "探查异常兜底" "$T4"

T5=$(run <<'PY'
import sys, os, inspect
sys.path.insert(0, ".")
import entries.bridge as b
src = inspect.getsource(b._probe_verdict)
# 结构性防呆：附结论的函数里不许有发送动作
for bad in ("post-issue-comment", "create-issue"):
    assert bad not in src, f"_probe_verdict 里出现发送动作：{bad}"
print("ok")
PY
)
[ "$(echo "$T5" | tail -1)" = "ok" ] && ok "附结论的函数不含发送动作（结构防呆）" || no "结构防呆" "$T5"

echo ""
echo "===== bridge.collect×probe 信号灯结果：$pass 通过 / $fail 失败 ====="
[ "$fail" -eq 0 ]
