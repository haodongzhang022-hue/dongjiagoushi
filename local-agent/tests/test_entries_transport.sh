#!/usr/bin/env bash
# 真实传输层 / 真实本地执行器 信号灯（entries.transport · Issue #105 三.6 欠债补齐）
#
# 判据：mock 不被破坏 + 真实通道可解析 + 拿不到回执就失败（不伪造成功）+ 执行器真跑
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONIOENCODING=utf-8
pass=0; fail=0
ok(){ echo " ✅ $1"; pass=$((pass+1)); }
no(){ echo " ❌ $1"; [ -n "${2:-}" ] && echo "$2" | tail -5; fail=$((fail+1)); }
run(){ python3 - "$@" 2>&1; }

T1=$(run <<'PY'
import sys, os
sys.path.insert(0, ".")
for k in ("BRIDGE_TRANSPORT", "BRIDGE_LOCAL_EXEC"):
    os.environ.pop(k, None)
import entries.bridge as b
h = b.request_cloud_dev("默认传输回归", entry="local")
assert h.get("real_send") is False, "默认必须是 mock"
assert h.get("transport_name") == "mock"
print("ok")
PY
)
[ "$(echo "$T1" | tail -1)" = "ok" ] && ok "默认仍走 mock（不联网）" || no "默认仍走 mock（不联网）" "$T1"

T2=$(run <<'PY'
import sys
sys.path.insert(0, ".")
from entries.transport import resolve_cnb_launcher
l = resolve_cnb_launcher()
assert l, "解析不到 cnb CLI"
assert len(l) >= 2 and l[-1].endswith("cnb.js"), f"期望 node+cnb.js，实际 {l}"
print("ok")
PY
)
[ "$(echo "$T2" | tail -1)" = "ok" ] && ok "cnb 启动器解析为 node+cnb.js（Windows 不静默失败）" || no "cnb 启动器解析" "$T2"

T3=$(run <<'PY'
import sys
sys.path.insert(0, ".")
from entries.transport import CnbTransport
h = {"handle_id": "tk-x", "req": "dry-run", "entry": "local", "issue_id": ""}
out = CnbTransport("dongdongxiaozu/dongjiagoushi", dry_run=True).send(h)
assert out["cloud_ref"]["issue_id"] == "", "dry-run 不该产生编号"
assert "dry-run" in str(out["cloud_ref"].get("sent_via")), "dry-run 应显式标注"
print("ok")
PY
)
[ "$(echo "$T3" | tail -1)" = "ok" ] && ok "dry-run 不伪造云端编号" || no "dry-run 不伪造云端编号" "$T3"

T4=$(run <<'PY'
import sys
sys.path.insert(0, ".")
import entries.bridge as b
class NoSend:
    name = "broken"
h = b.request_cloud_dev("失败路径", entry="local", transport=NoSend())
assert h["status"] == "pending", f"无 send 时应停留在 pending，实际 {h['status']}"
assert h.get("send_error"), "必须记录 send_error，不能静默成功"
assert h.get("real_send") is False
print("ok")
PY
)
[ "$(echo "$T4" | tail -1)" = "ok" ] && ok "传输失败显式留痕（不假装已投递）" || no "传输失败显式留痕" "$T4"

T5=$(run <<'PY'
import sys, os
sys.path.insert(0, ".")
os.environ["BRIDGE_LOCAL_EXEC"] = "shell"
import entries.bridge as b
h = b.request_cloud_dev("执行器契约", entry="local")
plan = b.local_test_first(h["handle_id"], test_scripts=["test_bridge_loop.sh"])
ex = plan["executor"]
assert isinstance(ex, dict), "executor 必须是 dict 契约（消费方用 .get）"
assert callable(ex.get("run"))
print("ok")
PY
)
[ "$(echo "$T5" | tail -1)" = "ok" ] && ok "executor 遵守 dict 契约" || no "executor 遵守 dict 契约" "$T5"

T6=$(run <<'PY'
import sys, os
sys.path.insert(0, ".")
from entries.transport import resolve_bash
b = resolve_bash()
low = b.lower()
assert "system32" not in low, f"选中了 WSL bash（会吃反斜杠）：{b}"
print("ok")
PY
)
[ "$(echo "$T6" | tail -1)" = "ok" ] && ok "bash 优先 Git Bash（不吃 Windows 反斜杠）" || no "bash 选择" "$T6"

T7=$(run <<'PY'
import sys, os
sys.path.insert(0, ".")
os.environ["BRIDGE_LOCAL_EXEC"] = "shell"
import entries.bridge as b
h = b.request_cloud_dev("真实执行器", entry="local")
plan = b.local_test_first(h["handle_id"], test_scripts=["test_bridge_loop.sh"])
res = plan["executor"]["run"](plan["routed_local"])
assert res["mode"] == "shell", res
assert res["executed"][0]["rc"] == 0, res["executed"][0]
print("ok")
PY
)
[ "$(echo "$T7" | tail -1)" = "ok" ] && ok "本地测试真跑（rc=0 而不是 mock）" || no "本地测试真跑" "$T7"

echo ""
echo "===== entries.transport 信号灯结果：$pass 通过 / $fail 失败 ====="
[ "$fail" -eq 0 ]
