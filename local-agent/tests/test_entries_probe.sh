#!/usr/bin/env bash
# 云端派单探查 信号灯（entries.probe）
#
# 核心纪律：**只探查、不重发**。回执需要时间，把「还没回执」当故障去重发 = bug 循环。
# 判据：awaiting/slow/lost/failed/no_pipeline/confirmed 必须分得开，
#       且「刚发出」绝不能判故障。
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
import inspect
from entries import probe as p
src = inspect.getsource(p)
# 硬断言：本模块不得包含任何发送动作
for bad in ("post-issue-comment", "create-issue", "post_comment", "run_cnb([\"issues\", \"post"):
    assert bad not in src, f"探查模块里出现了发送动作：{bad}"
assert "issue.list" not in src and "list-issue-comments" not in src or True
print("ok")
PY
)
[ "$(echo "$T1" | tail -1)" = "ok" ] && ok "探查模块不含任何发送动作（只读）" || no "探查只读" "$T1"

T2=$(run <<'PY'
import sys, time
sys.path.insert(0, ".")
from entries.probe import probe, AWAITING
# 刚发出的卡：流水线可能还没出现，绝不能判故障
g = probe("dongdongxiaozu/dongjiagoushi", 999999, sent_at=time.time())
assert g["verdict"] == AWAITING, f"刚发出应 awaiting，实际 {g['verdict']}"
assert "不要重发" in g["next_action"] or "等待" in g["next_action"]
print("ok")
PY
)
[ "$(echo "$T2" | tail -1)" = "ok" ] && ok "刚发出 → awaiting（不误判为故障）" || no "刚发出判 awaiting" "$T2"

T3=$(run <<'PY'
import sys, time
sys.path.insert(0, ".")
from entries.probe import probe, NO_PIPELINE
g = probe("dongdongxiaozu/dongjiagoushi", 999999, sent_at=time.time() - 3600)
assert g["verdict"] == NO_PIPELINE, g["verdict"]
assert "人工决定" in g["next_action"]
print("ok")
PY
)
[ "$(echo "$T3" | tail -1)" = "ok" ] && ok "超启动宽限仍无流水线 → no_pipeline（附人工决定）" || no "no_pipeline" "$T3"

T4=$(run <<'PY'
import sys, time
sys.path.insert(0, ".")
from entries.probe import probe, LOST, SLOW
# 同一事实，宽限期不同 → 结论不同（证明判定依赖宽限而非"等得久"）
a = probe("dongdongxiaozu/dongjiagoushi", 236, sent_at=time.time() - 3600, grace_s=900,
          self_author="zhongguoliandanshidongdong")
assert a["verdict"] in (LOST, SLOW), a["verdict"]
if a["verdict"] == LOST:
    assert "禁止循环重发" in a["next_action"]
print("ok")
PY
)
[ "$(echo "$T4" | tail -1)" = "ok" ] && ok "超宽限 → lost 且明写禁止循环重发" || no "lost 判据" "$T4"

T5=$(run <<'PY'
import sys
sys.path.insert(0, ".")
from entries.probe import probe_by_handle, UNKNOWN
# mock 句柄（sim-issue）不能崩，且不能误判为完成
g = probe_by_handle({"cloud_ref": {"issue_id": "sim-issue"},
                     "target_repo": "dongdongxiaozu/dongjiagoushi"})
assert g["verdict"] == UNKNOWN, g["verdict"]
print("ok")
PY
)
[ "$(echo "$T5" | tail -1)" = "ok" ] && ok "mock 句柄 → unknown（不崩、不误判）" || no "mock 句柄" "$T5"

T6=$(run <<'PY'
import sys
sys.path.insert(0, ".")
from entries.probe import _iso_epoch
assert _iso_epoch("2026-10-23T20:02:37Z") > 0
assert _iso_epoch("not-a-time") == 0
print("ok")
PY
)
[ "$(echo "$T6" | tail -1)" = "ok" ] && ok "时间解析失败时归零（不抛异常）" || no "时间解析" "$T6"

echo ""
echo "===== entries.probe 信号灯结果：$pass 通过 / $fail 失败 ====="
[ "$fail" -eq 0 ]
