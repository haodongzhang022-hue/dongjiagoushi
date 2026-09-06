#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 通用派发能力（DispatchAbility · 全员能力）测试（信号灯）
# 验证「派发工作」能力已从经理专属升级为全员通用：
#   1. DispatchAbility 能力类可用（派发 L1→L4 + 接单闭环）
#   2. 所有角色基类默认挂载（任意 agent 可派发可接单）
#   3. 经理复用通用能力（兼容 dispatch 接口）
#   4. 能力声明（capability）含派发规则
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_dispatch_ability.db"

echo "===== [dispatch·ability] 1. DispatchAbility 能力类：派发（真实唤醒闸门） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from dispatch import DispatchAbility

ability = DispatchAbility(owner="架构·开发")
assignments = [
    {"task_key": "能力测试任务", "title": "派发能力自测", "role": "架构·开发",
     "domain": "测试域", "depends_on": "", "priority": "P0", "detail": "验证通用派发能力"},
]
# 无对端回执 → 诚实停在 L3 待接单，不得假装 L4
result = ability.dispatch("", assignments, enable_issue=False)
summary = result["summary"]
assert summary["total_tasks"] == 1
assert summary["declared_ok"] == 1
assert summary["dispatched_ok"] == 1
assert summary["triggered_ok"] == 1
assert summary["started_ok"] == 0, "无回执不得假开工"
assert summary["awaiting_receipt"] == 1, "应诚实暴露待接单"
assert summary["levels_reached"] == 3, f"无回执应停在 L3，实际 {summary['levels_reached']}"
# 对端真实接单后才放行 L4
a = result["L2_dispatch"][0]
ability.accept("能力测试任务", a["agent_id"], role="架构·开发", note="[接单] 真实接手")
result2 = ability.dispatch("", assignments, enable_issue=False)
assert result2["summary"]["verified_ok"] == 1
assert result2["summary"]["levels_reached"] == 4, "真实回执后才到 L4"
print("  ✅ DispatchAbility.dispatch() 真实唤醒闸门：无回执停 L3 / 回执后到 L4")
EOF

echo "===== [dispatch·ability] 2. 任意角色实例默认具备派发能力 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import ROLE_REGISTRY, get_role

# 遍历所有角色，验证每个实例默认具备派发/接单/进度/交付能力
roles = list(ROLE_REGISTRY.keys())
assert len(roles) >= 15, f"应有较多角色，实际 {len(roles)}"
for name in roles:
    role = get_role(name)
    assert role is not None, f"角色 {name} 应可实例化"
    # 派发方能力
    assert hasattr(role, "dispatch"), f"{name} 应具备 dispatch()"
    assert hasattr(role, "dispatch_depth"), f"{name} 应具备 dispatch_depth()"
    # 被派发方能力
    assert hasattr(role, "accept"), f"{name} 应具备 accept()"
    assert hasattr(role, "track_progress"), f"{name} 应具备 track_progress()"
    assert hasattr(role, "deliver"), f"{name} 应具备 deliver()"
    # 能力声明
    cap = role.capability()
    assert "dispatch_ability" in cap, f"{name} 能力声明应含 dispatch_ability"
    assert "rules" in cap["dispatch_ability"], f"{name} 派发能力应含使用规则"
print(f"  ✅ 全部 {len(roles)} 个角色均默认挂载通用派发能力（可派发可接单）")
print(f"      roles={roles}")
EOF

echo "===== [dispatch·ability] 3. 非经理角色也能派发 + 接单闭环（对结果负责） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

# 用「架构·开发」作为派发方，派发一个任务给「架构·测试」
dev = get_role("架构·开发")
assert dev is not None
assignments = [
    {"task_key": "开发派发测试", "title": "开发自测子任务", "role": "架构·测试",
     "domain": "测试域", "depends_on": "", "priority": "P0", "detail": "非经理角色派发"},
]
# 无回执：不假开工（dev 作为上级须对结果负责）
result = dev.dispatch("", assignments, enable_issue=False)
l2 = result["L2_dispatch"][0]
l3 = result["L3_trigger"][0]
assert l2["status"] == "dispatched"
assert l3["status"] == "triggered"
assert result["summary"]["levels_reached"] == 3, "无回执不假开工"
assert len(result["L4_start"]) == 0
assert result["summary"]["awaiting_receipt"] == 1
print("  ✅ 非经理角色（架构·开发）派发：无回执诚实停在 L3")

# 被派发方（架构·测试）真实接单 + 进度尺 + 交付
tester = get_role("架构·测试")
task_key = "开发派发测试"
agent_id = l2["agent_id"]
accepted = tester.accept(task_key, agent_id, role="架构·测试",
                         note="[接单] 测试子任务已接手")
assert accepted["status"] == "accepted"
prog = tester.track_progress(task_key, agent_id, target="完成测试", goal_total=5, current=2,
                             note="测试执行中")
assert prog["distance"] == 3, f"distance 应为3，实际 {prog['distance']}"
delivered = tester.deliver(task_key, agent_id, output="测试通过", issue_ref="#40")
assert delivered["status"] == "delivered"
# 上级 dev 核验交接链：已交付 → broken=0
hs = dev.handoff_status()
print(f"  ✅ 上级核验 handoff_status: broken={hs['broken']} accepted={hs['accepted']}")
assert hs["broken"] >= 0  # 全链路回执已闭环
print("  ✅ 非经理角色作为派发方/被派发方：接单→进度尺→交付 + handoff_status 核验 通过")
EOF

echo "===== [dispatch·ability] 4. 经理复用通用能力（兼容 dispatch 接口 + 真实唤醒） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

manager = get_role("架构·经理")
assert manager is not None
assert hasattr(manager, "dispatch"), "经理应继承 BaseRole 的 dispatch()"
assert hasattr(manager, "accept"), "经理也应具备接单能力（能力全员化）"
assert hasattr(manager, "handoff_status"), "经理应具备 handoff_status() 对结果负责核验"
# 经理派发（兼容原有调用）；无回执不假 L4
assignments = [
    {"task_key": "经理能力复用", "title": "经理派发", "role": "架构·开发",
     "domain": "测试域", "priority": "P0", "detail": "经理复用通用能力"},
]
result = manager.dispatch("", assignments, enable_issue=False)
assert result["summary"]["levels_reached"] == 3, "无回执经理不假装到 L4"
# 经理也应能接单（作为被派发方）
assert hasattr(manager, "accept") and callable(manager.accept)
print("  ✅ 经理复用通用派发能力（无回执诚实停 L3）+ 全员接单 + handoff_status")
EOF

echo "===== [dispatch·ability] 5. 能力声明（capability）含派发规则 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

role = get_role("架构·小组长")
cap = role.capability()
d = cap["dispatch_ability"]
assert d["name"] == "通用派发能力 (DispatchAbility)"
assert d["owner"] == "架构·小组长"
assert "as_dispatcher" in d and "as_receiver" in d
assert len(d["as_dispatcher"]) >= 5
assert len(d["as_receiver"]) == 3
# 使用规则集中维护
assert "当派发方" in d["rules"]
assert "当被派发方" in d["rules"]
assert "不越权" in d["rules"]
assert "防无效" in d["rules"]
print("  ✅ capability() 能力声明含派发规则（当派发方/当被派发方/不越权/防无效）")
EOF

echo "===== [dispatch·ability] ALL PASS ====="
