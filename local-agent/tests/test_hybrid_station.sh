#!/usr/bin/env bash
# ============================================================
# 站点锚定模型测试（test_hybrid_station · Issue #90 M1-M3）
# ============================================================
# 验证「地铁站点模型」云端-本地协同的站点锚定语义（本地先行落地）：
#   M1 station  ：站点登记（cloud/local 各执一份版本基准）
#   M2 anchor   ：版本锚定（锚定 git commit，anti-drift）
#   M3 replay   ：迁移重放（两站点漂移 → 产重放计划 / 演练 apply）
#   M4 build-cache 联动：站点级缓存键随锚点变化（天然失效）
#   M5 review-gate：评审闸门 ≤5 轮熔断 → 人类 ⏸CP3 拍板
#
# 运行：bash local-agent/tests/test_hybrid_station.sh
# 预期：PASS≥18 FAIL=0（独立信号灯，不依赖其他模块）
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi; }

echo "== 站点锚定模型（M1-M3 + M4缓存联动 + M5评审闸门） =="

# 临时工作目录隔离锚点文件
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export STATION_ANCHOR_FILE="$WORK/anchors.json"

R=$(python3 - "$WORK" << 'PY'
import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), "local-agent"))
import hybrid.station as st
st.ANCHOR_FILE = os.path.join(sys.argv[1], "anchors.json")  # 隔离锚点文件
from hybrid.station import StationAnchor
a = StationAnchor(st.ANCHOR_FILE)

# M1 站点登记
a.register_station("local", "main", "aaa111", tag="v1", note="local base")
a.register_station("cloud", "main", "bbb222", tag="v1", note="cloud base")
stations = sorted(a.list_stations().keys())

# M2 锚定（手动指定 commit，可离线验证）
anc = a.anchor("local", branch="main", commit="ccc333", tag="v2", note="rebase anchor")
anc_commit = anc["commit"]

# M3 漂移判定 + 重放计划
# 让 cloud 站点锚定到更晚时点（源更新 → 目标 local 落后 → behind）
a.anchor("cloud", branch="main", commit="bbb222", tag="v2")
plan = a.replay_plan("cloud", "local")          # cloud 更新 vs local=ccc333 → drift
plan_status = plan["status"]
plan_drift = plan["drift"]
apply = a.replay_apply("cloud", "local", dry=True)
apply_status = apply.get("status", "?")
apply_applied = apply.get("applied", "?")

# M4 build-cache 联动（锚点不同 → 缓存键不同）
k1 = a.build_cache_key("local")
k2 = a.build_cache_key("local")
key_same = "same" if k1 == k2 else "diff"      # 同一锚点 → 键一致
a.anchor("local", branch="main", commit="ddd444")
k3 = a.build_cache_key("local")
key_changed = "changed" if k3 != k1 else "same"  # 锚点变 → 键变（缓存失效）

# M5 评审闸门
g1 = a.review_round("local", "fix_bug")
g1_fused = g1["fused"]
for _ in range(4):
    a.review_round("local", "fix_bug")
g5 = a.review_round("local", "fix_bug")       # 第 5 轮（熔断阈值）
g5_fused = g5["fused"]
g5_gate = g5["gate"]
g6 = a.review_round("local", "fix_bug")       # 超限仍熔断
g6_fused = g6["fused"]
reset = a.review_reset("local")
reset_gate = reset["gate"]

# 一次性输出，用 | 分隔便于 bash 断言
print("|".join([
    ",".join(stations),
    anc_commit, plan_status, str(plan_drift),
    apply_status, str(apply_applied),
    key_same, key_changed,
    str(g1_fused), str(g5_fused), g5_gate, str(g6_fused), reset_gate,
]))
PY
)

IFS='|' read -r STATIONS ANC_COMMIT PLAN_STATUS PLAN_DRIFT APPLY_STATUS APPLY_APPLIED KEY_SAME KEY_CHANGED G1F G5F G5G G6F RESETG <<< "$R"

echo "== M1 station 站点登记 =="
check "登记 cloud+local 两站点" "$STATIONS" "cloud,local"

echo "== M2 anchor 版本锚定 =="
check "锚定 commit 落库" "$ANC_COMMIT" "ccc333"

echo "== M3 replay 迁移重放 =="
# cloud(bbb222) 与 local(ccc333) 锚点不同 → drift=True
check "检测站点漂移" "$PLAN_DRIFT" "True"
check "重放计划状态(behind)" "$PLAN_STATUS" "behind"
check "重放 dry-run 演练不真改" "$APPLY_APPLIED" "False"

echo "== M4 build-cache 联动 =="
check "同锚点缓存键一致" "$KEY_SAME" "same"
check "锚点变缓存键变(失效)" "$KEY_CHANGED" "changed"

echo "== M5 review-gate 评审闸门 =="
check "首轮不熔断" "$G1F" "False"
check "第5轮熔断" "$G5F" "True"
check "熔断闸门=人类CP3" "$G5G" "human_cp3"
check "超限仍熔断" "$G6F" "True"
check "通过后复位=open" "$RESETG" "open"

echo ""
echo "== 结果 =="
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ] || exit 1
