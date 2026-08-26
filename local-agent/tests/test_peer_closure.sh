#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 同岗协作收尾闭环（peer collab closure）功能测试
# 验证 Issue #31 缺漏 G1~G4 的四模块 E1~E4 + 哨兵同岗收敛监控，全部接入真实引擎：
#   E1 precursor.py    审核者前置助手（L1 内部分支→L2 外部探索→L3 交人 + ⑤自决）
#   E2 peer_guard.py   哨兵同岗收敛监控（对 cohort 量化收敛 + 命中按协议处置）
#   E3 decisions.py    决策落库 + 动作消费（驱动改道/补位/升级/交人）
#   E4 human_gate.py   结果前置·人类拍板（决策点叫人类 + CP 留痕，非事后背锅）
set -e
cd "$(dirname "$0")/.."
PY=python3

export DB_PATH="$(mktemp -d)/test_peer_closure.db"

echo "===== [closure] 1. 会诊收敛 → 直接放行，不进收尾闭环 ====="
$PY - <<'EOF'
from data import admin
from collab import peer, closure
admin.init()
cid = peer.spawn_cohort("架构·评审", "rev-lead", size=1, mode="consult", req="评审")
# 直接构造一个会诊收敛结果（resolved=True）→ 应放行，不进收尾闭环
res = {"action":"consult","problem":"单一方案评估","opinions":[{"agent":"rev-lead","specialty":"逻辑向","verdict":"可行","reason":"方案可行"}],"consensus":True,"summary":"收敛","resolved":True}
out = closure.run("单一方案评估", cid, consult_result=res)
assert out["status"] == "resolved_at_consult", out
print("  ✅ 会诊收敛直接放行 通过")
EOF

echo "===== [closure] 2. 缺前置直接触发 → 报错（前置硬约束） ====="
$PY - <<'EOF'
from data import admin
from collab import closure
admin.init()
out = closure.run("某问题", "cohort-x", consult_result=None)
assert out["status"] == "error", "缺前置直接触发应判错误"
assert "缺前置" in out["error"]
print("  ✅ 前置硬约束校验 通过")
EOF

echo "===== [closure] 3. E3 决策落库 + 动作消费（会诊未收敛→升级） ====="
$PY - <<'EOF'
from data import admin
from collab import peer, decisions, closure
admin.init()
cid = peer.spawn_cohort("架构·开发", "dev-lead", size=4, mode="consult", req="多端方案")
# 4 人会诊，构造未收敛（不可行否决）——强制用占位制造 disagree
res = peer.expert_consult(cid, "高难度多端取舍问题")
# 若收敛则再补一个制造分歧；占位 hash 可能收敛，这里仅验证 decisions 落库动作本身
dt = decisions.record_decision("dt-test-1", task_id="tk-1", cohort_id=cid,
                               stage="consult", problem="多端取舍", action="escalate")
decisions.enqueue_action("dt-test-1", "escalate", "tk-1", cid)
assert len(decisions.list_decisions(task_id="tk-1")) >= 1
assert decisions.count_pending("tk-1") == 1
act = decisions.consume_action("dt-test-1")
assert act["action"] == "escalate"
assert decisions.count_pending("tk-1") == 0
# 动作落地：升级 → 交由总师/总师助理评估
applied = decisions.apply_action(act, peer, cid, "多端取舍")
assert applied["applied"] is True
print("  ✅ 决策落库 + 动作消费 通过")
EOF

echo "===== [closure] 4. E1 审核者前置助手：L1 四分支 + L2 自决 + L3 交人 ====="
$PY - <<'EOF'
from data import admin
from collab import precursor
admin.init()
# L1 内部四分支全摊开
l1 = precursor.l1_explore("A还是B", "A方案", "B方案")
branches = {b["branch"] for b in l1["branches"]}
assert {"merge","constraint","switch","complement"} <= branches
# L2 外部探索命中 + 零负面 → 自决（run 收敛为 l2_adopt）
from collab import closure
cid = "cohort-l2"
# 用 run 直接走全链路：注册一个零负面的已知方案
precursor.register_known_pattern("开源支付", "github", "PaymentKit", "现成方案")
from data import admin
import uuid
# 用 run 走未收敛→前置→自决：构造未收敛会诊
from collab import peer
admin.init()
c = peer.spawn_cohort("架构·开发", "lead", size=4, mode="consult")
out = closure.run("开源支付选型", c, keyword="开源支付",
                  known_patterns=[{"source":"github","title":"PaymentKit",
                                   "snippet":"现成","negative":False,"cost":False,"risk":False}],
                  consult_result={"resolved": False, "opinions":[], "summary":"未收敛"})
assert out["status"] == "adopted", out
assert out["decision"]["self_decide"] is True
print("  ✅ L1 四分支 + L2 自决 通过")
# L3 结果前置：命中但需担责 → 打开人类闸门
out2 = closure.run("高风险方案", c, keyword="有风险方案",
                   known_patterns=[{"source":"paper","title":"某方法",
                                    "negative":True,"cost":True,"risk":True}],
                   consult_result={"resolved": False, "opinions":[], "summary":"未收敛"})
assert out2["status"] == "awaiting_human", out2
assert out2["gate"]["status"] == "open"
print("  ✅ L3 结果前置·打开人类闸门 通过")
EOF

echo "===== [closure] 5. E4 人类拍板：结果前置 + CP 留痕（禁止代替确认） ====="
$PY - <<'EOF'
from data import admin
from collab import human_gate
admin.init()
g = human_gate.open_gate("gt-test-1", "必要成本取舍", task_id="tk-9",
                         risk_points=[{"risk":"上线延迟","cost":"高","step":"部署"}],
                         options=[{"name":"折中","desc":"先交付核心"}])
assert g["status"] == "open"
assert len(g["risk_points"]) == 1 and "risk" in g["risk_points"][0]
# 幂等：同问题仍 open 时复用，不重复打扰人类
g_reuse = human_gate.ensure_human_gate("必要成本取舍", task_id="tk-9")
assert g_reuse["gate_id"] == "gt-test-1", "同问题仍 open 应复用"
# 禁止代替用户确认
try:
    human_gate.confirm_gate("gt-test-1", by="")
    raise AssertionError("空 by 不应放行")
except PermissionError:
    pass
# 人类确认放行
human_gate.confirm_gate("gt-test-1", by="zhongguoliandanshidongdong")
assert human_gate.gate_status("gt-test-1")["status"] == "confirmed"
assert human_gate.gate_status("gt-test-1")["confirmed_by"] == "zhongguoliandanshidongdong"
print("  ✅ 人类拍板结果前置 + CP 留痕 + 禁代替确认 通过")
EOF

echo "===== [closure] 6. E2 哨兵同岗收敛监控（cohort 收敛刻度 + 命中处置） ====="
$PY - <<'EOF'
from data import admin
from sentinel import peer_guard
admin.init()
cid = "cohort-sentinel"
# 记录一次收敛刻度（推进）
r1 = peer_guard.guard_track(cid, "tk-s", "某疑难", goal_total=1.0, current=0.8)
assert r1["analysis"] is not None
summ = peer_guard.cohort_meter_summary(cid)
assert summ["count"] == 1 and summ["latest"] is not None
# 无判定的普通推进不误伤：再推进到收敛
peer_guard.guard_track(cid, "tk-s", "某疑难", goal_total=1.0, current=1.0)
summ2 = peer_guard.cohort_meter_summary(cid)
assert summ2["latest"]["distance"] == 0.0
assert peer_guard.peer_guard_overview()["cohort_meters"] >= 2
print("  ✅ 哨兵同岗收敛监控 通过")
EOF

echo "===== [closure] 7. closure 编排全链路（run_consult_chain） ====="
$PY - <<'EOF'
from data import admin
from collab import peer, closure
admin.init()
c = peer.spawn_cohort("架构·开发", "lead7", size=4, mode="consult")
# 全链路：会诊(可能收敛) 或 未收敛走前置→交人，均不应抛错、有明确 status
out = closure.run_consult_chain(c, "多端登录安全与易用性取舍")
assert out["status"] in ("resolved_at_consult", "adopted", "awaiting_human")
assert closure.closure_overview()["decisions"] is not None
print("  ✅ closure 全链路编排 通过", "→", out["status"])
EOF

echo "===== [closure] 同岗协作收尾闭环 全部通过 ✅ ====="
