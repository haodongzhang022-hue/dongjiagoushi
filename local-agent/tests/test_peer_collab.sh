#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 同岗位多角色交互机制（peer collab）功能测试
# 验证（对齐用户确立方向：非全员投票冗余，而是默认单兵+差异化补位+专家会诊+自动分形）：
#   ① cohort 同岗位编队：主战 + 差异化成员，稳定寻址二次取回同一 cohort
#   ② 触发时机门控：默认单兵 / 专长缺口·卡点·加量→补位 / 高风险·疑难·对错难辨→会诊
#   ③ 专家会诊：各自从专长角度给结论+留理由，收敛判定，未收敛→复评/上报
#   ④ 适配动态扩容：扩出的新 agent join_cohort 继承共享上下文并参与交互
#   ⑤ 自动分形：从串行 for 升级为小组内同岗 agent 真并行 + 互发消息
set -e
cd "$(dirname "$0")/.."
PY=python3

export DB_PATH="$(mktemp -d)/test_peer_collab.db"

echo "===== [peer] 1. cohort 同岗位编队 + 稳定寻址 ====="
$PY - <<'EOF'
from data import admin
from collab import peer
admin.init()
cid = peer.spawn_cohort("架构·开发", "dev-lead", size=3, mode="differentiated", req="支付模块")
v = peer.cohort_view(cid)
assert v["role"] == "架构·开发"
assert v["mode"] == "differentiated"
assert "dev-lead" in v["members"]
# 稳定寻址：二次 spawn 取回同一 cohort（不漂移）
cid2 = peer.spawn_cohort("架构·开发", "dev-lead", size=3, mode="differentiated")
assert cid == cid2, "二次触发应取回同一 cohort"
print("  ✅ cohort 编队 + 稳定寻址 通过")
EOF

echo "===== [peer] 2. 触发时机门控（默认单兵 / 补位 / 会诊） ====="
$PY - <<'EOF'
from data import admin
from collab import peer
admin.init()
cid = peer.spawn_cohort("架构·开发", "dev-lead", size=1, mode="differentiated")
# 默认无信号 → 单兵（防冗余，不无条件组队）
assert peer.decide_action(cid, [])["action"] == "single"
assert peer.decide_action(cid, [])["single"] is True
# 专长缺口 / 卡点 / 加量 → 补位
assert peer.decide_action(cid, ["skill_gap"])["action"] == "backup"
assert peer.decide_action(cid, ["stall"])["action"] == "backup"
assert peer.decide_action(cid, ["scale_up"])["action"] == "backup"
# 高风险 / 疑难 / 对错难辨 → 会诊
assert peer.decide_action(cid, ["high_risk"])["action"] == "consult"
assert peer.decide_action(cid, ["hard"])["action"] == "consult"
assert peer.decide_action(cid, ["dispute"])["action"] == "consult"
# 混合信号：会诊信号优先于补位信号
assert peer.decide_action(cid, ["stall", "hard"])["action"] == "consult"
print("  ✅ 触发时机门控 通过")
EOF

echo "===== [peer] 3. 专家会诊（各自专长结论+留理由，收敛判定） ====="
$PY - <<'EOF'
from data import admin
from collab import peer
admin.init()
cid = peer.spawn_cohort("架构·评审", "rev-lead", size=3, mode="consult", req="评审多端方案")
peer.join_cohort(cid, "rev-sec", specialty="安全向")
res = peer.expert_consult(cid, "多端登录安全与易用性取舍")
assert res["action"] == "consult"
assert len(res["opinions"]) == 2
# 每个会诊成员都留了专长视角的 verdict + reason
for o in res["opinions"]:
    assert "specialty" in o and "verdict" in o and "reason" in o
# 未收敛的会诊提供可判定摘要（复评/上报依据，而非终局）
assert "summary" in res
print("  ✅ 专家会诊 通过")
EOF

echo "===== [peer] 4. 适配动态扩容（join_cohort 继承共享上下文） ====="
$PY - <<'EOF'
from data import admin
from collab import peer
admin.init()
cid = peer.spawn_cohort("架构·开发", "dev-lead", size=2, mode="differentiated", req="报表")
v0 = peer.cohort_view(cid)
assert v0["size"] == 1  # 初始仅主战 1 人
# 动态扩增：按负载扩容出来的新 agent 加入 cohort
peer.join_cohort(cid, "dev-extra-1")
peer.join_cohort(cid, "dev-extra-2")
v1 = peer.cohort_view(cid)
assert v1["size"] == 3
assert "dev-extra-1" in v1["members"] and "dev-extra-2" in v1["members"]
# 扩出的 agent 获得差异化专长（不重复占用已有专长）
specs = {m["specialty"] for m in v1["members"].values()}
assert len(specs) == len(v1["members"]), "扩容 agent 应差异化分配专长"
print("  ✅ 适配动态扩容 通过")
EOF

echo "===== [peer] 5. 自动分形 + 小组内同岗真并行 + 互发消息 ====="
$PY - <<'EOF'
from data import admin
from collab import peer
admin.init()
af = peer.auto_fractal(["t1","t2","t3","t4","t5"], max_per_team=3, role="架构·开发")
assert af["plan"]["scaled"] is True
assert len(af["cohorts"]) == af["plan"]["team_count"] > 1
# 小组内多 agent 真并行执行，各自产出不同专长切面
cid = af["cohorts"]["team0"]
peer.join_cohort(cid, "team0-dev2", specialty="工程向")
peer.join_cohort(cid, "team0-dev3", specialty="安全向")
out = peer.team_parallel_execute(
    cid, ["登录","支付","权限"],
    lambda aid, task, fb: f"{aid} 完成 {task}"
)
assert set(out.keys()) == {"架构·开发-team0-lead", "team0-dev2", "team0-dev3"}
assert all("完成" in v for v in out.values())
# cohort 消息交互留痕递增
assert peer.cohort_view(cid)["messages"] > 0
print("  ✅ 自动分形 + 同岗并行 + 互发消息 通过")
EOF

echo "===== [peer] 6. 规模预设 collab_plan → peer 协作模式映射 ====="
$PY - <<'EOF'
from data import admin
from collab import peer
admin.init()
assert peer.collab_mode_from_plan("single") == "single"
assert peer.collab_mode_from_plan("single_plus_relay") == "differentiated"
assert peer.collab_mode_from_plan("differentiated_cohort") == "differentiated"
assert peer.collab_mode_from_plan("company_multi_dept") == "consult"
assert peer.collab_mode_from_plan("unknown") == "single"
print("  ✅ 规模预设 collab_plan → peer 模式 通过")
EOF

echo "===== [peer] 7. 接入 DAG 流水线（分形开发走同岗协作） ====="
$PY - <<'EOF'
from data import admin
admin.init()
import orchestrator
report = orchestrator.run_pipeline(
    "1. 实现登录 2. 实现支付 3. 实现报表 4. 实现通知 5. 实现权限 6. 实现日志",
    backend="mock", use_dag=True,
)
dev_step = next(s for s in report["steps"] if s["role"] == "架构·开发")
assert "分形计划" in dev_step["output"], "分形开发应产出分形计划"
assert "小组" in dev_step["output"]
print("  ✅ DAG 流水线分形开发接入同岗协作 通过")
EOF

echo "===== [peer] 同岗位多角色交互机制 全部通过 ✅ ====="
