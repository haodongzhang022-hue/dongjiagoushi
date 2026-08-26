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

echo "===== [dispatch·ability] 1. DispatchAbility 能力类：派发 L1→L4 一站式 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from dispatch import DispatchAbility

ability = DispatchAbility(owner="架构·开发")
assignments = [
    {"task_key": "能力测试任务", "title": "派发能力自测", "role": "架构·开发",
     "domain": "测试域", "depends_on": "", "priority": "P0", "detail": "验证通用派发能力"},
]
result = ability.dispatch("", assignments, enable_issue=False)
summary = result["summary"]
assert summary["total_tasks"] == 1
assert summary["declared_ok"] == 1
assert summary["dispatched_ok"] == 1
assert summary["triggered_ok"] == 1
assert summary["started_ok"] == 1
assert summary["levels_reached"] == 4
print("  ✅ DispatchAbility.dispatch() 四层分发一站式通过")
print(f"      levels_reached={summary['levels_reached']}")
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

echo "===== [dispatch·ability] 3. 非经理角色也能派发 + 接单闭环 ====="
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
result = dev.dispatch("", assignments, enable_issue=False)
l2 = result["L2_dispatch"][0]
l3 = result["L3_trigger"][0]
l4 = result["L4_start"][0]
assert l2["status"] == "dispatched"
assert l3["status"] == "triggered"
assert l4["status"] == "working"
print("  ✅ 非经理角色（架构·开发）作为派发方派发成功")

# 被派发方（架构·测试）接单 + 进度尺 + 交付
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
print("  ✅ 非经理角色（架构·测试）作为被派发方：接单→进度尺→交付 闭环通过")
EOF

echo "===== [dispatch·ability] 4. 经理复用通用能力（兼容 dispatch 接口） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

manager = get_role("架构·经理")
assert manager is not None
assert hasattr(manager, "dispatch"), "经理应继承 BaseRole 的 dispatch()"
assert hasattr(manager, "accept"), "经理也应具备接单能力（能力全员化）"
# 经理派发（兼容原有调用）
assignments = [
    {"task_key": "经理能力复用", "title": "经理派发", "role": "架构·开发",
     "domain": "测试域", "priority": "P0", "detail": "经理复用通用能力"},
]
result = manager.dispatch("", assignments, enable_issue=False)
assert result["summary"]["levels_reached"] == 4
# 经理也应能接单（作为被派发方）
assert hasattr(manager, "accept") and callable(manager.accept)
print("  ✅ 经理复用通用派发能力，且具备全员接单能力（与全员同源）")
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
