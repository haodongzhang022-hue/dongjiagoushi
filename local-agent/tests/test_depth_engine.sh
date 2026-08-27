#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 七层协作深度引擎（DepthEngine · L1→L7）测试（信号灯）
# ============================================================
# 验证用户 Issue #47 核心诉求：
#   1. 七层深度阶梯（L1表述→L2任务对接→L3开工·路由真实唤醒→L4成果交互→
#      L5进度可控·自动规则→L6持续到结果→L7全自动到结果）可执行
#   2. **路由真实唤醒**：awake() 校验目标 agent 是否真回执 [接单]——解决"只描述没唤醒"
#   3. 防跳层：某层操作前须先完成前置深度，不跳层空谈
#   4. 全员挂载：所有角色默认具备七层深度能力
#   5. 秘书目标档位 L6 / 体系目标档位 L7
#   6. 自动化规则维持流程（auto_guard：收敛/超时重触发/停滞升级）
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_depth_engine.db"

echo "===== [depth] 1. 全员挂载七层深度能力（任意角色直接调用） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import ROLE_REGISTRY, get_role

roles = list(ROLE_REGISTRY.keys())
assert len(roles) >= 15, f"应有较多角色，实际 {len(roles)}"
for name in roles:
    role = get_role(name)
    assert role is not None, f"{name} 应可实例化"
    # 七层深度能力全接口
    for m in ["express", "connect", "awake", "ack_wake", "start_work",
              "interact", "track_round", "auto_guard",
              "persist_to_result", "auto_run_to_result",
              "depth_of", "depth_overview"]:
        assert hasattr(role, m), f"{name} 应具备 {m}()"
    cap = role.capability()
    assert "depth_ability" in cap, f"{name} 能力声明应含 depth_ability"
    assert "rules" in cap["depth_ability"], f"{name} 深度能力应含使用规则"
print(f"  ✅ 全部 {len(roles)} 个角色均默认挂载七层协作深度能力")
EOF

echo "===== [depth] 2. L1-L7 全链路可执行（秘书路由→产品持续到结果） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

sec = get_role("架构·秘书")
prod = get_role("架构·产品")
task_key = "七层深度全链路演示"

# L1 表述
r1 = sec.express(task_key, "架构·产品", "有个需求需要产品澄清")
assert r1["level_key"] == "L1_表述", r1
# L2 任务对接
r2 = sec.connect(task_key, issue_ref="#99", role="架构·产品", domain="需求域",
                 title="产品澄清任务")
assert r2["level_key"] == "L2_任务对接", r2
assert r2.get("gid"), "应登记任务 gid"
# L3 路由真实唤醒（未回执）
r3a = sec.awake(task_key, "架构·产品", context="请澄清需求细节", issue_ref="#99")
assert r3a["awakened"] is False, "未回执时 awakened 应为 False"
# 产品回执接单 → 唤醒成立
prod.ack_wake(task_key, role="架构·产品", note="收到，接管需求澄清")
r3b = sec.awake(task_key, "架构·产品", context="确认唤醒", issue_ref="#99")
assert r3b["awakened"] is True, "已回执时 awakened 应为 True"
prod.start_work(task_key, role="架构·产品")
# L4 成果交互
r4 = prod.interact(task_key, "架构·开发", {"需求": "登录模块", "验收": "能登录"})
assert r4["level_key"] == "L4_成果交互", r4
assert r4["artifact_stored"], "产物应归档"
# L5 进度可控 + 自动规则
r5 = prod.track_round(task_key, "完成登录模块", goal_total=5, current=2, note="设计完成")
assert r5["level_key"] == "L5_进度可控", r5
assert r5["distance"] >= 0, "进度尺应有剩余距离"
r5g = prod.auto_guard(task_key, rule="converge_check")
assert "action" in r5g, r5g
# L6 持续到结果（秘书目标档位，收尾确认）
milestones = [
    {"step": "设计", "target": "设计完成", "goal_total": 3, "current": 3},
    {"step": "开发", "target": "开发完成", "goal_total": 3, "current": 3},
    {"step": "验收", "target": "验收通过", "goal_total": 3, "current": 3},
]
r6 = prod.persist_to_result(task_key, milestones, role="架构·产品", need_human_gate=True)
assert r6["level_key"] == "L6_持续到结果", r6
assert r6["reached_result"] is True, "L6 应到达结果"
assert r6["human_gate"] is True, "L6 秘书档位应设收尾确认闸门"
# L7 全自动到结果（体系目标档位）
r7 = prod.auto_run_to_result(task_key, milestones, role="架构·产品", max_rounds=10)
assert r7["level_key"] == "L7_全自动到结果", r7
assert r7["reached_result"] is True, "L7 应全自动到达结果"
# 深度俯瞰
ov = sec.depth_overview()
assert ov["total_tasks"] >= 1, "俯瞰应统计到任务"
assert ov["reached_L7"] >= 1, "应有任务到达 L7"
print("  ✅ L1→L7 全链路可执行（秘书路由真实唤醒 → 产品持续到结果）")
print(f"      俯瞰 by_depth={ov['by_depth']} | L6={ov['reached_L6']} L7={ov['reached_L7']}")
EOF

echo "===== [depth] 3. 防跳层：某层操作前须先完成前置深度 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
sec = get_role("架构·秘书")
prod = get_role("架构·产品")

# 全新任务直接跳到 L4 应报错（未完成 L1-L3）
try:
    sec.interact("跳层任务", "架构·开发", "x")
    raise SystemExit("⚠️ 跳层未拦截！L4 须先完成 L3")
except ValueError:
    print("  ✅ 防跳层拦截：L4 操作须先完成 L3 开工")

# 全新任务直接跳到 L7 应报错
try:
    prod.auto_run_to_result("跳层任务2", [], role="架构·产品")
    raise SystemExit("⚠️ 跳层未拦截！L7 须先完成 L6")
except ValueError:
    print("  ✅ 防跳层拦截：L7 操作须先完成 L6 持续到结果")
EOF

echo "===== [depth] 4. 秘书专项收口：route_wake（路由真实唤醒）+ L6 目标 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
sec = get_role("架构·秘书")
assert hasattr(sec, "route_wake"), "秘书应具备 route_wake()（路由真实唤醒专项）"
task_key = "秘书路由专项"
sec.express(task_key, "架构·产品", "消息")
sec.connect(task_key, role="架构·产品", domain="需求域")
# 未回执 → 未唤醒
w = sec.route_wake(task_key, "架构·产品", context="请澄清", issue_ref="#100")
assert w["awakened"] is False, "未回执应未唤醒"
print("  ✅ 秘书 route_wake()：未回执=未唤醒（路由未真实现唤醒会暴露）")
EOF

echo "===== [depth] 5. 自动化规则维持流程（auto_guard） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
prod = get_role("架构·产品")
sec = get_role("架构·秘书")
task_key = "自动规则演示"
sec.express(task_key, "架构·产品", "m")
sec.connect(task_key, role="架构·产品", domain="需求域")
prod.ack_wake(task_key, role="架构·产品")
sec.awake(task_key, "架构·产品")
prod.start_work(task_key, role="架构·产品")
prod.interact(task_key, "架构·开发", "产物")
# 三种自动化规则均可执行
for rule in ["converge_check", "timeout_retrigger", "stall_escalate"]:
    res = prod.auto_guard(task_key, rule=rule)
    assert "action" in res, res
print("  ✅ auto_guard 三种规则（converge_check/timeout_retrigger/stall_escalate）均可执行")
EOF

echo ""
echo "✅ [depth] 全部通过：七层协作深度能力（L1-L7）信号灯全绿"
echo "   秘书目标 L6 / 体系目标 L7 / 路由真实唤醒 / 防跳层 / 自动化维持流程 均达标"
